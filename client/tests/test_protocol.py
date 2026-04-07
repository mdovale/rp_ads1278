import struct

import pytest

from ads1278_client.models import CommandOpcode, MessageType
from ads1278_client.protocol import (
    CAPABILITY_LINE,
    CapabilityLineBuffer,
    MessageStreamBuffer,
    MIN_EXTCLK_DIV,
    build_message,
    pack_set_enable,
    pack_set_extclk_div,
    pack_trigger_sync,
    parse_message,
)


def test_capability_buffer_accepts_split_reads() -> None:
    buffer = CapabilityLineBuffer()
    assert buffer.feed(b"RP_CAP:ads") is None
    assert buffer.feed(b"1278_v1\n") == CAPABILITY_LINE
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


def test_parse_message_decodes_negative_channels_and_frame_count() -> None:
    payload = build_message(
        MessageType.SAMPLE,
        42,
        0,
        0,
        0xABCD0003,
        0x00000002,
        625,
        [-1, -2, 3, 4, 5, 6, 7, -8],
    )
    message = parse_message(payload)

    assert message.frame_cnt == 0xABCD
    assert message.new_data is True
    assert message.overflow is True
    assert message.enabled is True
    assert message.channels[0] == -1
    assert message.channels[-1] == -8


def test_command_packers_match_server_layout() -> None:
    enable_opcode, enable_value = struct.unpack("<II", pack_set_enable(True))
    assert enable_opcode == CommandOpcode.SET_ENABLE
    assert enable_value == 1

    sync_opcode, sync_value = struct.unpack("<II", pack_trigger_sync())
    assert sync_opcode == CommandOpcode.TRIGGER_SYNC
    assert sync_value == 0

    div_opcode, div_value = struct.unpack("<II", pack_set_extclk_div(625))
    assert div_opcode == CommandOpcode.SET_EXTCLK_DIV
    assert div_value == 625


def test_extclk_divider_below_server_minimum_rejected() -> None:
    with pytest.raises(ValueError, match=f">= {MIN_EXTCLK_DIV}"):
        pack_set_extclk_div(MIN_EXTCLK_DIV - 1)
