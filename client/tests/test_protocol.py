import struct

import pytest

from ads1278_client.models import CommandOpcode, MessageType
from ads1278_client.protocol import (
    CAPABILITY_LINE,
    CapabilityLineBuffer,
    MessageStreamBuffer,
    MIN_EXTCLK_DIV,
    build_bulk_message,
    build_message,
    default_csv_basename,
    modulation_divider_to_frequency_hz,
    modulation_frequency_to_divider,
    normalize_csv_basename,
    pack_mark_capture,
    pack_set_enable,
    pack_set_extclk_div,
    pack_set_local_log_duration,
    pack_set_local_log_filename,
    pack_set_modulation_frequency,
    pack_start_local_log,
    pack_stop_local_log,
    pack_trigger_sync,
    parse_message,
    usb_csv_path_hint,
)


def test_capability_buffer_accepts_split_reads() -> None:
    buffer = CapabilityLineBuffer()
    assert buffer.feed(b"RP_CAP:ads") is None
    assert buffer.feed(b"1278_v3\n") == CAPABILITY_LINE
    assert buffer.take_remainder() == b""


def test_capability_buffer_preserves_binary_remainder() -> None:
    buffer = CapabilityLineBuffer()
    payload = build_message(
        MessageType.SAMPLE,
        1,
        0,
        0,
        0x00120003,
        0x00000002,
        625,
        6_250_000,
        [1, 2, 3, 4, 5, 6, 7, 8],
    )
    combined = f"{CAPABILITY_LINE}\n".encode("ascii") + payload[:10]
    assert buffer.feed(combined) == CAPABILITY_LINE
    assert buffer.take_remainder() == payload[:10]


def test_invalid_capability_line_rejected() -> None:
    buffer = CapabilityLineBuffer()
    with pytest.raises(ValueError):
        buffer.feed(b"RP_CAP:wrong\n")


def test_message_stream_buffer_handles_split_messages() -> None:
    sample = build_message(
        MessageType.SAMPLE,
        10,
        0,
        0,
        0x00340001,
        0x00000002,
        625,
        6_250_000,
        [10, 11, 12, 13, 14, 15, 16, 17],
    )
    ack = build_message(
        MessageType.ACK,
        11,
        CommandOpcode.SET_ENABLE,
        1,
        0x00350001,
        0x00000002,
        625,
        6_250_000,
        [20, 21, 22, 23, 24, 25, 26, 27],
    )

    buffer = MessageStreamBuffer()
    assert buffer.feed(sample[:25]) == []
    messages = buffer.feed(sample[25:] + ack[:17])
    assert len(messages) == 1
    assert messages[0].msg_seq == 10

    messages = buffer.feed(ack[17:])
    assert len(messages) == 1
    assert messages[0].message_type is MessageType.ACK
    assert messages[0].opcode == CommandOpcode.SET_ENABLE


def test_message_stream_buffer_expands_bulk_samples() -> None:
    bulk = build_bulk_message(
        msg_seq=100,
        ctrl_raw=0x00000002,
        extclk_div=125,
        mod_div=6_250_000,
        frames=[
            (1, 0x00000001, [1, 2, 3, 4, 5, 6, 7, 8]),
            (2, 0x00000003, [-1, -2, -3, -4, -5, -6, -7, -8]),
        ],
    )

    buffer = MessageStreamBuffer()
    assert buffer.feed(bulk[:70]) == []
    messages = buffer.feed(bulk[70:])

    assert len(messages) == 2
    assert [message.message_type for message in messages] == [
        MessageType.SAMPLE,
        MessageType.SAMPLE,
    ]
    assert [message.msg_seq for message in messages] == [100, 101]
    assert [message.frame_cnt for message in messages] == [1, 2]
    assert messages[0].channels == (1, 2, 3, 4, 5, 6, 7, 8)
    assert messages[1].channels == (-1, -2, -3, -4, -5, -6, -7, -8)


