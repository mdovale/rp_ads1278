from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from .models import Ads1278Message, MessageType


class SampleCsvLogger:
    HEADER = [
        "host_timestamp",
        "msg_seq",
        "frame_cnt",
        "status_raw",
        "ctrl_raw",
        "extclk_div",
        "ch1",
        "ch2",
        "ch3",
        "ch4",
        "ch5",
        "ch6",
        "ch7",
        "ch8",
    ]

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(self.HEADER)
        self._file.flush()

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
            *message.channels,
        ]
        self._writer.writerow(row)
        self._file.flush()

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()
