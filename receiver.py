import socket

import cv2
import numpy as np
from PIL import Image, ImageTk
from appJar import gui

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
gui = gui("Receiver", "640x520")
sock.bind(("127.0.0.1", 1234))


def f():
    try:
        data, addr = sock.recvfrom(65_507)

        frame = cv2.imdecode(np.frombuffer(data, np.uint8), 1)
        image = ImageTk.PhotoImage(Image.fromarray(frame))
        gui.setImageData("video", image, fmt="PhotoImage")
    except socket.error:
        pass


data, addr = sock.recvfrom(65_507)
sock.setblocking(False)
frame = cv2.imdecode(np.frombuffer(data, np.uint8), 1)
image = ImageTk.PhotoImage(Image.fromarray(frame))
gui.addImageData("video", image, fmt="PhotoImage")
gui.setPollTime(10)
gui.registerEvent(f)
gui.go()
