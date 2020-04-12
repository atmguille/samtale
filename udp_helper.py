import time


class UDPDatagram:
    def __init__(self, seq_number: int, resolution: str, fps: float, data: bytes, ts: float = time.time()):
        self.seq_number = seq_number
        self.ts = ts
        self.resolution = resolution
        self.fps = fps
        self.data = data


def udp_datagram_from_msg(message: str) -> UDPDatagram:
    fields = message.split('#')
    return UDPDatagram(seq_number=int(fields[0]), ts=float(fields[1]), resolution=fields[2],
                       fps=float(fields[3]), data=fields[4].encode())