"""M6: live tuning with acknowledgements, and the calibration dialog."""

from __future__ import annotations

import asyncio

import pytest
from pybricksdev.ble.pybricks import StatusFlag
from PySide6.QtWidgets import QApplication

from app.core.config import SensorCalibration, TuningParams, check_calibration
from app.core.state import History
from app.ui.dialogs.calibration import CalibrationDialog
from app.ui.main_window import MainWindow
from app.ui.tuning_panel import TuningPanel
from tests.fakes import HUB, SCAN_OUTPUT, FakeHubs

LF_OUTPUT = b"R,LINE_FOLLOWER,1\nS,0,7800,120,1\nT,100,0.0,0.0,0.0,50,0,FOLLOW\n"


@pytest.fixture
async def window(qapp):
    fakes = FakeHubs()
    w = MainWindow(connection_factory=fakes.connection)
    w.fakes = fakes
    w.start()
    yield w
    await w.shutdown()
    QApplication.instance().removeEventFilter(w)


async def running(
    w, output: bytes = LF_OUTPUT, mode: str = "line_follower", drift: str | None = None
) -> None:
    await w.conn.connect(HUB)
    w.fakes.program_output[:] = [SCAN_OUTPUT]
    await w.scan_ports()
    w.fakes.hub.status_observable.on_next(StatusFlag(0))
    w.fakes.program_output[:] = [output]
    assert await w.run_program(mode, drift=drift)


def tuning_writes(w) -> list[str]:
    return [c for c in w.fakes.hub.written if c.split(",")[0] in ("KP", "KD", "SPD")]


# -- panel -------------------------------------------------------------------


def test_slider_and_field_stay_in_sync(qapp) -> None:
    panel = TuningPanel()
    seen = []
    panel.changed.connect(lambda k, v: seen.append((k, v)))
    row = panel.rows["KP"]
    row.slider.setValue(-50)  # 50 steps of 0.05
    assert row.value() == -2.5
    row.spin.setValue(-1.2)
    assert row.slider.value() == -24
    assert seen[-1] == ("KP", -1.2)


def test_set_values_is_silent(qapp) -> None:
    panel = TuningPanel()
    seen = []
    panel.changed.connect(lambda k, v: seen.append(k))
    panel.set_values(TuningParams(kp=-3.0, kd=-6.0, base_speed_mm_s=120))
    assert seen == []
    assert panel.values() == {"kp": -3.0, "kd": -6.0, "base_speed_mm_s": 120}
    assert panel.rows["SPD"].slider.value() == 24


def test_modes_enable_and_hint(qapp) -> None:
    panel = TuningPanel()
    for mode, enabled in (("config", True), ("waiting", False), ("live", True), ("off", False)):
        panel.set_mode(mode)
        assert panel.rows["KD"].slider.isEnabled() is enabled
    panel.set_mode("speed")  # teleop: SPD only
    assert panel.rows["SPD"].slider.isEnabled()
    assert not panel.rows["KD"].slider.isEnabled()


# -- live flow ----------------------------------------------------------------


async def test_line_follower_goes_live_without_resending_start_values(window) -> None:
    await running(window)
    assert window.tuning.mode == "live"
    await window.tuner.flush()
    assert tuning_writes(window) == []  # the hub already runs with them


async def test_drag_sends_latest_and_shows_ack(window) -> None:
    await running(window)
    window.tuning.rows["KP"].set_value(-2.0)
    window.tuning.rows["KP"].set_value(-2.5)
    await window.tuner.flush()
    assert tuning_writes(window) == ["KP,-2.5\r\n"]
    window._tick_ui()
    ack = window.tuning.rows["KP"].ack
    assert ack.text() == "hub -1.50 · sending"
    assert ack.property("tone") == "warn"

    window.fakes.hub.emit(b"E,ACK,900,0.0,0.0,KP:-2.5\n")
    await asyncio.sleep(0.01)
    window._tick_ui()
    assert ack.text() == "hub -2.50"
    assert ack.property("tone") == "ok"


