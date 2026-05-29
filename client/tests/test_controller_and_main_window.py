from __future__ import annotations

import csv
import os

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from ads1278_client.controller import (
    ClientController,
    ControllerSnapshot,
    compose_capture_duration_seconds,
    format_capture_duration,
    split_capture_duration_seconds,
)
from ads1278_client.main_window import (
    MainWindow,
    PLOT_LAYOUT_OVERLAY,
    PLOT_LAYOUT_SEPARATE,
)
from ads1278_client.models import Ads1278Message, CommandOpcode, MessageType
from ads1278_client.protocol import CHANNEL_COUNT, SERVER_PORT, pack_mark_capture
from ads1278_client.units import (
    frame_counts_to_relative_seconds,
    raw_codes_to_volts,
    sample_indices_to_relative_seconds,
    sample_period_seconds,
)


def _message(
    *,
    msg_type: MessageType = MessageType.SAMPLE,
    msg_seq: int = 7,
    opcode: int = 0,
    value: int = 0,
    status_raw: int = 0x00010001,
    ctrl_raw: int = 0x00000002,
    extclk_div: int = 625,
    mod_div: int = 6_250_000,
) -> Ads1278Message:
    return Ads1278Message(
        msg_type=msg_type,
        msg_seq=msg_seq,
        opcode=opcode,
        value=value,
        status_raw=status_raw,
        ctrl_raw=ctrl_raw,
        extclk_div=extclk_div,
        mod_div=mod_div,
        channels=(1, 2, 3, 4, 5, 6, 7, 8),
    )


def _empty_history() -> list[np.ndarray]:
    return [np.asarray([], dtype=np.int32) for _ in range(8)]


def _empty_frame_history() -> np.ndarray:
    return np.asarray([], dtype=np.int32)


def test_unit_helpers_convert_adc_codes_and_frame_counts() -> None:
    samples = np.asarray([-(1 << 23), 0, 1 << 22], dtype=np.int32)
    volts = raw_codes_to_volts(samples, reference_volts=2.5)

    assert np.allclose(volts, [-2.5, 0.0, 1.25])
    assert np.isclose(sample_period_seconds(625), 0.00512)
    assert np.allclose(
        frame_counts_to_relative_seconds(
            np.asarray([65534, 65535, 0], dtype=np.int32),
            extclk_div=625,
        ),
        [-0.01024, -0.00512, 0.0],
    )
    assert np.allclose(
        sample_indices_to_relative_seconds(3, extclk_div=625),
        [-0.01024, -0.00512, 0.0],
    )


def test_capture_duration_helpers_compose_split_and_format() -> None:
    assert compose_capture_duration_seconds(0, 0, 0) is None
    assert compose_capture_duration_seconds(1, 2, 3.5) == 3723.5
    assert split_capture_duration_seconds(3723.5) == (1, 2, 3.5)
    assert format_capture_duration(3723.5) == "1h 2m 3.5s"
    assert format_capture_duration(90.0) == "1m 30s"
    assert format_capture_duration(5.0) == "5s"


def test_controller_clears_latest_message_on_disconnect() -> None:
    controller = ClientController()

    controller._handle_message(_message())
    assert controller.get_snapshot().latest_message is not None

    controller._handle_disconnected("disconnected")

    snapshot = controller.get_snapshot()
    assert snapshot.connected is False
    assert snapshot.latest_message is None


def test_controller_starts_csv_only_after_capture_marker_ack(
    monkeypatch,
    tmp_path,
) -> None:
    sent_commands = []

    class FakeTransportClient:
        def __init__(self, on_message, on_connected, on_disconnected, on_error) -> None:
            self.on_message = on_message
            self.on_connected = on_connected
            self.on_disconnected = on_disconnected
            self.on_error = on_error

        def connect(self, host: str, port: int = SERVER_PORT) -> None:
            return None

        def disconnect(self) -> None:
            return None

        def send_command(self, payload: bytes) -> None:
            sent_commands.append(payload)

        def is_connected(self) -> bool:
            return True

    monkeypatch.setattr("ads1278_client.controller.TransportClient", FakeTransportClient)

    controller = ClientController()
    controller._handle_connected("RP_CAP:ads1278_v3")

    path = tmp_path / "capture.csv"
    controller.start_logging(path)
    controller._handle_message(_message(msg_seq=8, status_raw=0x00020001))
    controller._handle_message(
        _message(
            msg_type=MessageType.ACK,
            msg_seq=9,
            opcode=CommandOpcode.MARK_CAPTURE,
            value=0,
            status_raw=0x00020001,
        )
    )
    controller._handle_message(_message(msg_seq=10, status_raw=0x00030001))
    controller.stop_logging()

    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert sent_commands == [pack_mark_capture()]
    assert rows[0][0] == "host_timestamp"
    assert len(rows) == 2
    assert rows[1][1] == "10"
    assert rows[1][2] == "3"


