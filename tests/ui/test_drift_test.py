"""Drift test dialog on its own, and the full run through the main window."""

from __future__ import annotations

import asyncio
import json

import pytest
from pybricksdev.ble.pybricks import StatusFlag
from PySide6.QtWidgets import QApplication

from app.core.config import RobotConfig, RobotGeometry
from app.core.state import Pose
from app.ui.dialogs.drift_test import DriftTestDialog
from app.ui.main_window import MainWindow
from tests.fakes import HUB, SCAN_OUTPUT, FakeHubs


def dialog(tmp_path, applied: list) -> DriftTestDialog:
    async def run(key: str) -> bool:
        return True

    return DriftTestDialog(
        run=run, config=RobotConfig, apply_geometry=applied.append, records_dir=tmp_path
    )


def select(d: DriftTestDialog, key: str) -> None:
    d.test_combo.setCurrentIndex(d.test_combo.findData(key))


def test_straight_suggests_wheel_diameter_and_records(qapp, tmp_path) -> None:
    applied: list[RobotGeometry] = []
    d = dialog(tmp_path, applied)
    select(d, "straight")
    d.program_finished(Pose(9000, 1000.0, 0.0, 0.0))
    assert "1000.0 mm driven" in d.estimate_label.text()
    d.real_distance.setValue(980)
    d.compute()
    assert "54.88 mm" in d.result.text()
    d.apply_button.click()
    assert applied[0].wheel_diameter_mm == pytest.approx(54.88)
    record = json.loads(d.last_record.read_text(encoding="utf-8"))
    assert record["test"] == "straight"
    assert record["geometry"]["wheel_diameter_mm"] == 56.0
    assert record["measured"]["distance_mm"] == 980
    assert record["result"]["suggested"]["wheel_diameter_mm"] == 54.88


def test_turns_verdict(qapp, tmp_path) -> None:
    d = dialog(tmp_path, [])
    select(d, "turns")
    d.program_finished(Pose(20000, 0.0, 0.0, -1805.0))
    d.turn_offset.setValue(-4)
    d.compute()
    assert "PASS" in d.result.text()


def test_square_fail_offers_no_geometry(qapp, tmp_path) -> None:
    d = dialog(tmp_path, [])
    select(d, "square")
    d.program_finished(Pose(30000, 100.0, 60.0, 0.0))
    d.compute()
    assert "FAIL" in d.result.text()
    assert not d.apply_button.isEnabled()


def test_no_estimate_means_no_compute(qapp, tmp_path) -> None:
    d = dialog(tmp_path, [])
    d.program_finished(None)
    assert not d.compute_button.isEnabled()
    assert "without odometry" in d.status.text()


def test_changing_test_clears_old_estimate(qapp, tmp_path) -> None:
    d = dialog(tmp_path, [])
    d.program_finished(Pose(1, 1000.0, 0.0, 0.0))
    select(d, "square")
    assert not d.compute_button.isEnabled()


async def test_full_run_through_main_window(qapp, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.ui.main_window.DRAIN_GRACE_S", 0.0)
    fakes = FakeHubs()
    w = MainWindow(connection_factory=fakes.connection)
    w.start()
    try:
        await w.conn.connect(HUB)
        fakes.program_output[:] = [SCAN_OUTPUT]
        await w.scan_ports()
        fakes.hub.status_observable.on_next(StatusFlag(0))

        w.show_drift_test()
        d = w._drift_dialog
        d._records_dir = tmp_path
        fakes.program_output[:] = [
            b"R,DRIFT_TEST,1\nS,0,7810,120,0\nS,600,7810,120,1\n"
            b"T,700,500.0,0.0,0.0,0,0,TEST\nT,9000,1003.0,1.0,0.2,0,0,STOP\n"
        ]
        assert await w.run_program("drift_test", drift="straight")
        assert fakes.hub.ran[-1][0].endswith("hub_drift_test.py")
        await asyncio.sleep(0.05)
        w._tick_ui()
        assert w.battery_label.text() == "7.81 V"
        assert len(w.state.trail) == 2

        fakes.hub.status_observable.on_next(StatusFlag(0))  # program ended
        await asyncio.sleep(0.05)
        assert d.compute_button.isEnabled()
        assert "1003.0 mm driven" in d.estimate_label.text()
    finally:
        await w.shutdown()
        QApplication.instance().removeEventFilter(w)
