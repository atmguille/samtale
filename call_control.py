import socket
import threading
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
    Creates a tcp connection with NO timeout limit
    :param dst_user: user to create the connection with. ip and tcp_port will be gathered from it
    :return: created connection
    """
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(None)  # The connection should not be closed until wanted
    connection.connect((dst_user.ip, dst_user.tcp_port))
    return connection


class CallControl:
    def __init__(self, dst_user: User):
        self.src_user = CurrentUser.currentUser
        self.dst_user = dst_user
        self.connection = _create_tcp_connection(dst_user)
        self._in_call = False
        self._listener = threading.Thread(target=self._listen)  # TODO: primera solución que se me ocurre, para nada definitiva

    def __del__(self):
        self.connection.close()

    # TODO: funciones para usar con with, quitar si no usamos
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__del__()

    def _listen(self):
        # TODO: informar a la interfaz de lo que va pasando
        response = self.connection.recv(BUFFER_SIZE).decode().split()
        if response[0] == "CALLING":
            if self._in_call:
                self.call_busy()
            else:
                pass
        elif response[0] == "CALL_ACCEPTED":
            self._in_call = True
            self.dst_user.update_udp_port(int(response[2]))
        elif response[0] == "CALL_DENIED":
            raise CallDenied(self.dst_user.nick) # TODO: tanto esta como la siguiente excepcion posiblemente no tengan senitdo. Hay que ver como informar a la interfaz
        elif response[0] == "CALL_BUSY":
            raise CallBusy(self.dst_user.nick)
        elif response[0] == "CALL_HOLD":
            self._in_call = False
        elif response[0] == "CALL_RESUME":
            self._in_call = True
        elif response[0] == "CALL_END":
            self._in_call = False

    def call_start(self):
        string_to_send = f"CALLING {self.src_user.nick} {self.src_user.tcp_port}"
        self.connection.send(string_to_send.encode())

    def call_accept(self):
        string_to_send = f"CALL_ACCEPTED {self.src_user.nick} {self.src_user.udp_port}"
        self._in_call = True
        self.connection.send(string_to_send.encode())

    def call_deny(self):
        string_to_send = f"CALL_DENIED {self.src_user.nick}"
        self.connection.send(string_to_send.encode())

    def call_busy(self):
        string_to_send = f"CALL_BUSY"  # TODO: sin nick?, es la única que la web no dice nada, el resto todos llevan...
        self.connection.send(string_to_send.encode())

    def call_hold(self):
        string_to_send = f"CALL_HOLD {self.src_user.nick}"
        self._in_call = False
        self.connection.send(string_to_send.encode())

    def call_resume(self):
        string_to_send = f"CALL_RESUME {self.src_user.nick}"
        self._in_call = True
        self.connection.send(string_to_send.encode())

    def call_end(self):
        string_to_send = f"CALL_END {self.src_user.nick}"
        self._in_call = False
        self.connection.send(string_to_send.encode())

