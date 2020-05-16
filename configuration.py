import configparser
import logging
from enum import Enum, auto
import os
from typing import Tuple

from discovery_server import register, RegisterFailed
from logger import get_logger
from user import CurrentUser


class ConfigurationStatus(Enum):
    # The user information is loaded and correct
    LOADED = auto()
    # The password provided was not correct
    WRONG_PASSWORD = auto()
    # The configuration file was corrupt tampered
    WRONG_FILE = auto()
    # No configuration file was found
    NO_FILE = auto()


class Configuration:
    CONFIGURATION_FILENAME = "configuration.ini"

    def __init__(self):
        """
        Initializes a Configuration object. It will read the configuration file (whose name is in
        Configuration.CONFIGURATION_FILENAME) if present. If not, the load method can be called afterwards.
        The self.status method should be used to check if a user is logged in or not.
        """
        self.config = configparser.ConfigParser()
        if self.config.read(Configuration.CONFIGURATION_FILENAME):
            # File was read successfully
            try:
                nickname = self.config["Configuration"]["nickname"]
                password = self.config["Configuration"]["password"]
                tcp_port = int(self.config["Configuration"]["tcp_port"])
                udp_port = int(self.config["Configuration"]["udp_port"])
                private_ip = self.config["Configuration"]["private_ip"] == "True"
                get_logger().log(logging.DEBUG, "Configuration file read")

                CurrentUser(nickname, "V0#V1", tcp_port, password, udp_port=udp_port, private_ip=private_ip)
                # Check if the password is correct
                try:
                    register()
                    self.status = ConfigurationStatus.LOADED
                    get_logger().log(logging.INFO, f"Successfully signed in as {nickname}")
                except RegisterFailed:
                    get_logger().log(logging.WARNING, f"Couldn't sign in as {nickname}. "
                                                      f"The password is probably not correct")
                    self.status = ConfigurationStatus.WRONG_PASSWORD

            except KeyError as e:
                # File is corrupted or has been tampered
                get_logger().log(logging.WARNING, f"Error reading configuration file: {e}")
                self.status = ConfigurationStatus.WRONG_FILE
        else:
            # No configuration file found
            get_logger().log(logging.INFO, "No configuration file found")
            self.status = ConfigurationStatus.NO_FILE

    def load(self, nickname: str, password: str, tcp_port: int, udp_port: int, private_ip: bool,
             persistent: bool = True) -> Tuple[str, str]:
        """
        Tries to log in with the parameters passed
        :param nickname: nickname of the user
        :param password: password of the user
        :param tcp_port: tcp port to be used for call control
        :param udp_port: udp port to be used for the video stream
        :param private_ip: if set to true, it will get the local IP. If false, the global IP will be fetched.
        :param persistent: if set to true and if the logging information was correct, it will save the user information
        to a file called Configuration.CONFIGURATION_FILENAME
        :return: a pair of strings (title - message) so an information box can be displayed in the GUI
        """
        CurrentUser(nickname, "V0#V1", tcp_port, password, udp_port, private_ip=private_ip)
        # Check if the password is correct
        try:
            register()
        except RegisterFailed:
            get_logger().log(logging.WARNING, f"Couldn't sign in as {nickname}. "
                                              f"The password is probably not correct")
            self.status = ConfigurationStatus.WRONG_PASSWORD
            return "Wrong Password", f"The provided password for {nickname} was not correct"

        get_logger().log(logging.INFO, f"Successfully signed in as {nickname}")
        self.status = ConfigurationStatus.LOADED
        if persistent:
            self.config["Configuration"] = {
                "nickname": nickname,
                "password": password,
                "tcp_port": tcp_port,
                "udp_port": udp_port,
                "private_ip": private_ip
            }

            with open(Configuration.CONFIGURATION_FILENAME, "w") as f:
                self.config.write(f)

            get_logger().log(logging.DEBUG, f"User information saved into configuration file")

        return "Registration successfully", f"You were registered successfully as {nickname}"

    @staticmethod
    def delete():
        """
        Deletes the configuration file (whose filename is Configuration.CONFIGURATION_FILENAME) if present
        :return:
        """
        if os.path.exists(Configuration.CONFIGURATION_FILENAME):
            os.remove(Configuration.CONFIGURATION_FILENAME)
            get_logger().info("Configuration file deleted")
        else:
            get_logger().info("No configuration file to be deleted")
