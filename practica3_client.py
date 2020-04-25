import queue
import socket
from ipaddress import IPv4Network
from queue import Queue
from threading import Thread, Semaphore

import cv2
import numpy as np
from PIL import Image, ImageTk
from appJar import gui

from call_control import ControlDispatcher, CallControl
from udp_helper import UDPBuffer, udp_datagram_from_msg, UDPDatagram
from user import CurrentUser, User

VIDEO_PORT = 1234
CONTROL_PORT = 4321
MAX_DATAGRAM_SIZE = 65_507


class VideoClient(object):
    VIDEO_WIDGET_NAME = "video"
    CONNECT_BUTTON = "Connect"
    HOLD_BUTTON = "Hold"
    RESUME_BUTTON = "Resume"
    END_BUTTON = "End Call"

    def receive_video(self):
        while True:
            data, addr = self.receive_socket.recvfrom(MAX_DATAGRAM_SIZE)
            if self.call_control and addr[0] == self.call_control.dst_user.ip and self.call_control.should_video_flow():
                udp_datagram = udp_datagram_from_msg(data)
                if self.udp_buffer.insert(udp_datagram):  # Release semaphore only is data was really inserted
                    self.video_semaphore.release()

    def capture_and_send_video(self):
        sequence_number = 0
        while True:
            # Fetch webcam frame
            local_frame = self.get_frame()
            # Notify visualization thread
            self.camera_buffer.put(local_frame)
            self.video_semaphore.release()
            # Compress local frame to send it via the socket
            if self.call_control and self.call_control.should_video_flow():
                success, compressed_local_frame = cv2.imencode(".jpg", local_frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
                if not success:
                    raise Exception("Error compressing the image")
                compressed_local_frame = compressed_local_frame.tobytes()
                udp_datagram = UDPDatagram(sequence_number,
                                           f"{self.video_width}x{self.video_height}",
                                           30,
                                           compressed_local_frame).encode()

                assert (len(udp_datagram) <= MAX_DATAGRAM_SIZE)

                self.send_socket.sendto(udp_datagram, (self.call_control.dst_user.ip,
                                                       self.call_control.dst_user.udp_port))
                sequence_number += 1

    def __init__(self, window_size):
        self.gui = gui("Skype", window_size)
        self.gui.setGuiPadding(5)

        self.send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.receive_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.receive_socket.bind(("0.0.0.0", VIDEO_PORT))

        self.capture = cv2.VideoCapture(0)
        if not self.capture.isOpened():
            raise Exception("No camera detected")

        # Get dimensions of the video stream
        self.video_width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.video_height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # Add widgets
        self.last_local_frame = self.get_frame()
        self.gui.addImageData(VideoClient.VIDEO_WIDGET_NAME,
                              VideoClient.get_image(self.last_local_frame),
                              fmt="PhotoImage")
        self.gui.addButtons([VideoClient.CONNECT_BUTTON, VideoClient.END_BUTTON],
                            self.buttons_callback)

        # Initialize variables
        CurrentUser("daniel", "V0", CONTROL_PORT, "asdfasdf", VIDEO_PORT)
        self.dispatcher = ControlDispatcher(self.call_callback)
        self.call_control = None
        self.video_semaphore = Semaphore()
        self.camera_buffer = Queue()
        self.udp_buffer = UDPBuffer()
        self.receiving_thread = Thread(target=self.receive_video, daemon=True)
        self.capture_thread = Thread(target=self.capture_and_send_video, daemon=True)
        self.visualization_thread = Thread(target=self.display_video, daemon=True)
        self.receiving_thread.start()
        self.capture_thread.start()
        self.visualization_thread.start()

    def start(self):
        self.gui.go()

    def get_frame(self):
        success, frame = self.capture.read()
        if not success:
            raise Exception("Couldn't read from webcam")
        frame = cv2.flip(frame, 1)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return frame

    @staticmethod
    def get_image(frame):
        return ImageTk.PhotoImage(Image.fromarray(frame))

    def show_video(self, frame):
        self.gui.setImageData(VideoClient.VIDEO_WIDGET_NAME, self.get_image(frame), fmt="PhotoImage")

    def display_video(self):
        last_remote_frame = None
        while True:
            self.video_semaphore.acquire()
            # Fetch webcam frame
            try:
                local_frame = self.camera_buffer.get(block=False)
                self.last_local_frame = local_frame
            except queue.Empty:
                local_frame = self.last_local_frame
            # Fetch remote frame
            remote_frame, quality = self.udp_buffer.consume()
            if not remote_frame:
                remote_frame = last_remote_frame
            # Show local (and remote) frame
            if remote_frame:
                last_remote_frame = remote_frame
                remote_frame = cv2.imdecode(np.frombuffer(remote_frame, np.uint8), 1)
                margin = 10
                mini_frame_width = self.video_width // 4
                mini_frame_height = self.video_height // 4
                mini_frame = cv2.resize(local_frame, (mini_frame_width, mini_frame_height))
                remote_frame[-mini_frame_height - margin:-margin, -mini_frame_width - margin:-margin] = mini_frame
                self.show_video(remote_frame)
            elif not remote_frame or (self.call_control and not self.call_control.should_video_flow()):  # TODO: solucion temporal en caso de que la llamada esté parada
                self.show_video(local_frame)

    def buttons_callback(self, name: str):
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
        elif name == VideoClient.HOLD_BUTTON:
            self.call_control.call_hold()
            # TODO: intercambiar boton con resume y viceversa
        elif name == VideoClient.RESUME_BUTTON:
            self.call_control.call_resume()
        elif name == VideoClient.END_BUTTON:
            self.call_control.call_end()
            self.dispatcher.del_call_control()
            #self.call_control = None TODO creo que no hace falta

    def call_callback(self, username: str, ip: str) -> bool:
        accept = self.gui.yesNoBox("Incoming call",
                                   f"The user {username} is calling from {ip}. Do you want to accept the call?")
        if accept:
            self.call_control = self.dispatcher.current_call_control  # We are protected by the lock, so this is legal

        return accept


if __name__ == '__main__':
    vc = VideoClient("640x520")

    vc.start()
