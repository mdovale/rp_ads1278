from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence, TextIO

from .models import Ads1278Message, MessageType
from .protocol import CHANNEL_COUNT


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
