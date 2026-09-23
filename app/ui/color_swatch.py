"""Live colour swatch pinned to the map's top-right corner.

Shows the RGB of the latest HSV reading (D lines, 4 Hz) with the
classification and raw reflection underneath: a pale swatch alone is hard to
read at a glance, so the label stays (ui-spec).
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core.config import SensorCalibration
from app.core.protocol import Detail
from app.ui import theme
from app.ui.theme import label

SWATCH_WIDTH_PX = 132


def classify(reflection: int, calibration: SensorCalibration) -> str:
    """Same bands as line_follower.py.j2 (and the original script's klasifikasi):
    black below the midpoint of black and edge, white above that of white and edge."""
    edge = calibration.edge
    if reflection < (calibration.black + edge) // 2:
        return "BLACK"
    if reflection > (calibration.white + edge) // 2:
        return "WHITE"
    return "EDGE"


def hsv_color(hue: int, saturation: int, value: int) -> QColor:
    """Pybricks HSV (h 0-359, s and v 0-100) as a Qt colour."""
    return QColor.fromHsv(hue % 360, round(saturation * 2.55), round(value * 2.55))


class ColorSwatch(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("swatch")
        self.setFixedWidth(SWATCH_WIDTH_PX)
        self.setStyleSheet(
            f"QFrame#swatch {{ background: {theme.SURFACE};"
            f" border: 1px solid {theme.LINE_STRONG}; }}"
            f" QFrame#swatchChip {{ border: 0; border-bottom: 1px solid {theme.LINE_STRONG}; }}"
        )
        self.title = label("Line sensor", tone="muted")
        self.chip = QFrame()
        self.chip.setObjectName("swatchChip")
        self.chip.setFixedHeight(34)
        self.cls = QLabel("—")
        self.cls.setStyleSheet("font-weight: 600; letter-spacing: 1px;")
        self.refl = label("—", mono=True)
        self.refl.setStyleSheet("font-size: 17px;")
        self.hsv = label("H —  S —  V —", tone="muted", mono=True)
        self.hsv.setStyleSheet("font-size: 10px;")

        row = QHBoxLayout()
        row.addWidget(self.cls)
        row.addStretch()
        row.addWidget(self.refl)
        body = QVBoxLayout()
        body.setContentsMargins(9, 6, 9, 8)
        body.setSpacing(3)
        body.addLayout(row)
        body.addWidget(self.hsv)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        head = QVBoxLayout()
        head.setContentsMargins(9, 5, 9, 5)
        head.addWidget(self.title)
        layout.addLayout(head)
        layout.addWidget(self.chip)
        layout.addLayout(body)
        self.adjustSize()

    def show_reading(
        self, reflection: int | None, detail: Detail | None, calibration: SensorCalibration
    ) -> None:
        if reflection is not None:
            self.cls.setText(classify(reflection, calibration))
            self.refl.setText(str(reflection))
        if detail is not None:
            color = hsv_color(detail.hue, detail.saturation, detail.value)
            self.chip.setStyleSheet(f"background: {color.name()};")
            self.hsv.setText(f"H {detail.hue}  S {detail.saturation}  V {detail.value}")
