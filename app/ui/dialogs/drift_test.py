"""Odometry validation workflow: pick a test, run it, measure, compare.

Every computed result is written to configs/drift/ with the geometry it was
run with, so a calibration always has provenance.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.analysis import (
    DRIFT_TESTS,
    SQUARE_CLOSURE_LIMIT_PCT,
    TURNS_HEADING_LIMIT_DEG,
    analyze_square,
    analyze_straight,
    analyze_turns,
)
from app.core.config import CONFIGS_DIR, RobotConfig, RobotGeometry
from app.core.state import Pose
from app.ui.theme import caption, label, set_prop

DRIFT_RECORDS_DIR = CONFIGS_DIR / "drift"

RunFn = Callable[[str], Awaitable[bool]]


def _spin(low: float, high: float, suffix: str, value: float = 0.0) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setLocale(QLocale.c())
    spin.setRange(low, high)
    spin.setDecimals(1)
    spin.setSuffix(suffix)
    spin.setValue(value)
    spin.setFixedWidth(110)
    return spin


class DriftTestDialog(QDialog):
    def __init__(
        self,
        run: RunFn,
        config: Callable[[], RobotConfig],
        apply_geometry: Callable[[RobotGeometry], None],
        records_dir: Path = DRIFT_RECORDS_DIR,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Drift test")
        self.setMinimumWidth(520)
        self._run = run
        self._config = config
        self._apply_geometry = apply_geometry
        self._records_dir = records_dir
        self._estimate: Pose | None = None
        self._suggested: RobotGeometry | None = None
        self.last_record: Path | None = None

        self.test_combo = QComboBox()
        for test in DRIFT_TESTS.values():
            self.test_combo.addItem(test.label, test.key)
        self.instructions = label("", tone="muted")
        self.instructions.setWordWrap(True)
        self.run_button = QPushButton("Run test")
        self.run_button.setProperty("role", "run")
        self.status = label("", tone="muted")
        self.status.setWordWrap(True)
        self.estimate_label = label("Estimate: run the test first.", tone="dim", mono=True)

        # Measurement inputs, one page per test.
        self.real_distance = _spin(0, 5000, " mm", 1000)
        self.turn_offset = _spin(-360, 360, " °")
        self.real_x = _spin(-2000, 2000, " mm")
        self.real_y = _spin(-2000, 2000, " mm")
        self.inputs = QStackedWidget()
        self.inputs.addWidget(self._page(("Measured distance", self.real_distance)))
        self.inputs.addWidget(
            self._page(("Ended past the start heading by (+ over, − short)", self.turn_offset))
        )
        self.inputs.addWidget(
            self._page(
                ("Real end x from start (forward)", self.real_x),
                ("Real end y from start (left)", self.real_y),
            )
        )

        self.compute_button = QPushButton("Compute")
        self.compute_button.setProperty("role", "small")
        self.compute_button.setEnabled(False)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setProperty("mono", True)
        self.apply_button = QPushButton("Apply suggested geometry")
        self.apply_button.setProperty("role", "small")
        self.apply_button.setEnabled(False)
        close = QPushButton("Close")
        close.setProperty("role", "small")
        close.clicked.connect(self.close)

        run_row = QHBoxLayout()
        run_row.addWidget(self.test_combo, 1)
        run_row.addWidget(self.run_button)
        buttons = QHBoxLayout()
        buttons.addWidget(self.compute_button)
        buttons.addWidget(self.apply_button)
        buttons.addStretch()
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(caption("1 · Run"))
        layout.addLayout(run_row)
        layout.addWidget(self.instructions)
        layout.addWidget(self.status)
        layout.addWidget(caption("2 · Measure"))
        layout.addWidget(self.estimate_label)
        layout.addWidget(self.inputs)
        layout.addWidget(caption("3 · Compare"))
        layout.addWidget(self.result)
        layout.addLayout(buttons)

        self.test_combo.currentIndexChanged.connect(self._test_changed)
        self.run_button.clicked.connect(self._run_clicked)
        self.compute_button.clicked.connect(self.compute)
        self.apply_button.clicked.connect(self._apply_clicked)
        self._test_changed()

    # -- steps -------------------------------------------------------------

    @property
    def test_key(self) -> str:
        return self.test_combo.currentData()

    def program_finished(self, final_pose: Pose | None) -> None:
        """Called by the main window when the drift program ends."""
        self._estimate = final_pose
        self.run_button.setEnabled(True)
        if final_pose is None:
            self.status.setText("The test ended without odometry. Check the console.")
            set_prop(self.status, "tone", "warn")
            return
        self.status.setText("Done. Measure the robot where it stopped, then compute.")
        set_prop(self.status, "tone", "ok")
        self.estimate_label.setText(self._estimate_text(final_pose))
        set_prop(self.estimate_label, "tone", "text")
        self.compute_button.setEnabled(True)

    def compute(self) -> None:
        pose = self._estimate
        if pose is None:
            return
        geometry = self._config().geometry
        key = self.test_key
        try:
            if key == "straight":
                estimated = math.hypot(pose.x_mm, pose.y_mm)
                r = analyze_straight(geometry, estimated, self.real_distance.value())
                old_d, new_d = geometry.wheel_diameter_mm, r.suggested.wheel_diameter_mm
                lines = [
                    f"error      {r.error_mm_per_m:+.1f} mm per metre",
                    f"wheel Ø    {old_d:.2f} → {new_d:.2f} mm",
                ]
                result, self._suggested = asdict(r), r.suggested
            elif key == "turns":
                real = DRIFT_TESTS["turns"].commanded_rotation_deg + self.turn_offset.value()
                r = analyze_turns(geometry, pose.heading_deg, real)
                verdict = "PASS" if r.passed else "FAIL"
                lines = [
                    f"wheels     {r.wheel_error_deg_per_rev:+.1f}° per revolution",
                    f"map        {r.heading_error_deg:+.1f}° after 5 turns "
                    f"({verdict}, limit ±{TURNS_HEADING_LIMIT_DEG:g}°)",
                    f"axle track {geometry.axle_track_mm:.2f} → {r.suggested.axle_track_mm:.2f} mm",
                ]
                result, self._suggested = asdict(r), r.suggested
            else:
                r = analyze_square(pose.x_mm, pose.y_mm, self.real_x.value(), self.real_y.value())
                verdict = "PASS" if r.passed else "FAIL"
                lines = [
                    f"map error  {r.map_error_mm:.0f} mm = {r.error_pct:.1f}% of "
                    f"{r.perimeter_mm:.0f} mm ({verdict}, limit {SQUARE_CLOSURE_LIMIT_PCT:g}%)",
                ]
                result, self._suggested = asdict(r), None
        except ValueError as exc:
            self.result.setText(str(exc))
            set_prop(self.result, "tone", "warn")
            return
        self.result.setText("\n".join(lines))
        set_prop(self.result, "tone", "text")
        self.apply_button.setEnabled(self._suggested is not None)
        self.last_record = self._save_record(geometry, pose, result)

    # -- internals ---------------------------------------------------------

    def _page(self, *rows: tuple[str, QDoubleSpinBox]) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        for i, (text, spin) in enumerate(rows):
            grid.addWidget(label(text, tone="muted"), i, 0)
            grid.addWidget(spin, i, 1)
        grid.setColumnStretch(0, 1)
        return page

    def _estimate_text(self, pose: Pose) -> str:
        if self.test_key == "straight":
            return f"Estimate: {math.hypot(pose.x_mm, pose.y_mm):.1f} mm driven"
        if self.test_key == "turns":
            return f"Estimate: IMU turned {abs(pose.heading_deg):.1f}°"
        return f"Estimate: ended at x {pose.x_mm:.1f} mm, y {pose.y_mm:.1f} mm"

    def _test_changed(self) -> None:
        self.inputs.setCurrentIndex(self.test_combo.currentIndex())
        self.instructions.setText(DRIFT_TESTS[self.test_key].instructions)
        self._estimate = None
        self._suggested = None
        self.estimate_label.setText("Estimate: run the test first.")
        set_prop(self.estimate_label, "tone", "dim")
        self.result.setText("")
        self.compute_button.setEnabled(False)
        self.apply_button.setEnabled(False)

    def _run_clicked(self) -> None:
        key = self.test_key
        self._test_changed()
        self.run_button.setEnabled(False)
        self.status.setText("Running. Keep clear of the robot; Space stops it.")
        set_prop(self.status, "tone", "muted")

        async def go() -> None:
            if not await self._run(key):
                self.status.setText("The test did not start. See the console.")
                set_prop(self.status, "tone", "warn")
                self.run_button.setEnabled(True)

        asyncio.ensure_future(go())

    def _apply_clicked(self) -> None:
        if self._suggested is not None:
            self._apply_geometry(self._suggested)
            self.apply_button.setEnabled(False)
            self.status.setText("Geometry applied. Save the preset to keep it.")
            set_prop(self.status, "tone", "ok")

    def _save_record(self, geometry: RobotGeometry, pose: Pose, result: dict) -> Path:
        stamp = datetime.now(UTC)
        record = {
            "test": self.test_key,
            "at": stamp.isoformat(timespec="seconds"),
            "geometry": asdict(geometry),
            "estimate": asdict(pose),
            "measured": {
                "distance_mm": self.real_distance.value(),
                "turn_offset_deg": self.turn_offset.value(),
                "end_x_mm": self.real_x.value(),
                "end_y_mm": self.real_y.value(),
            },
            "result": _plain(result),
        }
        self._records_dir.mkdir(parents=True, exist_ok=True)
        path = self._records_dir / f"{stamp:%Y%m%dT%H%M%SZ}_{self.test_key}.json"
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return path


def _plain(value: object) -> object:
    """asdict() output with nested dataclass dicts already plain; round floats for humans."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, float):
        return round(value, 3)
    return value
