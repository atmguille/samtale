import socket
from typing import List
from user import User, CurrentUser

BUFFER_SIZE = 1024  # TODO: ajustar más si se quiere
server_hostname = 'vega.ii.uam.es'
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
    return response.decode()


def register(user: CurrentUser):
    """
    Registers the current user in the system with the specified parameters
    :param user
    :raise RegisterFailed
    """
    string_to_send = f"REGISTER {user.nick} {user.ip} {user.tcp_port} {user.password} {user.protocols}"
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
        return User(nick, ip=response[3], tcp_port=int(response[4]), protocols=response[5])


def list_users() -> List[User]:  # TODO: de verdad esto puede devolver NOK? TODO: devuelve ts en vez de protocols: PROTESTAR
    """
    Gets a list of all the users
    :return: list of users.
    """
    """Response contains something like OK USERS_LIST N_USERS user1#... So to get the actual list of users, 
        we look for N_USERS and start splitting the list from there. Afterwards, we get a list with all the info
        of each user in a string (users_str), so we need to split again each user to get a list of the needed values"""

    response = _send("LIST_USERS".encode())
    n_users = response.split()[2]
    start_index = response.find(n_users) + len(n_users) + 1  # The number itself and the white space
    users_str = response[start_index:].split('#')[:-1]  # Avoid final empty element
    users_splitted = [user.split() for user in users_str]

    return [User(nick=user[0], ip=user[1], tcp_port=int(float(user[2])), protocols=user[3]) for user in users_splitted]
