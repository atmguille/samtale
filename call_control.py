import socket
import threading
from threading import Lock
from user import User, CurrentUser

BUFFER_SIZE = 50  # TODO: espero que nadie tenga un nick demasiado largo
_user_in_call = False  # TODO: si se accede desde fuera podemos meterlo en CurrentUser
_in_call_mutex = Lock()


def _open_tcp_socket(src_user: User) -> socket:
    """
    Opens a tcp socket with the IP and port of the user
    :param src_user
    :return: tcp socket
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((src_user.ip, src_user.tcp_port))
    return sock


class ControlDispatcher:
    def __init__(self):
        self.src_user = CurrentUser.currentUser
        self.sock = _open_tcp_socket(self.src_user)
        self._listener = threading.Thread(target=self._listen)
        self._listener.start()
        self.__listener_stop = False

    def __del__(self):
        self.__listener_stop = True
        self._listener.join()

    def _listen(self):
        """
        Function executed by the listener, checking if someone is calling us. If we are already in a call,
        it answers CALL_BUSY to the incoming user. If we are available, builds a new CallControl, where
        the user can interact with the call (deny it, ...)
        :return:
        """
        global _user_in_call
        self.sock.listen(1)
        while not self.__listener_stop:
            connection, client_address = self.sock.accept()
            connection.settimeout(3)
            with _in_call_mutex:
                _in_call = _user_in_call
            if _in_call:
                connection.send("CALL_BUSY".encode())
                continue
            try:
                response = connection.recv(BUFFER_SIZE).decode().split()
                if response[0] != "CALLING":
                    raise Exception("Error in received string")
                incoming_user = User(nick=response[1],
                                     protocols="V0",  # TODO: sería maravilloso que viniera en el CALLING
                                     tcp_port=client_address[1],
                                     ip=client_address[0],
                                     udp_port=int(response[2]))
                # TODO: informar interfaz llamada entrante y si el usuario la deniega etc
                connection.settimeout(None)  # The connection should not be closed until wanted
                CallControl(incoming_user, connection)  # TODO: como sacamos este CallControl fuera? Que haya variable global y lo seteamos?
            except:
                connection.send(f"CALL_DENIED {self.src_user.nick}".encode())


class CallDenied(Exception):
    def __init__(self, nick: str):
        message = f"User {nick} denied our call"
        super().__init__(message)


class CallBusy(Exception):
    def __init__(self, nick: str):
        message = f"User {nick} is currently in a call. Please try later"
        super().__init__(message)


def _create_tcp_connection(dst_user: User) -> socket:
    """
    Creates a tcp connection
    :param dst_user: user to create the connection with. ip and tcp_port will be gathered from it
    :return: created connection
    """
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.connect((dst_user.ip, dst_user.tcp_port))
    return connection


class CallControl:
    def __init__(self, dst_user: User, connection: socket = None):
        self.src_user = CurrentUser.currentUser
        self.dst_user = dst_user
        self.connection = connection if connection is not None else _create_tcp_connection(dst_user)
        self._listener = threading.Thread(target=self._listen)
        self.__listener_stop = False
        # These two variables are needed in case both of the users hold the call.
        # Only if both of them are not in "hold", the call can continue
        self.own_hold = False  # If call is held by us
        self.foreign_hold = False  # If call is held by the other user

    def __del__(self):
        self.connection.close()
        self.__listener_stop = True
        self._listener.join()

    # TODO: funciones para usar con with, quitar si no usamos
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__del__()

    def _listen(self):
        """
        Function that is executed by the listener. Checks if the call must be held, resumed or ended
        """
        global _user_in_call
        # TODO: informar a la interfaz de lo que va pasando
        while not self.__listener_stop:
            response = self.connection.recv(BUFFER_SIZE).decode().split()
            if response:
                if response[0] == "CALL_HOLD":
                    self.foreign_hold = False
                    #self._in_call = False  TODO: podemos hacer que acepte otras llamadas mientras está en hold? Habría que actualizar en el resto de funciones relacionadas
                elif response[0] == "CALL_RESUME":
                    self.foreign_hold = True
                elif response[0] == "CALL_END":
                    with _in_call_mutex:
                        _user_in_call = False

    def call_start(self):
        """
        Calls the user, waits for his answer and updates variables depending on the answer's value. If call is accepted,
        dst_user's udp port is updated and listener thread is started.
        """
        global _user_in_call
        string_to_send = f"CALLING {self.src_user.nick} {self.src_user.tcp_port}"
        self.connection.send(string_to_send.encode())
        with _in_call_mutex:
            _user_in_call = True  # Avoid that other users call us while waiting for the answer

        self.connection.settimeout(30)  # Sets timeout long enough so the user is able to answer TODO: 30 segs es mucho o poco???
        response = self.connection.recv(BUFFER_SIZE).decode().split()

        if response[0] == "CALL_ACCEPTED":
            self.dst_user.update_udp_port(int(response[2]))
            self.connection.settimeout(None)  # The connection should not be closed until wanted
            self._listener.start()
        elif response[0] == "CALL_DENIED":
            with _in_call_mutex:
                _user_in_call = False
            raise CallDenied(self.dst_user.nick)  # TODO: tanto esta como la siguiente excepcion posiblemente no tengan senitdo. Hay que ver como informar a la interfaz
        elif response[0] == "CALL_BUSY":
            with _in_call_mutex:
                _user_in_call = False
            raise CallBusy(self.dst_user.nick)

    def call_accept(self):
        """
        Accepts the call, sending the other user the corresponding command and running the listener thread
        :return:
        """
        global _user_in_call
        with _in_call_mutex:
            _user_in_call = True
        string_to_send = f"CALL_ACCEPTED {self.src_user.nick} {self.src_user.udp_port}"
        self.connection.send(string_to_send.encode())
        self._listener.start()

    def call_deny(self):
        string_to_send = f"CALL_DENIED {self.src_user.nick}"
        self.connection.send(string_to_send.encode())

    def call_hold(self):
        self.own_hold = True
        string_to_send = f"CALL_HOLD {self.src_user.nick}"
        self.connection.send(string_to_send.encode())

    def call_resume(self):
        self.own_hold = False
        string_to_send = f"CALL_RESUME {self.src_user.nick}"
        self.connection.send(string_to_send.encode())

    def call_end(self):
        global _user_in_call
        with _in_call_mutex:
            _user_in_call = True
        string_to_send = f"CALL_END {self.src_user.nick}"
        self.connection.send(string_to_send.encode())

