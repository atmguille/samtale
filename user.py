import requests

currentUser = None


def _get_public_ip():  # TODO
    """
    :return: own public IP
    """
    return requests.get('http://ip.42.pl/raw').text


class User:
    def __init__(self, nick: str, protocols: str, tcp_port: int, ip: str = None, udp_port: int = None):
        """
        Constructor
        :param nick
        :param tcp_port
        :param udp_port: if not specified, initialized to None until it is updated
        :param ip: if not specified, own public IP will be set
        """
        self.nick = nick
        self.protocols = protocols
        self.ip = ip if ip is not None else _get_public_ip()
        self.tcp_port = tcp_port
        self.udp_port = udp_port

    def update_udp_port(self, port: int):
        self.udp_port = port


class CurrentUser(User):
    currentUser = None  # TODO

    def __init__(self, nick: str, protocols: str, tcp_port: int, password: str, udp_port: int = None, ip: str = None):
        super().__init__(nick, protocols, tcp_port, udp_port=udp_port, ip=ip)
        self.password = password
        CurrentUser.currentUser = self
