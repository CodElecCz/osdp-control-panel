"""
Security / key-management widget.

Allows the operator to:
  • Choose between Install mode (no secure channel) and
    Secure Channel mode (SCBK key required).
  • View / edit the 16-byte SCBK as a 32-character hex string.
  • Generate a cryptographically random key.
  • Send CMD_KEYSET to the connected PD (only valid in install-mode or
    an already-established secure channel).

The SCBK is saved to config.json so it survives restarts.
"""
from __future__ import annotations

import os
import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.osdp_manager import OsdpManager

_HEX_RE = re.compile(r"^[0-9A-Fa-f]{1,32}$")


def _text_to_padded_hex(text: str) -> str:
    """Convert text to hex representation and pad with zeros to 32 chars (16 bytes)."""
    # If already valid hex, just pad it
    if _HEX_RE.match(text.upper()):
        return text.upper().ljust(32, '0')
    # Otherwise convert text to hex bytes
    text_bytes = text.encode('utf-8')
    hex_str = text_bytes.hex().upper()
    # Truncate if too long (max 16 bytes = 32 hex chars)
    if len(hex_str) > 32:
        hex_str = hex_str[:32]
    # Pad with zeros if needed
    return hex_str.ljust(32, '0')


class SecurityWidget(QWidget):
    def __init__(
        self,
        manager: OsdpManager,
        config: ConfigManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._config = config
        self._build_ui()
        self._load_from_config()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── session mode ──────────────────────────────────────────────
        mode_box = QGroupBox("Session Security Mode")
        mode_layout = QVBoxLayout(mode_box)

        self._install_radio = QRadioButton(
            "Install mode  (no secure channel – PD accepts KEYSET)"
        )
        self._sc_radio = QRadioButton("Secure Channel  (SCBK key enforced)")
        self._install_radio.setChecked(True)

        note = QLabel(
            "⚠  Mode change takes effect on the <b>next</b> connection."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 11px;")

        mode_layout.addWidget(self._install_radio)
        mode_layout.addWidget(self._sc_radio)
        mode_layout.addWidget(note)
        root.addWidget(mode_box)

        # ── SCBK key ──────────────────────────────────────────────────
        key_box = QGroupBox("Secure Channel Base Key (SCBK)")
        key_form = QFormLayout(key_box)

        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("Text or hex (e.g., ESTELAR20260306)")
        
        mono = QFont("Courier New", 11)
        self._key_edit.setFont(mono)
        key_form.addRow("SCBK:", self._key_edit)

        self._key_status = QLabel("")
        self._key_status.setWordWrap(True)
        key_form.addRow("", self._key_status)

        btn_row_key = QHBoxLayout()
        gen_btn = QPushButton("Generate Random Key")
        gen_btn.clicked.connect(self._generate_key)
        btn_row_key.addWidget(gen_btn)

        save_btn = QPushButton("Save Key to Config")
        save_btn.clicked.connect(self._save_key)
        btn_row_key.addWidget(save_btn)
        btn_row_key.addStretch()
        key_form.addRow("", btn_row_key)

        root.addWidget(key_box)

        # ── KEYSET command ────────────────────────────────────────────
        keyset_box = QGroupBox("Send KEYSET to PD")
        keyset_layout = QVBoxLayout(keyset_box)

        keyset_info = QLabel(
            "Sends CMD_KEYSET with the SCBK above to the connected PD.\n"
            "The CP must be in install-mode or an established secure channel."
        )
        keyset_info.setWordWrap(True)
        keyset_layout.addWidget(keyset_info)

        send_keyset_btn = QPushButton("Send KEYSET Command")
        send_keyset_btn.setMinimumWidth(200)
        send_keyset_btn.clicked.connect(self._send_keyset)
        keyset_layout.addWidget(send_keyset_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        root.addWidget(keyset_box)
        root.addStretch()

        # wiring
        self._install_radio.toggled.connect(self._on_mode_changed)
        self._key_edit.textChanged.connect(self._validate_key_display)

    # ------------------------------------------------------------------
    def _load_from_config(self) -> None:
        self._key_edit.setText(self._config.scbk)
        if self._config.install_mode:
            self._install_radio.setChecked(True)
        else:
            self._sc_radio.setChecked(True)

    # ------------------------------------------------------------------
    def _on_mode_changed(self) -> None:
        install = self._install_radio.isChecked()
        self._config.install_mode = install
        self._config.save()

    # ------------------------------------------------------------------
    def _validate_key_display(self, text: str) -> None:
        if not text:
            self._key_status.setText("")
            self._key_status.setStyleSheet("")
            return
        
        try:
            converted = _text_to_padded_hex(text)
            if _HEX_RE.match(text.upper()):
                # Pure hex input
                if len(text) < 32:
                    self._key_status.setText(f"Hex mode: will pad with {32 - len(text)} zero(s)")
                else:
                    self._key_status.setText("Hex mode: ready")
            else:
                # Text input
                text_bytes = text.encode('utf-8')
                if len(text_bytes) > 16:
                    self._key_status.setText(f"Text mode: truncated to 16 bytes, padded to 32 hex chars")
                else:
                    self._key_status.setText(f"Text mode: {len(text_bytes)} bytes → {len(text_bytes)*2} hex chars, padded with {32 - len(text_bytes)*2} zero(s)")
            self._key_status.setStyleSheet("color: #3498db;")
        except Exception as e:
            self._key_status.setText(f"Error: {str(e)}")
            self._key_status.setStyleSheet("color: #c0392b;")

    # ------------------------------------------------------------------
    def _generate_key(self) -> None:
        key = os.urandom(16).hex().upper()
        self._key_edit.setText(key)
        self._key_status.setText("New random key generated – click 'Save Key to Config' to persist.")
        self._key_status.setStyleSheet("color: #27ae60;")

    # ------------------------------------------------------------------
    def _save_key(self) -> None:
        text = self._key_edit.text().strip()
        if not text:
            self._key_status.setText("Key not saved: input is empty.")
            self._key_status.setStyleSheet("color: #c0392b;")
            return
        
        try:
            # Convert text to hex and pad
            padded_key = _text_to_padded_hex(text)
            self._config.scbk = padded_key
            self._config.save()
            
            # Update the display to show the hex representation
            self._key_edit.setText(padded_key)
            self._key_status.setText(f"Key converted to hex and saved to config.json ✓")
            self._key_status.setStyleSheet("color: #27ae60;")
        except Exception as exc:
            self._key_status.setText(f"Error saving key: {str(exc)}")
            self._key_status.setStyleSheet("color: #c0392b;")

    # ------------------------------------------------------------------
    def _send_keyset(self) -> None:
        text = self._key_edit.text().strip()
        if not text:
            self._key_status.setText("Cannot send: input is empty.")
            self._key_status.setStyleSheet("color: #c0392b;")
            return
        
        try:
            # Convert text to hex and pad
            padded_key = _text_to_padded_hex(text)
            # Update display to show the hex representation
            self._key_edit.setText(padded_key)
            key_bytes = bytes.fromhex(padded_key)
            self._manager.send_keyset(key_data=key_bytes)
        except Exception as e:
            self._key_status.setText(f"Error sending key: {str(e)}")
            self._key_status.setStyleSheet("color: #c0392b;")

    # ------------------------------------------------------------------
    # called by MainWindow when settings are applied
    def refresh_from_config(self) -> None:
        self._load_from_config()
