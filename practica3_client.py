import queue
import socket
from enum import Enum, auto
from os import _exit, getcwd
from queue import Queue
from threading import Thread, Semaphore, Lock
from time import sleep
from timeit import default_timer

import cv2
import numpy as np
from PIL import Image, ImageTk
from appJar import gui
from appJar.appjar import ItemLookupError

from new_call_control import CallControl
from configuration import Configuration, ConfigurationStatus
from discovery_server import list_users
from udp_helper import UDPBuffer, udp_datagram_from_msg, UDPDatagram
from user import CurrentUser

MAX_DATAGRAM_SIZE = 65_507


class CaptureMode(Enum):
    CAMERA = auto()
    VIDEO = auto()
    NOT_SET = auto()


class VideoClient:
    APP_NAME = "Samtale"
    APP_WIDTH = 800
    APP_HEIGHT = 525
    VIDEO_WIDTH = 640
    VIDEO_HEIGHT = 480

    REMEMBER_USER_CHECKBOX = "Remember me"
    REGISTER_SUBWINDOW = "Register"
    NICKNAME_WIDGET = "Nickname"
    PASSWORD_WIDGET = "Password"
    TCP_PORT_WIDGET = "TCP Port"
    UDP_PORT_WIDGET = "UDP Port"
    SUBMIT_BUTTON = "Submit"
    VIDEO_WIDGET_NAME = "video"
    CONNECT_BUTTON = "Connect"
    HOLD_BUTTON = "Hold"
    RESUME_BUTTON = "Resume"
    END_BUTTON = "End Call"
    REGISTER_BUTTON = "Register"
    USER_SELECTOR_WIDGET = "USER_SELECTOR_WIDGET"
    SELECT_VIDEO_BUTTON = "Select video"
    CLEAR_VIDEO_BUTTON = "Clear video"
    TYPE_NICKNAME_LABEL = "Type nickname:"

    def receive_video(self):
        while True:
            data, addr = self.receive_socket.recvfrom(MAX_DATAGRAM_SIZE)
            if self.call_control.should_video_flow() and addr[0] == self.call_control.get_send_address()[0]:
                udp_datagram = udp_datagram_from_msg(data)
                if self.udp_buffer.insert(udp_datagram):  # Release semaphore only is data was really inserted
                    self.video_semaphore.release()

    def capture_and_send_video(self):
        while True:
            start_time = default_timer()
            # Fetch webcam frame
            local_frame = self.get_frame()
            # Notify visualization thread
            self.camera_buffer.put(local_frame)
            self.video_semaphore.release()
            # Compress local frame to send it via the socket
            if self.call_control.should_video_flow():
                success, compressed_local_frame = cv2.imencode(".jpg", local_frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
                if not success:
                    raise Exception("Error compressing the image")
                compressed_local_frame = compressed_local_frame.tobytes()
                sequence_number = self.call_control.get_sequence_number()
                if sequence_number < 0:
                    continue

                fps = round(1 / (default_timer() - start_time))
                udp_datagram = UDPDatagram(sequence_number,
                                           f"{VideoClient.VIDEO_WIDTH}x{VideoClient.VIDEO_HEIGHT}",
                                           fps,
                                           compressed_local_frame).encode()

                assert (len(udp_datagram) <= MAX_DATAGRAM_SIZE)

                address = self.call_control.get_send_address()
                if address:
                    self.send_socket.sendto(udp_datagram, address)

    def __init__(self):
        self.gui = gui(VideoClient.APP_NAME, f"{VideoClient.APP_WIDTH}x{VideoClient.APP_HEIGHT}")
        self.gui.setResizable(False)
        self.gui.setGuiPadding(5)

        self.configuration = Configuration()

        self.send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.receive_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self.configuration.status == ConfigurationStatus.LOADED:
            self.receive_socket.bind(("0.0.0.0", CurrentUser().udp_port))

        # Select capturing mode TODO: handle camera not found
        self.capture_lock = Lock()
        self.capture_mode = CaptureMode.CAMERA
        # This will only be used in CaptureMode.VIDEO
        self.video_frame = 0
        self.video_fps = 0

        self.capture = cv2.VideoCapture(0)
        if not self.capture.isOpened():
            raise Exception("No camera detected")

        # Add widgets
        self.last_local_frame = cv2.cvtColor(self.get_frame(), cv2.COLOR_BGR2RGB)
        self.last_remote_frame = None
        self.gui.addImageData(VideoClient.VIDEO_WIDGET_NAME,
                              VideoClient.get_image(self.last_local_frame),
                              fmt="PhotoImage", row=0, column=1, rowspan=2)
        self.gui.addButtons([VideoClient.CONNECT_BUTTON,
                             VideoClient.SELECT_VIDEO_BUTTON,
                             VideoClient.HOLD_BUTTON,
                             VideoClient.END_BUTTON,
                             VideoClient.REGISTER_BUTTON], self.buttons_callback, row=2, column=0, colspan=2)

        if self.configuration.status == ConfigurationStatus.LOADED:
            self.gui.setButton(VideoClient.REGISTER_BUTTON, CurrentUser().nick)

        self.users = {user.nick: user for user in list_users()}
        nicks = list(self.users.keys())
        # self.gui.setStretch("both")
        self.gui.setStretch("column")
        self.gui.setSticky("nw")
        self.gui.addLabel(VideoClient.TYPE_NICKNAME_LABEL, VideoClient.TYPE_NICKNAME_LABEL, row=0, column=0)
        self.gui.setStretch("both")
        self.gui.setSticky("new")
        self.gui.addAutoEntry(VideoClient.USER_SELECTOR_WIDGET, nicks, row=1, column=0)

        # Initialize threads
        start_control_thread = self.configuration.status == ConfigurationStatus.LOADED
        self.call_control = CallControl(self, start_control_thread)
        self.video_semaphore = Semaphore()
        self.camera_buffer = Queue()
        self.udp_buffer = UDPBuffer()
        self.receiving_thread = Thread(target=self.receive_video, daemon=True)
        self.capture_thread = Thread(target=self.capture_and_send_video, daemon=True)
        self.visualization_thread = Thread(target=self.display_video, daemon=True)
        self.receiving_thread.start()
        self.capture_thread.start()
        self.visualization_thread.start()

        # Set end function to hung up call if X button is pressed
        self.gui.setStopFunction(self.stop)

    def start(self):
        self.gui.go()

    def stop(self) -> bool:
        if self.call_control.in_call():
            self.call_control.call_end()

        return True

    def get_frame(self):
        with self.capture_lock:
            success, frame = self.capture.read()
            if not success:
                raise Exception("Couldn't read video")

            if self.capture_mode == CaptureMode.CAMERA:
                frame = cv2.flip(frame, 1)
            elif self.capture_mode == CaptureMode.VIDEO:
                self.video_frame += 1

                if self.video_frame == self.capture.get(cv2.CAP_PROP_FRAME_COUNT):
                    self.video_frame = 0
                    self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)

                sleep(1 / self.video_fps)

            frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_AREA)

            return frame

    @staticmethod
    def get_image(frame):
        return ImageTk.PhotoImage(Image.fromarray(frame))

    def show_video(self, frame):
        self.gui.setImageData(VideoClient.VIDEO_WIDGET_NAME, self.get_image(frame), fmt="PhotoImage")

    def display_video(self):
        while True:
            self.video_semaphore.acquire()
            # Fetch webcam frame
            try:
                local_frame = cv2.cvtColor(self.camera_buffer.get(block=False), cv2.COLOR_BGR2RGB)
                self.last_local_frame = local_frame
            except queue.Empty:
                local_frame = self.last_local_frame
            # Fetch remote frame
            remote_frame, quality = self.udp_buffer.consume()
            if not remote_frame and self.call_control.in_call():
                remote_frame = self.last_remote_frame
            # Show local (and remote) frame
            if remote_frame:
                self.last_remote_frame = remote_frame
                remote_frame = np.frombuffer(remote_frame, np.uint8)
                remote_frame = cv2.imdecode(remote_frame, 1)
                remote_frame = cv2.cvtColor(remote_frame, cv2.COLOR_BGR2RGB)
                margin = 10
                mini_frame_width = VideoClient.VIDEO_WIDTH // 4
                mini_frame_height = VideoClient.VIDEO_HEIGHT // 4
                mini_frame = cv2.resize(local_frame, (mini_frame_width, mini_frame_height))
                remote_frame[-mini_frame_height - margin:-margin, -mini_frame_width - margin:-margin] = mini_frame
                self.show_video(remote_frame)
            elif not remote_frame:
                self.show_video(local_frame)

    def buttons_callback(self, name: str):
        """
        if name == VideoClient.CONNECT_BUTTON:
            remote_ip = self.gui.textBox("Connect", "Type the IP of the computer you want to connect to")
            try:
                IPv4Network(remote_ip)
                user = User("qwerty", "V0", CONTROL_PORT, ip=remote_ip)
                self.call_control = CallControl(user)
                self.dispatcher.set_call_control(self.call_control)
                self.call_control.call_start()
            except ValueError:
                pass
        """
        if name == VideoClient.REGISTER_BUTTON:
            if self.configuration.status != ConfigurationStatus.LOADED:
                try:
                    # Load the register window
                    self.gui.startSubWindow(VideoClient.REGISTER_SUBWINDOW)
                    self.gui.setSize(300, 200)

                    self.gui.addEntry(VideoClient.NICKNAME_WIDGET)
                    self.gui.setEntryDefault(VideoClient.NICKNAME_WIDGET, VideoClient.NICKNAME_WIDGET)
                    self.gui.addSecretEntry(VideoClient.PASSWORD_WIDGET)
                    self.gui.setEntryDefault(VideoClient.PASSWORD_WIDGET, VideoClient.PASSWORD_WIDGET)
                    self.gui.addNumericEntry(VideoClient.TCP_PORT_WIDGET)
                    self.gui.setEntryDefault(VideoClient.TCP_PORT_WIDGET, VideoClient.TCP_PORT_WIDGET)
                    self.gui.addNumericEntry(VideoClient.UDP_PORT_WIDGET)
                    self.gui.setEntryDefault(VideoClient.UDP_PORT_WIDGET, VideoClient.UDP_PORT_WIDGET)

                    self.gui.addCheckBox(VideoClient.REMEMBER_USER_CHECKBOX)
                    self.gui.setCheckBox(VideoClient.REMEMBER_USER_CHECKBOX)
                    self.gui.addButton(VideoClient.SUBMIT_BUTTON, self.buttons_callback)
                except ItemLookupError:
                    # The register window has already been launched in the session
                    pass

                self.gui.showSubWindow(VideoClient.REGISTER_SUBWINDOW)
            else:
                ret = self.gui.okBox(f"Registered as {CurrentUser().nick}",
                                     f"You are already registered:\n\n"
                                     f" · nickname:\t{CurrentUser().nick}\n"
                                     f" · TCP Port:\t{CurrentUser().tcp_port}\n"
                                     f" · UDP Port:\t{CurrentUser().udp_port}\n\n"
                                     f"Would you like to end your session? (this will delete your configuration file)")
                if ret:
                    self.configuration.delete()
                    self.gui.stop()

        elif name == VideoClient.HOLD_BUTTON:
            if self.call_control.in_call():
                if self.gui.getButton(VideoClient.HOLD_BUTTON) == VideoClient.HOLD_BUTTON:
                    self.call_control.call_hold()
                    self.gui.setButton(VideoClient.HOLD_BUTTON, VideoClient.RESUME_BUTTON)
                else:
                    self.call_control.call_resume()
                    self.gui.setButton(VideoClient.HOLD_BUTTON, VideoClient.HOLD_BUTTON)

        elif name == VideoClient.END_BUTTON:
            if self.call_control.in_call():
                self.call_control.call_end()
        elif name == VideoClient.CONNECT_BUTTON:
            if self.configuration.status == ConfigurationStatus.LOADED:
                self.call_control.call_start(self.gui.getEntry(VideoClient.USER_SELECTOR_WIDGET))
            elif self.configuration.status == ConfigurationStatus.NO_FILE:
                self.display_message("Registration needed",
                                     "You have to register since no configuration.ini was found at program launch")
            elif self.configuration.status == ConfigurationStatus.WRONG_PASSWORD:
                self.display_message("Registration needed",
                                     "You have to register again since the password provided in the configuration.ini "
                                     "file was not correct")
            elif self.configuration.status == ConfigurationStatus.WRONG_FILE:
                self.display_message("Registration needed",
                                     "You have to register again since an error occurred reading the configuration.ini "
                                     "file")
        elif name == VideoClient.SUBMIT_BUTTON:
            persistent = self.gui.getCheckBox(VideoClient.REMEMBER_USER_CHECKBOX)
            title, message = self.configuration.load(self.gui.getEntry(VideoClient.NICKNAME_WIDGET),
                                                     self.gui.getEntry(VideoClient.PASSWORD_WIDGET),
                                                     int(self.gui.getEntry(VideoClient.TCP_PORT_WIDGET)),
                                                     int(self.gui.getEntry(VideoClient.UDP_PORT_WIDGET)),
                                                     persistent=persistent)
            self.gui.hideSubWindow(VideoClient.REGISTER_SUBWINDOW)
            self.display_message(title, message)
            if self.configuration.status == ConfigurationStatus.LOADED:
                self.receive_socket.bind(("0.0.0.0", CurrentUser().udp_port))
                self.call_control.control_thread.start()
                self.gui.setButton(VideoClient.REGISTER_BUTTON, CurrentUser().nick)
        elif name == VideoClient.SELECT_VIDEO_BUTTON:
            if self.gui.getButton(VideoClient.SELECT_VIDEO_BUTTON) == VideoClient.SELECT_VIDEO_BUTTON:
                ret = self.gui.openBox(title="Select video file",
                                       dirName=getcwd(),
                                       multiple=False)
                if not ret:
                    return
                try:
                    capture = cv2.VideoCapture(ret)
                    success, _ = capture.read()
                    if not success:
                        self.display_message("File not valid",
                                             f"Could't open {ret} as a video file")
                        return
                    with self.capture_lock:
                        self.capture_mode = CaptureMode.VIDEO
                        self.capture = capture
                        self.video_frame = 1
                        self.video_fps = self.capture.get(cv2.CAP_PROP_FPS)
                        self.gui.setButton(VideoClient.SELECT_VIDEO_BUTTON, VideoClient.CLEAR_VIDEO_BUTTON)
                except FileNotFoundError as e:
                    print(e)
            else:
                answer = self.gui.yesNoBox("Clear video",
                                           "Are you sure you want to clear the video?")
                if answer:
                    with self.capture_lock:
                        self.capture = cv2.VideoCapture(0)
                        self.capture_mode = CaptureMode.CAMERA
                        self.gui.setButton(VideoClient.SELECT_VIDEO_BUTTON, VideoClient.SELECT_VIDEO_BUTTON)

    def incoming_call(self, username: str, ip: str) -> bool:
        accept = self.gui.yesNoBox("Incoming call",
                                   f"The user {username} is calling from {ip}. Do you want to accept the call?")

        return accept

    def display_message(self, title: str, message: str):
        self.gui.infoBox(title, message)

    def flush_buffer(self):
        # TODO race condition on udpbuffer
        del self.udp_buffer
        self.last_remote_frame = None
        self.last_local_frame = None
        self.udp_buffer = UDPBuffer()

    def display_calling(self, nick: str):
        self.gui.setButton(VideoClient.CONNECT_BUTTON,
                           f"Calling {nick}...")

    def display_in_call(self, nick: str):
        self.gui.setButton(VideoClient.CONNECT_BUTTON,
                           f"In a call with {nick}")

    def display_connect(self):
        self.gui.setButton(VideoClient.CONNECT_BUTTON,
                           VideoClient.CONNECT_BUTTON)
        self.gui.setButton(VideoClient.HOLD_BUTTON, VideoClient.HOLD_BUTTON)


if __name__ == '__main__':
    vc = VideoClient()
    vc.start()
    _exit(0)
