import configparser

from discovery_server import register, RegisterFailed
from user import CurrentUser


class Configuration:
    CONFIGURATION_FILENAME = "configuration.ini"
    DEFAULT_UDP_PORT = 1234

    def __init__(self):
        self.config = configparser.ConfigParser()
        if self.config.read(Configuration.CONFIGURATION_FILENAME):
            # File was read successfully
            try:
                self.nickname = self.config["Configuration"]["nickname"]
                self.password = self.config["Configuration"]["password"]
                self.control_port = int(self.config["Configuration"]["control_port"])
                udp_port = self.config["Configuration"].get("udp_port", str(Configuration.DEFAULT_UDP_PORT))
                self.udp_port = int(udp_port)

                CurrentUser(self.nickname, "V0", self.control_port, self.password, udp_port=self.udp_port)
                return
            except KeyError:
                # File is corrupted or has been tampered
                pass

        # The file was not read successfully or file wasn't valid
        self.nickname = None
        self.password = None
        self.control_port = None
        self.udp_port = Configuration.DEFAULT_UDP_PORT

    def is_loaded(self):
        return self.nickname is not None

    def load(self, nickname: str, password: str, control_port: int, udp_port: int = DEFAULT_UDP_PORT):
        self.nickname = nickname
        self.password = password
        self.control_port = control_port
        self.udp_port = udp_port

        CurrentUser(self.nickname, "V0", self.control_port, self.password, self.udp_port)
        # Check if the password is correct
        try:
            register(CurrentUser.currentUser)
        except RegisterFailed:
            CurrentUser.currentUser = None
            raise RegisterFailed

        self.config["Configuration"]["nickname"] = self.nickname
        self.config["Configuration"]["password"] = self.password
        self.config["Configuration"]["control_port"] = str(self.control_port)
        self.config["Configuration"]["udp_port"] = str(self.udp_port)

        with open(Configuration.CONFIGURATION_FILENAME, "w") as f:
            self.config.write(f)
