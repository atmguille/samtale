from queue import Queue

import pyaudio
import socket
from threading import Thread

MAX_DATAGRAM_SIZE = 65_507

receive_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
receive_socket.bind(("0.0.0.0", 12345))
send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

send_queue = Queue()
receive_queue = Queue()

send_stream = pyaudio.PyAudio().open(format=pyaudio.paInt16,
                                     channels=2,
                                     rate=44100,
                                     input=True,
                                     frames_per_buffer=1024)

receive_stream = pyaudio.PyAudio().open(format=pyaudio.paInt16,
                                        channels=2,
                                        rate=44100,
                                        output=True,
                                        frames_per_buffer=1024)


def receive():
    while True:
        sound, addr = receive_socket.recvfrom(MAX_DATAGRAM_SIZE)
        receive_queue.put(sound)


def send():
    while True:
        chunk = send_queue.get()
        send_socket.sendto(chunk, ("83.39.57.22", 12345))


def record():
    while True:
        send_queue.put(send_stream.read(1024))


def play():
    while True:
        chunk = receive_queue.get()
        receive_stream.write(chunk, 1024)


record_thread = Thread(target=record, daemon=True)
play_thread = Thread(target=play, daemon=True)
send_thread = Thread(target=send, daemon=True)
receive_thread = Thread(target=receive, daemon=True)

record_thread.start()
send_thread.start()
receive_thread.start()
play_thread.start()