from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence, TextIO

from .models import Ads1278Message, MessageType
from .protocol import CHANNEL_COUNT
from .units import FRAME_COUNTER_MODULUS, frames_per_demod


class SampleCsvLogger:
    METADATA_HEADER = [
        "host_timestamp",
        "msg_seq",
        "frame_cnt",
        "status_raw",
        "ctrl_raw",
        "extclk_div",
        "mod_div",
    ]
    HEADER = METADATA_HEADER + [f"ch{idx + 1}" for idx in range(CHANNEL_COUNT)]

    def __init__(
        self,
        path: str | Path,
        channel_indices: Sequence[int] | None = None,
        *,
        demod_rate: bool = False,
    ) -> None:
        self.path = Path(path)
        self._channel_indices = tuple(
            range(CHANNEL_COUNT) if channel_indices is None else channel_indices
        )
        if not self._channel_indices:
            raise ValueError("at least one channel is required")
        for idx in self._channel_indices:
            if idx < 0 or idx >= CHANNEL_COUNT:
                raise ValueError(f"channel index out of range: {idx}")
        if demod_rate and self._channel_indices != (CHANNEL_COUNT - 1,):
            raise ValueError("demod-rate CSV logging requires CH8 only")
        self._demod_rate_requested = bool(demod_rate)
        self._have_last_demod_row = False
        self._last_demod_frame_cnt = 0
        self._last_demod_ch8 = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(self.header)
        self._file.flush()

    @property
    def header(self) -> list[str]:
        return self.METADATA_HEADER + [
            f"ch{idx + 1}" for idx in self._channel_indices
        ]

    def write_sample(self, message: Ads1278Message) -> None:
        if message.message_type is not MessageType.SAMPLE:
            raise ValueError("CSV logging only supports SAMPLE messages")
        if not self._should_write_sample(message):
            return

        row = [
            datetime.now(timezone.utc).isoformat(),
            message.msg_seq,
            message.frame_cnt,
            message.status_raw,
            message.ctrl_raw,
            message.extclk_div,
            message.mod_div,
            *(message.channels[idx] for idx in self._channel_indices),
        ]
        self._writer.writerow(row)
        self._file.flush()

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def _demod_gate_active(self, message: Ads1278Message) -> bool:
        return (
            self._demod_rate_requested
            and self._channel_indices == (CHANNEL_COUNT - 1,)
            and (message.ctrl_raw & 0x6) == 0x6
            and message.mod_div >= 2
        )

    def _should_write_sample(self, message: Ads1278Message) -> bool:
        if not self._demod_gate_active(message):
            self._have_last_demod_row = False
            return True

        frame_cnt = message.frame_cnt
        ch8 = message.channels[CHANNEL_COUNT - 1]
        if not self._have_last_demod_row:
            self._last_demod_frame_cnt = frame_cnt
            self._last_demod_ch8 = ch8
            self._have_last_demod_row = True
            return True

        frames_since_last = (
            frame_cnt - self._last_demod_frame_cnt
        ) % FRAME_COUNTER_MODULUS
        if frames_since_last == 0:
            return False
        if ch8 != self._last_demod_ch8 or frames_since_last >= frames_per_demod(
            message.extclk_div,
            message.mod_div,
        ):
            self._last_demod_frame_cnt = frame_cnt
            self._last_demod_ch8 = ch8
            return True
        return False