def test_controller_stops_csv_after_timed_capture(
    monkeypatch,
    tmp_path,
) -> None:
    sent_commands = []
    timers = []

    class FakeTimer:
        def __init__(self, interval, function) -> None:
            self.interval = interval
            self.function = function
            self.daemon = False
            self.cancelled = False
            timers.append(self)

        def start(self) -> None:
            return None

        def cancel(self) -> None:
            self.cancelled = True

        def fire(self) -> None:
            self.function()

    class FakeTransportClient:
        def __init__(self, on_message, on_connected, on_disconnected, on_error) -> None:
            self.on_message = on_message
            self.on_connected = on_connected
            self.on_disconnected = on_disconnected
            self.on_error = on_error

        def connect(self, host: str, port: int = SERVER_PORT) -> None:
            return None

        def disconnect(self) -> None:
            return None

        def send_command(self, payload: bytes) -> None:
            sent_commands.append(payload)

        def is_connected(self) -> bool:
            return True

    monkeypatch.setattr("ads1278_client.controller.TransportClient", FakeTransportClient)
    monkeypatch.setattr("ads1278_client.controller.threading.Timer", FakeTimer)

    controller = ClientController()
    controller._handle_connected("RP_CAP:ads1278_v3")

    path = tmp_path / "timed.csv"
    controller.start_logging(path, duration_s=2.5)
    controller._handle_message(
        _message(
            msg_type=MessageType.ACK,
            msg_seq=9,
            opcode=CommandOpcode.MARK_CAPTURE,
            value=0,
            status_raw=0x00020001,
        )
    )
    controller._handle_message(_message(msg_seq=10, status_raw=0x00030001))
    timers[0].fire()
    assert "timed capture" in controller.get_snapshot().status_text
    controller._handle_message(_message(msg_seq=11, status_raw=0x00040001))

    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert sent_commands == [pack_mark_capture()]
    assert timers[0].interval == 2.5
    assert len(rows) == 2
    assert rows[1][1] == "10"
    assert rows[1][2] == "3"
    assert controller.get_snapshot().logging_path == ""


def test_controller_ignores_stale_capture_marker_ack(monkeypatch, tmp_path) -> None:
    sent_commands = []

    class FakeTransportClient:
        def __init__(self, on_message, on_connected, on_disconnected, on_error) -> None:
            self.on_message = on_message
            self.on_connected = on_connected
            self.on_disconnected = on_disconnected
            self.on_error = on_error

        def connect(self, host: str, port: int = SERVER_PORT) -> None:
            return None

        def disconnect(self) -> None:
            return None

        def send_command(self, payload: bytes) -> None:
            sent_commands.append(payload)

        def is_connected(self) -> bool:
            return True

    monkeypatch.setattr("ads1278_client.controller.TransportClient", FakeTransportClient)

    controller = ClientController()
    controller._handle_connected("RP_CAP:ads1278_v3")

    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    controller.start_logging(first_path)
    controller.stop_logging()
    controller.start_logging(second_path)

    controller._handle_message(
        _message(
            msg_type=MessageType.ACK,
            msg_seq=9,
            opcode=CommandOpcode.MARK_CAPTURE,
            value=0,
            status_raw=0x00020001,
        )
    )
    controller._handle_message(_message(msg_seq=10, status_raw=0x00030001))
    assert second_path.exists() is False

    controller._handle_message(
        _message(
            msg_type=MessageType.ACK,
            msg_seq=11,
            opcode=CommandOpcode.MARK_CAPTURE,
            value=0,
            status_raw=0x00030001,
        )
    )
    controller._handle_message(_message(msg_seq=12, status_raw=0x00040001))
    controller.stop_logging()

    with second_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert sent_commands == [pack_mark_capture(), pack_mark_capture()]
    assert first_path.exists() is False
    assert len(rows) == 2
    assert rows[1][1] == "12"
    assert rows[1][2] == "4"


def test_controller_logs_selected_channels_only(
    monkeypatch,
    tmp_path,
) -> None:
    class FakeTransportClient:
        def __init__(self, on_message, on_connected, on_disconnected, on_error) -> None:
            self.on_message = on_message
            self.on_connected = on_connected
            self.on_disconnected = on_disconnected
            self.on_error = on_error

        def connect(self, host: str, port: int = SERVER_PORT) -> None:
            return None

        def disconnect(self) -> None:
            return None

        def send_command(self, payload: bytes) -> None:
            return None

        def is_connected(self) -> bool:
            return True

    monkeypatch.setattr("ads1278_client.controller.TransportClient", FakeTransportClient)

    controller = ClientController()
    controller._handle_connected("RP_CAP:ads1278_v3")

    path = tmp_path / "subset.csv"
    controller.start_logging(path, channel_indices=(0, 4))
    controller._handle_message(
        _message(
            msg_type=MessageType.ACK,
            msg_seq=9,
            opcode=CommandOpcode.MARK_CAPTURE,
            value=0,
            status_raw=0x00020001,
        )
    )
    controller._handle_message(_message(msg_seq=10, status_raw=0x00030001))
    controller.stop_logging()

    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == [
        "host_timestamp",
        "msg_seq",
        "frame_cnt",
        "status_raw",
        "ctrl_raw",
        "extclk_div",
        "mod_div",
        "ch1",
        "ch5",
    ]
    assert rows[1][7:] == ["1", "5"]