def test_parse_message_decodes_negative_channels_and_frame_count() -> None:
    payload = build_message(
        MessageType.SAMPLE,
        42,
        0,
        0,
        0xABCD0003,
        0x00000002,
        625,
        6_250_000,
        [-1, -2, 3, 4, 5, 6, 7, -8],
    )
    message = parse_message(payload)

    assert message.frame_cnt == 0xABCD
    assert message.new_data is True
    assert message.overflow is True
    assert message.enabled is True
    assert message.mod_div == 6_250_000
    assert message.channels[0] == -1
    assert message.channels[-1] == -8


def test_command_packers_match_server_layout() -> None:
    enable_opcode, enable_value = struct.unpack("<II", pack_set_enable(True))
    assert enable_opcode == CommandOpcode.SET_ENABLE
    assert enable_value == 1

    sync_opcode, sync_value = struct.unpack("<II", pack_trigger_sync())
    assert sync_opcode == CommandOpcode.TRIGGER_SYNC
    assert sync_value == 0

    capture_opcode, capture_value = struct.unpack("<II", pack_mark_capture())
    assert capture_opcode == CommandOpcode.MARK_CAPTURE
    assert capture_value == 0

    div_opcode, div_value = struct.unpack("<II", pack_set_extclk_div(625))
    assert div_opcode == CommandOpcode.SET_EXTCLK_DIV
    assert div_value == 625

    mod_opcode, mod_value = struct.unpack("<II", pack_set_modulation_frequency(10.0))
    assert mod_opcode == CommandOpcode.SET_MOD_DIV
    assert mod_value == 6_250_000

    local_log_opcode, local_log_value = struct.unpack(
        "<II",
        pack_start_local_log((0, 4, 7)),
    )
    assert local_log_opcode == CommandOpcode.START_LOCAL_LOG
    assert local_log_value == 0x91

    duration_opcode, duration_value = struct.unpack(
        "<II",
        pack_set_local_log_duration(3600.4),
    )
    assert duration_opcode == CommandOpcode.SET_LOCAL_LOG_DURATION
    assert duration_value == 3601

    stop_log_opcode, stop_log_value = struct.unpack("<II", pack_stop_local_log())
    assert stop_log_opcode == CommandOpcode.STOP_LOCAL_LOG
    assert stop_log_value == 0

    filename_commands = pack_set_local_log_filename("test")
    assert len(filename_commands) == 3
    first_opcode, first_value = struct.unpack("<II", filename_commands[0])
    second_opcode, second_value = struct.unpack("<II", filename_commands[1])
    third_opcode, third_value = struct.unpack("<II", filename_commands[2])
    assert first_opcode == CommandOpcode.SET_LOCAL_LOG_FILENAME
    assert first_value == int.from_bytes(b"tes", "little")
    assert second_opcode == CommandOpcode.SET_LOCAL_LOG_FILENAME
    assert second_value == (1 << 24) | int.from_bytes(b"t.c", "little")
    assert third_opcode == CommandOpcode.SET_LOCAL_LOG_FILENAME
    assert third_value == (2 << 24) | int.from_bytes(b"sv\0", "little")


def test_extclk_divider_below_server_minimum_rejected() -> None:
    with pytest.raises(ValueError, match=f">= {MIN_EXTCLK_DIV}"):
        pack_set_extclk_div(MIN_EXTCLK_DIV - 1)


def test_modulation_frequency_conversion_uses_125_mhz_half_period() -> None:
    assert modulation_frequency_to_divider(10.0) == 6_250_000
    assert modulation_divider_to_frequency_hz(6_250_000) == 10.0


def test_csv_basename_helpers_validate_usb_safe_names() -> None:
    assert normalize_csv_basename("noise_run_01") == "noise_run_01.csv"
    assert usb_csv_path_hint("noise_run_01") == (
        "USB: /mnt/usb/ads1278/logs/noise_run_01.csv"
    )
    assert default_csv_basename().startswith("ads1278_")
    with pytest.raises(ValueError, match="path separators"):
        normalize_csv_basename("../bad.csv")
    with pytest.raises(ValueError, match="may contain only"):
        normalize_csv_basename("bad name.csv")
