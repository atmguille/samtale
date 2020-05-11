import socket
from threading import Thread, Lock
from typing import Optional, Tuple
from timeit import default_timer

from decorators import run_in_thread
from discovery_server import get_user, UserUnknown, BadUser
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
        self.video_client = video_client
        # Control thread
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
        with self.call_lock:
            return self._in_call

    def waiting(self) -> bool:
        with self.call_lock:
            return self._waiting

    def should_video_flow(self) -> bool:
        return self.in_call() and not (self.we_on_hold or self.they_on_hold)

    def get_sequence_number(self) -> int:
        if self.in_call():
            self.sequence_number += 1
            return self.sequence_number

        return -1

    def get_send_address(self) -> Tuple[str, int]:
        return self.dst_user.ip, self.dst_user.udp_port

    def _call_start(self, nickname: str):
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
            self.video_client.display_message("Could not connect",
                                              f"Could not connect to {user.nick} at {user.ip}:{user.tcp_port}")
            with self.call_lock:
                self._waiting = False

            self.video_client.display_connect()
            return

        calling_str = f"CALLING {CurrentUser().nick} {CurrentUser().udp_port}"
        self.protocol = user.get_best_common_protocol()
        # If common protocol is greater than V0, append protocol to CALLING
        if self.protocol != "V0":
            calling_str += f" {self.protocol}"

        connection.send(calling_str.encode())
        try:
            response = connection.recv(CallControl.BUFFER_SIZE)
        except socket.timeout:
            # This exception only happened if the other user does not answer to our call
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
                self.video_client.display_message("Call denied",
                                                  f"The user {user.nick} denied the call")
                connection.close()
                self.video_client.display_connect()
                return
            elif response[0] == "CALL_BUSY":
                self.video_client.display_message("User busy",
                                                  f"The user {user.nick} is already in a call")
                connection.close()
                self.video_client.display_connect()
                return
            else:
                raise ValueError()
        except (ValueError, IndexError):
            self.video_client.display_message("Error establishing connection",
                                              f"Error establishing connection with{user.nick}")
            self.video_client.display_connect()
            connection.close()

    def call_start(self, nickname: str):
        self.call_lock.acquire()
        if self._in_call:
            self.call_lock.release()
            self.video_client.display_message("You are in a call",
                                              "You have to hang up in order to make a new call")
            return
        elif self._waiting:
            self.call_lock.release()
            self.video_client.display_message("You are making a call",
                                              "You have to cancel it in order to make a new call")
            return

        self._waiting = True
        self.video_client.display_calling(nickname)
        self.call_lock.release()

        Thread(target=self._call_start, args=(nickname,), daemon=True).start()

    def _call_end(self):
        self._in_call = False
        self._waiting = False
        self.we_on_hold = False
        self.they_on_hold = False
        self.sequence_number = 0
        self.protocol = None
        self.video_client.flush_buffer()
        self.call_socket.close()
        self.video_client.display_connect()

    @run_in_thread
    def call_end(self):
        self.call_socket.send(f"CALL_END {CurrentUser().nick}".encode())
        self._call_end()

    @run_in_thread
    def call_hold(self):
        self.we_on_hold = True
        self.call_socket.send(f"CALL_HOLD {CurrentUser().nick}".encode())

    @run_in_thread
    def call_resume(self):
        self.we_on_hold = False
        self.call_socket.send(f"CALL_RESUME {CurrentUser().nick}".encode())

    @run_in_thread
    def call_congested(self):
        # All protocols different to V0 should support this
        if self.protocol != "V0":
            self.call_socket.send(f"CALL_CONGESTED {CurrentUser().nick}".encode())

    def control_daemon(self):
        """
        Function executed by the listener, checking if someone is calling us. If we are already in a call,
        it answers CALL_BUSY to the incoming user. If we are available, builds a new CallControl, where
        the user can interact with the call (deny it, ...)
        :return:
        """
        sock = _open_tcp_socket(CurrentUser())
        sock.listen(1)
        while True:
            connection, client_address = sock.accept()
            connection.settimeout(3)

            try:
                response = connection.recv(BUFFER_SIZE).decode().split()

                self.call_lock.acquire()
                if self._in_call or self._waiting:
                    self.call_lock.release()
                    connection.send("CALL_BUSY".encode())
                    self.video_client.display_message(f"{response[1]} called you", f"{response[1]} called you")
                    continue

                if response[0] != "CALLING":
                    raise Exception("Error in received string")

                self.protocol = response[3] if len(response) > 3 else "V0"

                incoming_user = User(nick=response[1],
                                     # If V1 or +, CALLING has the protocol to be used in last argument
                                     protocols=self.protocol,
                                     tcp_port=client_address[1],
                                     ip=client_address[0],
                                     udp_port=int(response[2]))
                connection.settimeout(None)  # The connection should not be closed until wanted
                self.call_lock.release()
                accept = self.video_client.incoming_call(incoming_user.nick, incoming_user.ip)
                self.call_lock.acquire()
                if accept:
                    answer = f"CALL_ACCEPTED {CurrentUser().nick} {CurrentUser().udp_port}".encode()
                    connection.send(answer)
                    self._in_call = True
                    self.video_client.display_in_call(incoming_user.nick)
                    self.dst_user = incoming_user
                    self.call_socket = connection
                    self.call_thread = Thread(target=self.call_daemon, daemon=True)
                    self.call_thread.start()
                else:
                    connection.send(f"CALL_DENIED {CurrentUser().nick}".encode())
                self.call_lock.release()
            except (ValueError, IndexError):
                connection.send(f"CALL_DENIED {CurrentUser().nick}".encode())
                self.call_lock.release()

    def call_daemon(self):
        """
        Function that is executed by the listener. Checks if the call must be held, resumed or ended
        """

        last_congested = 0

        while True:
            if self.protocol != "V0":
                if last_congested and default_timer() - last_congested > CallControl.CONGESTED_INTERVAL:
                    # TODO
                    pass

            try:
                response = self.call_socket.recv(BUFFER_SIZE)
            except socket.error:
                self._call_end()
                break
            try:
                response = response.decode().split()
                if not response:
                    self._call_end()
                    break
                if response[0] == "CALL_HOLD":
                    self.they_on_hold = True
                elif response[0] == "CALL_RESUME":
                    self.they_on_hold = False
                elif self.protocol != "V0" and response[0] == "CALL_CONGESTED":
                    last_congested = default_timer()
                    # TODO
                    pass
                elif response[0] == "CALL_END":
                    self._call_end()
                    self.video_client.display_message("Call ended",
                                                      f"The user {self.dst_user.nick} has ended the call")
                    break
            except (ValueError, IndexError) as e:
                print(f"Error receiving information from client: {e}")
