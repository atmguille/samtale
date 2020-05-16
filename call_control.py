import logging
import socket
from threading import Thread, Lock
from typing import Optional, Tuple
from timeit import default_timer

from decorators import run_in_thread
from discovery_server import get_user, UserUnknown, BadUser
from logger import get_logger
from user import User, CurrentUser

BUFFER_SIZE = 1024


def _open_tcp_socket(src_user: User) -> socket:
    """
    Opens a tcp socket with the IP and port of the user
    :param src_user
    :return: tcp socket
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", src_user.tcp_port))
    return sock


class CallControl:
    BUFFER_SIZE = 1024
    TIMEOUT = 30
    CONGESTED_INTERVAL = 60

    def __init__(self, video_client, start_control_thread: bool):
        """
        Default constructor
        :param video_client: instance of the video client. Needed to access methods from the GUI
        :param start_control_thread: True in control thread (the one who listens for requests) should start.
                                     This may only happen when CurrentUser is initialized.
        """
        self.video_client = video_client
        # Control thread
        self.control_socket: Optional[socket] = None
        self.control_thread = Thread(target=self.control_daemon, daemon=True)
        if start_control_thread:
            self.control_thread.start()
        # Call
        self._in_call = False
        self._waiting = False
        self.we_on_hold = False
        self.they_on_hold = False
        self.sequence_number = 0
        self.protocol = None
        self.call_lock = Lock()
        self.dst_user: Optional[User] = None
        self.call_socket: Optional[socket] = None
        self.call_thread: Optional[Thread] = None

    def in_call(self) -> bool:
        """
        :return: if we are in a call
        """
        with self.call_lock:
            return self._in_call

    def waiting(self) -> bool:
        """
        :return: if we are waiting for a call to be answered
        """
        with self.call_lock:
            return self._waiting

    def should_video_flow(self) -> bool:
        """
        :return: if video should flow in both directions. This happens when we are in a call and
                 none of the users is on hold.
        """
        return self.in_call() and not (self.we_on_hold or self.they_on_hold)

    def get_sequence_number(self) -> int:
        """
        :return: sequence number of the current call, incrementing it by 1. If we are not in a call, -1.
        """
        if self.in_call():
            self.sequence_number += 1
            return self.sequence_number

        return -1

    def get_send_address(self) -> Tuple[str, int]:
        """
        Can be used to check if data received from socket comes from desired user
        :return: dst_user.ip, dst_user.udp_port.
        """
        return self.dst_user.ip, self.dst_user.udp_port

    def _call_start(self, nickname: str):
        """
        Try to establish a call with the desired user, waiting for his answer. It displays information of the process
        to the user using the GUI methods
        :param nickname
        """
        # Fetch user from server
        try:
            user = get_user(nickname)
        except (UserUnknown, BadUser) as e:
            with self.call_lock:
                self._waiting = False

            self.video_client.display_connect()
            self.video_client.display_message("Error fetching user", str(e))
            return

        # Call user
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connection.settimeout(CallControl.TIMEOUT)
        try:
            connection.connect((user.ip, user.tcp_port))
        except socket.error:
            get_logger().log(logging.INFO, f"Could not connect to {user.nick} at {user.ip}:{user.tcp_port}")
            self.video_client.display_message("Could not connect",
                                              f"Could not connect to {user.nick} at {user.ip}:{user.tcp_port}")
            with self.call_lock:
                self._waiting = False

            self.video_client.display_connect()
            return

        calling_str = f"CALLING {CurrentUser().nick} {CurrentUser().udp_port}"
        self.protocol = user.get_best_common_protocol()
        get_logger().log(logging.DEBUG, f"Best common protocol detected: {self.protocol}")
        # If common protocol is greater than V0, append protocol to CALLING
        if self.protocol != "V0":
            calling_str += f" {self.protocol}"

        get_logger().log(logging.DEBUG, f"Sending {calling_str} to {user.nick} at {user.ip}:{user.tcp_port}")
        connection.send(calling_str.encode())
        try:
            response = connection.recv(CallControl.BUFFER_SIZE)
        except (socket.timeout, OSError, ConnectionError):
            # This exception only happened if the other user does not answer to our call
            get_logger().log(logging.INFO, f"The user {user.nick} did not answer the call")
            self.video_client.display_message("Call not answered",
                                              f"The user {user.nick} did not answer the call")
            with self.call_lock:
                self._waiting = False

            self.video_client.display_connect()
            return

        with self.call_lock:
            self._waiting = False
        try:
            response = response.decode().split()
            if response[0] == "CALL_ACCEPTED":
                get_logger().log(logging.INFO, f"The user {user.nick} accepted the call")
                self.dst_user = user
                self.dst_user.update_udp_port(int(response[2]))
                connection.settimeout(None)  # The connection should not be closed until wanted
                self.call_socket = connection
                self.call_thread = Thread(target=self.call_daemon)
                self.call_thread.start()
                with self.call_lock:
                    self._in_call = True
                self.video_client.display_in_call(nickname)
            elif response[0] == "CALL_DENIED":
                get_logger().log(logging.INFO, f"The user {user.nick} denied the call")
                self.video_client.display_message("Call denied",
                                                  f"The user {user.nick} denied the call")
                connection.close()
                self.video_client.display_connect()
                return
            elif response[0] == "CALL_BUSY":
                get_logger().log(logging.INFO, f"The user {user.nick} is already in a call")
                self.video_client.display_message("User busy",
                                                  f"The user {user.nick} is already in a call")
                connection.close()
                self.video_client.display_connect()
                return
            else:
                raise ValueError()
        except (ValueError, IndexError):
            get_logger().log(logging.ERROR, f"Error establishing connection with {user.nick} at {user.ip}:{user.udp_port}")
            self.video_client.display_message("Error establishing connection",
                                              f"Error establishing connection with {user.nick}")
            self.video_client.display_connect()
            connection.close()

    def call_start(self, nickname: str):
        """
        Checks if a call can be started before calling _call_start in a separate Thread. By this, deadlock is avoided if
        two call_start are executed before the first one have an answer
        :param nickname: nickname of the user to be called
        """
        self.call_lock.acquire()
        if self._in_call:
            self.call_lock.release()
            get_logger().log(logging.INFO, "Tried to make a call while in a call")
            self.video_client.display_message("You are in a call",
                                              "You have to hang up in order to make a new call")
            return
        elif self._waiting:
            self.call_lock.release()
            get_logger().log(logging.INFO, "Tried to make a another call while calling someone")
            self.video_client.display_message("You are making a call",
                                              "You have to cancel it in order to make a new call")
            return

        self._waiting = True
        self.video_client.display_calling(nickname)
        self.call_lock.release()

        Thread(target=self._call_start, args=(nickname,), daemon=True).start()

    def _call_end(self):
        """
        Reset attributes related with a call when it is over
        """
        self._in_call = False
        self._waiting = False
        self.we_on_hold = False
        self.they_on_hold = False
        self.sequence_number = 0
        self.protocol = None
        self.video_client.flush_buffer()
        self.call_socket.close()
        self.video_client.display_connect()

    def call_end(self):
        """
        Notify the other end we are ending the call and reset attributes
        """
        get_logger().log(logging.INFO, f"Ending call with {self.dst_user.nick}")
        self.call_socket.send(f"CALL_END {CurrentUser().nick}".encode())
        self._call_end()

    @run_in_thread
    def call_hold(self):
        """
        Holds the call in our end and notifies the other end that we are doing so. Executed in a separate thread to
        avoid delays in executing other functions by the main thread.
        """
        self.we_on_hold = True
        get_logger().log(logging.INFO, f"Pausing call with {self.dst_user.nick}")
        self.call_socket.send(f"CALL_HOLD {CurrentUser().nick}".encode())

    @run_in_thread
    def call_resume(self):
        """
        Resumes the call in our end and notifies the other end that we are doing so. Executed in a separate thread to
        avoid delays in executing other functions by the main thread.
        """
        self.we_on_hold = False
        get_logger().log(logging.INFO, f"Resuming call with {self.dst_user.nick}")
        self.call_socket.send(f"CALL_RESUME {CurrentUser().nick}".encode())

    @run_in_thread
    def call_congested(self):
        """
        Notifies the other end that the quality of the connection in our end is not good, so he can take measures.
        This is done only if call protocol is not V0 (checked inside)
        """
        # All protocols different to V0 should support this
        if self.protocol != "V0":
            get_logger().log(logging.INFO, f"Sending CALL_CONGESTED to {self.dst_user.nick}")
            self.call_socket.send(f"CALL_CONGESTED {CurrentUser().nick}".encode())
        else:
            get_logger().log(logging.INFO, f"Won't send CALL_CONGESTED to {self.dst_user.nick} since it is using V0")

    def control_daemon(self):
        """
        Function executed by the listener, checking if someone is calling us. If we are already in a call,
        it answers CALL_BUSY to the incoming user. If we are available, builds a new CallControl, where
        the user can interact with the call (deny it, ...)
        """
        self.control_socket = _open_tcp_socket(CurrentUser())
        self.control_socket.listen(1)
        while True:
            connection, client_address = self.control_socket.accept()
            connection.settimeout(3)

            try:
                response = connection.recv(BUFFER_SIZE).decode().split()
                get_logger().log(logging.DEBUG, f"Received via control connection: {response}")

                self.call_lock.acquire()
                if self._in_call or self._waiting:
                    self.call_lock.release()  # Release the lock asap
                    connection.send("CALL_BUSY".encode())
                    get_logger().log(logging.INFO, f"{response[1]} called while in a call")
                    self.video_client.display_message(f"{response[1]} called you", f"{response[1]} called you")
                    continue

                if response[0] != "CALLING":
                    get_logger().log(logging.ERROR, f"The first word in {response} should be CALLING")
                    connection.close()
                    continue

                # If V1 or +, CALLING has the protocol to be used in last argument
                self.protocol = response[3] if len(response) > 3 else "V0"

                incoming_user = User(nick=response[1],
                                     protocols=self.protocol,
                                     tcp_port=client_address[1],
                                     ip=client_address[0],
                                     udp_port=int(response[2]))
                connection.settimeout(None)  # The connection should not be closed until wanted

                # Wait for the user's answer without blocking the execution (releasing the lock)
                self.call_lock.release()
                accept = self.video_client.incoming_call(incoming_user.nick, incoming_user.ip)
                self.call_lock.acquire()
                if accept:
                    get_logger().info(logging.INFO, f"We accepted a call with {incoming_user.nick}")
                    answer = f"CALL_ACCEPTED {CurrentUser().nick} {CurrentUser().udp_port}".encode()
                    connection.send(answer)
                    self._in_call = True
                    self.video_client.display_in_call(incoming_user.nick)
                    self.dst_user = incoming_user
                    self.call_socket = connection
                    self.call_thread = Thread(target=self.call_daemon, daemon=True)
                    self.call_thread.start()
                else:
                    get_logger().info(logging.INFO, f"We rejected a call with {incoming_user.nick}")
                    connection.send(f"CALL_DENIED {CurrentUser().nick}".encode())
                self.call_lock.release()
            except (ValueError, IndexError):
                get_logger().log(logging.ERROR, f"Error parsing control message: {response}")
                connection.send(f"CALL_DENIED {CurrentUser().nick}".encode())
                self.call_lock.release()

    def call_daemon(self):
        """
        Function that is executed by the listener thread (one per call).
        Checks if the call must be held, resumed, ended of if the connection is congested, notifying the user in any case
        """
        last_congested = 0

        while True:
            if self.protocol != "V0":  # Check congested condition only if using protocol that requires it
                # If last congested has not been received since CONGESTED_INTERVAL seconds, deactivate extreme compression
                if last_congested and default_timer() - last_congested > CallControl.CONGESTED_INTERVAL:
                    self.video_client.extreme_compression = False

            try:
                response = self.call_socket.recv(BUFFER_SIZE)
                get_logger().log(logging.DEBUG, f"{self.dst_user.nick} sent: {response}")
            except socket.error:
                self._call_end()
                break
            try:
                response = response.decode().split()
                # If socket is closed, no exception is thrown but response is empty
                if not response:
                    self._call_end()
                    break
                if response[0] == "CALL_HOLD":
                    get_logger().log(logging.INFO, f"{self.dst_user.nick} paused the call")
                    self.they_on_hold = True
                elif response[0] == "CALL_RESUME":
                    get_logger().log(logging.INFO, f"{self.dst_user.nick} resumed the call")
                    self.they_on_hold = False
                elif self.protocol != "V0" and response[0] == "CALL_CONGESTED":
                    get_logger().log(logging.INFO, f"{self.dst_user.nick} detected network congestion")
                    last_congested = default_timer()
                    self.video_client.extreme_compression = True
                elif response[0] == "CALL_END":
                    get_logger().log(logging.INFO, f"{self.dst_user.nick} ended the call")
                    self._call_end()
                    self.video_client.display_message("Call ended",
                                                      f"The user {self.dst_user.nick} has ended the call")
                    break
            except (ValueError, IndexError) as e:
                get_logger().log(logging.ERROR, f"Error receiving information from {self.dst_user.nick}: {e}")
