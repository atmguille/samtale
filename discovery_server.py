import socket
import requests

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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.connect((socket.gethostbyname(server_hostname), server_port))
        connection.send(message)
        response = connection.recv(BUFFER_SIZE)
    return str(response)


def _get_public_IP():  # TODO
    """
    :return: own public IP
    """
    return requests.get('http://ip.42.pl/raw').text


def register(nick: str, port: int, password: str, protocols: str):
    """
    Registers a user in the system with the specified parameters
    :param nick
    :param port
    :param password
    :param protocols
    :raise RegisterFailed
    """
    ip = _get_public_IP()
    string_to_send = f"REGISTER {nick} {ip} {port} {password} {protocols}"
    response = _send(string_to_send.encode()).split()
    if response[0] == "NOK":
        raise RegisterFailed


def get_user(nick: str) -> list:
    """
    Gets the IP, port and protocols of the user with the specified nickname
    :param nick
    :return: [ip, port, protocols] TODO: devolvemos también el nick? Ya lo tenemos así que para que no?
    :raise UserUnknown if user is not found
    """
    string_to_send = f"QUERY {nick}"
    response = _send(string_to_send.encode()).split()
    if response[0] == "NOK":
        raise UserUnknown(nick)
    else:
        return response[2:]


def list_users() -> list:
    """
    Gets a list of all the users
    :return: list of users. Each user is: [nick, ip, port, protocols]
    """
    return _send("LIST_USERS".encode()).split('#')  # TODO: de verdad esto puede devolver NOK?


def close_connection():
    """
    Let the server know that we are closing the connection TODO: pero si los sockets los cerramos cada vez, esto pa que? Y tener un socket general abierto creo que no tendría nada de sentido, porque seguramente salte el timeout
    """
    _send("QUIT".encode())


print(register("Dani", 8080, "secret", "V0"))
