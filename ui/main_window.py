"""
Main application window.

Layout
------
Left: PD tree panel (scan bus, capability view)
Right: command tabs (LED, Buzzer, Security, Log)
"""
from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.osdp_manager import OsdpManager
from ui.buzz_widget import BuzzWidget
from ui.led_widget import LedWidget
from ui.mfg_widget import MfgWidget
from ui.pd_tree_widget import PdTreeWidget
from ui.security_widget import SecurityWidget
from ui.settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._config = ConfigManager()
        self._manager = OsdpManager(self)

        self.setWindowTitle("OSDP CP Simulator")
        self.setMinimumSize(900, 580)

        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._wire_signals()

        self._led_widget.load_defaults(self._config.get_section("led"))
        self._buzz_widget.load_defaults(self._config.get_section("buzz"))
        self._mfg_widget.load_defaults(self._config.get_section("mfg"))

        self._update_status_bar()

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        settings_action = QAction("&Settings…", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        settings_act = QAction("⚙ Settings", self)
        settings_act.setToolTip("Open settings dialog (Ctrl+,)")
        settings_act.triggered.connect(self._open_settings)
        tb.addAction(settings_act)

        tb.addSeparator()

        self._connect_act = QAction("▶ Connect", self)
        self._connect_act.setToolTip("Connect to PD")
        self._connect_act.triggered.connect(self._connect)
        tb.addAction(self._connect_act)

        self._disconnect_act = QAction("■ Disconnect", self)
        self._disconnect_act.setToolTip("Disconnect from PD")
        self._disconnect_act.setEnabled(False)
        self._disconnect_act.triggered.connect(self._disconnect)
        tb.addAction(self._disconnect_act)

        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        tb.addWidget(spacer)

        self._pd_indicator = QLabel("● OFFLINE")
        self._pd_indicator.setStyleSheet(
            "color: #c0392b; font-weight: bold; margin-right: 8px;"
        )
        tb.addWidget(self._pd_indicator)

    def _build_central(self) -> None:
        # Main vertical splitter (top: controls, bottom: log)
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.setChildrenCollapsible(False)
        self.setCentralWidget(main_splitter)

        # ── top section: horizontal splitter ─────────────────────────
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.setChildrenCollapsible(False)
        main_splitter.addWidget(top_splitter)

        # ── left: PD tree / bus scanner ───────────────────────────────
        self._pd_tree = PdTreeWidget(self._manager, self._config)
        self._pd_tree.setMinimumWidth(220)
        self._pd_tree.setMaximumWidth(380)
        top_splitter.addWidget(self._pd_tree)

        # ── right: command tabs ───────────────────────────────────────
        tabs = QTabWidget()
        top_splitter.addWidget(tabs)

        self._led_widget = LedWidget(self._manager)
        tabs.addTab(self._led_widget, "💡 LED")

        self._buzz_widget = BuzzWidget(self._manager)
        tabs.addTab(self._buzz_widget, "🔔 Buzzer")

        self._mfg_widget = MfgWidget(self._manager)
        tabs.addTab(self._mfg_widget, "🏭 MFG")

        self._security_widget = SecurityWidget(self._manager, self._config)
        tabs.addTab(self._security_widget, "🔐 Security")

        top_splitter.setSizes([240, 660])

        # ── bottom section: log window ────────────────────────────────
        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(4, 2, 4, 4)
        log_layout.setSpacing(2)
        
        log_label = QLabel("📋 Log")
        log_label.setStyleSheet("font-weight: bold; padding: 2px;")
        log_layout.addWidget(log_label)
        
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont("Courier New", 9))
        self._log_view.setMaximumHeight(200)
        self._log_view.setMinimumHeight(80)
        log_layout.addWidget(self._log_view)
        
        main_splitter.addWidget(log_container)
        
        # Set initial sizes (top area larger, bottom area for logs)
        main_splitter.setSizes([400, 150])

    def _build_statusbar(self) -> None:
        self._status_label = QLabel()
        self.statusBar().addWidget(self._status_label)

    # ------------------------------------------------------------------
    # signals
    # ------------------------------------------------------------------

    def _wire_signals(self) -> None:
        m = self._manager
        m.log_message.connect(self._append_log)
        m.error_occurred.connect(self._on_error)
        m.pd_online.connect(self._on_pd_online)
        m.pd_offline.connect(self._on_pd_offline)
        m.connected.connect(self._on_connected)
        m.disconnected.connect(self._on_disconnected)

    # ------------------------------------------------------------------
    # connection
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        port = self._config.port
        if not port:
            QMessageBox.warning(
                self,
                "No port configured",
                "Please open Settings and select an RS-485 serial port.",
            )
            self._open_settings()
            return

        self._manager.connect(
            port=port,
            baud_rate=self._config.baud_rate,
            pd_address=self._config.pd_address,
            scbk=self._config.scbk_bytes() if not self._config.install_mode else None,
            install_mode=self._config.install_mode,
        )

    def _disconnect(self) -> None:
        self._manager.disconnect()

    # ------------------------------------------------------------------
    # slots
    # ------------------------------------------------------------------

    def _on_connected(self) -> None:
        self._connect_act.setEnabled(False)
        self._disconnect_act.setEnabled(True)
        self._update_status_bar()

    def _on_disconnected(self) -> None:
        self._connect_act.setEnabled(True)
        self._disconnect_act.setEnabled(False)
        self._pd_indicator.setText("● OFFLINE")
        self._pd_indicator.setStyleSheet(
            "color: #c0392b; font-weight: bold; margin-right: 8px;"
        )
        self._update_status_bar()

    def _on_pd_online(self, address: int) -> None:
        self._pd_indicator.setText(f"● PD {address} ONLINE")
        self._pd_indicator.setStyleSheet(
            "color: #27ae60; font-weight: bold; margin-right: 8px;"
        )

    def _on_pd_offline(self, address: int) -> None:
        self._pd_indicator.setText(f"● PD {address} OFFLINE")
        self._pd_indicator.setStyleSheet(
            "color: #c0392b; font-weight: bold; margin-right: 8px;"
        )

    def _on_error(self, msg: str) -> None:
        self._append_log(f"[ERROR] {msg}")
        self.statusBar().showMessage(f"Error: {msg}", 5000)

    def _append_log(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log_view.appendPlainText(f"[{ts}] {text}")
        sb = self._log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------
    # settings
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._config, parent=self)
        if dlg.exec():
            self._update_status_bar()
            self._security_widget.refresh_from_config()

    def _update_status_bar(self) -> None:
        port = self._config.port or "<no port>"
        baud = self._config.baud_rate
        addr = self._config.pd_address
        mode = "Install" if self._config.install_mode else "Secure Channel"
        state = "Connected" if self._manager.is_connected else "Disconnected"
        self._status_label.setText(
            f"{port} @ {baud} baud | PD {addr} | {mode} | {state}"
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "OSDP CP Simulator",
            "<b>OSDP Control-Panel Simulator</b><br><br>"
            "RS-485 CP simulation using <tt>pyosdp</tt>.<br>"
            "Supports LED (permanent / temporary), Buzzer, KEYSET commands "
            "and bus scanning with capability discovery.<br><br>"
            "Config stored in <tt>config.json</tt> next to the application.",
        )

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        self._config.update_section("led", self._led_widget.save_defaults())
        self._config.update_section("buzz", self._buzz_widget.save_defaults())
        self._config.update_section("mfg", self._mfg_widget.save_defaults())
        self._config.save()
        if self._manager.is_connected:
            self._manager.disconnect()
        event.accept()
