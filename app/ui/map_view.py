"""Map: heading tape, trail (four colouring modes), robot marker, origin, event
markers, and previous runs overlaid with their metrics. Units are mm, labelled
in cm.

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
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from app.core.analysis import RunMetrics, run_metrics
from app.core.config import SensorCalibration
from app.core.overlay import Overlay
from app.core.state import EventRecord, RobotState
from app.ui import theme
from app.ui.color_swatch import ColorSwatch
from app.ui.event_list import event_color
from app.ui.theme import label
from app.ui.trail_colors import segment_masks, trail_bins

GRID_MINOR_MM = 100  # 10 cm grid (ui-spec)
GRID_MAJOR_MM = 500
DEFAULT_HALF_SPAN_MM = 400
FIT_PADDING = 0.15
# Robot marker in world millimetres, so it scales with zoom like the robot does.
MARKER_NOSE_MM = 40
MARKER_TAIL_MM = -25
MARKER_HALF_WIDTH_MM = 25
TAPE_PX_PER_DEG = 3.2
TAPE_LABEL_CLEARANCE_PX = 40
SWATCH_MARGIN_PX = 12
LEGEND_MARGIN_PX = 12
EVENT_SYMBOLS = {
    "LOST": "t",
    "GIVEUP": "t",
    "FOUND": "o",
    "OBS": "x",
    "STALL": "d",
    "BUMP": "d",
    "WDOG": "s",
    "LAP": "star",
    "TURN": "p",
    "FINISH": "h",
}


def event_position(event: EventRecord, sensor_offset_mm: float) -> tuple[float, float]:
    """Where to draw an event. OBS sits at the obstacle: projected forward from the
    pose by the measured distance plus the sensor offset (the ultrasonic sensor is
    assumed to sit at the front, like the colour sensor)."""
    if event.kind == "OBS" and event.detail:
        try:
            ahead = float(event.detail) + sensor_offset_mm
        except ValueError:
            return event.x_mm, event.y_mm
        h = math.radians(event.heading_deg)
        return event.x_mm + ahead * math.cos(h), event.y_mm + ahead * math.sin(h)
    return event.x_mm, event.y_mm


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


SCALE_BAR_STEPS_MM = (10, 20, 50, 100, 200, 500, 1000, 2000, 5000)
SCALE_BAR_TARGET_PX = 110


def scale_bar_length(mm_per_px: float) -> int:
    """The round length whose bar comes closest to SCALE_BAR_TARGET_PX."""
    return min(SCALE_BAR_STEPS_MM, key=lambda mm: abs(mm / mm_per_px - SCALE_BAR_TARGET_PX))


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


class MapLegend(QFrame):
    """Bottom-left panel: the trail mode's key and, with overlays, run metrics."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("mapLegend")
        self.setStyleSheet(
            f"QFrame#mapLegend {{ background: {theme.SURFACE};"
            f" border: 1px solid {theme.LINE_STRONG}; }}"
        )
        self.mode_line = label("", tone="muted")
        self.mode_line.setStyleSheet("font-size: 11px;")
        self.table = QGridLayout()
        self.table.setHorizontalSpacing(14)
        self.table.setVerticalSpacing(3)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 7)
        layout.setSpacing(6)
        layout.addWidget(self.mode_line)
        layout.addLayout(self.table)
        self._structure: tuple = ()
        self._cells: list[list[QLabel]] = []

    def set_content(self, mode_text: str | None, rows: list[tuple[str, str, RunMetrics]]) -> None:
        self.mode_line.setText(mode_text or "")
        self.mode_line.setVisible(bool(mode_text))
        # Rebuild only when the set of runs changes; live metrics just update text.
        structure = tuple((color, text) for color, text, _ in rows)
        if structure != self._structure:
            self._structure = structure
            self._build(rows)
        for cells, (_, _, m) in zip(self._cells, rows, strict=True):
            for cell, value in zip(cells, _metric_texts(m), strict=True):
                if cell.text() != value:
                    cell.setText(value)
        self.setVisible(bool(mode_text) or bool(rows))
        self.adjustSize()

    def _build(self, rows: list[tuple[str, str, RunMetrics]]) -> None:
        while self.table.count():
            item = self.table.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
        self._cells = []
        if not rows:
            return
        for col, head in enumerate(("Run", "Time", "Path", "RMS err", "Lost")):
            h = label(head, tone="dim")
            h.setStyleSheet("font-size: 10px;")
            self.table.addWidget(h, 0, col)
        for r, (color, text, _) in enumerate(rows, start=1):
            name = QLabel(f"<span style='color:{color}'>━</span>&nbsp; {text}")
            name.setStyleSheet("font-size: 11px;")
            self.table.addWidget(name, r, 0)
            cells = []
            for col in range(1, 5):
                cell = label("", mono=True)
                cell.setStyleSheet("font-size: 11px;")
                self.table.addWidget(cell, r, col)
                cells.append(cell)
            self._cells.append(cells)


