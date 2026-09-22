"""Map: heading tape, trail, robot marker, origin. Units are mm, labelled in cm.

Frame (CLAUDE.md): x forward, y left, heading CCW from x, origin at run
start. With y up on screen this is a normal plot: a left turn curves up.
Redraws come from the window's refresh timer, never per incoming line.
"""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.core.config import SensorCalibration
from app.core.state import RobotState
from app.ui import theme
from app.ui.color_swatch import ColorSwatch

GRID_MINOR_MM = 100  # 10 cm grid (ui-spec)
GRID_MAJOR_MM = 500
DEFAULT_HALF_SPAN_MM = 400
FIT_PADDING = 0.15
# Robot marker in world millimetres, so it scales with zoom like the robot does.
MARKER_NOSE_MM = 70
MARKER_TAIL_MM = -45
MARKER_HALF_WIDTH_MM = 45
TAPE_PX_PER_DEG = 3.2
TAPE_LABEL_CLEARANCE_PX = 40
SWATCH_MARGIN_PX = 12
WAITING_TEXT = "heading appears once the IMU is ready"


def _mono(size_px: int) -> QFont:
    font = QFont(theme.load_fonts().mono)
    font.setPixelSize(size_px)
    return font


class HeadingTape(QWidget):
    """HUD-style heading strip. 0 deg = the run's start direction, CCW positive."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("tape")
        self.setFixedHeight(30)
        self.heading_deg: float | None = None
        self._font = _mono(10)

    def set_heading(self, heading_deg: float | None) -> None:
        if heading_deg != self.heading_deg:
            self.heading_deg = heading_deg
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.SURFACE))
        p.setPen(QPen(QColor(theme.LINE), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.setFont(self._font)
        mid = self.width() / 2
        h = self.height()
        if self.heading_deg is None:
            p.setPen(QColor(theme.DIM))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, WAITING_TEXT)
            p.end()
            return
        heading = self.heading_deg
        span = int(mid / TAPE_PX_PER_DEG) + 5
        first = int(math.floor((heading - span) / 5) * 5)
        for d in range(first, int(heading + span) + 1, 5):
            x = mid + (d - heading) * TAPE_PX_PER_DEG
            n = d % 360
            major = n % 30 == 0
            tick = 10 if major else 6 if n % 10 == 0 else 3
            p.setPen(QColor(theme.MUTED if major else theme.DIM))
            p.drawLine(QPointF(x, h), QPointF(x, h - tick))
            if major and abs(x - mid) > TAPE_LABEL_CLEARANCE_PX:  # keep clear of the value box
                p.drawText(QRectF(x - 20, 2, 40, 14), Qt.AlignmentFlag.AlignCenter, f"{n:03d}")
        box = QRectF(mid - 22, 2, 44, 16)
        p.fillRect(box, QColor(theme.SURFACE))
        p.setPen(QColor(theme.ACCENT))
        p.drawRect(box)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, f"{round(heading) % 360:03d}")
        p.setBrush(QColor(theme.ACCENT))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([QPointF(mid - 4, h), QPointF(mid, h - 7), QPointF(mid + 4, h)]))
        p.end()


class CmAxis(pg.AxisItem):
    """Axis in millimetres, labelled in centimetres."""

    def tickStrings(self, values, scale, spacing):  # noqa: N802
        return [f"{v / 10:g}" for v in values]


def marker_polygon(x_mm: float, y_mm: float, heading_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Closed triangle outline pointing along `heading_deg` (CCW from +x)."""
    h = math.radians(heading_deg)
    c, s = math.cos(h), math.sin(h)
    local = [
        (MARKER_NOSE_MM, 0),
        (MARKER_TAIL_MM, MARKER_HALF_WIDTH_MM),
        (MARKER_TAIL_MM, -MARKER_HALF_WIDTH_MM),
        (MARKER_NOSE_MM, 0),
    ]
    xs = np.array([x_mm + lx * c - ly * s for lx, ly in local])
    ys = np.array([y_mm + lx * s + ly * c for lx, ly in local])
    return xs, ys


