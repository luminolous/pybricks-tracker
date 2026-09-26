"""Small battery icon for the header, as in the approved mockup.

Colour: the hub's own status flags (low-voltage warning and shutdown), as
Pybricks Code shows them, plus red once the voltage is nearly at the cut-off.
Fill: the voltage between Pybricks' Li-ion thresholds for LEGO packs, 6.0 V
(the hub switches itself off) to 8.19 V (full). A flag alone was not enough:
the warning comes at 6.8 V and nothing changed until the hub died at 6.0 V
(2026-09-26). The exact voltage from S lines sits next to it as text.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from app.ui import theme

EMPTY_MV = 6000  # Pybricks LIION_CRITICAL_MV: the hub shuts down here
FULL_MV = 8190  # Pybricks LIION_FULL_MV
NEARLY_EMPTY_MV = 6300  # red and a console warning below this

# level -> (fill fraction without a voltage, colour, tooltip)
LEVELS = {
    "ok": (1.0, theme.OK, "Hub battery OK"),
    "low": (0.35, theme.WARN, "Hub battery low: charge soon"),
    "critical": (0.05, theme.DANGER, "Hub battery critical: the hub is about to shut down"),
}
NEARLY_EMPTY_TIP = "Hub battery nearly empty: charge now"


def charge_fraction(battery_mv: int) -> float:
    """0 at the 6.0 V cut-off, 1 when full. Voltage sags under load, so it is rough."""
    return max(0.0, min(1.0, (battery_mv - EMPTY_MV) / (FULL_MV - EMPTY_MV)))


def nearly_empty(battery_mv: int | None) -> bool:
    return battery_mv is not None and battery_mv < NEARLY_EMPTY_MV


class BatteryGauge(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(28, 13)
        self.level: str | None = None
        self.battery_mv: int | None = None
        self.setToolTip("Hub battery: not connected")

    @property
    def fraction(self) -> float:
        if self.battery_mv is not None:
            return charge_fraction(self.battery_mv)
        return LEVELS[self.level][0] if self.level in LEVELS else 0.0

    @property
    def color(self) -> str:
        if self.level is None:
            return theme.DIM  # no hub, or a replay: the voltage only
        if nearly_empty(self.battery_mv):
            return theme.DANGER
        return LEVELS[self.level][1]

    def set_state(self, level: str | None, battery_mv: int | None = None) -> None:
        """`level` from the hub's status flags; None when unknown (no hub, replay)."""
        if level is None and battery_mv is None:
            tip = "Hub battery: not connected"
        elif level is not None and nearly_empty(battery_mv):
            tip = NEARLY_EMPTY_TIP
        elif level in LEVELS:
            tip = LEVELS[level][2]
        else:
            tip = "Hub battery"
        if battery_mv is not None:
            margin_v = (battery_mv - EMPTY_MV) / 1000
            tip += (
                f"\n{battery_mv / 1000:.2f} V, about {charge_fraction(battery_mv):.0%}"
                f"\n{margin_v:.2f} V above the 6.0 V shutdown"
            )
        self.setToolTip(tip)
        if (level, battery_mv) != (self.level, self.battery_mv):
            self.level = level
            self.battery_mv = battery_mv
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        color = self.color
        outline = QColor(theme.MUTED if color in (theme.DIM, theme.OK) else color)
        p.setPen(QPen(outline, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(0.5, 0.5, 24, 12))
        p.fillRect(QRectF(25, 4, 2.5, 5), outline)  # terminal nub
        fraction = self.fraction
        if fraction:
            p.fillRect(QRectF(2.5, 2.5, max(1.0, 20 * fraction), 8), QColor(color))
        p.end()
