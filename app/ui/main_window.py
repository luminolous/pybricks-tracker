"""Main application window.

Placeholder only. The three-column layout and header strip from ui-spec.md are
built once the design reference is agreed.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMainWindow

APP_NAME = "Pybricks Tracker"
MIN_WIDTH_PX = 1280
MIN_HEIGHT_PX = 800


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(MIN_WIDTH_PX, MIN_HEIGHT_PX)
        self._loop_label = QLabel("loop: starting")
        self.statusBar().addPermanentWidget(self._loop_label)

    def set_loop_tick(self, tick: int) -> None:
        """Show the asyncio ticker count, proving the qasync loop is alive."""
        self._loop_label.setText(f"loop: tick {tick}")
