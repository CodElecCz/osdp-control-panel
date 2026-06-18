"""
PD bus scanner panel – left-side tree view.

Shows all discovered PDs with their ID info and capabilities.
A "Scan Bus" button triggers a full 0-126 address sweep.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.osdp_manager import OsdpManager

_ONLINE_COLOR = QColor("#27ae60")
_OFFLINE_COLOR = QColor("#c0392b")
_CAP_COLOR = QColor("#555555")


class PdTreeWidget(QWidget):
    """Left-side panel: scan controls + PD tree."""

    pd_selected = pyqtSignal(int)  # user clicked a PD node

    def __init__(
        self,
        manager: OsdpManager,
        config: ConfigManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._config = config
        self._pd_items: dict[int, QTreeWidgetItem] = {}  # addr → top-level item
        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        box = QGroupBox("Bus Devices")
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(4)

        # ── scan controls ─────────────────────────────────────────────
        ctrl_row = QHBoxLayout()

        self._scan_btn = QPushButton("🔍 Scan Bus")
        self._scan_btn.setToolTip("Scan all 127 OSDP addresses for connected PDs")
        self._scan_btn.clicked.connect(self._start_scan)
        ctrl_row.addWidget(self._scan_btn)

        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_scan)
        ctrl_row.addWidget(self._stop_btn)

        self._clear_btn = QPushButton("✕")
        self._clear_btn.setToolTip("Clear results")
        self._clear_btn.setFixedWidth(30)
        self._clear_btn.clicked.connect(self._clear)
        ctrl_row.addWidget(self._clear_btn)

        box_layout.addLayout(ctrl_row)

        # max PD address spinner
        addr_row = QHBoxLayout()
        addr_row.addWidget(QLabel("Max PD ID:"))
        self._max_addr_spin = QSpinBox()
        self._max_addr_spin.setRange(0, 126)
        self._max_addr_spin.setValue(126)
        self._max_addr_spin.setFixedWidth(55)
        addr_row.addWidget(self._max_addr_spin)
        addr_row.addStretch()
        box_layout.addLayout(addr_row)

        # progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 126)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.hide()
        box_layout.addWidget(self._progress)

        # status label
        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet("font-size: 11px; color: #666;")
        box_layout.addWidget(self._status_lbl)

        # ── tree ──────────────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Address / Info", "Value"])
        self._tree.setColumnWidth(0, 160)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._tree.itemClicked.connect(self._on_item_clicked)
        box_layout.addWidget(self._tree)

        root.addWidget(box)

    # ------------------------------------------------------------------
    def _wire_signals(self) -> None:
        m = self._manager
        m.scan_started.connect(self._on_scan_started)
        m.scan_progress.connect(self._on_scan_progress)
        m.pd_discovered.connect(self._on_pd_discovered)
        m.pd_capabilities.connect(self._on_pd_capabilities)
        m.scan_finished.connect(self._on_scan_finished)
        m.pd_online.connect(self._on_pd_status_change)
        m.pd_offline.connect(lambda addr: self._on_pd_status_change(addr, online=False))

    # ------------------------------------------------------------------
    # scan control
    # ------------------------------------------------------------------

    def _start_scan(self) -> None:
        port = self._config.port
        if not port:
            self._status_lbl.setText("⚠ No port configured")
            self._status_lbl.setStyleSheet("font-size: 11px; color: #c0392b;")
            return
        self._manager.scan_bus(
            port=port,
            baud_rate=self._config.baud_rate,
            max_pd_address=self._max_addr_spin.value(),
        )

    def _stop_scan(self) -> None:
        self._manager.stop_scan()

    def _clear(self) -> None:
        self._tree.clear()
        self._pd_items.clear()
        self._status_lbl.setText("Ready")
        self._status_lbl.setStyleSheet("font-size: 11px; color: #666;")

    # ------------------------------------------------------------------
    # scan signal handlers
    # ------------------------------------------------------------------

    def _on_scan_started(self) -> None:
        self._scan_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._progress.setValue(0)
        self._progress.show()
        self._status_lbl.setText("Scanning…")
        self._status_lbl.setStyleSheet("font-size: 11px; color: #2980b9;")

    def _on_scan_progress(self, address: int, total: int) -> None:
        self._progress.setMaximum(total)
        self._progress.setValue(address)

    def _on_pd_discovered(self, address: int, info: dict) -> None:
        # Check if PD already exists in tree
        if address in self._pd_items:
            # Update existing PD item with new info
            root_item = self._pd_items[address]
            self._update_pd_info(root_item, info)
            return

        # Build root item for new PD
        root_item = QTreeWidgetItem(self._tree)
        root_item.setText(0, f"PD  {address}")
        root_item.setData(0, Qt.ItemDataRole.UserRole, address)

        _set_online_style(root_item, online=True)

        # Vendor / model / firmware sub-items
        vendor_code = info.get("vendor_code", 0)
        if isinstance(vendor_code, int):
            vendor_str = f"0x{vendor_code:06X}"
        elif isinstance(vendor_code, (list, bytes)):
            vendor_str = "-".join(f"{b:02X}" for b in vendor_code)
        else:
            vendor_str = str(vendor_code)

        _add_child(root_item, "Vendor code", vendor_str)
        _add_child(root_item, "Model #", str(info.get("model_number", "?")))
        _add_child(root_item, "Version", str(info.get("version", "?")))
        _add_child(root_item, "Serial #", _fmt_serial(info.get("serial_number", 0)))
        _add_child(root_item, "Firmware", _fmt_firmware(info.get("firmware_version", 0)))

        # Placeholder for capabilities (populated by _on_pd_capabilities)
        cap_placeholder = QTreeWidgetItem(root_item)
        cap_placeholder.setText(0, "Capabilities")
        cap_placeholder.setData(0, Qt.ItemDataRole.UserRole, "caps_node")
        cap_placeholder.setForeground(0, QBrush(QColor("#aaa")))

        root_item.setExpanded(True)
        self._pd_items[address] = root_item
        self._status_lbl.setText(f"Found PD {address}")
    
    def _update_pd_info(self, root_item: QTreeWidgetItem, info: dict) -> None:
        """Update existing PD tree item with new information."""
        # Find and update child items by their label
        for i in range(root_item.childCount()):
            child = root_item.child(i)
            label = child.text(0)
            
            if label == "Vendor code":
                vendor_code = info.get("vendor_code", 0)
                if isinstance(vendor_code, int):
                    vendor_str = f"0x{vendor_code:06X}"
                elif isinstance(vendor_code, (list, bytes)):
                    vendor_str = "-".join(f"{b:02X}" for b in vendor_code)
                else:
                    vendor_str = str(vendor_code)
                child.setText(1, vendor_str)
            elif label == "Model #":
                child.setText(1, str(info.get("model_number", "?")))
            elif label == "Version":
                child.setText(1, str(info.get("version", "?")))
            elif label == "Serial #":
                child.setText(1, _fmt_serial(info.get("serial_number", 0)))
            elif label == "Firmware":
                child.setText(1, _fmt_firmware(info.get("firmware_version", 0)))

    def _on_pd_capabilities(self, address: int, caps: list) -> None:
        root_item = self._pd_items.get(address)
        if root_item is None:
            return

        # Find or replace the caps placeholder
        caps_node: QTreeWidgetItem | None = None
        for i in range(root_item.childCount()):
            child = root_item.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) == "caps_node":
                caps_node = child
                break

        if caps_node is None:
            caps_node = QTreeWidgetItem(root_item)
        caps_node.setText(0, f"Capabilities ({len(caps)})")
        caps_node.setData(0, Qt.ItemDataRole.UserRole, "caps_node")
        caps_node.setForeground(0, QBrush(QColor("#2c3e50")))

        # Remove previous capability children
        while caps_node.childCount():
            caps_node.removeChild(caps_node.child(0))

        if not caps:
            _add_child(caps_node, "  (none reported)", "")
        else:
            for cap in caps:
                name = cap.get("name", f"Function {cap.get('func','?')}")
                compliance = cap.get("compliance_level", 0)
                num_items = cap.get("num_items", 0)
                detail = f"level={compliance}"
                if num_items:
                    detail += f"  items={num_items}"
                _add_child(caps_node, f"  {name}", detail)

        caps_node.setExpanded(True)

    def _on_scan_finished(self, count: int) -> None:
        self._scan_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._progress.hide()
        if count == 0:
            self._status_lbl.setText("No PDs found")
            self._status_lbl.setStyleSheet("font-size: 11px; color: #c0392b;")
        else:
            self._status_lbl.setText(f"Found {count} PD(s)")
            self._status_lbl.setStyleSheet("font-size: 11px; color: #27ae60;")

    # ------------------------------------------------------------------
    # live online/offline updates from main connection
    # ------------------------------------------------------------------

    def _on_pd_status_change(self, address: int, online: bool = True) -> None:
        item = self._pd_items.get(address)
        if item:
            _set_online_style(item, online)

    # ------------------------------------------------------------------
    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        # Walk up to find the PD root node
        node = item
        while node.parent() is not None:
            node = node.parent()
        addr = node.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(addr, int):
            self.pd_selected.emit(addr)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _add_child(parent: QTreeWidgetItem, label: str, value: str) -> QTreeWidgetItem:
    item = QTreeWidgetItem(parent)
    item.setText(0, label)
    item.setText(1, value)
    item.setForeground(0, QBrush(_CAP_COLOR))
    return item


def _set_online_style(item: QTreeWidgetItem, online: bool) -> None:
    color = _ONLINE_COLOR if online else _OFFLINE_COLOR
    status = "● ONLINE" if online else "○ OFFLINE"
    addr = item.data(0, Qt.ItemDataRole.UserRole)
    item.setText(0, f"PD  {addr}")
    item.setText(1, status)
    item.setForeground(1, QBrush(color))
    bold = QFont()
    bold.setBold(True)
    item.setFont(0, bold)


def _fmt_serial(val) -> str:
    if isinstance(val, int):
        return f"0x{val:08X}"
    return str(val)


def _fmt_firmware(val) -> str:
    if isinstance(val, int):
        return f"0x{val:06X}"
    return str(val)
