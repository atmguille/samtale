import socket
import threading
from threading import Lock
from user import User, CurrentUser

BUFFER_SIZE = 50  # TODO: espero que nadie tenga un nick demasiado largo


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
        self.own_hold = True  # If call is held by us
        self.foreign_hold = False  # If call is held by the other user

    def __del__(self):
        self.connection.close()
        self.__listener_stop = True
        self._listener.join()

    def should_video_flow(self):
        return not (self.own_hold or self.foreign_hold)

    def _listen(self):
        """
        Function that is executed by the listener. Checks if the call must be held, resumed or ended
        """
        # TODO: informar a la interfaz de lo que va pasando
        while not self.__listener_stop:
            try:
                response = self.connection.recv(BUFFER_SIZE).decode().split()
            except socket.timeout:  # This exception may only happen if the other user does not answer to our call
                # TODO: informar que el otro no nos responde
                break
            if response:
                if response[0] == "CALL_ACCEPTED":
                    self.dst_user.update_udp_port(int(response[2]))
                    self.connection.settimeout(None)  # The connection should not be closed until wanted
                    self.own_hold = False  # Start sending video
                elif response[0] == "CALL_DENIED":
                    # TODO
                    break
                elif response[0] == "CALL_BUSY":
                    # TODO
                    break
                elif response[0] == "CALL_HOLD":
                    self.foreign_hold = False
                elif response[0] == "CALL_RESUME":
                    self.foreign_hold = True
                elif response[0] == "CALL_END":
                    # TODO
                    break

    def call_start(self):
        """
        Calls the user and runs listener thread
        """
        string_to_send = f"CALLING {self.src_user.nick} {self.src_user.tcp_port}"
        self.connection.send(string_to_send.encode())
        self.connection.settimeout(30)  # Sets timeout long enough so the user is able to answer TODO: 30 segs es mucho o poco???
        self._listener.start()

    def call_accept(self):
        """
        Accepts the call, sending the other user the corresponding command and running the listener thread
        :return:
        """
        string_to_send = f"CALL_ACCEPTED {self.src_user.nick} {self.src_user.udp_port}"
        self.connection.send(string_to_send.encode())
        self.own_hold = False  # Start sending video
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
        string_to_send = f"CALL_END {self.src_user.nick}"
        self.connection.send(string_to_send.encode())


def _open_tcp_socket(src_user: User) -> socket:
    """
    Opens a tcp socket with the IP and port of the user
    :param src_user
    :return: tcp socket
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", src_user.tcp_port))
    return sock


class ControlDispatcher:
    def __init__(self, callback):
        self.src_user = CurrentUser.currentUser
        self.sock = _open_tcp_socket(self.src_user)
        self.current_call_control = None
        self.__call_control_lock = Lock()
        self._listener = threading.Thread(target=self._listen)
        self.__listener_stop = False
        self.callback = callback
        self._listener.start()

    def __del__(self):
        self.__listener_stop = True
        self._listener.join()
        if self.current_call_control:
            del self.current_call_control

    def set_call_control(self, call_control: CallControl):
        with self.__call_control_lock:
            self.current_call_control = call_control

    def del_call_control(self):
        with self.__call_control_lock:
            if self.current_call_control:
                del self.current_call_control
                self.current_call_control = None

    def _listen(self):
        """
        Function executed by the listener, checking if someone is calling us. If we are already in a call,
        it answers CALL_BUSY to the incoming user. If we are available, builds a new CallControl, where
        the user can interact with the call (deny it, ...)
        :return:
        """
        self.sock.listen(1)
        while not self.__listener_stop:
            connection, client_address = self.sock.accept()
            connection.settimeout(3)

            try:
                response = connection.recv(BUFFER_SIZE).decode().split()

                with self.__call_control_lock:  # Block call control until resolving request
                    if self.current_call_control:  # If a call control exists, the user is busy
                        connection.send("CALL_BUSY".encode())
                        continue

                    if response[0] != "CALLING":
                        raise Exception("Error in received string")

                    incoming_user = User(nick=response[1],
                                         protocols="V0",  # TODO: sería maravilloso que viniera en el CALLING
                                         tcp_port=client_address[1],
                                         ip=client_address[0],
                                         udp_port=int(response[2]))
                    connection.settimeout(None)  # The connection should not be closed until wanted
                    self.current_call_control = CallControl(incoming_user, connection)
                    accept = self.callback(incoming_user.nick, incoming_user.ip)
                    if accept:
                        self.current_call_control.call_accept()
                    else:
                        self.current_call_control.call_deny()
                        del self.current_call_control
                        self.current_call_control = None
            except:
                connection.send(f"CALL_DENIED {self.src_user.nick}".encode())
