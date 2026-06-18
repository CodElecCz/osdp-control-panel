"""
Buzzer control widget (CMD_BUZ).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.osdp_manager import OsdpManager, ToneCode

_TONE_ITEMS: list[tuple[str, int]] = [
    ("Off (silence)", ToneCode.OFF),
    ("Default beep", ToneCode.DEFAULT),
    ("On (continuous)", ToneCode.ON),
]


class BuzzWidget(QWidget):
    def __init__(self, manager: OsdpManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        box = QGroupBox("Buzzer (CMD_BUZ)")
        form = QFormLayout(box)

        self._reader_spin = QSpinBox()
        self._reader_spin.setRange(0, 15)
        form.addRow("Reader #:", self._reader_spin)

        self._tone_combo = QComboBox()
        for name, val in _TONE_ITEMS:
            self._tone_combo.addItem(name, val)
        self._tone_combo.setCurrentIndex(1)  # Default beep
        form.addRow("Tone code:", self._tone_combo)

        self._on_cnt = QSpinBox()
        self._on_cnt.setRange(0, 255)
        self._on_cnt.setValue(3)
        self._on_cnt.setSuffix(" × 100 ms")
        form.addRow("On count:", self._on_cnt)

        self._off_cnt = QSpinBox()
        self._off_cnt.setRange(0, 255)
        self._off_cnt.setValue(3)
        self._off_cnt.setSuffix(" × 100 ms")
        form.addRow("Off count:", self._off_cnt)

        self._rep_cnt = QSpinBox()
        self._rep_cnt.setRange(0, 255)
        self._rep_cnt.setValue(3)
        self._rep_cnt.setSpecialValueText("∞ (continuous)")
        form.addRow("Repeat count:", self._rep_cnt)

        root.addWidget(box)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        send_btn = QPushButton("Send Buzz Command")
        send_btn.setMinimumWidth(160)
        send_btn.clicked.connect(self._send)
        btn_row.addWidget(send_btn)
        root.addLayout(btn_row)
        root.addStretch()

    def _send(self) -> None:
        self._manager.send_buzz(
            reader=self._reader_spin.value(),
            tone_code=self._tone_combo.currentData(),
            on_count=self._on_cnt.value(),
            off_count=self._off_cnt.value(),
            rep_count=self._rep_cnt.value(),
        )

    # persistence helpers
    def load_defaults(self, cfg: dict) -> None:
        tone_code = cfg.get("tone_code", ToneCode.DEFAULT)
        if tone_code is None:
            tone_code = ToneCode.DEFAULT
        
        # Find combo box index that matches the tone_code value
        for idx in range(self._tone_combo.count()):
            if self._tone_combo.itemData(idx) == tone_code:
                self._tone_combo.setCurrentIndex(idx)
                break
        
        self._on_cnt.setValue(cfg.get("on_count", 3))
        self._off_cnt.setValue(cfg.get("off_count", 3))
        self._rep_cnt.setValue(cfg.get("rep_count", 3))

    def save_defaults(self) -> dict:
        return {
            "reader": self._reader_spin.value(),
            "tone_code": self._tone_combo.currentData(),
            "on_count": self._on_cnt.value(),
            "off_count": self._off_cnt.value(),
            "rep_count": self._rep_cnt.value(),
        }
