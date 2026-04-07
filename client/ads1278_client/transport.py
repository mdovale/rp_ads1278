from __future__ import annotations

import queue
import socket
import threading
from typing import Callable, Optional

from .models import Ads1278Message
from .protocol import CapabilityLineBuffer, MessageStreamBuffer, SERVER_PORT


class TransportClient:
    def __init__(
        self,
        on_message: Callable[[Ads1278Message], None],
        on_connected: Callable[[str], None],
        on_disconnected: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._on_message = on_message
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_error = on_error
        self._command_queue: queue.Queue[bytes] = queue.Queue()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._socket: Optional[socket.socket] = None
        self._connected = False

    def connect(self, host: str, port: int = SERVER_PORT, timeout_s: float = 2.0) -> None:
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("transport is already running")

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._worker_main,
                args=(host, port, timeout_s),
                name="ads1278-transport",
                daemon=True,
            )
            self._thread.start()

    def disconnect(self) -> None:
        self._stop_event.set()

        with self._lock:
            sock = self._socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)

    def send_command(self, payload: bytes) -> None:
        if not payload:
            raise ValueError("command payload must not be empty")
        self._command_queue.put(payload)

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def _set_socket(self, sock: Optional[socket.socket]) -> None:
        with self._lock:
            self._socket = sock

    def _set_connected(self, connected: bool) -> None:
        with self._lock:
            self._connected = connected

    def _finish(self) -> None:
        with self._lock:
            self._socket = None
            self._connected = False
            self._thread = None
        while True:
            try:
                self._command_queue.get_nowait()
            except queue.Empty:
                return

    def _flush_outbound(self, sock: socket.socket) -> None:
        while True:
            try:
                payload = self._command_queue.get_nowait()
            except queue.Empty:
                return
            sock.sendall(payload)

    def _worker_main(self, host: str, port: int, timeout_s: float) -> None:
        reason = "disconnected"
        sock: Optional[socket.socket] = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout_s)
            sock.connect((host, port))
            self._set_socket(sock)

            capability_buffer = CapabilityLineBuffer()
            capability: Optional[str] = None
            while not self._stop_event.is_set():
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    raise ConnectionError("connection closed before capability handshake")
                capability = capability_buffer.feed(chunk)
                if capability is not None:
                    break

            if capability is None:
                return

            remainder = capability_buffer.take_remainder()
            message_buffer = MessageStreamBuffer()

            sock.settimeout(0.2)
            self._set_connected(True)
            self._on_connected(capability)

            if remainder:
                for message in message_buffer.feed(remainder):
                    self._on_message(message)

            while not self._stop_event.is_set():
                self._flush_outbound(sock)
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue

                if not chunk:
                    reason = "server closed the connection"
                    break

                for message in message_buffer.feed(chunk):
                    self._on_message(message)

        except Exception as exc:
            reason = str(exc)
            if not self._stop_event.is_set():
                self._on_error(reason)
        finally:
            self._set_connected(False)
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            self._on_disconnected(reason)
            self._finish()
