from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .asd_worker import (
    AsdComputation,
    AsdTraceRequest,
    AsdTraceResult,
    compute_asd_traces,
)
from .channel_math import (
    MathTrace,
    compute_trace,
    load_math_traces_from_settings,
    math_traces_to_json,
)
from .controller import (
    ClientController,
    LogDestination,
    compose_capture_duration_seconds,
    format_capture_duration,
    split_capture_duration_seconds,
)
from .math_trace_dialog import MathTraceDialog
from .protocol import (
    CHANNEL_COUNT,
    DEFAULT_MODULATION_FREQUENCY_HZ,
    MIN_EXTCLK_DIV,
    MAX_MODULATION_FREQUENCY_HZ,
    MIN_MODULATION_FREQUENCY_HZ,
    SERVER_PORT,
    default_csv_basename,
    LOCAL_LOG_DIR_HINT,
    modulation_divider_to_frequency_hz,
)
from .units import sample_rate_hz

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
PLOT_LAYOUT_SEPARATE = "Separate"
PLOT_LAYOUT_OVERLAY = "Combined"
VIEW_MODE_TIME = "Time"
VIEW_MODE_ASD = "ASD"
ASD_MIN_SAMPLE_COUNT = 256
CSV_DESTINATION_LOCAL = "This computer"
CSV_DESTINATION_USB = "USB on Red Pitaya"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._controller = ClientController()
        self._settings = QtCore.QSettings("rp_ads1278", "client")
        self._curves: list[pg.PlotDataItem] = []
        self._plots: list[pg.PlotItem] = []
        self._math_curves: list[pg.PlotDataItem] = []
        self._math_plots: list[pg.PlotItem] = []
        self._math_curve_traces: list[MathTrace] = []
        self._math_traces: list[MathTrace] = self._load_math_traces()
        self._channel_checkboxes: list[QtWidgets.QCheckBox] = []
        self._plot_graphics: pg.GraphicsLayoutWidget | None = None
        self._plot_host = QtWidgets.QWidget()
        self._plot_host_layout = QtWidgets.QVBoxLayout(self._plot_host)
        self._plot_host_layout.setContentsMargins(0, 0, 0, 0)
        self._asd_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asd")
        self._asd_future: Future | None = None
        self._asd_lock = threading.Lock()
        self._asd_pending_result: AsdComputation | None = None
        self._asd_results: dict[int, AsdTraceResult] = {}
        self._asd_revision = 0
        self._last_asd_request_monotonic = 0.0

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
        layout.addWidget(self._build_math_bar())
        layout.addWidget(self._build_status_bar())
        layout.addWidget(self._plot_host, 1)
        self._rebuild_plot_widget()
        self._sync_asd_controls()

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
        self.modulation_label = QtWidgets.QLabel("mod: -")
        for label in (
            self.frame_count_label,
            self.msg_seq_label,
            self.enabled_label,
            self.overflow_label,
            self.divider_label,
            self.modulation_label,
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
        layout.addWidget(QtWidgets.QLabel("MOD freq"))
        self.modulation_frequency_input = QtWidgets.QDoubleSpinBox()
        self.modulation_frequency_input.setRange(
            MIN_MODULATION_FREQUENCY_HZ,
            MAX_MODULATION_FREQUENCY_HZ,
        )
        self.modulation_frequency_input.setDecimals(3)
        self.modulation_frequency_input.setSingleStep(1.0)
        self.modulation_frequency_input.setSuffix(" Hz")
        self.modulation_frequency_input.setValue(DEFAULT_MODULATION_FREQUENCY_HZ)
        layout.addWidget(self.modulation_frequency_input)

        self.set_modulation_button = QtWidgets.QPushButton("Set MOD")
        self.set_modulation_button.clicked.connect(
            lambda: self._send_command(
                self._controller.set_modulation_frequency,
                self.modulation_frequency_input.value(),
            )
        )
        layout.addWidget(self.set_modulation_button)

        layout.addSpacing(16)
        layout.addWidget(QtWidgets.QLabel("Save CSV to"))
        self.csv_destination_combo = QtWidgets.QComboBox()
        self.csv_destination_combo.addItems([CSV_DESTINATION_LOCAL, CSV_DESTINATION_USB])
        saved_destination = self._settings.value(
            "csv_destination",
            CSV_DESTINATION_LOCAL,
            type=str,
        )
        if saved_destination in (CSV_DESTINATION_LOCAL, CSV_DESTINATION_USB):
            self.csv_destination_combo.setCurrentText(saved_destination)
        self.csv_destination_combo.currentTextChanged.connect(
            lambda value: self._settings.setValue("csv_destination", value)
        )
        layout.addWidget(self.csv_destination_combo)

        layout.addSpacing(16)
        layout.addWidget(QtWidgets.QLabel("CSV filename"))
        self.csv_filename_input = QtWidgets.QLineEdit()
        self.csv_filename_input.setPlaceholderText(default_csv_basename())
        self.csv_filename_input.setText(
            self._settings.value("csv_filename", default_csv_basename(), type=str)
        )
        self.csv_filename_input.textChanged.connect(
            lambda value: self._settings.setValue("csv_filename", value)
        )
        layout.addWidget(self.csv_filename_input)

        self.csv_folder_label = QtWidgets.QLabel("CSV folder")
        layout.addWidget(self.csv_folder_label)
        self.csv_folder_input = QtWidgets.QLineEdit()
        self.csv_folder_input.setText(self._load_csv_folder())
        self.csv_folder_input.textChanged.connect(self._save_csv_folder)
        layout.addWidget(self.csv_folder_input)
        self.csv_folder_browse_button = QtWidgets.QPushButton("Browse...")
        self.csv_folder_browse_button.clicked.connect(self._browse_csv_folder)
        layout.addWidget(self.csv_folder_browse_button)
        self.csv_destination_combo.currentTextChanged.connect(
            self._update_csv_destination_controls
        )
        self._update_csv_destination_controls(self.csv_destination_combo.currentText())

        layout.addSpacing(16)
        layout.addWidget(QtWidgets.QLabel("CSV duration"))
        self.csv_duration_hours_input = QtWidgets.QSpinBox()
        self.csv_duration_hours_input.setRange(0, 99)
        self.csv_duration_hours_input.setSuffix(" h")
        self.csv_duration_hours_input.setToolTip(
            "Timed capture length. Leave all fields at 0 for manual logging."
        )
        layout.addWidget(self.csv_duration_hours_input)

        self.csv_duration_minutes_input = QtWidgets.QSpinBox()
        self.csv_duration_minutes_input.setRange(0, 59)
        self.csv_duration_minutes_input.setSuffix(" m")
        layout.addWidget(self.csv_duration_minutes_input)

        self.csv_duration_seconds_input = QtWidgets.QDoubleSpinBox()
        self.csv_duration_seconds_input.setRange(0.0, 59.999)
        self.csv_duration_seconds_input.setDecimals(3)
        self.csv_duration_seconds_input.setSingleStep(1.0)
        self.csv_duration_seconds_input.setSuffix(" s")
        layout.addWidget(self.csv_duration_seconds_input)

        hours, minutes, seconds = self._load_csv_duration_parts()
        self.csv_duration_hours_input.setValue(hours)
        self.csv_duration_minutes_input.setValue(minutes)
        self.csv_duration_seconds_input.setValue(seconds)
        self.csv_duration_hours_input.valueChanged.connect(self._save_csv_duration_parts)
        self.csv_duration_minutes_input.valueChanged.connect(self._save_csv_duration_parts)
        self.csv_duration_seconds_input.valueChanged.connect(self._save_csv_duration_parts)

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

        layout.addWidget(QtWidgets.QLabel("View"))
        self.view_mode_combo = QtWidgets.QComboBox()
        self.view_mode_combo.addItems([VIEW_MODE_TIME, VIEW_MODE_ASD])
        self.view_mode_combo.setCurrentText(
            self._settings.value("view_mode", VIEW_MODE_TIME, type=str)
        )
        self.view_mode_combo.currentTextChanged.connect(self._on_view_mode_changed)
        layout.addWidget(self.view_mode_combo)

        layout.addSpacing(8)
        layout.addWidget(QtWidgets.QLabel("ASD window"))
        self.asd_window_seconds_input = QtWidgets.QDoubleSpinBox()
        self.asd_window_seconds_input.setRange(1.0, 600.0)
        self.asd_window_seconds_input.setDecimals(1)
        self.asd_window_seconds_input.setSingleStep(10.0)
        self.asd_window_seconds_input.setSuffix(" s")
        self.asd_window_seconds_input.setValue(
            self._settings.value("asd_window_seconds", 60.0, type=float)
        )
        self.asd_window_seconds_input.valueChanged.connect(self._on_asd_settings_changed)
        layout.addWidget(self.asd_window_seconds_input)

        layout.addWidget(QtWidgets.QLabel("refresh"))
        self.asd_refresh_seconds_input = QtWidgets.QDoubleSpinBox()
        self.asd_refresh_seconds_input.setRange(0.5, 10.0)
        self.asd_refresh_seconds_input.setDecimals(1)
        self.asd_refresh_seconds_input.setSingleStep(0.5)
        self.asd_refresh_seconds_input.setSuffix(" s")
        self.asd_refresh_seconds_input.setValue(
            self._settings.value("asd_refresh_seconds", 2.0, type=float)
        )
        self.asd_refresh_seconds_input.valueChanged.connect(self._on_asd_settings_changed)
        layout.addWidget(self.asd_refresh_seconds_input)

        self.asd_status_label = QtWidgets.QLabel("ASD: idle")
        layout.addSpacing(8)
        layout.addWidget(self.asd_status_label)

        layout.addSpacing(16)
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

        layout.addSpacing(16)
        layout.addWidget(QtWidgets.QLabel("Channels"))
        for idx in range(CHANNEL_COUNT):
            checkbox = QtWidgets.QCheckBox(f"CH{idx + 1}")
            checkbox.setChecked(self._load_channel_selected(idx))
            checkbox.toggled.connect(
                lambda checked, channel_idx=idx: self._on_channel_toggled(
                    channel_idx, checked
                )
            )
            layout.addWidget(checkbox)
            self._channel_checkboxes.append(checkbox)

        layout.addSpacing(16)
        layout.addWidget(QtWidgets.QLabel("Plot layout"))
        self.plot_layout_combo = QtWidgets.QComboBox()
        self.plot_layout_combo.addItems([PLOT_LAYOUT_SEPARATE, PLOT_LAYOUT_OVERLAY])
        self.plot_layout_combo.blockSignals(True)
        self.plot_layout_combo.setCurrentText(self._load_plot_layout())
        self.plot_layout_combo.blockSignals(False)
        self.plot_layout_combo.currentTextChanged.connect(self._on_plot_layout_changed)
        layout.addWidget(self.plot_layout_combo)

        self.sample_rate_label = QtWidgets.QLabel("fs: -")
        layout.addSpacing(8)
        layout.addWidget(self.sample_rate_label)

        layout.addStretch(1)
        return widget

    def _build_math_bar(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        controls = QtWidgets.QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(QtWidgets.QLabel("Math traces"))
        add_button = QtWidgets.QPushButton("Add")
        add_button.clicked.connect(self._add_math_trace)
        controls.addWidget(add_button)

        edit_button = QtWidgets.QPushButton("Edit")
        edit_button.clicked.connect(self._edit_selected_math_trace)
        controls.addWidget(edit_button)

        remove_button = QtWidgets.QPushButton("Remove")
        remove_button.clicked.connect(self._remove_selected_math_trace)
        controls.addWidget(remove_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.math_traces_list = QtWidgets.QListWidget()
        self.math_traces_list.setMaximumHeight(72)
        self.math_traces_list.itemChanged.connect(self._on_math_trace_item_changed)
        self.math_traces_list.itemDoubleClicked.connect(
            lambda _item: self._edit_selected_math_trace()
        )
        layout.addWidget(self.math_traces_list)
        self._refresh_math_traces_list()
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

    def _rebuild_plot_widget(self) -> None:
        if self._plot_graphics is not None:
            self._plot_host_layout.removeWidget(self._plot_graphics)
            self._plot_graphics.deleteLater()
            self._plot_graphics = None

        self._plots.clear()
        self._curves.clear()
        self._math_plots.clear()
        self._math_curves.clear()
        self._math_curve_traces.clear()

        pg.setConfigOptions(antialias=False)
        graphics = pg.GraphicsLayoutWidget()
        enabled_math_traces = self._enabled_math_traces()
        if self._is_asd_view_mode():
            if self._is_overlay_plot_mode():
                plot = graphics.addPlot(row=0, col=0, title="Selected channel ASD")
                plot.showGrid(x=True, y=True, alpha=0.25)
                plot.addLegend(offset=(10, 10))
                plot.setLogMode(x=True, y=True)
                self._plots.append(plot)
                for idx in range(CHANNEL_COUNT):
                    curve = plot.plot(
                        pen=pg.mkPen(pg.intColor(idx, hues=8), width=2),
                        name=f"CH{idx + 1}",
                    )
                    curve.setFftMode(False)
                    self._curves.append(curve)
            else:
                for idx in range(CHANNEL_COUNT):
                    row = idx // 2
                    col = idx % 2
                    plot = graphics.addPlot(row=row, col=col, title=f"CH{idx + 1} ASD")
                    plot.showGrid(x=True, y=True, alpha=0.25)
                    plot.setLogMode(x=True, y=True)
                    curve = plot.plot(pen=pg.intColor(idx, hues=8))
                    curve.setFftMode(False)
                    self._plots.append(plot)
                    self._curves.append(curve)
        elif self._is_overlay_plot_mode():
            plot = graphics.addPlot(row=0, col=0, title="Selected channels")
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.addLegend(offset=(10, 10))
            self._plots.append(plot)
            for idx in range(CHANNEL_COUNT):
                curve = plot.plot(
                    pen=pg.mkPen(pg.intColor(idx, hues=8), width=2),
                    name=f"CH{idx + 1}",
                )
                self._curves.append(curve)
            for math_idx, trace in enumerate(enabled_math_traces):
                curve = plot.plot(
                    pen=pg.mkPen(pg.intColor(math_idx + CHANNEL_COUNT, hues=12), width=2),
                    name=trace.label(),
                )
                self._math_curve_traces.append(trace)
                self._math_curves.append(curve)
        else:
            for idx in range(CHANNEL_COUNT):
                row = idx // 2
                col = idx % 2
                plot = graphics.addPlot(row=row, col=col, title=f"CH{idx + 1}")
                plot.showGrid(x=True, y=True, alpha=0.25)
                curve = plot.plot(pen=pg.intColor(idx, hues=8))
                self._plots.append(plot)
                self._curves.append(curve)
            row_offset = (CHANNEL_COUNT + 1) // 2
            for math_idx, trace in enumerate(enabled_math_traces):
                row = row_offset + math_idx // 2
                col = math_idx % 2
                plot = graphics.addPlot(row=row, col=col, title=trace.label())
                plot.showGrid(x=True, y=True, alpha=0.25)
                curve = plot.plot(
                    pen=pg.mkPen(pg.intColor(math_idx + CHANNEL_COUNT, hues=12), width=2)
                )
                self._math_plots.append(plot)
                self._math_curve_traces.append(trace)
                self._math_curves.append(curve)

        self._plot_graphics = graphics
        self._plot_host_layout.addWidget(self._plot_graphics)
        self._apply_plot_visibility()
        self._apply_axis_labels()

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
        try:
            duration_s = self._selected_csv_duration_seconds()
            channel_indices = self._selected_channel_indices()
            filename = self.csv_filename_input.text().strip()
            if not filename:
                filename = default_csv_basename()
                self.csv_filename_input.setText(filename)
            if self.csv_destination_combo.currentText() == CSV_DESTINATION_USB:
                self._controller.start_logging(
                    filename,
                    duration_s=duration_s,
                    channel_indices=channel_indices,
                    destination=LogDestination.USB_RED_PITAYA,
                )
            else:
                self._controller.start_logging(
                    filename,
                    duration_s=duration_s,
                    channel_indices=channel_indices,
                    destination=LogDestination.LOCAL_COMPUTER,
                    local_directory=self.csv_folder_input.text().strip() or str(Path.cwd()),
                )
        except Exception as exc:
            self._show_status(str(exc), "error")

    def _load_csv_folder(self) -> str:
        saved = self._settings.value("csv_folder", "", type=str).strip()
        if saved:
            return saved
        return str(Path.cwd())

    def _save_csv_folder(self) -> None:
        self._settings.setValue("csv_folder", self.csv_folder_input.text())

    def _browse_csv_folder(self) -> None:
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose CSV folder",
            self.csv_folder_input.text().strip() or str(Path.cwd()),
        )
        if not selected:
            return
        self.csv_folder_input.setText(selected)

    def _update_csv_destination_controls(self, destination: str) -> None:
        local_destination = destination == CSV_DESTINATION_LOCAL
        for widget in (
            self.csv_folder_label,
            self.csv_folder_input,
            self.csv_folder_browse_button,
        ):
            widget.setVisible(local_destination)
        if local_destination:
            self.csv_filename_input.setToolTip(
                "Base filename for the CSV on this computer."
            )
        else:
            self.csv_filename_input.setToolTip(
                f"Base filename written under {LOCAL_LOG_DIR_HINT} on the Red Pitaya USB stick."
            )

    def _load_csv_duration_parts(self) -> tuple[int, int, float]:
        if (
            self._settings.contains("csv_duration_h")
            or self._settings.contains("csv_duration_m")
            or self._settings.contains("csv_duration_sec")
        ):
            return (
                self._settings.value("csv_duration_h", 0, type=int),
                self._settings.value("csv_duration_m", 0, type=int),
                self._settings.value("csv_duration_sec", 0.0, type=float),
            )

        legacy_total = self._settings.value("csv_duration_s", 0.0, type=float)
        return split_capture_duration_seconds(legacy_total)

    def _save_csv_duration_parts(self) -> None:
        self._settings.setValue("csv_duration_h", self.csv_duration_hours_input.value())
        self._settings.setValue("csv_duration_m", self.csv_duration_minutes_input.value())
        self._settings.setValue("csv_duration_sec", self.csv_duration_seconds_input.value())

    def _selected_csv_duration_seconds(self) -> float | None:
        return compose_capture_duration_seconds(
            self.csv_duration_hours_input.value(),
            self.csv_duration_minutes_input.value(),
            self.csv_duration_seconds_input.value(),
        )

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
            self.modulation_label.setText("mod: -")
        else:
            modulation_frequency_hz = modulation_divider_to_frequency_hz(latest.mod_div)
            self.frame_count_label.setText(f"frame_cnt: {latest.frame_cnt}")
            self.msg_seq_label.setText(f"msg_seq: {latest.msg_seq}")
            self.enabled_label.setText(f"enabled: {'yes' if latest.enabled else 'no'}")
            self.overflow_label.setText(f"overflow: {'yes' if latest.overflow else 'no'}")
            self.divider_label.setText(f"divider: {latest.extclk_div}")
            self.modulation_label.setText(f"mod: {modulation_frequency_hz:.3f} Hz")
            if snapshot.connected and not self.divider_input.hasFocus():
                self.divider_input.setValue(latest.extclk_div)
            if snapshot.connected and not self.modulation_frequency_input.hasFocus():
                self.modulation_frequency_input.setValue(modulation_frequency_hz)

        self.capability_label.setText(
            f"capability: {snapshot.capability_line or '-'}"
        )
        if snapshot.logging_path:
            if snapshot.logging_remaining_s is not None:
                remaining_text = format_capture_duration(snapshot.logging_remaining_s)
                self.logging_label.setText(
                    f"logging: {snapshot.logging_path} ({remaining_text} left)"
                )
            else:
                self.logging_label.setText(f"logging: {snapshot.logging_path}")
        else:
            self.logging_label.setText("logging: off")
        self.status_label.setText(snapshot.status_text)
        self.status_label.setStyleSheet(self._status_style(snapshot.status_level))

        buttons_enabled = snapshot.connected
        for widget in (
            self.enable_button,
            self.disable_button,
            self.sync_button,
            self.set_divider_button,
            self.set_modulation_button,
            self.start_logging_button,
            self.stop_logging_button,
            self.csv_destination_combo,
            self.csv_filename_input,
            self.csv_folder_input,
            self.csv_folder_browse_button,
            self.csv_duration_hours_input,
            self.csv_duration_minutes_input,
            self.csv_duration_seconds_input,
        ):
            widget.setEnabled(buttons_enabled)

        divider = self._effective_divider(latest)
        dt = self._sample_period(divider)
        self._update_sample_rate_label(dt)

        y_unit = self.y_unit_combo.currentText()
        x_unit = self.x_unit_combo.currentText()
        vref = self.vref_input.value()
        y_scale = vref / ADS1278_FULL_SCALE_CODE if y_unit == Y_UNIT_VOLTS else None

        self._consume_asd_result()
        if self._is_asd_view_mode():
            self._refresh_asd(snapshot, divider, vref)
            return

        if self._is_overlay_plot_mode():
            for idx, curve in enumerate(self._curves):
                if not self._is_channel_selected(idx):
                    curve.setVisible(False)
                    continue

                curve.setVisible(True)
                self._update_curve_data(
                    curve,
                    snapshot.channel_history[idx],
                    x_unit=x_unit,
                    dt=dt,
                    y_scale=y_scale,
                )
            for trace, curve in zip(self._math_curve_traces, self._math_curves):
                curve.setVisible(True)
                history = compute_trace(trace, snapshot.channel_history)
                self._update_curve_data(
                    curve,
                    history,
                    x_unit=x_unit,
                    dt=dt,
                    y_scale=y_scale,
                    is_math=True,
                )
            return

        for idx, (plot, curve) in enumerate(zip(self._plots, self._curves)):
            visible = self._is_channel_selected(idx)
            plot.setVisible(visible)
            if not visible:
                continue

            self._update_curve_data(
                curve,
                snapshot.channel_history[idx],
                x_unit=x_unit,
                dt=dt,
                y_scale=y_scale,
            )

        for plot, trace, curve in zip(
            self._math_plots,
            self._math_curve_traces,
            self._math_curves,
        ):
            plot.setVisible(True)
            history = compute_trace(trace, snapshot.channel_history)
            self._update_curve_data(
                curve,
                history,
                x_unit=x_unit,
                dt=dt,
                y_scale=y_scale,
                is_math=True,
            )

    @staticmethod
    def _update_curve_data(
        curve: pg.PlotDataItem,
        history: np.ndarray,
        *,
        x_unit: str,
        dt: float | None,
        y_scale: float | None,
        is_math: bool = False,
    ) -> None:
        if history.size == 0:
            curve.setData([], [])
            return

        if is_math or y_scale is not None:
            y = history.astype(np.float64)
            if y_scale is not None:
                y = y * y_scale
        else:
            y = history

        if x_unit == X_UNIT_TIME and dt is not None:
            x = np.arange(history.size, dtype=np.float64) * dt
            curve.setData(x, y)
        else:
            curve.setData(y)

    def _refresh_asd(self, snapshot, divider: int, vref: float) -> None:
        try:
            fs_hz = sample_rate_hz(divider)
        except ValueError:
            self.asd_status_label.setText("ASD: invalid sample rate")
            return

        selected_indices = [
            idx for idx in range(CHANNEL_COUNT) if self._is_channel_selected(idx)
        ]
        for idx, curve in enumerate(self._curves):
            visible = idx in selected_indices
            curve.setVisible(visible)
            if not visible:
                curve.setData([], [])
                continue
            result = self._asd_results.get(idx)
            if result is None:
                curve.setData([], [])
            else:
                curve.setData(result.spectrum.frequencies_hz, result.spectrum.asd)

        if not selected_indices:
            self.asd_status_label.setText("ASD: no channel selected")
            return

        available = min(
            snapshot.asd_channel_history[idx].size for idx in selected_indices
        )
        if available < ASD_MIN_SAMPLE_COUNT:
            self._asd_results.clear()
            for curve in self._curves:
                curve.setData([], [])
            self.asd_status_label.setText(
                f"ASD: accumulating {available}/{ASD_MIN_SAMPLE_COUNT} samples"
            )
            return

        window_samples = max(ASD_MIN_SAMPLE_COUNT, int(self.asd_window_seconds_input.value() * fs_hz))
        window_samples = min(window_samples, available)
        now = time.monotonic()
        refresh_s = self.asd_refresh_seconds_input.value()
        if self._asd_future is not None and not self._asd_future.done():
            self.asd_status_label.setText(
                f"ASD: computing {window_samples / fs_hz:.1f}s window..."
            )
            return
        if now - self._last_asd_request_monotonic < refresh_s and self._asd_results:
            return

        traces = [
            AsdTraceRequest(
                channel_index=idx,
                label=f"CH{idx + 1}",
                samples_codes=snapshot.asd_channel_history[idx][-window_samples:].copy(),
            )
            for idx in selected_indices
        ]
        self._request_asd_compute(
            traces=traces,
            fs_hz=fs_hz,
            reference_volts=vref,
        )

    def _request_asd_compute(
        self,
        *,
        traces: list[AsdTraceRequest],
        fs_hz: float,
        reference_volts: float,
    ) -> None:
        if self._asd_future is not None and not self._asd_future.done():
            return
        self._asd_revision += 1
        revision = self._asd_revision
        self._last_asd_request_monotonic = time.monotonic()
        self._asd_future = self._asd_executor.submit(
            compute_asd_traces,
            revision=revision,
            traces=traces,
            fs_hz=fs_hz,
            reference_volts=reference_volts,
        )
        self._asd_future.add_done_callback(self._on_asd_compute_done)

    def _on_asd_compute_done(self, future: Future) -> None:
        try:
            result = future.result()
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            result = AsdComputation(
                revision=self._asd_revision,
                results=(),
                sample_count=0,
                duration_s=0.0,
                compute_ms=0.0,
                error=str(exc),
            )
        with self._asd_lock:
            self._asd_pending_result = result

    def _consume_asd_result(self) -> None:
        with self._asd_lock:
            result = self._asd_pending_result
            self._asd_pending_result = None
        if result is None:
            return
        if self._asd_future is not None and self._asd_future.done():
            self._asd_future = None
        if result.revision < self._asd_revision:
            return
        if result.error:
            self.asd_status_label.setText(f"ASD: {result.error}")
            return
        self._asd_results = {
            trace.channel_index: trace for trace in result.results
        }
        self.asd_status_label.setText(
            "ASD: "
            f"{result.duration_s:.1f}s, {result.sample_count} samples, "
            f"{result.compute_ms:.0f} ms"
        )

    def _load_math_traces(self) -> list[MathTrace]:
        return load_math_traces_from_settings(
            self._settings.value("math_traces", "", type=str)
        )

    def _save_math_traces(self) -> None:
        self._settings.setValue("math_traces", math_traces_to_json(self._math_traces))

    def _enabled_math_traces(self) -> list[MathTrace]:
        return [trace for trace in self._math_traces if trace.enabled]

    def _refresh_math_traces_list(self) -> None:
        if not hasattr(self, "math_traces_list"):
            return
        self.math_traces_list.blockSignals(True)
        self.math_traces_list.clear()
        for idx, trace in enumerate(self._math_traces):
            item = QtWidgets.QListWidgetItem(trace.label())
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.Checked if trace.enabled else QtCore.Qt.Unchecked
            )
            item.setData(QtCore.Qt.UserRole, idx)
            self.math_traces_list.addItem(item)
        self.math_traces_list.blockSignals(False)

    def _add_math_trace(self) -> None:
        dialog = MathTraceDialog(self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        self._math_traces.append(dialog.build_trace(enabled=True))
        self._save_math_traces()
        self._refresh_math_traces_list()
        self._rebuild_plot_widget()

    def _edit_selected_math_trace(self) -> None:
        item = self.math_traces_list.currentItem()
        if item is None:
            return
        trace_idx = int(item.data(QtCore.Qt.UserRole))
        dialog = MathTraceDialog(self, trace=self._math_traces[trace_idx])
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        enabled = self._math_traces[trace_idx].enabled
        self._math_traces[trace_idx] = dialog.build_trace(enabled=enabled)
        self._save_math_traces()
        self._refresh_math_traces_list()
        self._rebuild_plot_widget()

    def _remove_selected_math_trace(self) -> None:
        row = self.math_traces_list.currentRow()
        if row < 0:
            return
        del self._math_traces[row]
        self._save_math_traces()
        self._refresh_math_traces_list()
        self._rebuild_plot_widget()

    def _on_math_trace_item_changed(self, item: QtWidgets.QListWidgetItem) -> None:
        if item is None:
            return
        trace_idx = item.data(QtCore.Qt.UserRole)
        if trace_idx is None:
            return
        enabled = item.checkState() == QtCore.Qt.Checked
        trace = self._math_traces[int(trace_idx)]
        if trace.enabled == enabled:
            return
        self._math_traces[int(trace_idx)] = MathTrace(
            enabled=enabled,
            terms=trace.terms,
        )
        self._save_math_traces()
        self._rebuild_plot_widget()

    def _load_channel_selected(self, idx: int) -> bool:
        default = [True] * CHANNEL_COUNT
        stored = self._settings.value("visible_channels", default, type=list)
        if not isinstance(stored, list) or len(stored) != CHANNEL_COUNT:
            return True
        if not any(bool(value) for value in stored):
            return True
        return bool(stored[idx])

    def _save_channel_selection(self) -> None:
        self._settings.setValue(
            "visible_channels",
            [checkbox.isChecked() for checkbox in self._channel_checkboxes],
        )

    def _is_channel_selected(self, idx: int) -> bool:
        if idx < 0 or idx >= len(self._channel_checkboxes):
            return True
        return self._channel_checkboxes[idx].isChecked()

    def _selected_channel_indices(self) -> tuple[int, ...]:
        indices = tuple(
            idx
            for idx, checkbox in enumerate(self._channel_checkboxes)
            if checkbox.isChecked()
        )
        if indices:
            return indices
        return (0,)

    def _on_channel_toggled(self, idx: int, checked: bool) -> None:
        if 0 <= idx < len(self._channel_checkboxes):
            checked = self._channel_checkboxes[idx].isChecked()
        if not checked and sum(checkbox.isChecked() for checkbox in self._channel_checkboxes) == 0:
            checkbox = self._channel_checkboxes[idx]
            checkbox.blockSignals(True)
            checkbox.setChecked(True)
            checkbox.blockSignals(False)
            self._apply_plot_visibility()
            return
        self._save_channel_selection()
        self._apply_plot_visibility()

    def _load_plot_layout(self) -> str:
        layout = self._settings.value("plot_layout", PLOT_LAYOUT_SEPARATE, type=str)
        if layout in (PLOT_LAYOUT_SEPARATE, PLOT_LAYOUT_OVERLAY):
            return layout
        return PLOT_LAYOUT_SEPARATE

    def _is_asd_view_mode(self) -> bool:
        if hasattr(self, "view_mode_combo"):
            return self.view_mode_combo.currentText() == VIEW_MODE_ASD
        return False

    def _is_overlay_plot_mode(self) -> bool:
        if hasattr(self, "plot_layout_combo"):
            return self.plot_layout_combo.currentText() == PLOT_LAYOUT_OVERLAY
        return self._load_plot_layout() == PLOT_LAYOUT_OVERLAY

    def _on_view_mode_changed(self, value: str) -> None:
        if value not in (VIEW_MODE_TIME, VIEW_MODE_ASD):
            value = VIEW_MODE_TIME
            self.view_mode_combo.setCurrentText(value)
        self._settings.setValue("view_mode", value)
        self._asd_results.clear()
        self._sync_asd_controls()
        self._rebuild_plot_widget()

    def _on_asd_settings_changed(self, _value: float) -> None:
        self._settings.setValue(
            "asd_window_seconds",
            self.asd_window_seconds_input.value(),
        )
        self._settings.setValue(
            "asd_refresh_seconds",
            self.asd_refresh_seconds_input.value(),
        )
        self._asd_results.clear()
        self._last_asd_request_monotonic = 0.0

    def _sync_asd_controls(self) -> None:
        is_asd = self._is_asd_view_mode()
        self.asd_window_seconds_input.setEnabled(is_asd)
        self.asd_refresh_seconds_input.setEnabled(is_asd)
        self.x_unit_combo.setEnabled(not is_asd)
        self.y_unit_combo.setEnabled(not is_asd)
        if is_asd and self.y_unit_combo.currentText() != Y_UNIT_VOLTS:
            self.y_unit_combo.setCurrentText(Y_UNIT_VOLTS)

    def _on_plot_layout_changed(self, value: str) -> None:
        self._settings.setValue("plot_layout", value)
        self._rebuild_plot_widget()

    def _apply_plot_visibility(self) -> None:
        if not self._plots:
            return
        if self._is_overlay_plot_mode():
            self._plots[0].setVisible(True)
            for idx, curve in enumerate(self._curves):
                curve.setVisible(self._is_channel_selected(idx))
            return

        for idx, plot in enumerate(self._plots):
            plot.setVisible(self._is_channel_selected(idx))

    def _on_y_unit_changed(self, value: str) -> None:
        self._settings.setValue("y_unit", value)
        self._apply_axis_labels()

    def _on_x_unit_changed(self, value: str) -> None:
        self._settings.setValue("x_unit", value)
        self._apply_axis_labels()

    def _on_vref_changed(self, value: float) -> None:
        self._settings.setValue("vref_volts", value)

    def _apply_axis_labels(self) -> None:
        if not self._plots and not self._math_plots:
            return
        if self._is_asd_view_mode():
            for plot in self._plots:
                plot.setLabel("left", "ASD (V/sqrt(Hz))")
                plot.setLabel("bottom", "Frequency (Hz)")
            return
        y_unit = self.y_unit_combo.currentText()
        x_unit = self.x_unit_combo.currentText()
        y_label = "Voltage (V)" if y_unit == Y_UNIT_VOLTS else "ADC code"
        x_label = "Time (s)" if x_unit == X_UNIT_TIME else "Recent samples"
        for plot in (*self._plots, *self._math_plots):
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
        self._asd_executor.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
