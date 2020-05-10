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
                self.nickname = self.config["Configuration"]["nickname"]
                self.password = self.config["Configuration"]["password"]
                self.tcp_port = int(self.config["Configuration"]["tcp_port"])
                self.udp_port = int(self.config["Configuration"]["udp_port"])

                CurrentUser(self.nickname, "V0", self.tcp_port, self.password, udp_port=self.udp_port)
                # Check if the password is correct
                try:
                    register(CurrentUser.currentUser)
                except RegisterFailed:
                    CurrentUser.currentUser = None
                    self.status = ConfigurationStatus.WRONG_PASSWORD
                    return

                self.status = ConfigurationStatus.LOADED
                return
            except KeyError:
                # File is corrupted or has been tampered
                self.status = ConfigurationStatus.WRONG_FILE
        else:
            # No configuration file found
            self.status = ConfigurationStatus.NO_FILE

        # The file wasn't read successfully or wasn't valid
        self.nickname = None
        self.password = None
        self.tcp_port = None
        self.udp_port = None

    def is_loaded(self):
        return self.status == ConfigurationStatus.LOADED

    def load(self, nickname: str,
             password: str,
             tcp_port: int,
             udp_port: int,
             persistent: bool = True) -> Tuple[str, str]:
        self.nickname = nickname
        self.password = password
        self.tcp_port = tcp_port
        self.udp_port = udp_port

        CurrentUser(self.nickname, "V0", self.tcp_port, self.password, self.udp_port)
        # Check if the password is correct
        try:
            register(CurrentUser.currentUser)
        except RegisterFailed:
            CurrentUser.currentUser = None
            self.status = ConfigurationStatus.WRONG_PASSWORD
            return "Wrong Password", f"The provided password for {nickname} was not correct"

        self.status = ConfigurationStatus.LOADED
        if persistent:
            self.config["Configuration"] = {
                "nickname": self.nickname,
                "password": self.password,
                "control_port": self.tcp_port,
                "udp_port": self.udp_port
            }

            with open(Configuration.CONFIGURATION_FILENAME, "w") as f:
                self.config.write(f)

        return "Registration successfully", f"You were registered successfully as {self.nickname}"

    @staticmethod
    def delete():
        if os.path.exists(Configuration.CONFIGURATION_FILENAME):
            os.remove(Configuration.CONFIGURATION_FILENAME)
