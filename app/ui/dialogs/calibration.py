"""Black/white reflection calibration.

Runs the calibrate hub program (it holds still and streams reflection in T
lines), samples the median of the last second on black and then on white,
and stores both plus the derived edge in the config.
"""

from __future__ import annotations

import asyncio
import statistics
from collections.abc import Awaitable, Callable

from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout

from app.core.config import SensorCalibration, check_calibration
from app.ui.theme import caption, label, set_prop

SAMPLE_WINDOW_MS = 1000
MIN_SAMPLES = 5  # T runs at 20 Hz: a full second gives ~20


class CalibrationDialog(QDialog):
    def __init__(
        self,
        start: Callable[[], Awaitable[bool]],
        stop: Callable[[], Awaitable[None]],
        samples: Callable[[float], list[float]],
        current: Callable[[], SensorCalibration],
        apply: Callable[[SensorCalibration], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sensor calibration")
        self.setMinimumWidth(440)
        self._start = start
        self._stop = stop
        self._samples = samples
        self._current = current
        self._apply = apply
        self.black: int | None = None
        self.white: int | None = None
        self.result: SensorCalibration | None = None

        self.start_button = QPushButton("Start sensor stream")
        self.start_button.setProperty("role", "run")
        self.status = label("", tone="muted")
        self.status.setWordWrap(True)
        self.black_button = QPushButton("Sample black")
        self.white_button = QPushButton("Sample white")
        for button in (self.black_button, self.white_button):
            button.setProperty("role", "small")
            button.setEnabled(False)
        self.black_value = label("—", mono=True)
        self.white_value = label("—", mono=True)
        self.summary = label("", mono=True)
        self.summary.setWordWrap(True)
        self.save_button = QPushButton("Save to config")
        self.save_button.setProperty("role", "small")
        self.save_button.setEnabled(False)
        close = QPushButton("Close")
        close.setProperty("role", "small")
        close.clicked.connect(self.close)

        grid = QGridLayout()
        grid.addWidget(label("1. Sensor over the black line", tone="muted"), 0, 0)
        grid.addWidget(self.black_button, 0, 1)
        grid.addWidget(self.black_value, 0, 2)
        grid.addWidget(label("2. Sensor over the white floor", tone="muted"), 1, 0)
        grid.addWidget(self.white_button, 1, 1)
        grid.addWidget(self.white_value, 1, 2)
        grid.setColumnStretch(0, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addStretch()
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(caption("Sensor calibration"))
        now = current()
        layout.addWidget(
            label(f"Current: black {now.black}, white {now.white}, edge {now.edge}", tone="dim")
        )
        layout.addWidget(self.start_button)
        layout.addWidget(self.status)
        layout.addLayout(grid)
        layout.addWidget(self.summary)
        layout.addLayout(buttons)

        self.start_button.clicked.connect(lambda: asyncio.ensure_future(self.start()))
        self.black_button.clicked.connect(lambda: self.sample("black"))
        self.white_button.clicked.connect(lambda: self.sample("white"))
        self.save_button.clicked.connect(self.save)

    async def start(self) -> bool:
        self.start_button.setEnabled(False)
        self._say("Starting. The robot holds still; wait for the IMU, then sample.", "muted")
        if not await self._start():
            self._say("The calibration program did not start. See the console.", "warn")
            self.start_button.setEnabled(True)
            return False
        self._say("Streaming. Place the sensor, wait a second, then sample.", "ok")
        self.black_button.setEnabled(True)
        self.white_button.setEnabled(True)
        return True

    def sample(self, which: str) -> int | None:
        values = self._samples(SAMPLE_WINDOW_MS)
        if len(values) < MIN_SAMPLES:
            self._say("No reflection readings yet. Is the IMU still settling?", "warn")
            return None
        value = round(statistics.median(values))
        setattr(self, which, value)
        (self.black_value if which == "black" else self.white_value).setText(str(value))
        self._evaluate()
        return value

    def save(self) -> None:
        if self.result is None:
            return
        self._apply(self.result)
        self._say("Saved into the config. Save the preset to keep it.", "ok")
        self.save_button.setEnabled(False)

    def closeEvent(self, event) -> None:  # noqa: N802
        asyncio.ensure_future(self._stop())
        super().closeEvent(event)

    def _evaluate(self) -> None:
        self.result = None
        self.save_button.setEnabled(False)
        if self.black is None or self.white is None:
            return
        try:
            calibration, warning = check_calibration(self.black, self.white)
        except ValueError as exc:
            self.summary.setText(str(exc))
            set_prop(self.summary, "tone", "danger")
            return
        self.result = calibration
        text = f"edge {calibration.edge} · gap {calibration.white - calibration.black}"
        self.summary.setText(text + (f"\n{warning}" if warning else ""))
        set_prop(self.summary, "tone", "warn" if warning else "ok")
        self.save_button.setEnabled(True)

    def _say(self, text: str, tone: str) -> None:
        self.status.setText(text)
        set_prop(self.status, "tone", tone)
