"""Tuning knobs: slider plus exact-entry field, and the value the hub acknowledged.

Each program shows only the knobs it uses (its group):
- line: KP, KD, SPD, PIV (pivot), SRCH (search), sent live and acknowledged
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
)

from app.core.config import TuningParams
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


DEG_S = " °/s"
KNOBS = (
    Knob("kp", "KP", -10.0, 10.0, 0.05, 2),
    Knob("kd", "KD", -20.0, 20.0, 0.1, 2),
    Knob("base_speed_mm_s", "SPD", 0.0, 300.0, 5.0, 0, " mm/s", frozenset({"line", "teleop"})),
    Knob("pivot_deg_s", "PIV", 10.0, 360.0, 5.0, 0, DEG_S),
    Knob("search_deg_s", "SRCH", 10.0, 360.0, 5.0, 0, DEG_S),
    Knob("teleop_turn_deg_s", "TURN", 10.0, 360.0, 5.0, 0, DEG_S, frozenset({"teleop"}), False),
    Knob("drift_speed_mm_s", "DSPD", 10.0, 300.0, 5.0, 0, " mm/s", frozenset({"drift"}), False),
    Knob("drift_turn_deg_s", "DTRN", 10.0, 360.0, 5.0, 0, DEG_S, frozenset({"drift"}), False),
)
HUB_KEYS = tuple(k.key for k in KNOBS if k.hub)
GROUPS = {"line": "Line", "teleop": "Teleop", "drift": "Drift"}
# program mode -> knob group; calibration drives nothing and keeps the current one
MODE_GROUPS = {"line_follower": "line", "teleop": "teleop", "drift_test": "drift"}
MODE_HINTS = {
    "config": "sent with Run",
    "waiting": "waiting for the hub",
    "live": "live, no re-upload",
    "speed": "live",
    "off": "not used by this program",
    "replay": "disabled during replay",
}


class TuningRow:
    def __init__(self, knob: Knob, grid: QGridLayout, row: int, on_change) -> None:
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
        grid.addWidget(self.name, 2 * row, 0)
        grid.addWidget(self.slider, 2 * row, 1)
        grid.addWidget(self.spin, 2 * row, 2)
        grid.addWidget(self.ack, 2 * row + 1, 1, 1, 2)

        self.slider.valueChanged.connect(self._slider_moved)
        self.spin.valueChanged.connect(self._spin_changed)

    def value(self) -> float:
        return self.spin.value()

    def set_visible(self, visible: bool) -> None:
        for w in (self.name, self.slider, self.spin, self.ack):
            w.setVisible(visible)

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


class TuningPanel(QFrame):
    """Emits `changed(key, value)` with the protocol key, e.g. ("KP", -1.8)."""

    changed = Signal(str, float)

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
            button.clicked.connect(lambda _=False, g=group: self.set_group(g))
            self._group_box.addButton(button)
            self.group_buttons[group] = button
            head.addWidget(button)
        head.addStretch()
        head.addWidget(self.hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        self.rows = {
            k.key: TuningRow(k, grid, i, lambda key, v: self.changed.emit(key, v))
            for i, k in enumerate(KNOBS)
        }
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addLayout(head)
        layout.addLayout(grid)
        self.set_group("line")
        self.set_mode("config")

    def values(self) -> dict[str, float]:
        """TuningParams field -> value."""
        return {row.knob.field: row.value() for row in self.rows.values()}

    def set_values(self, tuning: TuningParams) -> None:
        for row in self.rows.values():
            row.spin.blockSignals(True)
            row.set_value(getattr(tuning, row.knob.field))
            row.slider.setValue(row._tick(row.value()))
            row.spin.blockSignals(False)

    def knobs(self) -> dict[str, float]:
        """Protocol key -> value, e.g. {"SPD": 50.0, "PIV": 180.0}."""
        return {key: row.value() for key, row in self.rows.items()}

    def set_group(self, group: str) -> None:
        """Show one program's knobs."""
        self.group = group
        self.group_buttons[group].setChecked(True)
        self._refresh()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.hint.setText(MODE_HINTS[mode])
        self._refresh()

    def _refresh(self) -> None:
        enabled = self.mode in ("config", "live", "speed")
        for button in self.group_buttons.values():
            button.setEnabled(self.mode == "config")  # a running program owns the group
        for row in self.rows.values():
            shown = self.group in row.knob.groups
            row.set_visible(shown)
            row.set_enabled(enabled and shown)
            if self.mode != "live":
                row.ack.setText("")

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
