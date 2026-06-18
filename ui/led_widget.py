"""
LED control widget.

Exposes controls for both the *permanent* and *temporary* LED commands
(CMD_LED).  Permanent mode keeps the LED state indefinitely; temporary
mode blinks for timer_count × 100 ms then reverts to the permanent state.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.osdp_manager import LedColor, LedControlCode, OsdpManager

# ── colour names ──────────────────────────────────────────────────────
_COLOR_ITEMS: list[tuple[str, int]] = [
    ("None", LedColor.NONE),
    ("Red", LedColor.RED),
    ("Green", LedColor.GREEN),
    ("Amber", LedColor.AMBER),
    ("Blue", LedColor.BLUE),
    ("Magenta", LedColor.MAGENTA),
    ("Cyan", LedColor.CYAN),
    ("White", LedColor.WHITE),
]

_CC_ITEMS: list[tuple[str, int]] = [
    ("NOP", LedControlCode.NOP),
    ("Cancel", LedControlCode.CANCEL),
    ("Set", LedControlCode.SET),
]


def _make_color_combo(default: int = LedColor.NONE) -> QComboBox:
    cb = QComboBox()
    for name, val in _COLOR_ITEMS:
        cb.addItem(name, val)
    cb.setCurrentIndex(default)
    return cb


def _make_cc_combo(default: int = LedControlCode.SET) -> QComboBox:
    cb = QComboBox()
    for name, val in _CC_ITEMS:
        cb.addItem(name, val)
    # select SET by default
    idx = cb.findData(default)
    if idx >= 0:
        cb.setCurrentIndex(idx)
    return cb


class LedWidget(QWidget):
    def __init__(self, manager: OsdpManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── common ────────────────────────────────────────────────────
        common_box = QGroupBox("Common")
        common_form = QFormLayout(common_box)

        self._reader_spin = QSpinBox()
        self._reader_spin.setRange(0, 15)
        common_form.addRow("Reader #:", self._reader_spin)

        self._led_spin = QSpinBox()
        self._led_spin.setRange(0, 15)
        common_form.addRow("LED #:", self._led_spin)

        root.addWidget(common_box)

        # ── permanent ─────────────────────────────────────────────────
        perm_box = QGroupBox("Permanent LED")
        perm_form = QFormLayout(perm_box)

        self._perm_cc = _make_cc_combo(LedControlCode.SET)
        perm_form.addRow("Control code:", self._perm_cc)

        self._perm_on_color = _make_color_combo(LedColor.GREEN)
        perm_form.addRow("On colour:", self._perm_on_color)

        self._perm_off_color = _make_color_combo(LedColor.NONE)
        perm_form.addRow("Off colour:", self._perm_off_color)

        self._perm_on_cnt = QSpinBox()
        self._perm_on_cnt.setRange(0, 255)
        self._perm_on_cnt.setValue(5)
        self._perm_on_cnt.setSuffix(" × 100 ms")
        perm_form.addRow("On count:", self._perm_on_cnt)

        self._perm_off_cnt = QSpinBox()
        self._perm_off_cnt.setRange(0, 255)
        self._perm_off_cnt.setValue(5)
        self._perm_off_cnt.setSuffix(" × 100 ms")
        perm_form.addRow("Off count:", self._perm_off_cnt)

        root.addWidget(perm_box)

        # ── temporary ─────────────────────────────────────────────────
        self._temp_enabled = QCheckBox("Enable temporary override")
        root.addWidget(self._temp_enabled)

        self._temp_box = QGroupBox("Temporary LED")
        self._temp_box.setEnabled(False)
        temp_form = QFormLayout(self._temp_box)

        self._temp_cc = _make_cc_combo(LedControlCode.SET)
        temp_form.addRow("Control code:", self._temp_cc)

        self._temp_on_color = _make_color_combo(LedColor.RED)
        temp_form.addRow("On colour:", self._temp_on_color)

        self._temp_off_color = _make_color_combo(LedColor.NONE)
        temp_form.addRow("Off colour:", self._temp_off_color)

        self._temp_on_cnt = QSpinBox()
        self._temp_on_cnt.setRange(0, 255)
        self._temp_on_cnt.setValue(3)
        self._temp_on_cnt.setSuffix(" × 100 ms")
        temp_form.addRow("On count:", self._temp_on_cnt)

        self._temp_off_cnt = QSpinBox()
        self._temp_off_cnt.setRange(0, 255)
        self._temp_off_cnt.setValue(3)
        self._temp_off_cnt.setSuffix(" × 100 ms")
        temp_form.addRow("Off count:", self._temp_off_cnt)

        self._temp_timer = QSpinBox()
        self._temp_timer.setRange(1, 9999)
        self._temp_timer.setValue(10)
        self._temp_timer.setSuffix(" × 100 ms")
        temp_form.addRow("Duration (timer):", self._temp_timer)

        root.addWidget(self._temp_box)

        # ── send button ───────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        send_btn = QPushButton("Send LED Command")
        send_btn.setMinimumWidth(160)
        send_btn.clicked.connect(self._send)
        btn_row.addWidget(send_btn)
        root.addLayout(btn_row)
        root.addStretch()

        # wiring
        self._temp_enabled.toggled.connect(self._temp_box.setEnabled)

    # ------------------------------------------------------------------
    def _send(self) -> None:
        temp_enabled = self._temp_enabled.isChecked()
        self._manager.send_led(
            reader=self._reader_spin.value(),
            led_number=self._led_spin.value(),
            # permanent
            perm_control_code=self._perm_cc.currentData(),
            perm_on_color=self._perm_on_color.currentData(),
            perm_off_color=self._perm_off_color.currentData(),
            perm_on_count=self._perm_on_cnt.value(),
            perm_off_count=self._perm_off_cnt.value(),
            # temporary
            temp_control_code=(
                self._temp_cc.currentData()
                if temp_enabled
                else LedControlCode.NOP
            ),
            temp_on_color=(
                self._temp_on_color.currentData() if temp_enabled else LedColor.NONE
            ),
            temp_off_color=(
                self._temp_off_color.currentData() if temp_enabled else LedColor.NONE
            ),
            temp_on_count=self._temp_on_cnt.value() if temp_enabled else 0,
            temp_off_count=self._temp_off_cnt.value() if temp_enabled else 0,
            temp_timer_count=self._temp_timer.value() if temp_enabled else 0,
        )

    # ------------------------------------------------------------------
    # persistence helpers called by MainWindow
    # ------------------------------------------------------------------
    def load_defaults(self, cfg: dict) -> None:
        # Load on_color - find combo index matching the color value
        on_color = cfg.get("on_color", LedColor.GREEN)
        if on_color is None:
            on_color = LedColor.GREEN
        for idx in range(self._perm_on_color.count()):
            if self._perm_on_color.itemData(idx) == on_color:
                self._perm_on_color.setCurrentIndex(idx)
                break
        
        # Load off_color - find combo index matching the color value
        off_color = cfg.get("off_color", LedColor.NONE)
        if off_color is None:
            off_color = LedColor.NONE
        for idx in range(self._perm_off_color.count()):
            if self._perm_off_color.itemData(idx) == off_color:
                self._perm_off_color.setCurrentIndex(idx)
                break
        
        self._perm_on_cnt.setValue(cfg.get("on_count", 5))
        self._perm_off_cnt.setValue(cfg.get("off_count", 5))
        self._temp_timer.setValue(cfg.get("timer_count", 10))

    def save_defaults(self) -> dict:
        return {
            "reader": self._reader_spin.value(),
            "led_number": self._led_spin.value(),
            "on_color": self._perm_on_color.currentData(),
            "off_color": self._perm_off_color.currentData(),
            "on_count": self._perm_on_cnt.value(),
            "off_count": self._perm_off_cnt.value(),
            "timer_count": self._temp_timer.value(),
        }
