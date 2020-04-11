import socket
from typing import List
from user import User

BUFFER_SIZE = 1024  # TODO: ajustar más si se quiere
server_hostname = 'tfg.eps.uam.es'
server_port = 8000


class RegisterFailed(Exception):
    def __init__(self):
        message = "Register failed"
        super().__init__(message)


class UserUnknown(Exception):
    def __init__(self, nick: str):
        message = f"User {nick} was not found"
        super().__init__(message)


def _send(message: bytes) -> str:
    """
    Sends a message to the Discovery Server
    :param message: message encoded in bytes to be sent
    :return: response of the server TODO: type
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:  # TODO: organizar según conveniencia
        connection.connect((socket.gethostbyname(server_hostname), server_port))
        connection.send(message)
        response = connection.recv(BUFFER_SIZE)
        connection.send("QUIT".encode())  # TODO: esto va aquí o no?
    return str(response)


def register(user: User, password: str):  # TODO: incluir password en User si se necesita en otros sitios
    """
    Registers the user in the system with the specified parameters
    :param user
    :param password
    :raise RegisterFailed
    """
    string_to_send = f"REGISTER {user.nick} {user.ip} {user.tcp_port} {password} {user.protocols}"
    response = _send(string_to_send.encode()).split()
    if response[0] == "NOK":
        raise RegisterFailed


def get_user(nick: str) -> User:
    """
    Gets the IP, port and protocols of the user with the specified nickname
    :param nick
    :return: User
    :raise UserUnknown if user is not found
    """
    string_to_send = f"QUERY {nick}"
    response = _send(string_to_send.encode()).split()
    if response[0] == "NOK":
        raise UserUnknown(nick)
    else:
        return User(nick, ip=response[2], tcp_port=int(response[3]), protocols=response[4])


def list_users() -> List[User]:
    """
    Gets a list of all the users
    :return: list of users.
    """
    return [User(nick=response[0], ip=response[1], tcp_port=int(response[2]), protocols=response[3])
            for response in (_send("LIST_USERS".encode()).split()[2]).split('#')]  # TODO: de verdad esto puede devolver NOK?


print(register(User("dani", "V0", 8080), "secret"))
