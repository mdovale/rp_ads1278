from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .controller import ClientController
from .protocol import MIN_EXTCLK_DIV, SERVER_PORT


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._controller = ClientController()
        self._settings = QtCore.QSettings("rp_ads1278", "client")
        self._curves = []

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
        layout.addWidget(self._build_status_bar())
        layout.addWidget(self._build_plot_widget(), 1)

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
            plot.setLabel("left", "ADC")
            plot.setLabel("bottom", "Recent samples")
            curve = plot.plot(pen=pg.intColor(idx, hues=8))
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

        for curve, history in zip(self._curves, snapshot.channel_history):
            if history.size == 0:
                curve.setData([], [])
            else:
                curve.setData(history)

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
