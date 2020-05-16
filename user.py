import socket
import requests

from decorators import singleton

currentUser = None


def _get_public_ip():
    """
    :return: own public IP
    """
    return requests.get('http://ip.42.pl/raw').text


def _get_private_ip():
    """
    :return: own private IP
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    private_ip = s.getsockname()[0]
    s.close()
    return private_ip


class User:
    def __init__(self, nick: str, protocols: str, tcp_port: int, ip: str, udp_port: int = None):
        """
        Constructor
        :param nick
        :param protocols
        :param tcp_port
        :param ip
        :param udp_port: if not specified, initialized to None until it is updated
        """
        self.nick = nick
        # Avoid misunderstandings with users that log in with protocol in lower case
        self.protocols = [protocol.upper() for protocol in protocols.split("#")]
        self.ip = ip if ip is not None else _get_public_ip()
        self.tcp_port = tcp_port
        self.udp_port = udp_port

    def update_udp_port(self, port: int):
        self.udp_port = port

    def get_best_common_protocol(self) -> str:
        """
        Returns best common protocol with the current user
        """
        common_protocols = list(set(self.protocols).intersection(CurrentUser().protocols))
        best_protocol = sorted(common_protocols)[-1]
        return best_protocol


@singleton
class CurrentUser(User):
    def __init__(self, nick: str, protocols: str, tcp_port: int, password: str, udp_port: int, ip: str = None,
                 private_ip: bool = False):
        """
        Constructor
        :param nick
        :param protocols
        :param tcp_port
        :param password
        :param udp_port
        :param ip: if not specified, own public (or private) IP will be set
        :param private_ip: if ip should be set to public or private
        """
        if ip is None:
            if private_ip:
                ip = _get_private_ip()
            else:
                ip = _get_public_ip()

        super().__init__(nick, protocols, tcp_port, udp_port=udp_port, ip=ip)
        self.password = password
