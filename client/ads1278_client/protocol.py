from __future__ import annotations

import math
import re
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Sequence

from .models import Ads1278Message, CommandOpcode, MessageType

SERVER_PORT = 5000
CAPABILITY_LINE = "RP_CAP:ads1278_v3"
SUPPORTED_CAPABILITY_LINES = frozenset({CAPABILITY_LINE, "RP_CAP:ads1278_v2"})
CAPABILITY_LINE_MAX = max(len(line) for line in SUPPORTED_CAPABILITY_LINES) + 1
CHANNEL_COUNT = 8
MIN_EXTCLK_DIV = 3
MIN_MOD_DIV = 2
MODULATION_CLOCK_HZ = 125_000_000.0
DEFAULT_MODULATION_FREQUENCY_HZ = 10.0
MIN_MODULATION_FREQUENCY_HZ = 0.1
MAX_MODULATION_FREQUENCY_HZ = 100_000.0
LOCAL_LOG_DIR_HINT = "/mnt/usb/ads1278/logs"
LOCAL_LOG_PATH_HINT = f"{LOCAL_LOG_DIR_HINT}/<filename>.csv"
LOCAL_LOG_DEFAULT_FILENAME_PREFIX = "ads1278"
MAX_LOCAL_LOG_FILENAME_LEN = 63
_LOCAL_LOG_FILENAME_CHUNK_SHIFT = 24
_LOCAL_LOG_FILENAME_CHUNK_BYTES = 3
_LOCAL_LOG_FILENAME_SAFE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
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


def channel_indices_to_mask(channel_indices: Sequence[int] | None = None) -> int:
    if channel_indices is None:
        return 0
    mask = 0
    for idx in channel_indices:
        channel_idx = int(idx)
        if channel_idx < 0 or channel_idx >= CHANNEL_COUNT:
            raise ValueError(f"channel index out of range: {channel_idx}")
        mask |= 1 << channel_idx
    if mask == 0:
        raise ValueError("at least one channel is required")
    return mask


def default_csv_basename(now: datetime | None = None) -> str:
    timestamp = now or datetime.now(timezone.utc)
    return (
        f"{LOCAL_LOG_DEFAULT_FILENAME_PREFIX}_"
        f"{timestamp.strftime('%Y%m%d_%H%M%S')}.csv"
    )


def normalize_csv_basename(name: str) -> str:
    stem = str(name).strip()
    if not stem:
        raise ValueError("CSV filename is required")
    if "/" in stem or "\\" in stem:
        raise ValueError("CSV filename must not contain path separators")
    stem = Path(stem).name
    if stem in ("", ".", ".."):
        raise ValueError("CSV filename is required")
    if not stem.lower().endswith(".csv"):
        stem = f"{stem}.csv"
    if len(stem) > MAX_LOCAL_LOG_FILENAME_LEN:
        raise ValueError(
            f"CSV filename must be at most {MAX_LOCAL_LOG_FILENAME_LEN} characters"
        )
    if not _LOCAL_LOG_FILENAME_SAFE_RE.match(stem):
        raise ValueError(
            "CSV filename may contain only letters, numbers, dots, underscores, and dashes"
        )
    return stem


def resolve_local_csv_path(directory: str | Path, basename: str) -> Path:
    normalized = normalize_csv_basename(basename)
    folder = Path(directory).expanduser()
    if not folder.is_absolute():
        folder = Path.cwd() / folder
    return folder / normalized


def usb_csv_path_hint(basename: str) -> str:
    normalized = normalize_csv_basename(basename)
    return f"USB: {LOCAL_LOG_DIR_HINT}/{normalized}"


def pack_set_local_log_filename(basename: str) -> list[bytes]:
    normalized = normalize_csv_basename(basename)
    encoded = normalized.encode("ascii")
    chunks: list[bytes] = [
        encoded[index : index + _LOCAL_LOG_FILENAME_CHUNK_BYTES]
        for index in range(0, len(encoded), _LOCAL_LOG_FILENAME_CHUNK_BYTES)
    ]
    if not chunks or len(chunks[-1]) == _LOCAL_LOG_FILENAME_CHUNK_BYTES:
        chunks.append(b"")
    commands: list[bytes] = []
    for chunk_index, chunk_bytes in enumerate(chunks):
        padded = (chunk_bytes + b"\0\0\0")[:_LOCAL_LOG_FILENAME_CHUNK_BYTES]
        packed = int.from_bytes(padded, "little")
        value = (chunk_index << _LOCAL_LOG_FILENAME_CHUNK_SHIFT) | (packed & 0x00FFFFFF)
        commands.append(pack_command(CommandOpcode.SET_LOCAL_LOG_FILENAME, value))
    return commands


def pack_start_local_log(channel_indices: Sequence[int] | None = None) -> bytes:
    return pack_command(
        CommandOpcode.START_LOCAL_LOG,
        channel_indices_to_mask(channel_indices),
    )


def pack_set_local_log_duration(duration_s: float | None) -> bytes:
    if duration_s is None or duration_s <= 0.0:
        duration = 0
    else:
        duration = int(math.ceil(float(duration_s)))
    return pack_command(CommandOpcode.SET_LOCAL_LOG_DURATION, duration)


def pack_stop_local_log() -> bytes:
    return pack_command(CommandOpcode.STOP_LOCAL_LOG, 0)


def pack_set_extclk_div(divider: int) -> bytes:
    if divider < MIN_EXTCLK_DIV:
        raise ValueError(f"EXTCLK divider must be >= {MIN_EXTCLK_DIV}")
    return pack_command(CommandOpcode.SET_EXTCLK_DIV, divider)


def modulation_divider_to_frequency_hz(divider: int) -> float:
    divider = max(int(divider), MIN_MOD_DIV)
    return MODULATION_CLOCK_HZ / (2.0 * divider)


def modulation_frequency_to_divider(frequency_hz: float) -> int:
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


def pack_set_modulation_div(divider: int) -> bytes:
    if divider < MIN_MOD_DIV:
        raise ValueError(f"modulation divider must be >= {MIN_MOD_DIV}")
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
