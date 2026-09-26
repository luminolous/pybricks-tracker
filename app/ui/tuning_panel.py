"""Tuning knobs: slider plus exact-entry field, and the value the hub acknowledged.

Each program shows only the knobs it uses (its group):
- line, in three foldable sections: PID (KP, KI, KD), Speed (SPD, INNER, SRCH)
  and Route (THR, FIN, LOCK, and the route: L/R/S step buttons rendered into
  the program at Run). The knobs are sent live and acknowledged. A folded
  section shows a one-line summary instead, so the event list keeps its room.
- teleop: SPD, TURN, applied in the app (every DRV carries them)
- drift: DSPD, DTRN, rendered into the program and locked while it runs

While no program runs, the group buttons pick which set to edit. A started
program switches the group to its own and locks the buttons.

Modes:
- config: no program runs; values are the ones rendered into the next Run.
- waiting: a program was started but its R handshake has not arrived; disabled.
- live: every change goes to the hub (rate limited by TuningSender) and the
  acknowledged value is shown under the control, so a dropped write is visible.
- speed: teleop runs; its knobs act in the app, so there is no hub acknowledgement.
- off: the running program takes no live tuning (drift test, calibration); disabled.
- replay: a recorded run is showing; disabled.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.core.config import MAX_ROUTE_STEPS, MAX_SPEED_MM_S, MAX_TURN_DEG_S, TuningParams
from app.ui.theme import caption, label, set_prop


@dataclass(frozen=True)
class Knob:
    field: str  # TuningParams field
    key: str  # protocol command
    low: float
    high: float
    step: float
    decimals: int
    suffix: str = ""
    groups: frozenset[str] = frozenset({"line"})
    hub: bool = True  # sent to the hub live and acknowledged (protocol.md)
    integer: bool = False  # the TuningParams field is an int
    section: str | None = None  # foldable section in the line group


DEG_S = " °/s"
SPD_MAX = float(MAX_SPEED_MM_S)
TRN_MAX = float(MAX_TURN_DEG_S)
LINE_AND_TELEOP = frozenset({"line", "teleop"})
KNOBS = (
    Knob("kp", "KP", -10.0, 10.0, 0.05, 2, section="pid"),
    Knob("ki", "KI", -5.0, 5.0, 0.05, 2, section="pid"),
    Knob("kd", "KD", -20.0, 20.0, 0.1, 2, section="pid"),
    Knob("base_speed_mm_s", "SPD", 0.0, SPD_MAX, 5.0, 0, " mm/s", LINE_AND_TELEOP, section="speed"),
    Knob("inner_pct", "INNER", -100.0, 100.0, 5.0, 0, " %", section="speed"),
    Knob("search_deg_s", "SRCH", 10.0, TRN_MAX, 5.0, 0, DEG_S, section="speed"),
    Knob("obstacle_threshold_mm", "THR", 20.0, 300.0, 5.0, 0, " mm", integer=True, section="route"),
    Knob("finish_mm", "FIN", 0.0, 5000.0, 10.0, 0, " mm", section="route"),
    Knob("route_lock_deg", "LOCK", 5.0, 60.0, 1.0, 0, " °", section="route"),
    Knob("teleop_turn_deg_s", "TURN", 10.0, TRN_MAX, 5.0, 0, DEG_S, frozenset({"teleop"}), False),
    Knob("drift_speed_mm_s", "DSPD", 10.0, SPD_MAX, 5.0, 0, " mm/s", frozenset({"drift"}), False),
    Knob("drift_turn_deg_s", "DTRN", 10.0, TRN_MAX, 5.0, 0, DEG_S, frozenset({"drift"}), False),
)
HUB_KEYS = tuple(k.key for k in KNOBS if k.hub)
# line group sections, in order; the route editor closes the last one
SECTIONS = {"pid": "PID", "speed": "Speed", "route": "Route"}
FOLDED_AT_START = frozenset({"route"})
GROUPS = {"line": "Line", "teleop": "Teleop", "drift": "Drift"}
# program mode -> knob group; calibration drives nothing and keeps the current one
MODE_GROUPS = {"line_follower": "line", "teleop": "teleop", "drift_test": "drift"}
MODE_HINTS = {
    "config": "sent with Run",
    "waiting": "waiting for the hub",
    "live": "live",
    "speed": "live",
    "off": "not used by this program",
    "replay": "disabled during replay",
}


class TuningRow:
    def __init__(self, knob: Knob, grid: QGridLayout, row: int, on_change) -> None:
        """Takes grid rows `row` (controls) and `row + 1` (hub acknowledgement)."""
        self.knob = knob
        self._on_change = on_change
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(self._tick(knob.low), self._tick(knob.high))
        self.spin = QDoubleSpinBox()
        self.spin.setLocale(QLocale.c())
        self.spin.setRange(knob.low, knob.high)
        self.spin.setDecimals(knob.decimals)
        self.spin.setSingleStep(knob.step)
        self.spin.setSuffix(knob.suffix)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.spin.setFixedWidth(92)
        self.ack = label("", tone="dim", mono=True)
        self.ack.setStyleSheet("font-size: 10px;")

        self.name = label(knob.key, tone="muted", mono=True)
        self.name.setFixedWidth(36)
        grid.addWidget(self.name, row, 0)
        grid.addWidget(self.slider, row, 1)
        grid.addWidget(self.spin, row, 2)
        grid.addWidget(self.ack, row + 1, 1, 1, 2)

        self.slider.valueChanged.connect(self._slider_moved)
        self.spin.valueChanged.connect(self._spin_changed)

    def value(self) -> float:
        return self.spin.value()

    def field_value(self) -> float | int:
        return round(self.value()) if self.knob.integer else self.value()

    def set_visible(self, visible: bool, ack: bool) -> None:
        for w in (self.name, self.slider, self.spin):
            w.setVisible(visible)
        self.ack.setVisible(visible and ack)  # only while live: keeps the panel short

    def set_enabled(self, enabled: bool) -> None:
        self.slider.setEnabled(enabled)
        self.spin.setEnabled(enabled)

    def set_value(self, value: float) -> None:
        self.spin.setValue(value)  # syncs the slider through _spin_changed

    def _tick(self, value: float) -> int:
        return round(value / self.knob.step)

    def _slider_moved(self, tick: int) -> None:
        value = round(tick * self.knob.step, self.knob.decimals)
        if abs(value - self.spin.value()) > self.knob.step / 2:
            self.spin.setValue(value)

    def _spin_changed(self, value: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(self._tick(value))
        self.slider.blockSignals(False)
        self._on_change(self.knob.key, value)


STEP_NAMES = {"L": "left", "R": "right", "S": "straight across the crossing"}
NEXT_STEP = {"L": "R", "R": "S", "S": "L"}  # a click on a step cycles it


class RouteEditor(QWidget):
    """Planned steps as L/R/S buttons: click one to cycle it, +L / +R / +S add, ⌫ removes.

    While a run goes, taken turns are filled and the next one is outlined.
    """

    changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._route = ""
        self._done: int | None = None
        self._editable = True
        self.setToolTip(
            "Planned steps in order, corners included. L / R: before the turn the robot\n"
            "follows the line edge on that side, so it takes that branch at the next\n"
            "junction. S: straight across the next crossing, heading held within LOCK.\n"
            "Empty: plain line following. Click a step to change it."
        )
        self.name = label("ROUTE", tone="muted", mono=True)
        self.name.setFixedWidth(36)
        self.empty = label("none", tone="dim")
        self.chips: list[QPushButton] = []
        self._chip_row = QHBoxLayout()
        self._chip_row.setContentsMargins(0, 0, 0, 0)
        self._chip_row.setSpacing(2)
        self.add_buttons = {}
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self.name)
        row.addSpacing(6)
        row.addLayout(self._chip_row)
        row.addWidget(self.empty)
        row.addStretch()
        for text, turn in (("+L", "L"), ("+R", "R"), ("+S", "S"), ("⌫", "")):
            button = QPushButton(text)
            button.setProperty("role", "chip")
            button.setToolTip(
                "Remove the last step" if not turn else f"Add a step: {STEP_NAMES[turn]}"
            )
            button.clicked.connect(lambda _=False, t=turn: self._add(t))
            self.add_buttons[turn] = button
            row.addWidget(button)
        self._rebuild()

    def route(self) -> str:
        return self._route

    def set_route(self, route: str) -> None:
        """Silent: no `changed`."""
        self._route = route
        self._rebuild()

    def set_progress(self, done: int | None) -> None:
        """Turns taken in the current run, or None when nothing runs."""
        if done != self._done:
            self._done = done
            self._paint()

    def set_editable(self, editable: bool) -> None:
        self._editable = editable
        self._paint()

    def _add(self, turn: str) -> None:
        if turn:
            if len(self._route) >= MAX_ROUTE_STEPS:
                return
            self._route += turn
        else:
            self._route = self._route[:-1]
        self._rebuild()
        self.changed.emit(self._route)

    def _flip(self, i: int) -> None:
        turn = NEXT_STEP[self._route[i]]
        self._route = self._route[:i] + turn + self._route[i + 1 :]
        self._rebuild()
        self.changed.emit(self._route)

    def _rebuild(self) -> None:
        for chip in self.chips:
            chip.deleteLater()
        self.chips = []
        for i, turn in enumerate(self._route):
            chip = QPushButton(turn)
            chip.setProperty("role", "chip")
            chip.setToolTip(f"Step {i + 1}: {STEP_NAMES[turn]}. Click to change.")
            chip.clicked.connect(lambda _=False, j=i: self._flip(j))
            self._chip_row.addWidget(chip)
            self.chips.append(chip)
        self.empty.setVisible(not self._route)
        self._paint()

    def _paint(self) -> None:
        full = len(self._route) >= MAX_ROUTE_STEPS
        for turn in "LRS":
            self.add_buttons[turn].setEnabled(self._editable and not full)
        self.add_buttons[""].setEnabled(self._editable and bool(self._route))
        for i, chip in enumerate(self.chips):
            chip.setEnabled(self._editable)
            if self._done is None:
                step = ""
            else:
                step = "done" if i < self._done else "next" if i == self._done else ""
            set_prop(chip, "step", step)


class SectionHeader(QPushButton):
    """A foldable section title in the line group, with a summary when folded."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self.setProperty("role", "section")
        self.setCheckable(True)  # checked = open
        self.summary = ""

    def show_state(self, summary: str) -> None:
        self.summary = summary
        arrow = "▾" if self.isChecked() else "▸"
        text = f"{arrow} {self.title}"
        if not self.isChecked() and summary:
            text += f"   {summary}"
        if self.text() != text:
            self.setText(text)