async def test_dropped_write_turns_red(window) -> None:
    await running(window)
    window.tuning.rows["KD"].set_value(-6.0)
    await window.tuner.flush()
    window.tuner.params["KD"].sent_at -= 5  # long ago, never acknowledged
    window._tick_ui()
    assert window.tuning.rows["KD"].ack.text() == "hub -5.00 · no reply"
    assert window.tuning.rows["KD"].ack.property("tone") == "danger"


async def test_tuning_off_for_drift_test_and_back_to_config_after(window) -> None:
    await running(window, b"R,DRIFT_TEST,1\n", "drift_test", drift="straight")
    assert window.tuning.mode == "off"
    assert not window.tuning.rows["KP"].slider.isEnabled()
    window.fakes.hub.status_observable.on_next(StatusFlag(0))
    assert window.tuning.mode == "config"


async def test_tuned_values_carry_into_next_run(window) -> None:
    await running(window)
    window.tuning.rows["KP"].set_value(-2.25)
    window.fakes.hub.status_observable.on_next(StatusFlag(0))
    assert window.current_config().tuning.kp == -2.25


# -- calibration ---------------------------------------------------------------


def test_check_calibration() -> None:
    cal, warning = check_calibration(10, 90)
    assert cal == SensorCalibration(10, 90) and cal.edge == 50 and warning is None
    _, warning = check_calibration(50, 70)
    assert "too high" in warning
    with pytest.raises(ValueError):
        check_calibration(80, 20)


def test_history_recent_window() -> None:
    h = History()
    for t, v in ((0, 90), (500, 12), (1200, 10), (1600, 11)):
        h.add(t, v)
    assert h.recent(0, 1000) == [10, 11]
    assert History().recent(0, 1000) == []


def make_dialog(values: list[float], applied: list):
    async def start() -> bool:
        return True

    async def stop() -> None:
        pass

    return CalibrationDialog(
        start=start,
        stop=stop,
        samples=lambda window_ms: values,
        current=SensorCalibration,
        apply=applied.append,
    )


async def test_calibration_flow(qapp) -> None:
    readings: list[float] = []
    applied: list[SensorCalibration] = []
    d = make_dialog(readings, applied)
    assert await d.start()
    readings[:] = [9, 10, 11, 10, 40, 10]  # median ignores the one bad reading
    assert d.sample("black") == 10
    readings[:] = [91, 90, 89, 90, 90]
    assert d.sample("white") == 90
    assert d.summary.text() == "edge 50 · gap 80"
    d.save()
    assert applied == [SensorCalibration(10, 90)]


async def test_calibration_needs_readings(qapp) -> None:
    d = make_dialog([], [])
    await d.start()
    assert d.sample("black") is None
    assert "No reflection readings yet" in d.status.text()


async def test_calibration_small_gap_warns_but_allows_save(qapp) -> None:
    readings: list[float] = [50] * 10
    d = make_dialog(readings, [])
    await d.start()
    d.sample("black")
    readings[:] = [70] * 10
    d.sample("white")
    assert "too high" in d.summary.text()
    assert d.summary.property("tone") == "warn"
    assert d.save_button.isEnabled()


async def test_calibration_through_main_window(window) -> None:
    output = b"R,CALIBRATE,1\nS,0,7800,120,1\n" + b"".join(
        f"T,{t},0.0,0.0,0.0,12,0,IDLE\n".encode() for t in range(100, 1100, 50)
    )
    await window.conn.connect(HUB)
    window.fakes.program_output[:] = [SCAN_OUTPUT]
    await window.scan_ports()
    window.fakes.hub.status_observable.on_next(StatusFlag(0))
    window.fakes.program_output[:] = [output]
    window.show_calibration()
    d = window._calibration_dialog
    assert await d.start()
    assert window.fakes.hub.ran[-1].endswith("hub_calibrate.py")
    await asyncio.sleep(0.05)
    assert d.sample("black") == 12
    window._tick_ui()
    assert d.live.text() == "Live reflection: 12"
    window.apply_calibration(SensorCalibration(12, 88))
    assert window.current_config().calibration.edge == 50
