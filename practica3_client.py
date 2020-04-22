import socket
from ipaddress import IPv4Network

import cv2
import numpy as np
from PIL import Image, ImageTk
from appJar import gui

PORT = 1234
MAX_DATAGRAM_SIZE = 65_507


class VideoClient(object):
    VIDEO_WIDGET_NAME = "video"
    CONNECT_BUTTON = "Connect"

    def __init__(self, window_size):
        self.gui = gui("Skype", window_size)
        self.gui.setGuiPadding(5)

        self.send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.receive_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.receive_socket.bind(("0.0.0.0", PORT))
        self.receive_socket.setblocking(False)

        self.capture = cv2.VideoCapture(0)
        if not self.capture.isOpened():
            raise Exception("No camera detected")

        # Get dimensions of the video stream
        self.video_width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.video_height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # Add widgets
        self.gui.addImageData(VideoClient.VIDEO_WIDGET_NAME, VideoClient.get_image(self.get_frame()), fmt="PhotoImage")
        self.gui.addButton(VideoClient.CONNECT_BUTTON, self.buttons_callback)

        # Register repeating function
        self.gui.setPollTime(20)
        self.gui.registerEvent(self.repeating_function)

        # Initialize variables
        self.remote_ip = None

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

    def repeating_function(self):
        remote_frame = None
        # Get video stream from socket
        try:
            data, addr = self.receive_socket.recvfrom(MAX_DATAGRAM_SIZE)
            remote_frame = cv2.imdecode(np.frombuffer(data, np.uint8), 1)
        except BlockingIOError:
            # No one has sent us data yet
            pass

        # Display local (and remote) frame(s)
        local_frame = self.get_frame()
        if remote_frame is not None:
            margin = 10
            mini_frame_width = self.video_width // 4
            mini_frame_height = self.video_height // 4
            mini_frame = cv2.resize(local_frame, (mini_frame_width, mini_frame_height))
            remote_frame[-mini_frame_height - margin:-margin, -mini_frame_width - margin:-margin] = mini_frame
            self.show_video(remote_frame)
        else:
            self.show_video(local_frame)

        # Compress local frame to send it via the socket
        if self.remote_ip:
            success, compressed_local_frame = cv2.imencode(".jpg", local_frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
            if not success:
                raise Exception("Error compressing the image")
            compressed_local_frame = compressed_local_frame.tobytes()
            # TODO: check that len(compressed_frame) <= 65_507 - cabecera

            bytes_sent = self.send_socket.sendto(compressed_local_frame, (self.remote_ip, 1234))
            # print(f"Sent {bytes_sent} bytes")

    def buttons_callback(self, name: str):
        if name == VideoClient.CONNECT_BUTTON:
            remote_ip = self.gui.textBox("Connect", "Type the IP of the computer you want to connect to")
            try:
                IPv4Network(remote_ip)
                self.remote_ip = remote_ip
            except ValueError:
                pass


if __name__ == '__main__':
    vc = VideoClient("640x520")

    vc.start()
