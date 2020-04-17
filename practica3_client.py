import socket
import cv2
from PIL import Image, ImageTk
from appJar import gui


class VideoClient(object):
    VIDEO_WIDGET_NAME = "video"

    def __init__(self, window_size):
        self.gui = gui("Skype", window_size)
        self.gui.setGuiPadding(5)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.capture = cv2.VideoCapture(0)
        if not self.capture.isOpened():
            raise Exception("No camera detected")
        self.gui.addImageData(VideoClient.VIDEO_WIDGET_NAME, VideoClient.get_image(self.get_frame()), fmt="PhotoImage")
        self.gui.setPollTime(20)
        self.gui.registerEvent(self.f)

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

    def f(self):
        frame = self.get_frame()
        self.show_video(frame)
        # Compress image to send it via the socket
        success, compressed_frame = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
        if not success:
            raise Exception("Error compressing the image")
        compressed_frame = compressed_frame.tobytes()
        # TODO: check that len(compressed_frame) <= 65_507 - cabecera

        bytes_sent = self.sock.sendto(compressed_frame, ("95.120.76.179", 1234))
        # print(f"Sent {bytes_sent} bytes")


if __name__ == '__main__':
    vc = VideoClient("640x520")

    vc.start()
