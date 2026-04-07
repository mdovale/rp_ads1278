from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, List, Optional, Sequence

import numpy as np

from .csv_logger import SampleCsvLogger
from .models import Ads1278Message, MessageType
from .protocol import (
    CHANNEL_COUNT,
    SERVER_PORT,
    pack_set_enable,
    pack_set_extclk_div,
    pack_trigger_sync,
)
from .transport import TransportClient


@dataclass(frozen=True)
class ControllerSnapshot:
    connected: bool
    host: str
    port: int
    capability_line: str
    latest_message: Optional[Ads1278Message]
    status_text: str
    status_level: str
    logging_path: str
    channel_history: Sequence[np.ndarray]


class ClientController:
    def __init__(self, history_length: int = 600) -> None:
        self._lock = threading.Lock()
        self._history_length = history_length
        self._channel_history: List[Deque[int]] = [
            deque(maxlen=history_length) for _ in range(CHANNEL_COUNT)
        ]
        self._connected = False
        self._host = ""
        self._port = SERVER_PORT
        self._capability_line = ""
        self._latest_message: Optional[Ads1278Message] = None
        self._status_text = "Disconnected"
        self._status_level = "info"
        self._logging_path = ""
        self._logger: Optional[SampleCsvLogger] = None
        self._transport = TransportClient(
            on_message=self._handle_message,
            on_connected=self._handle_connected,
            on_disconnected=self._handle_disconnected,
            on_error=self._handle_error,
        )

    def connect(self, host: str, port: int = SERVER_PORT) -> None:
        if not host.strip():
            raise ValueError("host is required")
        with self._lock:
            if self._connected or self._transport.is_connected():
                raise RuntimeError("already connected")
            self._host = host.strip()
            self._port = port
            self._status_text = f"Connecting to {self._host}:{self._port}..."
            self._status_level = "info"
        self._transport.connect(self._host, self._port)

    def disconnect(self) -> None:
        self._transport.disconnect()

    def shutdown(self) -> None:
        self.disconnect()
        with self._lock:
            self._close_logger_locked()

    def set_enabled(self, enabled: bool) -> None:
        self._transport.send_command(pack_set_enable(enabled))

    def trigger_sync(self) -> None:
        self._transport.send_command(pack_trigger_sync())

    def set_extclk_div(self, divider: int) -> None:
        self._transport.send_command(pack_set_extclk_div(divider))

    def start_logging(self, path: str | Path) -> None:
        with self._lock:
            self._close_logger_locked()
            self._logger = SampleCsvLogger(path)
            self._logging_path = str(Path(path))
            self._status_text = f"Logging samples to {self._logging_path}"
            self._status_level = "info"

    def stop_logging(self) -> None:
        with self._lock:
            self._close_logger_locked()
            self._status_text = "CSV logging stopped"
            self._status_level = "info"

    def get_snapshot(self) -> ControllerSnapshot:
        with self._lock:
            history = [np.asarray(list(channel), dtype=np.int32) for channel in self._channel_history]
            return ControllerSnapshot(
                connected=self._connected,
                host=self._host,
                port=self._port,
                capability_line=self._capability_line,
                latest_message=self._latest_message,
                status_text=self._status_text,
                status_level=self._status_level,
                logging_path=self._logging_path,
                channel_history=history,
            )

    def _handle_connected(self, capability_line: str) -> None:
        with self._lock:
            self._connected = True
            self._capability_line = capability_line
            self._status_text = f"Connected to {self._host}:{self._port}"
            self._status_level = "ok"

    def _handle_disconnected(self, reason: str) -> None:
        with self._lock:
            self._connected = False
            self._capability_line = ""
            self._close_logger_locked()
            self._status_text = f"Disconnected: {reason}"
            self._status_level = "error" if reason and reason != "disconnected" else "info"

    def _handle_error(self, message: str) -> None:
        with self._lock:
            self._status_text = f"Transport error: {message}"
            self._status_level = "error"

    def _handle_message(self, message: Ads1278Message) -> None:
        with self._lock:
            self._latest_message = message
            if message.message_type is MessageType.SAMPLE:
                for idx, channel in enumerate(message.channels):
                    self._channel_history[idx].append(channel)
                if self._logger is not None:
                    self._logger.write_sample(message)
                self._status_text = (
                    f"SAMPLE seq={message.msg_seq} frame_cnt={message.frame_cnt}"
                )
                self._status_level = "ok"
                return

            if message.message_type is MessageType.ACK:
                self._status_text = (
                    f"ACK {message.opcode_label} value={message.value} seq={message.msg_seq}"
                )
                self._status_level = "ok"
                return

            if message.message_type is MessageType.ERROR:
                self._status_text = (
                    f"ERROR {message.opcode_label} value={message.value} seq={message.msg_seq}"
                )
                self._status_level = "error"
                return

            self._status_text = f"Unknown message type {message.msg_type}"
            self._status_level = "error"

    def _close_logger_locked(self) -> None:
        if self._logger is not None:
            self._logger.close()
            self._logger = None
        self._logging_path = ""
