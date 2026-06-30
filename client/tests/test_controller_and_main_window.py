from __future__ import annotations

import csv
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from ads1278_client.controller import (
    ClientController,
    ControllerSnapshot,
    LogDestination,
    compose_capture_duration_seconds,
    format_capture_duration,
    split_capture_duration_seconds,
)
from ads1278_client.main_window import (
    MainWindow,
    PLOT_LAYOUT_OVERLAY,
    PLOT_LAYOUT_SEPARATE,
    VIEW_MODE_ASD,
)
from ads1278_client.models import Ads1278Message, CommandOpcode, MessageType
from ads1278_client.protocol import (
    CHANNEL_COUNT,
    DEFAULT_MODULATION_FREQUENCY_HZ,
    SERVER_PORT,
    pack_mark_capture,
    pack_set_local_log_duration,
    pack_set_local_log_filename,
    pack_set_modulation_div,
    pack_set_modulation_frequency,
    pack_start_local_log,
    pack_stop_local_log,
)
from ads1278_client.units import (
    frames_per_demod,
    frame_counts_to_relative_seconds,
    raw_codes_to_volts,
    sample_indices_to_relative_seconds,
    sample_period_seconds,
    sample_rate_hz,
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


def _empty_asd_history() -> list[np.ndarray]:
    return [np.asarray([], dtype=np.int32) for _ in range(8)]


def test_unit_helpers_convert_adc_codes_and_frame_counts() -> None:
    samples = np.asarray([-(1 << 23), 0, 1 << 22], dtype=np.int32)
    volts = raw_codes_to_volts(samples, reference_volts=2.5)

    assert np.allclose(volts, [-2.5, 0.0, 1.25])
    assert np.isclose(sample_period_seconds(625), 0.00512)
    assert np.isclose(sample_rate_hz(625), 195.3125)
    assert frames_per_demod(extclk_div=1, mod_div=5120) == 10
    assert frames_per_demod(extclk_div=625, mod_div=1) == 1
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


def test_controller_reports_csv_countdown_when_timed_capture_starts(
    monkeypatch,
    tmp_path,
) -> None:
    class FakeTransportClient:
        def __init__(self, on_message, on_connected, on_disconnected, on_error) -> None:
            return None

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

    path = tmp_path / "countdown.csv"
    controller.start_logging(path, duration_s=90.0)
    snapshot = controller.get_snapshot()

    assert snapshot.logging_path == str(path)
    assert snapshot.logging_remaining_s is not None
    assert 89.0 <= snapshot.logging_remaining_s <= 90.0


def test_controller_clears_latest_message_on_disconnect() -> None:
    controller = ClientController()

    controller._handle_message(_message())
    assert controller.get_snapshot().latest_message is not None

    controller._handle_disconnected("disconnected")

    snapshot = controller.get_snapshot()
    assert snapshot.connected is False
    assert snapshot.latest_message is None


def test_controller_keeps_longer_asd_history_and_clears_on_disconnect() -> None:
    controller = ClientController(history_length=2, asd_history_length=4)

    for msg_seq in range(6):
        controller._handle_message(_message(msg_seq=msg_seq))

    snapshot = controller.get_snapshot()
    assert snapshot.channel_history[0].tolist() == [1, 1]
    assert snapshot.asd_channel_history[0].tolist() == [1, 1, 1, 1]

    controller._handle_disconnected("disconnected")

    assert controller.get_snapshot().asd_channel_history[0].size == 0


def test_controller_sets_modulation_off_or_frequency(monkeypatch) -> None:
    sent_commands = []

    class FakeTransportClient:
        def __init__(self, on_message, on_connected, on_disconnected, on_error) -> None:
            return None

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
    controller.set_modulation(False, 10.0)
    controller.set_modulation(True, 10.0)

    assert sent_commands == [
        pack_set_modulation_div(0),
        pack_set_modulation_frequency(10.0),
    ]


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
    assert timers[0].interval == pytest.approx(2.5, abs=0.05)
    assert len(rows) == 2
    assert rows[1][1] == "10"
    assert rows[1][2] == "3"
    assert controller.get_snapshot().logging_path == ""


def test_controller_arms_server_timed_usb_csv_without_client_timer(monkeypatch) -> None:
    sent_commands = []
    timers = []

    class FakeTimer:
        def __init__(self, interval, function) -> None:
            timers.append((interval, function))

        def start(self) -> None:
            return None

        def cancel(self) -> None:
            return None

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

    controller.start_logging(
        "usb_run",
        duration_s=2.5,
        channel_indices=(0, 4, 7),
        destination=LogDestination.USB_RED_PITAYA,
    )
    controller._handle_message(
        _message(
            msg_type=MessageType.ACK,
            msg_seq=9,
            opcode=CommandOpcode.MARK_CAPTURE,
            value=0,
            status_raw=0x00020001,
        )
    )
    controller._handle_message(
        _message(
            msg_type=MessageType.ACK,
            msg_seq=10,
            opcode=CommandOpcode.START_LOCAL_LOG,
            value=0x91,
            status_raw=0x00020001,
        )
    )

    assert sent_commands == [
        pack_mark_capture(),
        pack_set_local_log_duration(2.5),
        *pack_set_local_log_filename("usb_run.csv"),
        pack_start_local_log((0, 4, 7)),
    ]
    assert timers == []
    snapshot = controller.get_snapshot()
    assert snapshot.logging_path == "USB: /mnt/usb/ads1278/logs/usb_run.csv"
    assert "Logging samples on" in snapshot.status_text

    controller.stop_logging()
    assert sent_commands[-1] == pack_stop_local_log()
    controller._handle_message(
        _message(
            msg_type=MessageType.ACK,
            msg_seq=11,
            opcode=CommandOpcode.STOP_LOCAL_LOG,
            value=123,
            status_raw=0x00020001,
        )
    )
    assert "123 rows" in controller.get_snapshot().status_text


def test_controller_sends_demod_rate_bit_for_usb_ch8_logging(monkeypatch) -> None:
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
    controller._handle_message(_message(ctrl_raw=0x00000006))

    controller.start_logging(
        "usb_demod",
        channel_indices=(7,),
        destination=LogDestination.USB_RED_PITAYA,
        demod_rate=True,
    )
    controller._handle_message(
        _message(
            msg_type=MessageType.ACK,
            msg_seq=9,
            opcode=CommandOpcode.MARK_CAPTURE,
            value=0,
            ctrl_raw=0x00000006,
        )
    )

    assert sent_commands == [
        pack_mark_capture(),
        pack_set_local_log_duration(None),
        *pack_set_local_log_filename("usb_demod.csv"),
        pack_start_local_log((7,), demod_rate=True),
    ]


def test_controller_rejects_usb_demod_rate_without_demod_ctrl(monkeypatch) -> None:
    class FakeTransportClient:
        def __init__(self, on_message, on_connected, on_disconnected, on_error) -> None:
            return None

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
    controller._handle_message(_message(ctrl_raw=0x00000002))

    with pytest.raises(RuntimeError, match="acquisition \\+ demod"):
        controller.start_logging(
            "usb_demod",
            channel_indices=(7,),
            destination=LogDestination.USB_RED_PITAYA,
            demod_rate=True,
        )


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
        logging_remaining_s=None,
        channel_history=_empty_history(),
        asd_channel_history=_empty_asd_history(),
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
        for checkbox in window._channel_checkboxes:
            checkbox.setChecked(True)
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


def test_main_window_passes_demod_rate_only_for_ch8_logging(monkeypatch) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    calls = []
    snapshot = ControllerSnapshot(
        connected=True,
        host="127.0.0.1",
        port=SERVER_PORT,
        capability_line="RP_CAP:ads1278_v3",
        latest_message=_message(ctrl_raw=0x00000006),
        status_text="Connected",
        status_level="ok",
        logging_path="",
        logging_remaining_s=None,
        channel_history=_empty_history(),
        asd_channel_history=_empty_asd_history(),
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

        def set_modulation(self, enabled: bool, frequency_hz: float) -> None:
            return None

        def set_modulation_frequency(self, frequency_hz: float) -> None:
            return None

        def start_logging(
            self,
            path: str,
            duration_s: float | None = None,
            channel_indices=None,
            *,
            destination=LogDestination.LOCAL_COMPUTER,
            local_directory=None,
            demod_rate: bool = False,
        ) -> None:
            calls.append((path, duration_s, channel_indices, destination, local_directory, demod_rate))

        def stop_logging(self) -> None:
            return None

        def shutdown(self) -> None:
            return None

    monkeypatch.setattr("ads1278_client.main_window.ClientController", FakeController)

    window = MainWindow()
    try:
        window.csv_destination_combo.setCurrentText("This computer")
        for idx, checkbox in enumerate(window._channel_checkboxes):
            checkbox.blockSignals(True)
            checkbox.setChecked(idx == 7)
            checkbox.blockSignals(False)
        window._sync_demod_rate_checkbox()

        assert window.csv_demod_rate_checkbox.isEnabled() is True

        window.csv_demod_rate_checkbox.setChecked(True)
        window._start_logging()

        assert calls
        assert calls[-1][2] == (7,)
        assert calls[-1][-1] is True

        window._channel_checkboxes[0].setChecked(True)
        window._on_channel_toggled(0, True)
        assert window.csv_demod_rate_checkbox.isEnabled() is False
        assert window.csv_demod_rate_checkbox.isChecked() is False
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
        logging_remaining_s=None,
        channel_history=_empty_history(),
        asd_channel_history=_empty_asd_history(),
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


def test_main_window_asd_view_uses_spectrum_axis_labels(monkeypatch) -> None:
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
        logging_remaining_s=None,
        channel_history=_empty_history(),
        asd_channel_history=_empty_asd_history(),
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
        window.view_mode_combo.setCurrentText(VIEW_MODE_ASD)

        assert len(window._plots) == CHANNEL_COUNT
        assert window._plots[0].getAxis("bottom").labelText == "Frequency (Hz)"
        assert window._plots[0].getAxis("left").labelText == "ASD (V/sqrt(Hz))"
        assert window.y_unit_combo.currentText() == "Volts"
        assert window.y_unit_combo.isEnabled() is False
        assert window.x_unit_combo.isEnabled() is False
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
        logging_remaining_s=None,
        channel_history=_empty_history(),
        asd_channel_history=_empty_asd_history(),
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
        window.divider_input.blockSignals(True)
        window.divider_input.setValue(1000)
        window.divider_input.blockSignals(False)
        window._divider_settings_dirty = True

        window._refresh()

        assert window.divider_label.text() == "divider: 625"
        assert window.divider_input.value() == 1000
    finally:
        window.close()
        app.processEvents()


def test_refresh_preserves_pending_divider_after_set_click(monkeypatch) -> None:
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
        logging_remaining_s=None,
        channel_history=_empty_history(),
        asd_channel_history=_empty_asd_history(),
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
    monkeypatch.setattr(QtWidgets.QSpinBox, "hasFocus", lambda self: False)

    window = MainWindow()
    try:
        window.divider_input.blockSignals(True)
        window.divider_input.setValue(1000)
        window.divider_input.blockSignals(False)
        window._send_divider_command()

        window._refresh()

        assert window.divider_label.text() == "divider: 625"
        assert window.divider_input.value() == 1000
        assert window._divider_settings_dirty is True
    finally:
        window.close()
        app.processEvents()


def test_refresh_clears_divider_dirty_when_server_matches(monkeypatch) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    snapshot_holder = {"extclk_div": 625}

    def make_snapshot() -> ControllerSnapshot:
        return ControllerSnapshot(
            connected=True,
            host="127.0.0.1",
            port=SERVER_PORT,
            capability_line="RP_CAP:ads1278_v3",
            latest_message=_message(extclk_div=snapshot_holder["extclk_div"]),
            status_text="Connected",
            status_level="ok",
            logging_path="",
            logging_remaining_s=None,
            channel_history=_empty_history(),
            asd_channel_history=_empty_asd_history(),
            frame_history=_empty_frame_history(),
        )

    class FakeController:
        def get_snapshot(self) -> ControllerSnapshot:
            return make_snapshot()

        def connect(self, host: str, port: int = SERVER_PORT) -> None:
            return None

        def disconnect(self) -> None:
            return None

        def set_enabled(self, enabled: bool) -> None:
            return None

        def trigger_sync(self) -> None:
            return None

        def set_extclk_div(self, divider: int) -> None:
            snapshot_holder["extclk_div"] = divider

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
        window.divider_input.blockSignals(True)
        window.divider_input.setValue(1000)
        window.divider_input.blockSignals(False)
        window._send_divider_command()
        snapshot_holder["extclk_div"] = 1000

        window._refresh()

        assert window.divider_label.text() == "divider: 1000"
        assert window.divider_input.value() == 1000
        assert window._divider_settings_dirty is False
    finally:
        window.close()
        app.processEvents()


def test_refresh_shows_modulation_off_from_zero_divider(monkeypatch) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    snapshot = ControllerSnapshot(
        connected=True,
        host="127.0.0.1",
        port=SERVER_PORT,
        capability_line="RP_CAP:ads1278_v3",
        latest_message=_message(mod_div=0),
        status_text="Connected",
        status_level="ok",
        logging_path="",
        logging_remaining_s=None,
        channel_history=_empty_history(),
        asd_channel_history=_empty_asd_history(),
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

        def set_modulation(self, enabled: bool, frequency_hz: float) -> None:
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
        window._refresh()

        assert window.modulation_label.text() == "mod: off"
        assert window.modulation_enable_checkbox.isChecked() is False
        assert window.modulation_frequency_input.isEnabled() is False
    finally:
        window.close()
        app.processEvents()


def test_refresh_preserves_unchecked_mod_while_settings_dirty(monkeypatch) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    snapshot = ControllerSnapshot(
        connected=True,
        host="127.0.0.1",
        port=SERVER_PORT,
        capability_line="RP_CAP:ads1278_v3",
        latest_message=_message(mod_div=6_250_000),
        status_text="Connected",
        status_level="ok",
        logging_path="",
        logging_remaining_s=None,
        channel_history=_empty_history(),
        asd_channel_history=_empty_asd_history(),
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

        def set_modulation(self, enabled: bool, frequency_hz: float) -> None:
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
        window.modulation_enable_checkbox.blockSignals(True)
        window.modulation_enable_checkbox.setChecked(False)
        window.modulation_enable_checkbox.blockSignals(False)
        window._mod_enable_user_value = False
        window._mod_settings_dirty = True

        window._refresh()

        assert window.modulation_enable_checkbox.isChecked() is False
        assert window._mod_enable_user_value is False
    finally:
        window.close()
        app.processEvents()


def test_send_modulation_uses_user_value_when_checkbox_resynced(monkeypatch) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    calls: list[tuple[bool, float]] = []

    class FakeController:
        def get_snapshot(self) -> ControllerSnapshot:
            return ControllerSnapshot(
                connected=True,
                host="127.0.0.1",
                port=SERVER_PORT,
                capability_line="RP_CAP:ads1278_v3",
                latest_message=_message(mod_div=6_250_000),
                status_text="Connected",
                status_level="ok",
                logging_path="",
                logging_remaining_s=None,
                channel_history=_empty_history(),
                asd_channel_history=_empty_asd_history(),
                frame_history=_empty_frame_history(),
            )

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

        def set_modulation(self, enabled: bool, frequency_hz: float) -> None:
            calls.append((enabled, frequency_hz))

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
        window._mod_enable_user_value = False
        window._mod_settings_dirty = True
        window.modulation_enable_checkbox.setChecked(True)

        window._send_modulation_command()

        assert calls == [(False, DEFAULT_MODULATION_FREQUENCY_HZ)]
    finally:
        window.close()
        app.processEvents()


def test_modulation_checkbox_sends_command_when_connected(monkeypatch) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    calls: list[tuple[bool, float]] = []

    class FakeController:
        def get_snapshot(self) -> ControllerSnapshot:
            return ControllerSnapshot(
                connected=True,
                host="127.0.0.1",
                port=SERVER_PORT,
                capability_line="RP_CAP:ads1278_v3",
                latest_message=_message(mod_div=6_250_000),
                status_text="Connected",
                status_level="ok",
                logging_path="",
                logging_remaining_s=None,
                channel_history=_empty_history(),
                asd_channel_history=_empty_asd_history(),
                frame_history=_empty_frame_history(),
            )

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

        def set_modulation(self, enabled: bool, frequency_hz: float) -> None:
            calls.append((enabled, frequency_hz))

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
        window.modulation_enable_checkbox.setChecked(False)

        assert calls == [(False, DEFAULT_MODULATION_FREQUENCY_HZ)]
    finally:
        window.close()
        app.processEvents()