def _metric_texts(m: RunMetrics) -> tuple[str, str, str, str]:
    return (
        f"{int(m.duration_s // 60):02d}:{int(m.duration_s % 60):02d}",
        f"{m.path_mm / 1000:.2f} m",
        f"{m.rms_error:.1f}",
        str(m.lost_count),
    )


class MapView(QWidget):
    """Emits `follow_changed` when a manual pan or zoom turns following off."""

    follow_changed = Signal(bool)
    event_clicked = Signal(object)  # EventRecord

    def __init__(self) -> None:
        super().__init__()
        self.follow = True
        self.sensor_offset_mm = 40.0
        self.calibration = SensorCalibration()
        self.trail_mode = "plain"
        self.current_label = "now"
        self.overlays: list[Overlay] = []
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
        self.events = pg.ScatterPlotItem(size=11, hoverable=True, tip=None)
        self.events.sigClicked.connect(self._event_clicked)
        self.selection = pg.ScatterPlotItem(
            size=22, symbol="o", pen=pg.mkPen(theme.TEXT, width=1.4), brush=None
        )
        for graphic in (
            self.origin,
            self.trail,
            self.events,
            self.selection,
            self.robot,
            self.sensor,
        ):
            self.plot.addItem(graphic)
        self._shown_events: list[EventRecord] = []
        self.selected: EventRecord | None = None
        self.trail_bins: list[pg.PlotDataItem] = []  # coloured modes, one curve per bin
        self.overlay_curves: list[pg.PlotDataItem] = []
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
        self.legend = MapLegend(self.plot)
        self.legend.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_swatch()
        self._place_legend()

    def _place_legend(self) -> None:
        self.legend.adjustSize()
        bottom_axis = self.plot.getPlotItem().getAxis("bottom").height()
        self.legend.move(
            self.plot.getPlotItem().getAxis("left").width() + LEGEND_MARGIN_PX,
            self.plot.height() - bottom_axis - self.legend.height() - LEGEND_MARGIN_PX,
        )

    def set_trail_mode(self, mode: str) -> None:
        self.trail_mode = mode
        self._drawn_version = -1

    def set_overlays(self, overlays: list[Overlay]) -> None:
        self.overlays = list(overlays)
        for curve in self.overlay_curves:
            self.plot.removeItem(curve)
        self.overlay_curves = []
        for overlay in self.overlays:
            curve = pg.PlotDataItem(
                [p.x_mm for p in overlay.trail],
                [p.y_mm for p in overlay.trail],
                pen=pg.mkPen(overlay.color, width=1.4),
            )
            curve.setZValue(-1)  # under the live trail
            self.plot.addItem(curve)
            self.overlay_curves.append(curve)
        self._drawn_version = -1

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
        self._draw_events(state.events)
        mode_text = self._draw_trail(state)
        rows = []
        if self.overlays:
            rows.append(
                (theme.TRAIL, self.current_label, run_metrics(state, self.calibration.edge))
            )
            rows += [(o.color, o.label, o.metrics) for o in self.overlays]
        self.legend.set_content(mode_text, rows)
        self._place_legend()
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

    def _draw_trail(self, state: RobotState) -> str | None:
        trail = state.trail
        n = len(trail)
        xs = np.fromiter((p.x_mm for p in trail), float, n)
        ys = np.fromiter((p.y_mm for p in trail), float, n)
        if self.trail_mode == "plain" or n < 2:
            self.trail.setData(xs, ys)
            for curve in self.trail_bins:
                curve.setData([], [])
            _, _, text = trail_bins(trail, self.trail_mode)
            return text
        self.trail.setData([], [])
        bins, palette, text = trail_bins(trail, self.trail_mode)
        while len(self.trail_bins) < len(palette):
            curve = pg.PlotDataItem()
            self.plot.addItem(curve)
            self.trail_bins.append(curve)
        masks = segment_masks(bins, len(palette))
        for i, curve in enumerate(self.trail_bins):
            if i < len(palette) and masks[i].any():
                curve.setPen(pg.mkPen(palette[i], width=2))
                curve.setData(xs, ys, connect=masks[i])
            else:
                curve.setData([], [])
        return text

    def render_png(self, path) -> None:
        """Save the current view with a scale bar (ui-spec, Export)."""
        pixmap = self.plot.grab()
        vb = self.plot.getViewBox()
        area = self.plot.mapFromScene(vb.sceneBoundingRect()).boundingRect()
        mm_per_px = vb.viewPixelSize()[0]
        length_mm = scale_bar_length(mm_per_px)
        length_px = length_mm / mm_per_px
        # bottom-right: the legend owns the bottom-left corner
        x0 = area.right() - 16 - length_px
        y0 = area.bottom() - 18
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(theme.TEXT), 2))
        painter.drawLine(QPointF(x0, y0), QPointF(x0 + length_px, y0))
        for x in (x0, x0 + length_px):
            painter.drawLine(QPointF(x, y0 - 5), QPointF(x, y0 + 1))
        painter.setFont(_mono(11))
        text = f"{length_mm / 10:g} cm" if length_mm < 1000 else f"{length_mm / 1000:g} m"
        painter.drawText(QPointF(x0, y0 - 8), text)
        painter.end()
        pixmap.save(str(path), "PNG")

    def fit(self, state: RobotState) -> None:
        points = [(p.x_mm, p.y_mm) for p in state.trail] + [(0.0, 0.0)]
        for overlay in self.overlays:
            points += [(p.x_mm, p.y_mm) for p in overlay.trail]
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
        self.select_event(None)

    def select_event(self, event: EventRecord | None) -> None:
        self.selected = event
        if event is None:
            self.selection.setData([], [])
            return
        x, y = event_position(event, self.sensor_offset_mm)
        self.selection.setData([x], [y])

    def _draw_events(self, events: list[EventRecord]) -> None:
        if events == self._shown_events:
            return
        self._shown_events = list(events)
        spots = []
        for event in events:
            x, y = event_position(event, self.sensor_offset_mm)
            color = event_color(event.kind)
            spots.append(
                {
                    "pos": (x, y),
                    "symbol": EVENT_SYMBOLS.get(event.kind, "o"),
                    "pen": pg.mkPen(color, width=1.4),
                    "brush": pg.mkBrush(theme.SUNKEN),
                    "data": event,
                }
            )
        self.events.setData(spots)
        if self.selected is not None and self.selected not in events:
            self.select_event(None)

    def _event_clicked(self, _item, points, _ev=None) -> None:
        if len(points):
            event = points[0].data()
            self.select_event(event)
            self.event_clicked.emit(event)
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
