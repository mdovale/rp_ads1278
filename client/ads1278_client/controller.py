from __future__ import annotations

import threading
import time
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
    pack_set_modulation_frequency,
    pack_trigger_sync,
)
from .transport import TransportClient


def compose_capture_duration_seconds(
    hours: int,
    minutes: int,
    seconds: float,
) -> Optional[float]:
    total = (max(int(hours), 0) * 3600) + (max(int(minutes), 0) * 60) + max(float(seconds), 0.0)
    if total <= 0.0:
        return None
    return total


def split_capture_duration_seconds(total_seconds: float) -> tuple[int, int, float]:
    remaining = max(float(total_seconds), 0.0)
    hours = int(remaining // 3600)
    remaining -= hours * 3600
    minutes = int(remaining // 60)
    remaining -= minutes * 60
    return hours, minutes, remaining


def format_capture_duration(duration_s: float) -> str:
    hours, minutes, seconds = split_capture_duration_seconds(duration_s)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds:g}s")
    return " ".join(parts)


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
    logging_remaining_s: Optional[float]
    channel_history: Sequence[np.ndarray]
    asd_channel_history: Sequence[np.ndarray]
    frame_history: np.ndarray


@dataclass(frozen=True)
class PendingLoggingRequest:
    path: Optional[str]
    duration_s: Optional[float]
    channel_indices: tuple[int, ...]


class ClientController:
    def __init__(self, history_length: int = 600, asd_history_length: int = 131_072) -> None:
        self._lock = threading.Lock()
        self._history_length = history_length
        self._asd_history_length = asd_history_length
        self._channel_history: List[Deque[int]] = [
            deque(maxlen=history_length) for _ in range(CHANNEL_COUNT)
        ]
        self._asd_channel_history: List[Deque[int]] = [
            deque(maxlen=asd_history_length) for _ in range(CHANNEL_COUNT)
        ]
        self._frame_history: Deque[int] = deque(maxlen=history_length)
        self._connected = False
        self._host = ""
        self._port = SERVER_PORT
        self._capability_line = ""
        self._latest_message: Optional[Ads1278Message] = None
        self._status_text = "Disconnected"
        self._status_level = "info"
        self._logging_path = ""
        self._logging_deadline_monotonic: Optional[float] = None
        self._pending_logging_requests: Deque[PendingLoggingRequest] = deque()
        self._logger: Optional[SampleCsvLogger] = None
        self._logging_stop_timer: Optional[threading.Timer] = None
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

    def set_modulation_frequency(self, frequency_hz: float) -> None:
        self._transport.send_command(pack_set_modulation_frequency(frequency_hz))

    def start_logging(
        self,
        path: str | Path,
        duration_s: float | None = None,
        channel_indices: Sequence[int] | None = None,
    ) -> None:
        logging_path = str(Path(path))
        duration = self._normalize_logging_duration(duration_s)
        indices = self._normalize_channel_indices(channel_indices)
        with self._lock:
            if not self._connected:
                raise RuntimeError("must be connected before starting CSV capture")
            self._cancel_pending_logging_locked()
            self._close_logger_locked()
            self._logging_path = logging_path
            self._set_logging_deadline_locked(duration)
            self._pending_logging_requests.append(
                PendingLoggingRequest(logging_path, duration, indices)
            )
            if duration is None:
                self._status_text = f"Arming CSV capture for {self._logging_path}"
            else:
                self._status_text = (
                    f"Arming {format_capture_duration(duration)} CSV capture "
                    f"for {self._logging_path}"
                )
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
            history = [
                np.asarray(list(channel), dtype=np.int32)
                for channel in self._channel_history
            ]
            asd_history = [
                np.asarray(list(channel), dtype=np.int32)
                for channel in self._asd_channel_history
            ]
            frame_history = np.asarray(list(self._frame_history), dtype=np.int32)
            return ControllerSnapshot(
                connected=self._connected,
                host=self._host,
                port=self._port,
                capability_line=self._capability_line,
                latest_message=self._latest_message,
                status_text=self._status_text,
                status_level=self._status_level,
                logging_path=self._logging_path,
                logging_remaining_s=self._logging_remaining_seconds_unlocked(),
                channel_history=history,
                asd_channel_history=asd_history,
                frame_history=frame_history,
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
            self._clear_asd_history_locked()
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
                self._frame_history.append(message.frame_cnt)
                for idx, channel in enumerate(message.channels):
                    self._channel_history[idx].append(channel)
                    self._asd_channel_history[idx].append(channel)
                if self._logger is not None:
                    self._logger.write_sample(message)
                self._status_text = (
                    f"SAMPLE seq={message.msg_seq} frame_cnt={message.frame_cnt}"
                )
                self._status_level = "ok"
                return

            if message.message_type is MessageType.ACK:
                if message.command_opcode is CommandOpcode.MARK_CAPTURE:
                    self._activate_logger_locked(
                        self._pop_pending_logging_request_locked()
                    )
                    return
                self._status_text = (
                    f"ACK {message.opcode_label} value={message.value} seq={message.msg_seq}"
                )
                self._status_level = "ok"
                return

            if message.message_type is MessageType.ERROR:
                if message.command_opcode is CommandOpcode.MARK_CAPTURE:
                    pending = self._pop_pending_logging_request_locked()
                    if pending is not None and pending.path is not None:
                        self._logging_path = ""
                        self._clear_logging_deadline_locked()
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

    @staticmethod
    def _normalize_logging_duration(duration_s: float | None) -> Optional[float]:
        if duration_s is None:
            return None
        duration = float(duration_s)
        if duration <= 0.0:
            return None
        return duration

    def _activate_logger_locked(
        self,
        request: Optional[PendingLoggingRequest],
    ) -> None:
        if request is None or not request.path:
            self._status_text = "Capture marker acknowledged"
            self._status_level = "ok"
            return
        try:
            self._logger = SampleCsvLogger(
                request.path,
                channel_indices=request.channel_indices,
            )
        except Exception as exc:
            self._close_logger_locked()
            self._status_text = f"Failed to start CSV logging: {exc}"
            self._status_level = "error"
            return
        self._logging_path = request.path
        if request.duration_s is None:
            self._status_text = f"Logging samples to {self._logging_path}"
        else:
            self._start_logging_timer_locked()
            remaining_s = self._logging_remaining_seconds_unlocked()
            if remaining_s is not None:
                self._status_text = (
                    f"Logging samples to {self._logging_path} "
                    f"({format_capture_duration(remaining_s)} remaining)"
                )
            else:
                self._status_text = f"Logging samples to {self._logging_path}"
        self._status_level = "ok"

    def _logging_remaining_seconds_unlocked(self) -> Optional[float]:
        if self._logging_deadline_monotonic is None:
            return None
        return max(0.0, self._logging_deadline_monotonic - time.monotonic())

    def _set_logging_deadline_locked(self, duration_s: Optional[float]) -> None:
        if duration_s is None:
            self._logging_deadline_monotonic = None
        else:
            self._logging_deadline_monotonic = time.monotonic() + duration_s

    def _clear_logging_deadline_locked(self) -> None:
        self._logging_deadline_monotonic = None

    def _start_logging_timer_locked(self) -> None:
        self._cancel_logging_timer_locked()
        remaining_s = self._logging_remaining_seconds_unlocked()
        if remaining_s is None:
            return
        self._logging_stop_timer = threading.Timer(
            remaining_s,
            self._handle_logging_duration_elapsed,
        )
        self._logging_stop_timer.daemon = True
        self._logging_stop_timer.start()

    def _handle_logging_duration_elapsed(self) -> None:
        with self._lock:
            if self._logger is None:
                self._logging_stop_timer = None
                return
            self._cancel_pending_logging_locked()
            self._close_logger_locked(cancel_timer=False)
            self._logging_stop_timer = None
            self._status_text = "CSV logging stopped after timed capture"
            self._status_level = "info"

    @staticmethod
    def _normalize_channel_indices(
        channel_indices: Sequence[int] | None,
    ) -> tuple[int, ...]:
        if channel_indices is None:
            return tuple(range(CHANNEL_COUNT))
        indices = tuple(int(idx) for idx in channel_indices)
        if not indices:
            raise ValueError("at least one channel is required")
        for idx in indices:
            if idx < 0 or idx >= CHANNEL_COUNT:
                raise ValueError(f"channel index out of range: {idx}")
        return indices

    def _cancel_pending_logging_locked(self) -> None:
        self._pending_logging_requests = deque(
            PendingLoggingRequest(None, None, ())
            for _ in self._pending_logging_requests
        )

    def _clear_asd_history_locked(self) -> None:
        for channel in self._asd_channel_history:
            channel.clear()

    def _pop_pending_logging_request_locked(
        self,
    ) -> Optional[PendingLoggingRequest]:
        if not self._pending_logging_requests:
            return None
        return self._pending_logging_requests.popleft()

    def _cancel_logging_timer_locked(self) -> None:
        if self._logging_stop_timer is not None:
            self._logging_stop_timer.cancel()
            self._logging_stop_timer = None

    def _close_logger_locked(self, cancel_timer: bool = True) -> None:
        if cancel_timer:
            self._cancel_logging_timer_locked()
        if self._logger is not None:
            self._logger.close()
            self._logger = None
        self._logging_path = ""
        self._clear_logging_deadline_locked()
