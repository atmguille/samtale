import time
from typing import List, Tuple
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
        return f"{self.seq_number}#{self.sent_ts}#{self.resolution}#{self.fps}#{self.data}"


def udp_datagram_from_msg(message: str) -> UDPDatagram:
    fields = message.split('#')
    return UDPDatagram(seq_number=int(fields[0]), ts=float(fields[1]), resolution=fields[2],
                       fps=float(fields[3]), data=fields[4].encode())


class BufferQuality(Enum):
    """
    Enum with the different types of quality (depending on datagrams lost, delays...)
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

    def insert(self, datagram: UDPDatagram):
        """
        Inserts the specified datagram in the buffer, preserving the order. It discards the datagram if it's too old
        :param datagram
        """
        datagram.set_received_time(time.time())
        # If datagram should have already been consumed, discard it
        if datagram.seq_number < self.__last_seq_number:
            return

        with self.__mutex:
            for i in range(len(self._buffer), -1, -1):
                if self._buffer[i].seq_number < datagram.seq_number:
                    self._buffer = self._buffer[:i] + [datagram] + self._buffer[i:]
                    break

    def consume(self, n_slots: int = 40) -> Tuple[List[UDPDatagram], BufferQuality]:
        """
        Gets n_slots from the buffer
        :param n_slots:
        :return: If there are not enough slots, it returns an empty list and quality SUPER_LOW. If there are enough,
                 it returns the slots and their quality
        """
        with self.__mutex:
            if len(self._buffer) < n_slots:
                return [], BufferQuality.SUPER_LOW
            consumed_buffer = self._buffer[:n_slots]
            self._buffer = self._buffer[n_slots:]

        self.__last_seq_number = consumed_buffer[-1].seq_number
        # Determine buffer quality
        datagrams_lost = 0
        delays_sum = 0
        for i in range(n_slots):
            if i+1 < n_slots:
                datagrams_lost += consumed_buffer[i+1].seq_number - consumed_buffer[i].seq_number
            delays_sum = consumed_buffer[i].delay_ts

        quality_avg = 10 * (datagrams_lost / (n_slots * 2)) + 1000 * (delays_sum / n_slots)  # TODO: pesos
        if quality_avg < 10:  # TODO: rangos
            quality = BufferQuality.HIGH
        elif quality_avg < 1000:
            quality = BufferQuality.MEDIUM
        else:
            quality = BufferQuality.LOW

        return consumed_buffer, quality