class MapView(QWidget):
    """Emits `follow_changed` when a manual pan or zoom turns following off."""

    follow_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.follow = True
        self.sensor_offset_mm = 40.0
        self.calibration = SensorCalibration()
        self._drawn_version = -1

        self.tape = HeadingTape()
        axes = {"left": CmAxis("left"), "bottom": CmAxis("bottom")}
        self.plot = pg.PlotWidget(axisItems=axes, background=theme.SUNKEN)
        self.plot.setAspectLocked(True)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        item = self.plot.getPlotItem()
        for name in ("left", "bottom"):
            axis = item.getAxis(name)
            axis.setTickSpacing(GRID_MAJOR_MM, GRID_MINOR_MM)
            axis.setPen(pg.mkPen(theme.LINE_STRONG))
            axis.setTextPen(pg.mkPen(theme.DIM))
            axis.setStyle(tickFont=_mono(10), tickTextOffset=4)
        item.getAxis("bottom").setLabel("x cm", color=theme.DIM)
        item.getAxis("left").setLabel("y cm", color=theme.DIM)
        item.showGrid(x=True, y=True, alpha=0.18)

        self.origin = pg.ScatterPlotItem(
            [0], [0], symbol="+", size=16, pen=pg.mkPen(theme.MUTED, width=1), brush=None
        )
        self.trail = pg.PlotDataItem(pen=pg.mkPen(theme.TRAIL, width=2))
        self.robot = pg.PlotDataItem(pen=pg.mkPen(theme.ACCENT, width=1.6))
        self.sensor = pg.ScatterPlotItem(size=5, pen=None, brush=pg.mkBrush(theme.ACCENT))
        for graphic in (self.origin, self.trail, self.robot, self.sensor):
            self.plot.addItem(graphic)
        self._set_default_range()
        self.plot.getViewBox().sigRangeChangedManually.connect(self._manual_range)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tape)
        layout.addWidget(self.plot, 1)

        # Overlay on the plot, pinned top-right; hidden until the sensor reports.
        self.swatch = ColorSwatch(self.plot)
        self.swatch.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_swatch()

    def _place_swatch(self) -> None:
        self.swatch.adjustSize()
        self.swatch.move(
            self.plot.width() - self.swatch.width() - SWATCH_MARGIN_PX, SWATCH_MARGIN_PX
        )

    def refresh(self, state: RobotState) -> None:
        """Redraw from `state` if it changed since the last call."""
        if state.version == self._drawn_version:
            return
        self._drawn_version = state.version
        if state.reflection is not None or state.detail is not None:
            self.swatch.show_reading(state.reflection, state.detail, self.calibration)
            if self.swatch.isHidden():
                self._place_swatch()
                self.swatch.show()
        if state.trail:
            xs = np.fromiter((p.x_mm for p in state.trail), float, len(state.trail))
            ys = np.fromiter((p.y_mm for p in state.trail), float, len(state.trail))
            self.trail.setData(xs, ys)
        else:
            self.trail.setData([], [])
        pose = state.pose if state.imu_ready else None
        if pose is None:
            self.robot.setData([], [])
            self.sensor.setData([], [])
            self.tape.set_heading(None)
            return
        self.robot.setData(*marker_polygon(pose.x_mm, pose.y_mm, pose.heading_deg))
        h = math.radians(pose.heading_deg)
        self.sensor.setData(
            [pose.x_mm + self.sensor_offset_mm * math.cos(h)],
            [pose.y_mm + self.sensor_offset_mm * math.sin(h)],
        )
        self.tape.set_heading(pose.heading_deg)
        if self.follow:
            self._center_on(pose.x_mm, pose.y_mm)

    def fit(self, state: RobotState) -> None:
        points = [(p.x_mm, p.y_mm) for p in state.trail] + [(0.0, 0.0)]
        xs, ys = zip(*points, strict=True)
        half = max(max(xs) - min(xs), max(ys) - min(ys), 2 * DEFAULT_HALF_SPAN_MM) / 2
        half *= 1 + FIT_PADDING
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        self._set_follow(False)
        self.plot.setRange(xRange=(cx - half, cx + half), yRange=(cy - half, cy + half), padding=0)

    def set_follow(self, on: bool) -> None:
        self._set_follow(on)

    def clear(self) -> None:
        self._drawn_version = -1
        self.swatch.hide()
        self._set_default_range()

    def _set_default_range(self) -> None:
        span = DEFAULT_HALF_SPAN_MM
        self.plot.setRange(xRange=(-span, span), yRange=(-span, span), padding=0)

    def _center_on(self, x_mm: float, y_mm: float) -> None:
        (x0, x1), (y0, y1) = self.plot.getViewBox().viewRange()
        hx, hy = (x1 - x0) / 2, (y1 - y0) / 2
        self.plot.setRange(xRange=(x_mm - hx, x_mm + hx), yRange=(y_mm - hy, y_mm + hy), padding=0)

    def _manual_range(self, *_args) -> None:
        self._set_follow(False)

    def _set_follow(self, on: bool) -> None:
        if on != self.follow:
            self.follow = on
            self.follow_changed.emit(on)
