from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Tuple


class CommandOpcode(IntEnum):
    SET_ENABLE = 1
    TRIGGER_SYNC = 2
    SET_EXTCLK_DIV = 3


class MessageType(IntEnum):
    SAMPLE = 1
    ACK = 2
    ERROR = 3


@dataclass(frozen=True)
class Ads1278Message:
    msg_type: int
    msg_seq: int
    opcode: int
    value: int
    status_raw: int
    ctrl_raw: int
    extclk_div: int
    channels: Tuple[int, ...]

    @property
    def frame_cnt(self) -> int:
        return (self.status_raw >> 16) & 0xFFFF

    @property
    def new_data(self) -> bool:
        return bool(self.status_raw & 0x1)

    @property
    def overflow(self) -> bool:
        return bool(self.status_raw & 0x2)

    @property
    def enabled(self) -> bool:
        return bool(self.ctrl_raw & 0x2)

    @property
    def message_type(self) -> MessageType | None:
        try:
            return MessageType(self.msg_type)
        except ValueError:
            return None

    @property
    def command_opcode(self) -> CommandOpcode | None:
        try:
            return CommandOpcode(self.opcode)
        except ValueError:
            return None

    @property
    def message_type_label(self) -> str:
        message_type = self.message_type
        return message_type.name if message_type is not None else f"UNKNOWN({self.msg_type})"

    @property
    def opcode_label(self) -> str:
        if self.opcode == 0:
            return "NONE"
        opcode = self.command_opcode
        return opcode.name if opcode is not None else f"UNKNOWN({self.opcode})"
