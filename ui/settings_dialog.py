"""
Settings dialog – configure RS-485 port, baud rate, PD address and
security mode.  Changes are written to ConfigManager; the caller is
responsible for calling save() and reconnecting.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from core.config_manager import ConfigManager

_BAUD_RATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]


def _list_serial_ports() -> list[str]:
    """Return available serial port names (best-effort, no crash)."""
    try:
        import serial.tools.list_ports  # type: ignore

        return [p.device for p in serial.tools.list_ports.comports()]
    except Exception:
        return []


class SettingsDialog(QDialog):
    def __init__(self, config: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── RS-485 / serial ───────────────────────────────────────────
        serial_box = QGroupBox("RS-485 / Serial Port")
        serial_form = QFormLayout(serial_box)

        port_row_layout = QFormLayout()
        self._port_combo = QComboBox()
        self._port_combo.setEditable(True)
        self._port_combo.setMinimumWidth(140)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(70)
        refresh_btn.clicked.connect(self._refresh_ports)

        from PyQt6.QtWidgets import QHBoxLayout

        port_row = QHBoxLayout()
        port_row.addWidget(self._port_combo, stretch=1)
        port_row.addWidget(refresh_btn)

        serial_form.addRow("Port:", port_row)

        self._baud_combo = QComboBox()
        for br in _BAUD_RATES:
            self._baud_combo.addItem(str(br), br)
        serial_form.addRow("Baud rate:", self._baud_combo)

        root.addWidget(serial_box)

        # ── OSDP ──────────────────────────────────────────────────────
        osdp_box = QGroupBox("OSDP")
        osdp_form = QFormLayout(osdp_box)

        self._addr_spin = QSpinBox()
        self._addr_spin.setRange(0, 126)
        osdp_form.addRow("PD Address:", self._addr_spin)

        root.addWidget(osdp_box)

        # ── info ──────────────────────────────────────────────────────
        info = QLabel(
            "Security settings (SCBK key, install/secure mode) are\n"
            "managed on the <b>Security</b> tab."
        )
        info.setAlignment(Qt.AlignmentFlag.AlignLeft)
        info.setWordWrap(True)
        root.addWidget(info)

        # ── buttons ───────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._refresh_ports()

    # ------------------------------------------------------------------
    def _refresh_ports(self) -> None:
        current = self._port_combo.currentText()
        self._port_combo.clear()
        ports = _list_serial_ports()
        for p in ports:
            self._port_combo.addItem(p)
        if current:
            idx = self._port_combo.findText(current)
            if idx >= 0:
                self._port_combo.setCurrentIndex(idx)
            else:
                self._port_combo.setEditText(current)

    # ------------------------------------------------------------------
    def _load(self) -> None:
        port = self._config.port
        if port:
            idx = self._port_combo.findText(port)
            if idx >= 0:
                self._port_combo.setCurrentIndex(idx)
            else:
                self._port_combo.setEditText(port)

        baud_idx = self._baud_combo.findData(self._config.baud_rate)
        if baud_idx >= 0:
            self._baud_combo.setCurrentIndex(baud_idx)

        self._addr_spin.setValue(self._config.pd_address)

    # ------------------------------------------------------------------
    def _apply(self) -> None:
        self._config.port = self._port_combo.currentText().strip()
        self._config.baud_rate = self._baud_combo.currentData()
        self._config.pd_address = self._addr_spin.value()
        self._config.save()
        self.accept()
