from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .controller import ClientController
from .protocol import MIN_EXTCLK_DIV, SERVER_PORT

# ADS1278 high-resolution mode: data rate = EXTCLK / 512.
# EXTCLK from FPGA divider: EXTCLK = SYS_CLK / (2 * div_val).
SYS_CLK_HZ = 125_000_000
ADS1278_OSR_HR = 512
# 24-bit two's-complement: positive full-scale code maps to +VREF.
ADS1278_FULL_SCALE_CODE = 1 << 23

Y_UNIT_CODES = "Codes"
Y_UNIT_VOLTS = "Volts"
X_UNIT_SAMPLES = "Samples"
X_UNIT_TIME = "Time (s)"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._controller = ClientController()
        self._settings = QtCore.QSettings("rp_ads1278", "client")
        self._curves: list[pg.PlotDataItem] = []
        self._plots: list[pg.PlotItem] = []

        self.setWindowTitle("rp_ads1278 Client")
        self.resize(1400, 900)
        self._build_ui()

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(self._build_connection_bar())
        layout.addWidget(self._build_command_bar())
        layout.addWidget(self._build_display_bar())
        layout.addWidget(self._build_status_bar())
        layout.addWidget(self._build_plot_widget(), 1)
        self._apply_axis_labels()

        self.setCentralWidget(central)

    def _build_connection_bar(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QtWidgets.QLabel("Host"))
        self.host_input = QtWidgets.QLineEdit(
            self._settings.value("last_host", "127.0.0.1", type=str)
        )
        self.host_input.setPlaceholderText("Red Pitaya host or IP")
        self.host_input.setMinimumWidth(200)
        layout.addWidget(self.host_input)

        layout.addWidget(QtWidgets.QLabel("Port"))
        self.port_input = QtWidgets.QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(self._settings.value("last_port", SERVER_PORT, type=int))
        layout.addWidget(self.port_input)

        self.connect_button = QtWidgets.QPushButton("Connect")
        self.connect_button.clicked.connect(self._toggle_connection)
        layout.addWidget(self.connect_button)

        layout.addSpacing(12)
        layout.addWidget(QtWidgets.QLabel("Connection"))
        self.connection_indicator = QtWidgets.QLabel()
        self.connection_indicator.setFixedSize(12, 12)
        layout.addWidget(self.connection_indicator)

        layout.addSpacing(16)
        self.frame_count_label = QtWidgets.QLabel("frame_cnt: -")
        self.msg_seq_label = QtWidgets.QLabel("msg_seq: -")
        self.enabled_label = QtWidgets.QLabel("enabled: -")
        self.overflow_label = QtWidgets.QLabel("overflow: -")
        self.divider_label = QtWidgets.QLabel("divider: -")
        for label in (
            self.frame_count_label,
            self.msg_seq_label,
            self.enabled_label,
            self.overflow_label,
            self.divider_label,
        ):
            layout.addWidget(label)

        layout.addStretch(1)
        return widget

    def _build_command_bar(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self.enable_button = QtWidgets.QPushButton("Enable")
        self.enable_button.clicked.connect(lambda: self._send_command(self._controller.set_enabled, True))
        layout.addWidget(self.enable_button)

        self.disable_button = QtWidgets.QPushButton("Disable")
        self.disable_button.clicked.connect(
            lambda: self._send_command(self._controller.set_enabled, False)
        )
        layout.addWidget(self.disable_button)

        self.sync_button = QtWidgets.QPushButton("SYNC")
        self.sync_button.clicked.connect(lambda: self._send_command(self._controller.trigger_sync))
        layout.addWidget(self.sync_button)

        layout.addSpacing(16)
        layout.addWidget(QtWidgets.QLabel("EXTCLK divider"))
        self.divider_input = QtWidgets.QSpinBox()
        self.divider_input.setRange(MIN_EXTCLK_DIV, 1_000_000)
        self.divider_input.setValue(625)
        layout.addWidget(self.divider_input)

        self.set_divider_button = QtWidgets.QPushButton("Set divider")
        self.set_divider_button.clicked.connect(
            lambda: self._send_command(
                self._controller.set_extclk_div, self.divider_input.value()
            )
        )
        layout.addWidget(self.set_divider_button)

        layout.addSpacing(16)
        self.start_logging_button = QtWidgets.QPushButton("Start CSV")
        self.start_logging_button.clicked.connect(self._start_logging)
        layout.addWidget(self.start_logging_button)

        self.stop_logging_button = QtWidgets.QPushButton("Stop CSV")
        self.stop_logging_button.clicked.connect(self._controller.stop_logging)
        layout.addWidget(self.stop_logging_button)

        layout.addStretch(1)
        return widget

    def _build_display_bar(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QtWidgets.QLabel("Y axis"))
        self.y_unit_combo = QtWidgets.QComboBox()
        self.y_unit_combo.addItems([Y_UNIT_CODES, Y_UNIT_VOLTS])
        self.y_unit_combo.setCurrentText(
            self._settings.value("y_unit", Y_UNIT_CODES, type=str)
        )
        self.y_unit_combo.currentTextChanged.connect(self._on_y_unit_changed)
        layout.addWidget(self.y_unit_combo)

        layout.addSpacing(8)
        layout.addWidget(QtWidgets.QLabel("VREF (V)"))
        self.vref_input = QtWidgets.QDoubleSpinBox()
        self.vref_input.setDecimals(6)
        self.vref_input.setRange(0.000001, 100.0)
        self.vref_input.setSingleStep(0.1)
        self.vref_input.setValue(self._settings.value("vref_volts", 2.5, type=float))
        self.vref_input.setToolTip(
            "Reference voltage applied on the ADS1278EVM. "
            "Used to convert 24-bit codes to volts: V = code * VREF / 2^23."
        )
        self.vref_input.valueChanged.connect(self._on_vref_changed)
        layout.addWidget(self.vref_input)

        layout.addSpacing(16)
        layout.addWidget(QtWidgets.QLabel("X axis"))
        self.x_unit_combo = QtWidgets.QComboBox()
        self.x_unit_combo.addItems([X_UNIT_SAMPLES, X_UNIT_TIME])
        self.x_unit_combo.setCurrentText(
            self._settings.value("x_unit", X_UNIT_SAMPLES, type=str)
        )
        self.x_unit_combo.currentTextChanged.connect(self._on_x_unit_changed)
        layout.addWidget(self.x_unit_combo)

        self.sample_rate_label = QtWidgets.QLabel("fs: -")
        layout.addSpacing(8)
        layout.addWidget(self.sample_rate_label)

        layout.addStretch(1)
        return widget

    def _build_status_bar(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self.capability_label = QtWidgets.QLabel("capability: -")
        self.logging_label = QtWidgets.QLabel("logging: off")
        self.status_label = QtWidgets.QLabel("Disconnected")
        self.status_label.setWordWrap(True)

        layout.addWidget(self.capability_label, 2)
        layout.addWidget(self.logging_label, 2)
        layout.addWidget(self.status_label, 4)
        return widget

    def _build_plot_widget(self) -> QtWidgets.QWidget:
        pg.setConfigOptions(antialias=False)
        graphics = pg.GraphicsLayoutWidget()
        for idx in range(8):
            row = idx // 2
            col = idx % 2
            plot = graphics.addPlot(row=row, col=col, title=f"CH{idx + 1}")
            plot.showGrid(x=True, y=True, alpha=0.25)
            curve = plot.plot(pen=pg.intColor(idx, hues=8))
            self._plots.append(plot)
            self._curves.append(curve)
        return graphics

    def _toggle_connection(self) -> None:
        snapshot = self._controller.get_snapshot()
        if snapshot.connected:
            self._controller.disconnect()
            return

        host = self.host_input.text().strip()
        port = self.port_input.value()
        try:
            self._controller.connect(host, port)
        except Exception as exc:
            self._show_status(str(exc), "error")
            return

        self._settings.setValue("last_host", host)
        self._settings.setValue("last_port", port)

    def _send_command(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception as exc:
            self._show_status(str(exc), "error")

    def _start_logging(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = str(Path.cwd() / f"ads1278_samples_{timestamp}.csv")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Choose CSV log path",
            default_path,
            "CSV files (*.csv)",
        )
        if not path:
            return
        try:
            self._controller.start_logging(path)
        except Exception as exc:
            self._show_status(str(exc), "error")

    def _refresh(self) -> None:
        snapshot = self._controller.get_snapshot()
        self.connect_button.setText("Disconnect" if snapshot.connected else "Connect")
        self.connection_indicator.setStyleSheet(
            self._indicator_style("#0a0" if snapshot.connected else "#c00")
        )

        latest = snapshot.latest_message
        if latest is None:
            self.frame_count_label.setText("frame_cnt: -")
            self.msg_seq_label.setText("msg_seq: -")
            self.enabled_label.setText("enabled: -")
            self.overflow_label.setText("overflow: -")
            self.divider_label.setText("divider: -")
        else:
            self.frame_count_label.setText(f"frame_cnt: {latest.frame_cnt}")
            self.msg_seq_label.setText(f"msg_seq: {latest.msg_seq}")
            self.enabled_label.setText(f"enabled: {'yes' if latest.enabled else 'no'}")
            self.overflow_label.setText(f"overflow: {'yes' if latest.overflow else 'no'}")
            self.divider_label.setText(f"divider: {latest.extclk_div}")
            if snapshot.connected and not self.divider_input.hasFocus():
                self.divider_input.setValue(latest.extclk_div)

        self.capability_label.setText(
            f"capability: {snapshot.capability_line or '-'}"
        )
        self.logging_label.setText(
            f"logging: {snapshot.logging_path or 'off'}"
        )
        self.status_label.setText(snapshot.status_text)
        self.status_label.setStyleSheet(self._status_style(snapshot.status_level))

        buttons_enabled = snapshot.connected
        for widget in (
            self.enable_button,
            self.disable_button,
            self.sync_button,
            self.set_divider_button,
            self.start_logging_button,
            self.stop_logging_button,
        ):
            widget.setEnabled(buttons_enabled)

        divider = self._effective_divider(latest)
        dt = self._sample_period(divider)
        self._update_sample_rate_label(dt)

        y_unit = self.y_unit_combo.currentText()
        x_unit = self.x_unit_combo.currentText()
        vref = self.vref_input.value()
        y_scale = vref / ADS1278_FULL_SCALE_CODE if y_unit == Y_UNIT_VOLTS else None

        for curve, history in zip(self._curves, snapshot.channel_history):
            if history.size == 0:
                curve.setData([], [])
                continue

            y = history.astype(np.float64) * y_scale if y_scale is not None else history
            if x_unit == X_UNIT_TIME and dt is not None:
                x = np.arange(history.size, dtype=np.float64) * dt
                curve.setData(x, y)
            else:
                curve.setData(y)

    def _on_y_unit_changed(self, value: str) -> None:
        self._settings.setValue("y_unit", value)
        self._apply_axis_labels()

    def _on_x_unit_changed(self, value: str) -> None:
        self._settings.setValue("x_unit", value)
        self._apply_axis_labels()

    def _on_vref_changed(self, value: float) -> None:
        self._settings.setValue("vref_volts", value)

    def _apply_axis_labels(self) -> None:
        if not self._plots:
            return
        y_unit = self.y_unit_combo.currentText()
        x_unit = self.x_unit_combo.currentText()
        y_label = "Voltage (V)" if y_unit == Y_UNIT_VOLTS else "ADC code"
        x_label = "Time (s)" if x_unit == X_UNIT_TIME else "Recent samples"
        for plot in self._plots:
            plot.setLabel("left", y_label)
            plot.setLabel("bottom", x_label)

    def _effective_divider(self, latest) -> int:
        # Prefer the divider reported by the server; fall back to the user's
        # current spinbox value so axis scaling still works pre-connect.
        if latest is not None and latest.extclk_div >= MIN_EXTCLK_DIV:
            return int(latest.extclk_div)
        return int(self.divider_input.value())

    @staticmethod
    def _sample_period(divider: int) -> float | None:
        if divider < MIN_EXTCLK_DIV:
            return None
        extclk_hz = SYS_CLK_HZ / (2.0 * divider)
        fs_hz = extclk_hz / ADS1278_OSR_HR
        if fs_hz <= 0:
            return None
        return 1.0 / fs_hz

    def _update_sample_rate_label(self, dt: float | None) -> None:
        if dt is None or dt <= 0:
            self.sample_rate_label.setText("fs: -")
            return
        fs_hz = 1.0 / dt
        if fs_hz >= 1000.0:
            self.sample_rate_label.setText(f"fs: {fs_hz / 1000.0:.3f} kHz")
        else:
            self.sample_rate_label.setText(f"fs: {fs_hz:.2f} Hz")

    def _show_status(self, text: str, level: str) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(self._status_style(level))

    @staticmethod
    def _indicator_style(color: str) -> str:
        return f"background-color: {color}; border: 1px solid #333; border-radius: 6px;"

    @staticmethod
    def _status_style(level: str) -> str:
        color = {"ok": "#0a0", "error": "#c00"}.get(level, "#333")
        return f"color: {color};"

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._controller.shutdown()
        super().closeEvent(event)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
