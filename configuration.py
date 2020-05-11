import configparser
from enum import Enum
import os
from typing import Tuple

from discovery_server import register, RegisterFailed
from user import CurrentUser

ConfigurationStatus = Enum("ConfigurationStatus", ("LOADED", "WRONG_PASSWORD", "WRONG_FILE", "NO_FILE"))


class Configuration:
    CONFIGURATION_FILENAME = "configuration.ini"

    def __init__(self):
        self.config = configparser.ConfigParser()
        if self.config.read(Configuration.CONFIGURATION_FILENAME):
            # File was read successfully
            try:
                nickname = self.config["Configuration"]["nickname"]
                password = self.config["Configuration"]["password"]
                tcp_port = int(self.config["Configuration"]["tcp_port"])
                udp_port = int(self.config["Configuration"]["udp_port"])

                CurrentUser(nickname, "V0", tcp_port, password, udp_port=udp_port)
                # Check if the password is correct
                try:
                    register()
                    self.status = ConfigurationStatus.LOADED
                except RegisterFailed:
                    self.status = ConfigurationStatus.WRONG_PASSWORD

            except KeyError:
                # File is corrupted or has been tampered
                self.status = ConfigurationStatus.WRONG_FILE
        else:
            # No configuration file found
            self.status = ConfigurationStatus.NO_FILE

    def load(self, nickname: str,
             password: str,
             tcp_port: int,
             udp_port: int,
             persistent: bool = True) -> Tuple[str, str]:
        CurrentUser(nickname, "V0", tcp_port, password, udp_port)
        # Check if the password is correct
        try:
            register()
        except RegisterFailed:
            self.status = ConfigurationStatus.WRONG_PASSWORD
            return "Wrong Password", f"The provided password for {nickname} was not correct"

        self.status = ConfigurationStatus.LOADED
        if persistent:
            self.config["Configuration"] = {
                "nickname": nickname,
                "password": password,
                "tcp_port": tcp_port,
                "udp_port": udp_port
            }

            with open(Configuration.CONFIGURATION_FILENAME, "w") as f:
                self.config.write(f)

        return "Registration successfully", f"You were registered successfully as {nickname}"

    @staticmethod
    def delete():
        if os.path.exists(Configuration.CONFIGURATION_FILENAME):
            os.remove(Configuration.CONFIGURATION_FILENAME)
