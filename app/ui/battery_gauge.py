"""Small battery icon for the header, as in the approved mockup.

The hub's 2-cell Li-ion pack reads about 8.3 V full; Pybricks warns and shuts
down in the high 6 V range. The fill is a linear estimate between those, good
enough to see "charge soon" at a glance; the exact voltage sits next to it.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from app.ui import theme

FULL_MV = 8300
EMPTY_MV = 6800
WARN_BELOW = 0.20
DANGER_BELOW = 0.10


def battery_fraction(battery_mv: int) -> float:
    return min(max((battery_mv - EMPTY_MV) / (FULL_MV - EMPTY_MV), 0.0), 1.0)


def battery_tone(fraction: float) -> str:
    if fraction < DANGER_BELOW:
        return "danger"
    if fraction < WARN_BELOW:
        return "warn"
    return "text"


TONE_COLORS = {"text": theme.TEXT, "warn": theme.WARN, "danger": theme.DANGER}


class BatteryGauge(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(28, 13)
        self.fraction: float | None = None
        self.tone = "text"

    def set_voltage(self, battery_mv: int | None) -> None:
        fraction = None if battery_mv is None else battery_fraction(battery_mv)
        if fraction == self.fraction:
            return
        self.fraction = fraction
        self.tone = "text" if fraction is None else battery_tone(fraction)
        self.setToolTip(
            "Hub battery: no reading yet"
            if fraction is None
            else f"Hub battery ≈ {fraction:.0%} ({battery_mv / 1000:.2f} V)"
        )
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        body = QRectF(0.5, 0.5, 24, 12)
        outline = QColor(theme.MUTED if self.tone == "text" else TONE_COLORS[self.tone])
        p.setPen(QPen(outline, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(body)
        p.fillRect(QRectF(25, 4, 2.5, 5), outline)  # terminal nub
        if self.fraction:
            p.fillRect(QRectF(2.5, 2.5, 20 * self.fraction, 8), QColor(TONE_COLORS[self.tone]))
        p.end()
