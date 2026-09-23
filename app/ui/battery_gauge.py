"""Small battery icon for the header, as in the approved mockup.

The state comes from the hub's own status flags (low-voltage warning and
shutdown), exactly what Pybricks Code shows. The hub reports no percentage,
and a Li-ion pack's voltage under load is a poor charge estimate: an earlier
linear 6.8-8.3 V guess called a healthy 7.12 V pack "nearly empty" on the
real robot. So the icon shows ok / low / critical, and the exact voltage from
S lines sits next to it as text.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from app.ui import theme

# level -> (fill fraction, colour, tooltip)
LEVELS = {
    "ok": (1.0, theme.OK, "Hub battery OK"),
    "low": (0.35, theme.WARN, "Hub battery low: charge soon"),
    "critical": (0.12, theme.DANGER, "Hub battery critical: the hub is about to shut down"),
}


class BatteryGauge(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(28, 13)
        self.level: str | None = None
        self.setToolTip("Hub battery: not connected")

    def set_state(self, level: str | None, battery_mv: int | None = None) -> None:
        """`level` from the hub's status flags; None when unknown (no hub, replay)."""
        tip = LEVELS[level][2] if level in LEVELS else "Hub battery: not connected"
        if battery_mv is not None:
            tip += f" ({battery_mv / 1000:.2f} V)"
        self.setToolTip(tip)
        if level != self.level:
            self.level = level
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        fraction, color = (LEVELS[self.level][:2]) if self.level in LEVELS else (0.0, theme.DIM)
        outline = QColor(theme.MUTED if self.level in (None, "ok") else color)
        p.setPen(QPen(outline, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(0.5, 0.5, 24, 12))
        p.fillRect(QRectF(25, 4, 2.5, 5), outline)  # terminal nub
        if fraction:
            p.fillRect(QRectF(2.5, 2.5, 20 * fraction, 8), QColor(color))
        p.end()
