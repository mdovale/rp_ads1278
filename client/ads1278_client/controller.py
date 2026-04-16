from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, List, Optional, Sequence

import numpy as np

from .csv_logger import SampleCsvLogger
from .models import Ads1278Message, CommandOpcode, MessageType
from .protocol import (
    CHANNEL_COUNT,
    SERVER_PORT,
    pack_mark_capture,
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
        self._pending_logging_paths: Deque[Optional[str]] = deque()
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
        logging_path = str(Path(path))
        with self._lock:
            if not self._connected:
                raise RuntimeError("must be connected before starting CSV capture")
            self._cancel_pending_logging_locked()
            self._close_logger_locked()
            self._logging_path = logging_path
            self._pending_logging_paths.append(logging_path)
            self._status_text = f"Arming CSV capture for {self._logging_path}"
            self._status_level = "info"
        try:
            self._transport.send_command(pack_mark_capture())
        except Exception:
            with self._lock:
                self._cancel_pending_logging_locked()
                self._close_logger_locked()
            raise

    def stop_logging(self) -> None:
        with self._lock:
            self._cancel_pending_logging_locked()
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
            self._latest_message = None
            self._cancel_pending_logging_locked()
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
                if message.command_opcode is CommandOpcode.MARK_CAPTURE:
                    self._activate_logger_locked(self._pop_pending_logging_path_locked())
                    return
                self._status_text = (
                    f"ACK {message.opcode_label} value={message.value} seq={message.msg_seq}"
                )
                self._status_level = "ok"
                return

            if message.message_type is MessageType.ERROR:
                if message.command_opcode is CommandOpcode.MARK_CAPTURE:
                    if self._pop_pending_logging_path_locked() is not None:
                        self._logging_path = ""
                    self._status_text = (
                        f"ERROR {message.opcode_label} value={message.value} seq={message.msg_seq}"
                    )
                    self._status_level = "error"
                    return
                self._status_text = (
                    f"ERROR {message.opcode_label} value={message.value} seq={message.msg_seq}"
                )
                self._status_level = "error"
                return

            self._status_text = f"Unknown message type {message.msg_type}"
            self._status_level = "error"

    def _activate_logger_locked(self, logging_path: Optional[str]) -> None:
        if not logging_path:
            self._status_text = "Capture marker acknowledged"
            self._status_level = "ok"
            return
        try:
            self._logger = SampleCsvLogger(logging_path)
        except Exception as exc:
            self._close_logger_locked()
            self._status_text = f"Failed to start CSV logging: {exc}"
            self._status_level = "error"
            return
        self._logging_path = logging_path
        self._status_text = f"Logging samples to {self._logging_path}"
        self._status_level = "ok"

    def _cancel_pending_logging_locked(self) -> None:
        self._pending_logging_paths = deque(
            None for _ in self._pending_logging_paths
        )

    def _pop_pending_logging_path_locked(self) -> Optional[str]:
        if not self._pending_logging_paths:
            return None
        return self._pending_logging_paths.popleft()

    def _close_logger_locked(self) -> None:
        if self._logger is not None:
            self._logger.close()
            self._logger = None
        self._logging_path = ""