def test_main_window_requires_at_least_one_selected_channel(monkeypatch) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    snapshot = ControllerSnapshot(
        connected=False,
        host="127.0.0.1",
        port=SERVER_PORT,
        capability_line="",
        latest_message=None,
        status_text="Disconnected",
        status_level="info",
        logging_path="",
        channel_history=_empty_history(),
        frame_history=_empty_frame_history(),
    )

    class FakeController:
        def get_snapshot(self) -> ControllerSnapshot:
            return snapshot

        def connect(self, host: str, port: int = SERVER_PORT) -> None:
            return None

        def disconnect(self) -> None:
            return None

        def set_enabled(self, enabled: bool) -> None:
            return None

        def trigger_sync(self) -> None:
            return None

        def set_extclk_div(self, divider: int) -> None:
            return None

        def set_modulation_frequency(self, frequency_hz: float) -> None:
            return None

        def start_logging(
            self,
            path: str,
            duration_s: float | None = None,
            channel_indices=None,
        ) -> None:
            return None

        def stop_logging(self) -> None:
            return None

        def shutdown(self) -> None:
            return None

    monkeypatch.setattr("ads1278_client.main_window.ClientController", FakeController)

    window = MainWindow()
    try:
        window.plot_layout_combo.setCurrentText(PLOT_LAYOUT_SEPARATE)
        for idx in range(1, CHANNEL_COUNT):
            window._channel_checkboxes[idx].setChecked(False)
            window._on_channel_toggled(idx, False)

        window._channel_checkboxes[0].setChecked(False)
        window._on_channel_toggled(0, False)

        assert window._channel_checkboxes[0].isChecked() is True
        assert window._selected_channel_indices() == (0,)
        assert window._plots[0].isVisible() is True
        assert window._plots[1].isVisible() is False
    finally:
        window.close()
        app.processEvents()


def test_main_window_overlay_plot_mode_uses_single_plot(monkeypatch) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    snapshot = ControllerSnapshot(
        connected=False,
        host="127.0.0.1",
        port=SERVER_PORT,
        capability_line="",
        latest_message=None,
        status_text="Disconnected",
        status_level="info",
        logging_path="",
        channel_history=_empty_history(),
        frame_history=_empty_frame_history(),
    )

    class FakeController:
        def get_snapshot(self) -> ControllerSnapshot:
            return snapshot

        def connect(self, host: str, port: int = SERVER_PORT) -> None:
            return None

        def disconnect(self) -> None:
            return None

        def set_enabled(self, enabled: bool) -> None:
            return None

        def trigger_sync(self) -> None:
            return None

        def set_extclk_div(self, divider: int) -> None:
            return None

        def set_modulation_frequency(self, frequency_hz: float) -> None:
            return None

        def start_logging(
            self,
            path: str,
            duration_s: float | None = None,
            channel_indices=None,
        ) -> None:
            return None

        def stop_logging(self) -> None:
            return None

        def shutdown(self) -> None:
            return None

    monkeypatch.setattr("ads1278_client.main_window.ClientController", FakeController)

    window = MainWindow()
    try:
        window.plot_layout_combo.setCurrentText(PLOT_LAYOUT_SEPARATE)
        assert len(window._plots) == CHANNEL_COUNT
        window.plot_layout_combo.setCurrentText(PLOT_LAYOUT_OVERLAY)
        assert len(window._plots) == 1
        assert len(window._curves) == CHANNEL_COUNT
        assert window._plots[0].isVisible() is True
    finally:
        window.close()
        app.processEvents()


def test_refresh_does_not_overwrite_divider_while_editing(monkeypatch) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    snapshot = ControllerSnapshot(
        connected=True,
        host="127.0.0.1",
        port=SERVER_PORT,
        capability_line="RP_CAP:ads1278_v3",
        latest_message=_message(extclk_div=625),
        status_text="Connected",
        status_level="ok",
        logging_path="",
        channel_history=_empty_history(),
        frame_history=_empty_frame_history(),
    )

    class FakeController:
        def get_snapshot(self) -> ControllerSnapshot:
            return snapshot

        def connect(self, host: str, port: int = SERVER_PORT) -> None:
            return None

        def disconnect(self) -> None:
            return None

        def set_enabled(self, enabled: bool) -> None:
            return None

        def trigger_sync(self) -> None:
            return None

        def set_extclk_div(self, divider: int) -> None:
            return None

        def set_modulation_frequency(self, frequency_hz: float) -> None:
            return None

        def start_logging(
            self,
            path: str,
            duration_s: float | None = None,
            channel_indices=None,
        ) -> None:
            return None

        def stop_logging(self) -> None:
            return None

        def shutdown(self) -> None:
            return None

    monkeypatch.setattr("ads1278_client.main_window.ClientController", FakeController)
    monkeypatch.setattr(QtWidgets.QSpinBox, "hasFocus", lambda self: True)

    window = MainWindow()
    try:
        window.divider_input.setValue(1000)

        window._refresh()

        assert window.divider_label.text() == "divider: 625"
        assert window.divider_input.value() == 1000
    finally:
        window.close()
        app.processEvents()