class TuningPanel(QFrame):
    """Emits `changed(key, value)` with the protocol key, e.g. ("KP", -1.8)."""

    changed = Signal(str, float)
    route_changed = Signal(str)
    group_clicked = Signal(str)  # a group button pressed by the user, not set_group()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("section")
        self.mode = "config"
        self.group = "line"
        self.hint = label("", tone="dim")
        head = QHBoxLayout()
        head.addWidget(caption("Tuning"))
        head.addSpacing(8)
        self.group_buttons: dict[str, QPushButton] = {}
        self._group_box = QButtonGroup(self)
        for group, title in GROUPS.items():
            button = QPushButton(title)
            button.setProperty("role", "small")
            button.setCheckable(True)
            button.setToolTip(f"Show the {title.lower()} knobs")
            button.clicked.connect(lambda _=False, g=group: self._group_button(g))
            self._group_box.addButton(button)
            self.group_buttons[group] = button
            head.addWidget(button)
        head.addStretch()
        head.addWidget(self.hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        self.rows: dict[str, TuningRow] = {}
        self.sections: dict[str, SectionHeader] = {}
        self.route = RouteEditor()
        self.route.changed.connect(self.route_changed)
        self.route.changed.connect(lambda _route: self._refresh())

        def add_row(knob: Knob, at: int) -> None:
            self.rows[knob.key] = TuningRow(knob, grid, at, self._knob_changed)

        at = 0
        for key, title in SECTIONS.items():
            header = SectionHeader(title)
            header.setChecked(key not in FOLDED_AT_START)
            header.toggled.connect(lambda _on: self._refresh())
            self.sections[key] = header
            grid.addWidget(header, at, 0, 1, 3)
            at += 1
            for knob in KNOBS:
                if knob.section == key:
                    add_row(knob, at)
                    at += 2
        grid.addWidget(self.route, at, 0, 1, 3)
        at += 1
        for knob in KNOBS:
            if knob.section is None:
                add_row(knob, at)
                at += 2
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addLayout(head)
        layout.addLayout(grid)
        self.set_group("line")
        self.set_mode("config")

    def values(self) -> dict[str, float | int | str]:
        """TuningParams field -> value."""
        out: dict[str, float | int | str] = {
            row.knob.field: row.field_value() for row in self.rows.values()
        }
        out["route"] = self.route.route()
        return out

    def set_values(self, tuning: TuningParams) -> None:
        self.route.set_route(tuning.route)
        for row in self.rows.values():
            row.spin.blockSignals(True)
            row.set_value(getattr(tuning, row.knob.field))
            row.slider.setValue(row._tick(row.value()))
            row.spin.blockSignals(False)
        self._show_summaries()

    def _knob_changed(self, key: str, value: float) -> None:
        self.changed.emit(key, value)
        self._show_summaries()

    def summary(self, section: str) -> str:
        """One line for a folded section, e.g. "KP -1.50 · KI 0.00 · KD -5.00"."""
        parts = [
            f"{row.knob.key} {row.value():.{row.knob.decimals}f}"
            for row in self.rows.values()
            if row.knob.section == section
        ]
        if section == "route":
            parts.append(self.route.route() or "no route")
        return " · ".join(parts)

    def _show_summaries(self) -> None:
        for key, header in self.sections.items():
            header.show_state(self.summary(key))

    def set_open(self, section: str, open_: bool) -> None:
        self.sections[section].setChecked(open_)

    def knobs(self) -> dict[str, float]:
        """Protocol key -> value, e.g. {"SPD": 50.0, "INNER": 20.0}."""
        return {key: row.value() for key, row in self.rows.items()}

    def set_group(self, group: str) -> None:
        """Show one program's knobs."""
        self.group = group
        self.group_buttons[group].setChecked(True)
        self._refresh()

    def _group_button(self, group: str) -> None:
        self.set_group(group)
        self.group_clicked.emit(group)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.hint.setText(MODE_HINTS[mode])
        self._refresh()

    def _refresh(self) -> None:
        enabled = self.mode in ("config", "live", "speed")
        for button in self.group_buttons.values():
            button.setEnabled(self.mode == "config")  # a running program owns the group
        line = self.group == "line"
        for header in self.sections.values():
            header.setVisible(line)
        for row in self.rows.values():
            section = row.knob.section
            folded = line and section is not None and not self.sections[section].isChecked()
            shown = self.group in row.knob.groups and not folded
            row.set_visible(shown, ack=self.mode == "live")
            row.set_enabled(enabled and shown)
            if self.mode != "live":
                row.ack.setText("")
        self.route.setVisible(line and self.sections["route"].isChecked())
        self.route.set_editable(self.mode == "config")  # rendered at Run, fixed while it runs
        self._show_summaries()

    def show_ack(self, key: str, acked: float | None, pending: bool, stale: bool) -> None:
        row = self.rows.get(key)
        if row is None or self.mode != "live" or not row.knob.hub:
            return
        decimals = row.knob.decimals
        shown = "—" if acked is None else f"{acked:.{decimals}f}"
        if stale:
            text, tone = f"hub {shown} · no reply", "danger"
        elif pending:
            text, tone = f"hub {shown} · sending", "warn"
        else:
            text, tone = f"hub {shown}", "ok"
        if row.ack.text() != text:
            row.ack.setText(text)
            set_prop(row.ack, "tone", tone)
