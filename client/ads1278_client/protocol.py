from __future__ import annotations

import struct
from typing import List, Sequence

from .models import Ads1278Message, CommandOpcode, MessageType

SERVER_PORT = 5000
CAPABILITY_LINE = "RP_CAP:ads1278_v1"
CAPABILITY_LINE_MAX = len(CAPABILITY_LINE) + 1
CHANNEL_COUNT = 8
MIN_EXTCLK_DIV = 3
COMMAND_SIZE = 8
MESSAGE_SIZE = 60

COMMAND_STRUCT = struct.Struct("<II")
MESSAGE_STRUCT = struct.Struct("<7I8i")


class CapabilityLineBuffer:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self._remainder = b""

    def feed(self, chunk: bytes) -> str | None:
        if not chunk:
            return None
        self._buffer.extend(chunk)
        newline_index = self._buffer.find(b"\n")
        if newline_index == -1:
            if len(self._buffer) > CAPABILITY_LINE_MAX:
                raise ValueError("capability line too long")
            return None

        line_bytes = bytes(self._buffer[:newline_index])
        self._remainder = bytes(self._buffer[newline_index + 1 :])
        self._buffer.clear()

        try:
            line = line_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("capability line must be ASCII") from exc

        return validate_capability_line(line)

    def take_remainder(self) -> bytes:
        remainder = self._remainder
        self._remainder = b""
        return remainder


class MessageStreamBuffer:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> List[Ads1278Message]:
        self._buffer.extend(chunk)
        messages: List[Ads1278Message] = []
        while len(self._buffer) >= MESSAGE_SIZE:
            payload = bytes(self._buffer[:MESSAGE_SIZE])
            del self._buffer[:MESSAGE_SIZE]
            messages.append(parse_message(payload))
        return messages


def validate_capability_line(line: str) -> str:
    if line != CAPABILITY_LINE:
        raise ValueError(f"unexpected capability line: {line!r}")
    return line


def pack_command(opcode: int | CommandOpcode, value: int) -> bytes:
    return COMMAND_STRUCT.pack(int(opcode), value & 0xFFFFFFFF)


def pack_set_enable(enabled: bool) -> bytes:
    return pack_command(CommandOpcode.SET_ENABLE, 1 if enabled else 0)


def pack_trigger_sync() -> bytes:
    return pack_command(CommandOpcode.TRIGGER_SYNC, 0)


def pack_set_extclk_div(divider: int) -> bytes:
    if divider < MIN_EXTCLK_DIV:
        raise ValueError(f"EXTCLK divider must be >= {MIN_EXTCLK_DIV}")
    return pack_command(CommandOpcode.SET_EXTCLK_DIV, divider)


def unpack_command(payload: bytes) -> tuple[int, int]:
    if len(payload) != COMMAND_SIZE:
        raise ValueError(f"command must be {COMMAND_SIZE} bytes")
    return COMMAND_STRUCT.unpack(payload)


def parse_message(payload: bytes) -> Ads1278Message:
    if len(payload) != MESSAGE_SIZE:
        raise ValueError(f"message must be {MESSAGE_SIZE} bytes")

    words = MESSAGE_STRUCT.unpack(payload)
    return Ads1278Message(
        msg_type=words[0],
        msg_seq=words[1],
        opcode=words[2],
        value=words[3],
        status_raw=words[4],
        ctrl_raw=words[5],
        extclk_div=words[6],
        channels=tuple(words[7:]),
    )


def build_message(
    msg_type: int | MessageType,
    msg_seq: int,
    opcode: int | CommandOpcode,
    value: int,
    status_raw: int,
    ctrl_raw: int,
    extclk_div: int,
    channels: Sequence[int],
) -> bytes:
    if len(channels) != CHANNEL_COUNT:
        raise ValueError(f"expected {CHANNEL_COUNT} channels")

    return MESSAGE_STRUCT.pack(
        int(msg_type),
        msg_seq,
        int(opcode),
        value & 0xFFFFFFFF,
        status_raw & 0xFFFFFFFF,
        ctrl_raw & 0xFFFFFFFF,
        extclk_div & 0xFFFFFFFF,
        *[int(channel) for channel in channels],
    )
