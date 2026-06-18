"""
Manufacturer-specific command widget (CMD_MFG).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.osdp_manager import OsdpManager


class MfgWidget(QWidget):
    def __init__(self, manager: OsdpManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._build_ui()
        self._wire_signals()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Input section
        input_box = QGroupBox("Manufacturer-Specific Command (CMD_MFG)")
        form = QFormLayout(input_box)

        self._vendor_edit = QLineEdit()
        self._vendor_edit.setPlaceholderText("e.g., 001234 (hex, 3 bytes)")
        self._vendor_edit.setMaxLength(6)
        self._vendor_edit.setToolTip("3-byte vendor code in hexadecimal (6 hex digits)")
        form.addRow("Vendor Code:", self._vendor_edit)

        self._command_edit = QLineEdit()
        self._command_edit.setPlaceholderText("e.g., Hello\\r\\n or STATUS")
        self._command_edit.setToolTip("Command text (supports escape sequences: \\r \\n \\t \\\\)")
        form.addRow("Command Text:", self._command_edit)

        root.addWidget(input_box)

        # Send button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        send_btn = QPushButton("Send MFG Command")
        send_btn.setMinimumWidth(160)
        send_btn.clicked.connect(self._send)
        btn_row.addWidget(send_btn)
        root.addLayout(btn_row)

        # Response section
        response_box = QGroupBox("Response")
        response_layout = QVBoxLayout(response_box)
        
        self._response_text = QPlainTextEdit()
        self._response_text.setReadOnly(True)
        self._response_text.setMaximumHeight(150)
        self._response_text.setPlaceholderText("Manufacturer-specific responses will appear here...")
        response_layout.addWidget(self._response_text)

        clear_btn = QPushButton("Clear Response")
        clear_btn.clicked.connect(self._clear_response)
        response_layout.addWidget(clear_btn)

        root.addWidget(response_box)
        root.addStretch()

    def _wire_signals(self) -> None:
        self._manager.event_received.connect(self._on_event)

    def _parse_command_text(self, text: str) -> bytes:
        """Convert text with escape sequences to bytes."""
        # Use decode('unicode_escape') to handle escape sequences
        # This will convert \\r\\n to actual \r\n characters
        try:
            # Encode to bytes first, then decode escape sequences
            return text.encode('utf-8').decode('unicode_escape').encode('latin-1')
        except (UnicodeDecodeError, UnicodeEncodeError):
            # If that fails, try just encoding as UTF-8
            return text.encode('utf-8')

    def _send(self) -> None:
        vendor_hex = self._vendor_edit.text().strip()
        command_text = self._command_edit.text().strip()

        # Validate vendor code
        if not vendor_hex:
            self._show_error("Vendor code is required")
            return
        
        try:
            vendor_bytes = bytes.fromhex(vendor_hex)
            if len(vendor_bytes) != 3:
                self._show_error("Vendor code must be exactly 3 bytes (6 hex digits)")
                return
        except ValueError:
            self._show_error("Invalid vendor code hex format")
            return

        # Validate and convert command text
        if not command_text:
            self._show_error("Command text is required")
            return
        
        try:
            command_bytes = self._parse_command_text(command_text)
        except Exception as e:
            self._show_error(f"Failed to convert command text: {e}")
            return

        # Send the command
        self._manager.send_mfg(
            vendor_code=vendor_bytes,
            command_data=command_bytes
        )
        
        self._response_text.appendPlainText(
            f"→ Sent: Vendor={vendor_hex.upper()} Text=\"{command_text}\" "
            f"(Hex: {command_bytes.hex().upper()})"
        )

    def _on_event(self, event: dict) -> None:
        """Handle events from the manager - specifically MFGREP events."""
        from core.osdp_manager import EventType
        
        event_type = event.get("event", event.get("type", 0))
        
        if event_type == EventType.MFGREP:
            pd = event.get("pd", "?")
            vendor = event.get("vendor_code", b"")
            data = event.get("data", b"")
            
            vendor_hex = vendor.hex().upper() if isinstance(vendor, bytes) else str(vendor)
            data_hex = data.hex().upper() if isinstance(data, bytes) else str(data)
            
            # Try to decode as text
            data_text = ""
            if isinstance(data, bytes):
                try:
                    data_text = data.decode('utf-8', errors='replace')
                    # Show printable version
                    data_text_display = repr(data_text)[1:-1]  # Remove outer quotes
                except:
                    data_text_display = data_hex
            else:
                data_text_display = data_hex
            
            self._response_text.appendPlainText(
                f"← Response from PD {pd}: Vendor={vendor_hex} "
                f"Text=\"{data_text_display}\" (Hex: {data_hex})"
            )

    def _clear_response(self) -> None:
        self._response_text.clear()

    def _show_error(self, message: str) -> None:
        self._response_text.appendPlainText(f"✗ Error: {message}")

    # persistence helpers
    def load_defaults(self, cfg: dict) -> None:
        vendor = cfg.get("vendor_code", "")
        if vendor:
            self._vendor_edit.setText(vendor)
        
        command = cfg.get("command_text", "")
        if command:
            self._command_edit.setText(command)

    def save_defaults(self) -> dict:
        return {
            "vendor_code": self._vendor_edit.text().strip(),
            "command_text": self._command_edit.text().strip(),
        }
