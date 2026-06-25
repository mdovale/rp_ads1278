from __future__ import annotations

import struct
from typing import List, Sequence

from .models import Ads1278Message, CommandOpcode, MessageType

SERVER_PORT = 5000
CAPABILITY_LINE = "RP_CAP:ads1278_v3"
SUPPORTED_CAPABILITY_LINES = frozenset({CAPABILITY_LINE, "RP_CAP:ads1278_v2"})
CAPABILITY_LINE_MAX = max(len(line) for line in SUPPORTED_CAPABILITY_LINES) + 1
CHANNEL_COUNT = 8
MIN_EXTCLK_DIV = 3
MODULATION_OFF_DIV = 0
MIN_MOD_DIV = 2
MODULATION_CLOCK_HZ = 125_000_000.0
DEFAULT_MODULATION_FREQUENCY_HZ = 10.0
MIN_MODULATION_FREQUENCY_HZ = 0.1
MAX_MODULATION_FREQUENCY_HZ = 100_000.0
COMMAND_SIZE = 8
MESSAGE_SIZE = 64
BULK_FRAME_SIZE = 40

COMMAND_STRUCT = struct.Struct("<II")
MESSAGE_STRUCT = struct.Struct("<8I8i")
BULK_FRAME_STRUCT = struct.Struct("<II8i")


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
            header_payload = bytes(self._buffer[:MESSAGE_SIZE])
            header = parse_message(header_payload)
            if header.message_type is MessageType.BULK_SAMPLES:
                payload_size = header.value * BULK_FRAME_SIZE
                total_size = MESSAGE_SIZE + payload_size
                if len(self._buffer) < total_size:
                    break
                payload = bytes(self._buffer[MESSAGE_SIZE:total_size])
                del self._buffer[:total_size]
                messages.extend(parse_bulk_samples(header, payload))
                continue

            del self._buffer[:MESSAGE_SIZE]
            messages.append(header)
        return messages


def validate_capability_line(line: str) -> str:
    if line not in SUPPORTED_CAPABILITY_LINES:
        raise ValueError(f"unexpected capability line: {line!r}")
    return line


def pack_command(opcode: int | CommandOpcode, value: int) -> bytes:
    return COMMAND_STRUCT.pack(int(opcode), value & 0xFFFFFFFF)


def pack_set_enable(enabled: bool) -> bytes:
    return pack_command(CommandOpcode.SET_ENABLE, 1 if enabled else 0)


def pack_trigger_sync() -> bytes:
    return pack_command(CommandOpcode.TRIGGER_SYNC, 0)


def pack_mark_capture() -> bytes:
    return pack_command(CommandOpcode.MARK_CAPTURE, 0)


def pack_set_extclk_div(divider: int) -> bytes:
    if divider < MIN_EXTCLK_DIV:
        raise ValueError(f"EXTCLK divider must be >= {MIN_EXTCLK_DIV}")
    return pack_command(CommandOpcode.SET_EXTCLK_DIV, divider)


def modulation_divider_to_frequency_hz(divider: int) -> float:
    if int(divider) == MODULATION_OFF_DIV:
        return 0.0
    divider = max(int(divider), MIN_MOD_DIV)
    return MODULATION_CLOCK_HZ / (2.0 * divider)


def modulation_frequency_to_divider(frequency_hz: float) -> int:
    if frequency_hz == 0.0:
        return MODULATION_OFF_DIV
    if frequency_hz < MIN_MODULATION_FREQUENCY_HZ:
        raise ValueError(
            f"modulation frequency must be >= {MIN_MODULATION_FREQUENCY_HZ:g} Hz"
        )
    if frequency_hz > MAX_MODULATION_FREQUENCY_HZ:
        raise ValueError(
            f"modulation frequency must be <= {MAX_MODULATION_FREQUENCY_HZ:g} Hz"
        )
    divider = int(round(MODULATION_CLOCK_HZ / (2.0 * frequency_hz)))
    return max(divider, MIN_MOD_DIV)


def pack_set_modulation_frequency(frequency_hz: float) -> bytes:
    return pack_set_modulation_div(modulation_frequency_to_divider(frequency_hz))


def pack_set_modulation_off() -> bytes:
    return pack_set_modulation_div(MODULATION_OFF_DIV)


def pack_set_modulation_div(divider: int) -> bytes:
    if divider != MODULATION_OFF_DIV and divider < MIN_MOD_DIV:
        raise ValueError(f"modulation divider must be 0 or >= {MIN_MOD_DIV}")
    return pack_command(CommandOpcode.SET_MOD_DIV, divider)


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
        mod_div=words[7],
        channels=tuple(words[8:]),
    )


def parse_bulk_samples(header: Ads1278Message, payload: bytes) -> List[Ads1278Message]:
    if header.message_type is not MessageType.BULK_SAMPLES:
        raise ValueError("bulk sample payload requires a BULK_SAMPLES header")
    expected_size = header.value * BULK_FRAME_SIZE
    if len(payload) != expected_size:
        raise ValueError(f"bulk payload must be {expected_size} bytes")

    messages: List[Ads1278Message] = []
    for index in range(header.value):
        offset = index * BULK_FRAME_SIZE
        frame_words = BULK_FRAME_STRUCT.unpack(payload[offset : offset + BULK_FRAME_SIZE])
        frame_count = frame_words[0]
        status_raw = (frame_words[1] & 0x0000FFFF) | ((frame_count & 0xFFFF) << 16)
        messages.append(
            Ads1278Message(
                msg_type=MessageType.SAMPLE,
                msg_seq=(header.msg_seq + index) & 0xFFFFFFFF,
                opcode=0,
                value=0,
                status_raw=status_raw,
                ctrl_raw=header.ctrl_raw,
                extclk_div=header.extclk_div,
                mod_div=header.mod_div,
                channels=tuple(frame_words[2:]),
            )
        )
    return messages


def build_message(
    msg_type: int | MessageType,
    msg_seq: int,
    opcode: int | CommandOpcode,
    value: int,
    status_raw: int,
    ctrl_raw: int,
    extclk_div: int,
    mod_div: int,
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
        mod_div & 0xFFFFFFFF,
        *[int(channel) for channel in channels],
    )


def build_bulk_message(
    msg_seq: int,
    ctrl_raw: int,
    extclk_div: int,
    mod_div: int,
    frames: Sequence[tuple[int, int, Sequence[int]]],
) -> bytes:
    if not frames:
        raise ValueError("bulk message requires at least one frame")

    _, last_status_raw, last_channels = frames[-1]
    header = build_message(
        MessageType.BULK_SAMPLES,
        msg_seq,
        0,
        len(frames),
        last_status_raw,
        ctrl_raw,
        extclk_div,
        mod_div,
        last_channels,
    )
    payload = bytearray()
    for frame_count, status_raw, channels in frames:
        if len(channels) != CHANNEL_COUNT:
            raise ValueError(f"expected {CHANNEL_COUNT} channels")
        payload.extend(
            BULK_FRAME_STRUCT.pack(
                frame_count & 0xFFFFFFFF,
                status_raw & 0xFFFFFFFF,
                *[int(channel) for channel in channels],
            )
        )
    return header + bytes(payload)
