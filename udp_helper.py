from time import sleep, time
from timeit import default_timer
from typing import Tuple
from functools import total_ordering
from enum import Enum, auto
from threading import Lock, Semaphore, Thread

from logger import get_logger


class UDPDatagram:
    def __init__(self, seq_number: int, resolution: str, fps: float, data: bytes, ts: float = None):
        """
        Constructor
        :param seq_number
        :param resolution
        :param fps
        :param data
        :param ts: timestamp. If not specified, it will be set to time.time()
        """
        self.seq_number = seq_number
        self.sent_ts = ts if ts is not None else time()
        self.resolution = resolution
        self.fps = fps
        self.data = data
        self.received_ts = -1
        self.delay_ts = -1  # Measured in ms

    def set_received_time(self):
        """
        Sets received time and computes datagram delay
        """
        self.received_ts = time()
        self.delay_ts = (self.received_ts - self.sent_ts) * 1000

    def __str__(self):
        return f"{self.seq_number}#{self.sent_ts}#{self.resolution}#{self.fps}#" + self.data.decode()

    def encode(self) -> bytes:
        return f"{self.seq_number}#{self.sent_ts}#{self.resolution}#{self.fps}#".encode() + self.data


def udp_datagram_from_msg(message: bytes) -> UDPDatagram:
    """
    Builds a UDPDatagram object from a message
    :param message
    :return: UDPDatagram object built
    """
    # Find the fourth '#' to split the message (we cannot use split because the binary data could contain '#')
    count = 0
    for index, c in enumerate(map(chr, message)):
        if c == '#':
            count += 1
            if count == 4:
                fields = message[:index].decode().split('#')
                data = message[index + 1:]
                return UDPDatagram(seq_number=int(fields[0]), ts=float(fields[1]), resolution=fields[2],
                                   fps=float(fields[3]), data=data)


@total_ordering
class BufferQuality(Enum):
    """
    Enum with the different types of quality (depending on packages lost, delays...)
    """
    SUPER_LOW = auto()
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.value < other.value
        return NotImplemented


class UDPBuffer:
    MINIMUM_INITIAL_FRAMES = 5
    U = 0.01
    BUFFER_MAX = 5
    CONSUME_SPEEDUP = 1.5

    def __init__(self, display_video_semaphore: Semaphore):
        """
        Constructor
        :param display_video_semaphore: semaphore to be released when displayer should consume
        """
        self._buffer = []
        self.__last_seq_number = 0
        self.__mutex = Lock()
        self._buffer_quality = BufferQuality.MEDIUM
        self.__num_holes = 0  # Number of missing packages in the buffer
        self.__packages_lost = 0
        self.__avg_delay = 0  # Measured in ms
        self.__jitter = 0
        self.__initial_frames = 0
        self.__time_between_frames = 0
        self.__last_consumed = None
        self.__waker_continue = True
        self.display_video_semaphore = display_video_semaphore

    def __del__(self):
        self.__waker_continue = False

    def wake_displayer(self):
        """
        Tells the displayer it should display video according to computed fps
        """
        while self.__waker_continue:
            self.display_video_semaphore.release()
            sleep(self.__time_between_frames)

    def get_statistics(self) -> Tuple[BufferQuality, int, float, float]:
        """
        :return: buffer quality, packages lost, average delay, jitter
        """
        return self._buffer_quality, self.__packages_lost, self.__avg_delay, self.__jitter

    def insert(self, datagram: UDPDatagram) -> bool:
        """
        Inserts the specified datagram in the buffer, preserving the order. It discards the datagram if it's too old
        :param datagram
        :return True if datagram is inserted, False if not
        """
        datagram.set_received_time()

        with self.__mutex:
            # If datagram should have already been consumed, discard it
            if datagram.seq_number < self.__last_seq_number:
                return False

            # Update time_between_frames
            self.__time_between_frames = UDPBuffer.U*1/datagram.fps + (1 - UDPBuffer.U)*self.__time_between_frames

            buffer_len = len(self._buffer)
            if buffer_len >= UDPBuffer.BUFFER_MAX:
                self.__time_between_frames /= UDPBuffer.CONSUME_SPEEDUP

            if self.__initial_frames < UDPBuffer.MINIMUM_INITIAL_FRAMES:
                self.__initial_frames += 1
                if self.__initial_frames == 1:
                    self.__avg_delay = datagram.delay_ts
                if self.__initial_frames == UDPBuffer.MINIMUM_INITIAL_FRAMES:
                    # If we are ready to start playing, start the waker thread
                    Thread(target=self.wake_displayer, daemon=True).start()

            # If buffer is currently empty
            if buffer_len == 0:
                self._buffer.append(datagram)

            # If datagram should be the first element
            elif self._buffer[0].seq_number > datagram.seq_number:
                self.__num_holes += self._buffer[0].seq_number - datagram.seq_number - 1
                self._buffer.insert(0, datagram)

            else:
                for i in range(buffer_len - 1, -1, -1):
                    if self._buffer[i].seq_number < datagram.seq_number:
                        if i + 1 < buffer_len:
                            self.__num_holes -= 1  # Since package is inserted in the middle, there is one less lost
                        else:
                            self.__num_holes += datagram.seq_number - self._buffer[i].seq_number - 1

                        self._buffer.insert(i + 1, datagram)
                        break

            self.__avg_delay = (1 - UDPBuffer.U)*self.__avg_delay + UDPBuffer.U*datagram.delay_ts
            self.__jitter = (1 - UDPBuffer.U)*self.__jitter + UDPBuffer.U*abs(datagram.delay_ts - self.__avg_delay)

            # Recompute buffer_quality  # TODO: definitivo???
            score = 5 * self.__num_holes + 2 * self.__packages_lost/(datagram.seq_number+1)
            if 150 < self.__avg_delay < 300:
                score += 10
            elif self.__avg_delay > 300:
                score += 30

            if score < 5:
                self._buffer_quality = BufferQuality.HIGH
            elif score < 20:
                self._buffer_quality = BufferQuality.MEDIUM
            else:
                self._buffer_quality = BufferQuality.LOW
            return True

    def consume(self) -> bytes:
        """
        Consumes first datagram of the buffer, returning its data and updating buffer statistics
        :return: consumed_datagram.data
        """
        with self.__mutex:
            now = default_timer()
            if self.__last_consumed is not None and now - self.__last_consumed < self.__time_between_frames:
                return bytes()

            if not self._buffer or self.__initial_frames < UDPBuffer.MINIMUM_INITIAL_FRAMES:
                return bytes()

            # Update last time consumed
            self.__last_consumed = now

            consumed_datagram = self._buffer.pop(0)
            # Update packages that have been definitely lost
            self.__packages_lost += consumed_datagram.seq_number - self.__last_seq_number - 1
            self.__last_seq_number = consumed_datagram.seq_number

            if self._buffer:
                self.__num_holes -= self._buffer[0].seq_number - consumed_datagram.seq_number - 1

            return consumed_datagram.data
