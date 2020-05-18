import queue
import socket
import argparse
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

from call_control import CallControl
from configuration import Configuration, ConfigurationStatus
from discovery_server import list_users
from udp_helper import UDPBuffer, udp_datagram_from_msg, UDPDatagram, BufferQuality
from user import CurrentUser
from logger import get_logger, set_logger

MAX_DATAGRAM_SIZE = 65_507


class CaptureMode(Enum):
    # The video is provided by a webcam (video0 by default)
    CAMERA = auto()
    # The video is provided by a file
    FILE = auto()
    # There's no video, just an image showing that there's no webcam (on video0)
    NO_CAMERA = auto()


class VideoClient:
    APP_NAME = "Samtale"
    APP_WIDTH = 850
    APP_HEIGHT = 550
    VIDEO_WIDTH = 640
    VIDEO_HEIGHT = 480

    # On V1+, the CALL_CONGESTED message will be sent at most once every CONGEST_INTERVAL seconds
    CONGESTED_INTERVAL = 30
    # On NO_CAMERA mode, the static image will be set NO_CAMERA_FPS per second
    NO_CAMERA_FPS = 30
    NO_CAMERA_IMAGE = "no_camera.bmp"

    # Widgets
    SUBMIT_BUTTON = "Submit"
    CONNECT_BUTTON = "Connect"
    HOLD_BUTTON = "Hold"
    RESUME_BUTTON = "Resume"
    END_BUTTON = "End Call"
    REGISTER_BUTTON = "Register"
    SELECT_VIDEO_BUTTON = "Select video"
    CLEAR_VIDEO_BUTTON = "Clear video"
    NICKNAME_ENTRY = "Nickname"
    PASSWORD_ENTRY = "Password"
    TCP_PORT_ENTRY = "TCP Port"
    UDP_PORT_ENTRY = "UDP Port"
    REMEMBER_USER_CHECKBOX = "Remember me"
    PRIVATE_IP_CHECKBOX = "Use private ip?"
    TYPE_NICKNAME_LABEL = "Type nickname:"
    REGISTER_SUBWINDOW = "Register"
    VIDEO_WIDGET_NAME = "video"
    USER_SELECTOR_WIDGET = "USER_SELECTOR_WIDGET"

    def __init__(self):
        """
        Initializes the GUI, reads the configuration and creates the necessary threads and sockets
        """
        self.gui = gui(VideoClient.APP_NAME, f"{VideoClient.APP_WIDTH}x{VideoClient.APP_HEIGHT}", handleArgs=False)
        self.gui.setLogLevel("WARNING")
        self.gui.setResizable(False)
        self.gui.setGuiPadding(5)

        self.configuration = Configuration()

        # The extreme compression mode will be activated when congestion has been detected
        self.extreme_compression = False

        self.send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.receive_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self.configuration.status == ConfigurationStatus.LOADED:
            self.receive_socket.bind(("0.0.0.0", CurrentUser().udp_port))

        # Select capturing mode
        self.capture_lock = Lock()
        self.capture_mode = CaptureMode.CAMERA
        # This will only be used in CaptureMode.VIDEO
        self.video_current_frame = 0

        self.capture = cv2.VideoCapture(0)
        self.no_camera = cv2.imread(VideoClient.NO_CAMERA_IMAGE)
        if not self.capture.isOpened():
            get_logger().info("No camera mode enabled")
            self.capture_mode = CaptureMode.NO_CAMERA
            self.fps = VideoClient.NO_CAMERA_FPS
        else:
            get_logger().info("Camera mode enabled")
            self.fps = int(self.capture.get(cv2.CAP_PROP_FPS))

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
        self.gui.setStretch("column")
        self.gui.setSticky("nw")
        self.gui.addLabel(VideoClient.TYPE_NICKNAME_LABEL, VideoClient.TYPE_NICKNAME_LABEL, row=0, column=0)
        self.gui.setStretch("both")
        self.gui.setSticky("new")
        self.gui.addAutoEntry(VideoClient.USER_SELECTOR_WIDGET, nicks, row=1, column=0)
        self.gui.addStatusbar(fields=4)
        self.gui.setStatusbar("Call Quality: N/A", 0)
        self.gui.setStatusbar("Packages lost: N/A", 1)
        self.gui.setStatusbar("Delay avg: N/A", 2)
        self.gui.setStatusbar("Jitter: N/A", 3)

        # Initialize threads
        start_control_thread = self.configuration.status == ConfigurationStatus.LOADED
        self.call_control = CallControl(self, start_control_thread)
        self.video_semaphore = Semaphore()
        self.camera_buffer = Queue()
        self.udp_buffer = UDPBuffer(self.video_semaphore)
        self.receiving_thread = Thread(target=self.receive_video, daemon=True)
        self.capture_thread = Thread(target=self.capture_and_send_video, daemon=True)
        self.visualization_thread = Thread(target=self.display_video, daemon=True)
        self.receiving_thread.start()
        self.capture_thread.start()
        self.visualization_thread.start()

        # Set end function to hung up call if X button is pressed
        self.gui.setStopFunction(self.stop)

    def receive_video(self):
        """
        This function will receive data from the UDP socket. After checking that the video should indeed flow
        (a not-that-good-programmed client might send us video even if the video is on pause), it inserts the datagram
        into the UDPBuffer. This function is meant to be run on a separate thread.
        """
        while True:
            data, addr = self.receive_socket.recvfrom(MAX_DATAGRAM_SIZE)
            if self.call_control.should_video_flow() and addr[0] == self.call_control.get_send_address()[0]:
                udp_datagram = udp_datagram_from_msg(data)
                self.udp_buffer.insert(udp_datagram)

    def capture_and_send_video(self):
        """
        This function will capture video from the preferred source (webcam, file or static image), insert it into a
        queue (so the visualization thread can play it) and send it to the other end in the case that we are in a call
        and the video should flow. This function is meant to be run on a separate thread.
        """
        while True:
            # Fetch webcam frame
            local_frame = self.get_frame()
            # Notify visualization thread
            self.camera_buffer.put(local_frame)
            self.video_semaphore.release()
            # Compress local frame to send it via the socket
            if self.call_control.should_video_flow():
                if self.extreme_compression:
                    # If the connection quality is not that good, we shrink the image that we'll send
                    video_width = VideoClient.VIDEO_WIDTH // 2
                    video_height = VideoClient.VIDEO_HEIGHT // 2
                    local_frame = cv2.resize(local_frame, (video_width, video_height))
                else:
                    video_width = VideoClient.VIDEO_WIDTH
                    video_height = VideoClient.VIDEO_HEIGHT

                success, compressed_local_frame = cv2.imencode(".jpg", local_frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
                if not success:
                    get_logger().error("Error compressing a frame")
                    sleep(1 / self.fps)
                    continue
                compressed_local_frame = compressed_local_frame.tobytes()
                sequence_number = self.call_control.get_sequence_number()
                if sequence_number < 0:
                    continue

                udp_datagram = UDPDatagram(sequence_number,
                                           f"{video_width}x{video_height}",
                                           self.fps,
                                           compressed_local_frame).encode()

                assert (len(udp_datagram) <= MAX_DATAGRAM_SIZE)

                address = self.call_control.get_send_address()
                if address:
                    self.send_socket.sendto(udp_datagram, address)

            sleep(1 / self.fps)

    def start(self):
        """
        Runs the GUI. This function won't return until the X is pressed
        """
        self.gui.go()

    def stop(self) -> bool:
        """
        This function will be called just before the GUI closes
        :return: true (so the GUI will definitely close)
        """
        get_logger().info(f"Closing {VideoClient.APP_NAME}")

        if self.call_control.in_call():
            self.call_control.call_end()
        # Close sockets
        if self.call_control.control_socket is not None:
            self.call_control.control_socket.close()
        self.send_socket.close()
        self.receive_socket.close()

        return True

    def get_frame(self):
        """
        Captures a frame using the selected capture mode.
        :return:
        """
        with self.capture_lock:
            if self.capture_mode == CaptureMode.NO_CAMERA:
                frame = self.no_camera
            else:
                success, frame = self.capture.read()
                if not success:
                    frame = self.no_camera
                else:
                    if self.capture_mode == CaptureMode.CAMERA:
                        # Flip the image so it has the natural orientation
                        frame = cv2.flip(frame, 1)
                    elif self.capture_mode == CaptureMode.FILE:
                        # Update the current video frame number
                        self.video_current_frame += 1

                        # If the reached the end of the video file, we'll start back again
                        if self.video_current_frame == self.capture.get(cv2.CAP_PROP_FRAME_COUNT):
                            self.video_current_frame = 0
                            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)

            return cv2.resize(frame, (VideoClient.VIDEO_WIDTH, VideoClient.VIDEO_HEIGHT), interpolation=cv2.INTER_AREA)

    @staticmethod
    def get_image(frame):
        """
        :param frame: a frame returned by the get_frame function
        :return: an image that can be displayed on the GUI
        """
        return ImageTk.PhotoImage(Image.fromarray(frame))

    def display_frame(self, frame):
        """
        Displays the frame on the GUI
        :param frame: a frame returned by the get_frame function
        """
        self.gui.setImageData(VideoClient.VIDEO_WIDGET_NAME, self.get_image(frame), fmt="PhotoImage")

    def display_video(self):
        """
        This function is meant to run on a separate thread. It will block until someone wakes it (the capture_video
        thread or the waker thread). Two "frozen" frames are stored, one for the local one and one for the remote one.
        If data cannot be consumed from the local video feed or from the UDPBuffer, a frozen frame will be shown. If
        we are in a call, our image will be shown in a small rectangle at the bottom right (with 1/16th of the original
        area). It will also check if the buffer quality is bad in order to take measures (which will vary of with the
        protocol version being used)
        """
        # Do first acquire so next one is blocking
        self.video_semaphore.acquire()
        last_congested = 0
        while True:
            self.video_semaphore.acquire()
            # Fetch webcam frame
            try:
                local_frame = cv2.cvtColor(self.camera_buffer.get(block=False), cv2.COLOR_BGR2RGB)
                self.last_local_frame = local_frame
            except queue.Empty:
                local_frame = self.last_local_frame
            # Fetch remote frame
            remote_frame = self.udp_buffer.consume()
            quality, packages_lost, delay_avg, jitter = self.udp_buffer.get_statistics()
            # If we are using V0, decrease our video quality (assuming that the connection is symmetric)
            # If V1 (or higher) is used, we will send a CALL_CONGESTED to the other end
            if self.call_control.in_call() and quality < BufferQuality.MEDIUM:
                if self.call_control.protocol == "V0":
                    self.extreme_compression = True
                else:
                    now = default_timer()
                    if now - last_congested > VideoClient.CONGESTED_INTERVAL:
                        last_congested = now
                        self.call_control.call_congested()
            else:
                self.extreme_compression = False

            if not remote_frame and self.call_control.in_call():
                remote_frame = self.last_remote_frame
            # Show local (and remote) frame
            if remote_frame:
                self.last_remote_frame = remote_frame
                remote_frame = np.frombuffer(remote_frame, np.uint8)
                remote_frame = cv2.imdecode(remote_frame, 1)
                remote_frame = cv2.resize(remote_frame, (VideoClient.VIDEO_WIDTH, VideoClient.VIDEO_HEIGHT))
                remote_frame = cv2.cvtColor(remote_frame, cv2.COLOR_BGR2RGB)
                margin = 10
                mini_frame_width = VideoClient.VIDEO_WIDTH // 4
                mini_frame_height = VideoClient.VIDEO_HEIGHT // 4
                mini_frame = cv2.resize(local_frame, (mini_frame_width, mini_frame_height))
                remote_frame[-mini_frame_height - margin:-margin, -mini_frame_width - margin:-margin] = mini_frame

                self.gui.setStatusbar(f"Call Quality: {quality.name}", 0)
                self.gui.setStatusbar(f"Packages lost: {packages_lost}", 1)
                self.gui.setStatusbar(f"Delay avg: {round(delay_avg, ndigits=2)} ms", 2)
                self.gui.setStatusbar(f"Jitter: {round(jitter, ndigits=2)} ms", 3)

                self.display_frame(remote_frame)
            elif not remote_frame:
                self.gui.setStatusbar("Call Quality: N/A", 0)
                self.gui.setStatusbar("Packages lost: N/A", 1)
                self.gui.setStatusbar("Delay avg: N/A", 2)
                self.gui.setStatusbar("Jitter: N/A", 3)
                self.display_frame(local_frame)

    def buttons_callback(self, name: str):
        """
        All buttons have this function as callback
        :param name: name of the button
        """
        if name == VideoClient.REGISTER_BUTTON:
            if self.configuration.status != ConfigurationStatus.LOADED:
                get_logger().info("Opening register window")
                try:
                    # Load the register window
                    self.gui.startSubWindow(VideoClient.REGISTER_SUBWINDOW)
                    self.gui.setSize(300, 200)

                    self.gui.addEntry(VideoClient.NICKNAME_ENTRY)
                    self.gui.setEntryDefault(VideoClient.NICKNAME_ENTRY, VideoClient.NICKNAME_ENTRY)
                    self.gui.addSecretEntry(VideoClient.PASSWORD_ENTRY)
                    self.gui.setEntryDefault(VideoClient.PASSWORD_ENTRY, VideoClient.PASSWORD_ENTRY)
                    self.gui.addNumericEntry(VideoClient.TCP_PORT_ENTRY)
                    self.gui.setEntryDefault(VideoClient.TCP_PORT_ENTRY, VideoClient.TCP_PORT_ENTRY)
                    self.gui.addNumericEntry(VideoClient.UDP_PORT_ENTRY)
                    self.gui.setEntryDefault(VideoClient.UDP_PORT_ENTRY, VideoClient.UDP_PORT_ENTRY)

                    self.gui.addCheckBox(VideoClient.REMEMBER_USER_CHECKBOX)
                    self.gui.setCheckBox(VideoClient.REMEMBER_USER_CHECKBOX)
                    self.gui.addCheckBox(VideoClient.PRIVATE_IP_CHECKBOX)
                    self.gui.addButton(VideoClient.SUBMIT_BUTTON, self.buttons_callback)
                except ItemLookupError:
                    # The register window has already been launched in the session
                    pass

                self.gui.showSubWindow(VideoClient.REGISTER_SUBWINDOW)
            else:
                get_logger().info("Opening profile window")
                ret = self.gui.okBox(f"Registered as {CurrentUser().nick}",
                                     f"You are already registered:\n\n"
                                     f" · nickname:\t{CurrentUser().nick}\n"
                                     f" · IP:\t{CurrentUser().ip}\n"
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
                nickname = self.gui.getEntry(VideoClient.USER_SELECTOR_WIDGET)
                if nickname == CurrentUser().nick:
                    get_logger().info("Blocked attempt to call ourselves")
                    self.display_message("Not Allowed", "You can't call yourself!")
                else:
                    self.call_control.call_start(nickname)
            elif self.configuration.status == ConfigurationStatus.NO_FILE:
                get_logger().info("Cannot call before registering (no configuration file found)")
                self.display_message("Registration needed",
                                     "You have to register since no configuration.ini was found at program launch")
            elif self.configuration.status == ConfigurationStatus.WRONG_PASSWORD:
                get_logger().info("Cannot call before registering (last time a wrong password was provided)")
                self.display_message("Registration needed",
                                     "You have to register again since the password provided in the configuration.ini "
                                     "file was not correct")
            elif self.configuration.status == ConfigurationStatus.WRONG_FILE:
                get_logger().info("Cannot call before registering (the file read last time wasn't correct)")
                self.display_message("Registration needed",
                                     "You have to register again since an error occurred reading the configuration.ini "
                                     "file")

        elif name == VideoClient.SUBMIT_BUTTON:
            persistent = self.gui.getCheckBox(VideoClient.REMEMBER_USER_CHECKBOX)
            private_ip = self.gui.getCheckBox(VideoClient.PRIVATE_IP_CHECKBOX)
            title, message = self.configuration.load(self.gui.getEntry(VideoClient.NICKNAME_ENTRY),
                                                     self.gui.getEntry(VideoClient.PASSWORD_ENTRY),
                                                     int(self.gui.getEntry(VideoClient.TCP_PORT_ENTRY)),
                                                     int(self.gui.getEntry(VideoClient.UDP_PORT_ENTRY)),
                                                     persistent=persistent,
                                                     private_ip=private_ip)
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
                    get_logger().info("No video file selected")
                    return
                try:
                    capture = cv2.VideoCapture(ret)
                    success, _ = capture.read()
                    if not success:
                        get_logger().warning(f"Couldn't open {ret} as a video file")
                        self.display_message("File not valid",
                                             f"Could't open {ret} as a video file")
                        return
                    with self.capture_lock:
                        get_logger().info(f"File {ret} loaded")
                        self.capture_mode = CaptureMode.FILE
                        self.capture = capture
                        self.video_current_frame = 1
                        self.fps = int(self.capture.get(cv2.CAP_PROP_FPS))
                        self.gui.setButton(VideoClient.SELECT_VIDEO_BUTTON, VideoClient.CLEAR_VIDEO_BUTTON)
                except FileNotFoundError as e:
                    print(e)
            else:
                answer = self.gui.yesNoBox("Clear video",
                                           "Are you sure you want to clear the video?")
                if answer:
                    with self.capture_lock:
                        self.capture = cv2.VideoCapture(0)
                        if not self.capture.isOpened():
                            get_logger().info("No camera mode enabled")
                            self.capture_mode = CaptureMode.NO_CAMERA
                            self.fps = VideoClient.NO_CAMERA_FPS
                        else:
                            get_logger().info("Camera mode enabled")
                            self.fps = int(self.capture.get(cv2.CAP_PROP_FPS))
                            self.capture_mode = CaptureMode.CAMERA

                        self.gui.setButton(VideoClient.SELECT_VIDEO_BUTTON, VideoClient.SELECT_VIDEO_BUTTON)
                else:
                    get_logger().info("Video was not cleared")

    def incoming_call(self, nickname: str, ip: str) -> bool:
        """
        This function will be called when there's an incoming call
        :param nickname: nickname of the user
        :param ip: the actual IP address of the user
        :return: true if the call is accepted and false otherwise
        """
        accept = self.gui.yesNoBox("Incoming call",
                                   f"The user {nickname} is calling from {ip}. Do you want to accept the call?")

        return accept

    def display_message(self, title: str, message: str):
        """
        Displays a message on the GUI
        :param title: title of the window that will be created
        :param message: message that will be displayed
        """
        self.gui.infoBox(title, message)

    def flush_buffer(self):
        """
        This function will be called when a call ends. It will flush the UDPBuffer and delete the "frozen" remote frame
        """
        get_logger().debug("Flushing buffer")
        del self.udp_buffer
        self.last_remote_frame = None
        self.udp_buffer = UDPBuffer(self.video_semaphore)

    def display_calling(self, nickname: str):
        """
        This function will be called when calling someone.
        Changes the connect button name to: Calling <nickname>
        :param nickname: nickname of the user that is being called
        """
        self.gui.setButton(VideoClient.CONNECT_BUTTON,
                           f"Calling {nickname}...")

    def display_in_call(self, nickname: str):
        """
        This function will be called when a call is stablished.
        Changes the connect button name to: In a call with <nickname>
        :param nickname: nickname of the user whom the are talking to
        """
        self.gui.setButton(VideoClient.CONNECT_BUTTON,
                           f"In a call with {nickname}")

    def display_connect(self):
        """
        This function will be called when a call ends. Changes the connect and hold buttons names to the default ones.
        :return:
        """
        self.gui.setButton(VideoClient.CONNECT_BUTTON,
                           VideoClient.CONNECT_BUTTON)
        self.gui.setButton(VideoClient.HOLD_BUTTON, VideoClient.HOLD_BUTTON)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Samtale')

    parser.add_argument('-log_level', action='store', nargs='?', default='info',
                        choices=['debug', 'info', 'warning', 'error'], required=False,
                        help='Indicate logging level')

    args = parser.parse_args()

    set_logger(args)
    VideoClient().start()
    _exit(0)
