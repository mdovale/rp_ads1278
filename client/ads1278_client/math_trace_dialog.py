from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .channel_math import MathTrace, validate_terms
from .protocol import CHANNEL_COUNT


class MathTraceDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        *,
        trace: MathTrace | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Channel math trace")
        self.resize(420, 320)

        self._term_rows: list[tuple[QtWidgets.QComboBox, QtWidgets.QComboBox]] = []

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(
            QtWidgets.QLabel(
                "Build a linear combination of channels, for example CH1+CH2 or CH1-CH3."
            )
        )

        self.preview_label = QtWidgets.QLabel()
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

        self.terms_widget = QtWidgets.QWidget()
        self.terms_layout = QtWidgets.QVBoxLayout(self.terms_widget)
        self.terms_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.terms_widget)

        buttons_row = QtWidgets.QHBoxLayout()
        add_term_button = QtWidgets.QPushButton("Add term")
        add_term_button.clicked.connect(lambda: self._add_term_row())
        buttons_row.addWidget(add_term_button)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        dialog_buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        dialog_buttons.accepted.connect(self._accept)
        dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(dialog_buttons)

        if trace is None or not trace.terms:
            self._add_term_row(channel_idx=0, sign=1)
            self._add_term_row(channel_idx=1, sign=1)
        else:
            for channel_idx, sign in trace.terms:
                self._add_term_row(channel_idx=channel_idx, sign=sign)

        self._update_preview()

    def _add_term_row(self, channel_idx: int = 0, sign: int = 1) -> None:
        row_widget = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)

        channel_combo = QtWidgets.QComboBox()
        for idx in range(CHANNEL_COUNT):
            channel_combo.addItem(f"CH{idx + 1}", idx)
        channel_combo.setCurrentIndex(max(0, min(channel_idx, CHANNEL_COUNT - 1)))

        sign_combo = QtWidgets.QComboBox()
        sign_combo.addItem("+", 1)
        sign_combo.addItem("-", -1)
        sign_combo.setCurrentIndex(0 if sign >= 0 else 1)

        remove_button = QtWidgets.QPushButton("Remove")
        remove_button.clicked.connect(
            lambda: self._remove_term_row(row_widget, channel_combo, sign_combo)
        )

        channel_combo.currentIndexChanged.connect(self._update_preview)
        sign_combo.currentIndexChanged.connect(self._update_preview)

        row_layout.addWidget(QtWidgets.QLabel("Term"))
        row_layout.addWidget(channel_combo)
        row_layout.addWidget(sign_combo)
        row_layout.addWidget(remove_button)
        row_layout.addStretch(1)

        self.terms_layout.addWidget(row_widget)
        self._term_rows.append((channel_combo, sign_combo))
        self._update_preview()

    def _remove_term_row(
        self,
        row_widget: QtWidgets.QWidget,
        channel_combo: QtWidgets.QComboBox,
        sign_combo: QtWidgets.QComboBox,
    ) -> None:
        if len(self._term_rows) <= 1:
            return
        self._term_rows.remove((channel_combo, sign_combo))
        row_widget.deleteLater()
        self._update_preview()

    def _current_terms(self) -> tuple[tuple[int, int], ...]:
        terms: list[tuple[int, int]] = []
        for channel_combo, sign_combo in self._term_rows:
            terms.append((int(channel_combo.currentData()), int(sign_combo.currentData())))
        return validate_terms(terms)

    def _update_preview(self) -> None:
        try:
            preview = MathTrace(enabled=True, terms=self._current_terms()).label()
        except ValueError as exc:
            preview = str(exc)
        self.preview_label.setText(f"Preview: {preview}")

    def _accept(self) -> None:
        try:
            self._current_terms()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid math trace", str(exc))
            return
        self.accept()

    def build_trace(self, *, enabled: bool = True) -> MathTrace:
        return MathTrace(enabled=enabled, terms=self._current_terms())
