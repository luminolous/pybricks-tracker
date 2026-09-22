"""Tabbed scrolling plots over the last 10 seconds (docs/design: tabs, not stacks).

Reflection with calibrated black/edge/white lines, error and steer, motor
load left/right, loop dt with nominal and 1.5x lines. Fed from RobotState on
the window's refresh timer.
"""

from __future__ import annotations

from dataclasses import dataclass

import pyqtgraph as pg
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTabBar, QVBoxLayout, QWidget

from app.core.config import SensorCalibration
from app.core.state import HISTORY_S, History, RobotState
from app.ui import theme
from app.ui.theme import label

STEER_SCALE = 3  # steer (deg/s) shares the error axis divided by this
DT_WARN = 1.5  # loop dt warning factor (protocol.md, D line)


@dataclass
class Series:
    name: str
    color: str
    source: str  # "fast" (T, 20 Hz) or "slow" (D, 4 Hz)
    column: int
    transform: object = None  # callable on each value, or None


@dataclass
class Tab:
    title: str
    series: list[Series]
    y_range: tuple[float, float] | None
    unit: str = ""


class PlotPanel(QWidget):
    def __init__(self, nominal_dt_ms: int) -> None:
        super().__init__()
        self.nominal_dt_ms = nominal_dt_ms
        self.calibration = SensorCalibration()
        self._drawn_key: tuple = ()

        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.big = label("—", mono=True)
        self.big.setStyleSheet("font-size: 24px;")
        self.meta = label("", tone="dim", mono=True)
        self.meta.setStyleSheet("font-size: 10px;")
        self.legend = QHBoxLayout()
        self.legend.setSpacing(14)

        self.plot = pg.PlotWidget(background=theme.SUNKEN)
        self.plot.setFixedHeight(150)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setMouseEnabled(x=False, y=False)
        item = self.plot.getPlotItem()
        for name in ("left", "bottom"):
            axis = item.getAxis(name)
            axis.setPen(pg.mkPen(theme.LINE_STRONG))
            axis.setTextPen(pg.mkPen(theme.DIM))
        item.getAxis("left").setWidth(34)
        # Ticks inside the range: labels at the exact edges get clipped.
        item.getAxis("bottom").setTicks([[(t, f"−{-t} s") for t in (-8, -6, -4, -2)]])
        item.showGrid(x=True, y=False, alpha=0.12)
        self.plot.setXRange(-HISTORY_S, 0, padding=0)

        self.curves: dict[str, pg.PlotDataItem] = {}
        self.ref_lines: list[pg.InfiniteLine] = []
        self._tabs = self._build_tabs()
        for tab in self._tabs:
            self.tabs.addTab(tab.title)
        self.tabs.currentChanged.connect(self._tab_changed)

        top = QHBoxLayout()
        top.addWidget(self.big)
        top.addStretch()
        top.addWidget(self.meta)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(self.tabs)
        layout.addLayout(top)
        layout.addWidget(self.plot)
        layout.addLayout(self.legend)
        self._tab_changed(0)

    # -- public ------------------------------------------------------------

    def refresh(self, state: RobotState) -> None:
        key = (state.version, self.tabs.currentIndex(), self.calibration)
        if key == self._drawn_key:
            return
        self._drawn_key = key
        tab = self._tabs[self.tabs.currentIndex()]
        latest = {"fast": _latest(state.fast), "slow": _latest(state.slow)}
        big_value = None
        for s in tab.series:
            history: History = getattr(state, s.source)
            end = latest[s.source]
            if end is None:
                self.curves[s.name].setData([], [])
                continue
            xs = [(t - end) / 1000 for t in history.t_ms]
            ys = history.column(s.column)
            if s.transform:
                ys = [s.transform(y) for y in ys]
            self.curves[s.name].setData(xs, ys)
            if big_value is None and ys:
                big_value = ys[-1]
        self.big.setText("—" if big_value is None else f"{big_value:.0f}{tab.unit}")

    # -- internals ---------------------------------------------------------

    def _build_tabs(self) -> list[Tab]:
        return [
            Tab("Reflection", [Series("reflection", theme.TEXT, "fast", 0)], (0, 100)),
            Tab(
                "Error / steer",
                [
                    Series("error", theme.TEXT, "fast", 0, lambda r: r - self.calibration.edge),
                    Series(
                        f"steer ÷ {STEER_SCALE}", theme.ACCENT, "fast", 1, lambda v: v / STEER_SCALE
                    ),
                ],
                (-60, 60),
            ),
            Tab(
                "Motor load",
                [
                    Series("left", theme.TEXT, "slow", 0),
                    Series("right", theme.ACCENT, "slow", 1),
                ],
                None,
                " mNm",
            ),
            Tab("Loop dt", [Series("loop dt", theme.ACCENT, "slow", 2)], None, " ms"),
        ]

    def _refs(self, tab_index: int) -> tuple[list[tuple[float, str, bool]], str]:
        c = self.calibration
        nominal = self.nominal_dt_ms
        if tab_index == 0:
            refs = [
                (c.white, f"white {c.white}", False),
                (c.edge, f"edge {c.edge}", True),
                (c.black, f"black {c.black}", False),
            ]
            return refs, "last 10 s"
        if tab_index == 1:
            return [(0, "0", False)], f"error = refl − {c.edge}"
        if tab_index == 2:
            return [], "4 Hz · D lines"
        warn = nominal * DT_WARN
        refs = [(nominal, f"{nominal} ms nominal", True), (warn, f"{DT_WARN:g}× warn", False)]
        return refs, f"warn > {warn:g} ms"

    def _tab_changed(self, index: int) -> None:
        tab = self._tabs[index]
        for curve in self.curves.values():
            self.plot.removeItem(curve)
        self.curves.clear()
        for line in self.ref_lines:
            self.plot.removeItem(line)
        self.ref_lines.clear()

        refs, meta = self._refs(index)
        top = max((value for value, _, _ in refs), default=None)
        for value, text, key in refs:
            color = "#3FD0E673" if key else theme.LINE_STRONG
            # Labels point into the plot: below the highest line, above the others,
            # so neither edge clips them.
            anchor = (1, 0) if value == top else (1, 1)
            line = pg.InfiniteLine(
                pos=value,
                angle=0,
                pen=pg.mkPen(color, style=pg.QtCore.Qt.PenStyle.DashLine),
                label=text,
                labelOpts={"position": 0.98, "color": theme.DIM, "anchors": [anchor, anchor]},
            )
            self.plot.addItem(line)
            self.ref_lines.append(line)
        for s in tab.series:
            curve = pg.PlotDataItem(pen=pg.mkPen(s.color, width=1.4))
            self.plot.addItem(curve)
            self.curves[s.name] = curve
        if tab.y_range:
            self.plot.setYRange(*tab.y_range, padding=0.02)
            self.plot.enableAutoRange(axis="y", enable=False)
        else:
            self.plot.enableAutoRange(axis="y", enable=True)
        self.meta.setText(meta)
        self._set_legend(tab)
        self._drawn_key = ()

    def _set_legend(self, tab: Tab) -> None:
        while self.legend.count():
            item = self.legend.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()  # deleteLater waits for the event loop; hide now
                widget.setParent(None)
                widget.deleteLater()
        for s in tab.series:
            swatch = QLabel()
            swatch.setFixedSize(12, 2)
            swatch.setStyleSheet(f"background: {s.color};")
            self.legend.addWidget(swatch)
            self.legend.addWidget(label(s.name, tone="muted"))
        self.legend.addStretch()


def _latest(history: History) -> int | None:
    return history.t_ms[-1] if history.t_ms else None
