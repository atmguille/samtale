import time
from typing import Tuple
from enum import Enum, auto
from threading import Lock


class UDPDatagram:
    def __init__(self, seq_number: int, resolution: str, fps: float, data: bytes, ts: float = time.time()):
        self.seq_number = seq_number
        self.sent_ts = ts
        self.resolution = resolution
        self.fps = fps
        self.data = data
        self.received_ts = -1
        self.delay_ts = -1

    def set_received_time(self, ts: float):
        """
        Sets received time and computes datagram delay
        :param ts: received time
        """
        self.received_ts = ts
        self.delay_ts = self.received_ts - self.sent_ts

    def __str__(self):
        return f"{self.seq_number}#{self.sent_ts}#{self.resolution}#{self.fps}#" + self.data.decode()

    def encode(self) -> bytes:
        return f"{self.seq_number}#{self.sent_ts}#{self.resolution}#{self.fps}#".encode() + self.data


def udp_datagram_from_msg(message: bytes) -> UDPDatagram:
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


class BufferQuality(Enum):
    """
    Enum with the different types of quality (depending on packages lost, delays...)
    """
    SUPER_LOW = auto()
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()


class UDPBuffer:
    def __init__(self):
        self._buffer = []
        self.__last_seq_number = -1
        self.__mutex = Lock()
        self._buffer_quality = BufferQuality.SUPER_LOW
        self.__packages_lost = 0
        self.__delay_sum = 0

    def insert(self, datagram: UDPDatagram) -> bool:
        """
        Inserts the specified datagram in the buffer, preserving the order. It discards the datagram if it's too old
        :param datagram
        :return True if datagram is inserted, False if not
        """
        # TODO: Return if datagram was inserted or not
        datagram.set_received_time(time.time())

        with self.__mutex:
            # If datagram should have already been consumed, discard it
            if datagram.seq_number < self.__last_seq_number:
                return False

            buffer_len = len(self._buffer)

            # If buffer is currently empty
            if buffer_len == 0:
                self._buffer.append(datagram)
                self.__delay_sum += datagram.delay_ts
                self._buffer_quality = BufferQuality.LOW
                return True
            # If datagram should be the first element
            if self._buffer[0].seq_number > datagram.seq_number:
                self._buffer.insert(0, datagram)
                self.__delay_sum += datagram.delay_ts
                return True

            for i in range(buffer_len - 1, -1, -1):
                if self._buffer[i].seq_number < datagram.seq_number:
                    if i+1 < buffer_len:
                        self.__packages_lost -= 1  # Since package is inserted in the middle, there is one less lost
                    else:
                        self.__packages_lost += datagram.seq_number - self._buffer[i].seq_number - 1

                    self.__delay_sum += datagram.delay_ts
                    self._buffer.insert(i+1, datagram)
                    # Recompute buffer_quality TODO: pesos y score
                    score = self.__packages_lost + 10 * (self.__delay_sum / (buffer_len+1))
                    if score < 10:
                        self._buffer_quality = BufferQuality.HIGH
                    elif score < 100:
                        self._buffer_quality = BufferQuality.MEDIUM
                    else:
                        self._buffer_quality = BufferQuality.LOW
                    return True

    def consume(self) -> Tuple[bytes, BufferQuality]:
        """
        Consumes first datagram of the buffer, returning its data and the current buffer quality
        :return: consumed_datagram.data, quality
        """
        with self.__mutex:
            if not self._buffer:
                # TODO: probar last_seq_number += 1
                return bytes(), BufferQuality.SUPER_LOW

            consumed_datagram = self._buffer.pop(0)
            self.__last_seq_number = consumed_datagram.seq_number
            self.__delay_sum -= consumed_datagram.delay_ts
            quality = self._buffer_quality

            if not self._buffer:
                self._buffer_quality = BufferQuality.SUPER_LOW
            else:
                self.__packages_lost -= self._buffer[0].seq_number - consumed_datagram.seq_number - 1

            return consumed_datagram.data, quality
