"""
OSDP CP Simulator – entry point.

Run:
    python main.py

Requirements:
    pip install -r requirements.txt
"""
import logging
import sys

from PyQt6.QtWidgets import QApplication

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("OSDP CP Simulator")
    app.setOrganizationName("OsdpUI")
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
