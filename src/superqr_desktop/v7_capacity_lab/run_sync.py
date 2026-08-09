"""Local implementation of the laboratory-only optical run envelope."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


SYNC_MAGIC = 0xD7
SYNC_VERSION = 1
SYNC_BYTES = 10


class RunState(IntEnum):
    READY = 0
    RUNNING = 1
    DONE = 2


def crc8_atm(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


@dataclass(frozen=True)
class LabRunEnvelope:
    state: RunState
    profile_id: int
    run_token: int
    frame_index: int
    frame_count: int
    dwell_epochs: int

    def encode(self) -> bytes:
        if not 0 <= self.profile_id <= 0xFF:
            raise ValueError("profile_id must fit uint8")
        if not 0 <= self.run_token <= 0xFFFF:
            raise ValueError("run_token must fit uint16")
        if not 0 <= self.frame_index <= 0xFF:
            raise ValueError("frame_index must fit uint8")
        if not 1 <= self.frame_count <= 256:
            raise ValueError("frame_count must be in [1, 256]")
        if self.dwell_epochs not in (2, 3):
            raise ValueError("dwell_epochs must be 2 or 3")
        body = bytes((
            SYNC_MAGIC, SYNC_VERSION, int(self.state), self.profile_id,
            self.run_token & 0xFF, self.run_token >> 8, self.frame_index,
            0 if self.frame_count == 256 else self.frame_count, self.dwell_epochs,
        ))
        return body + bytes((crc8_atm(body),))

    def bits(self) -> list[int]:
        return [(value >> shift) & 1 for value in self.encode() for shift in range(7, -1, -1)]

    @classmethod
    def decode(cls, packet: bytes) -> "LabRunEnvelope":
        if len(packet) != SYNC_BYTES or packet[0] != SYNC_MAGIC or packet[1] != SYNC_VERSION:
            raise ValueError("invalid sync header")
        if crc8_atm(packet[:-1]) != packet[-1]:
            raise ValueError("sync CRC mismatch")
        return cls(
            RunState(packet[2]), packet[3], packet[4] | packet[5] << 8,
            packet[6], packet[7] or 256, packet[8],
        )
