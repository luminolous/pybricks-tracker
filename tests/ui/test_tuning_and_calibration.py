"""M6: live tuning with acknowledgements, and the calibration dialog."""

from __future__ import annotations

import asyncio
from pathlib import Path

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
    return [
        c for c in w.fakes.hub.written if c.split(",")[0] in ("KP", "KD", "SPD", "INNER", "SRCH")
    ]


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
    assert panel.values() == {
        "kp": -3.0,
        "ki": 0.0,
        "kd": -6.0,
        "base_speed_mm_s": 120,
        "inner_pct": 20,
        "inner_min_pct": -40,
        "inner_ramp_ms": 400,
        "search_deg_s": 60,
        "teleop_turn_deg_s": 180,
        "drift_speed_mm_s": 150,
        "drift_turn_deg_s": 90,
        "obstacle_threshold_mm": 50,
        "finish_mm": 0,
        "route_lock_deg": 20,
        "route": "",
    }
    assert panel.rows["SPD"].slider.value() == 24


def test_modes_enable_and_hint(qapp) -> None:
    panel = TuningPanel()
    for mode, enabled in (("config", True), ("waiting", False), ("live", True), ("off", False)):
        panel.set_mode(mode)
        assert panel.rows["KD"].slider.isEnabled() is enabled

    panel.set_mode("config")
    panel.set_open("route", True)
    groups = {
        "line": {"KP", "KI", "KD", "SPD", "INNER", "IMIN", "RAMP", "SRCH", "THR", "FIN", "LOCK"},
        "teleop": {"SPD", "TURN"},
        "drift": {"DSPD", "DTRN"},
    }
    for group, keys in groups.items():
        panel.group_buttons[group].click()
        assert panel.group == group
        shown = {k for k, row in panel.rows.items() if not row.slider.isHidden()}
        assert shown == keys


def test_line_sections_fold_with_a_summary(qapp) -> None:
    panel = TuningPanel()
    panel.set_values(TuningParams())  # the window always fills it from the config
    route = panel.sections["route"]
    assert not route.isChecked()  # folded at start: the event list keeps its room
    assert panel.rows["THR"].slider.isHidden() and panel.route.isHidden()
    assert route.text() == "▸ Route   THR 50 · FIN 0 · LOCK 20 · no route"
    pid = panel.sections["pid"]
    assert pid.text() == "▾ PID"  # open: no summary
    pid.click()
    assert panel.rows["KP"].slider.isHidden()
    panel.rows["KP"].set_value(-2.0)
    assert pid.text() == "▸ PID   KP -2.00 · KI 0.00 · KD -5.00"
    route.click()
    assert not panel.rows["LOCK"].slider.isHidden() and not panel.route.isHidden()
    panel.set_group("teleop")  # sections belong to the line group only
    assert pid.isHidden()
    assert not panel.rows["SPD"].slider.isHidden()


def test_route_editor(qapp) -> None:
    panel = TuningPanel()
    seen = []
    panel.route_changed.connect(seen.append)
    editor = panel.route
    for turn in "RLL":
        editor.add_buttons[turn].click()
    editor.add_buttons["R"].click()
    assert editor.route() == "RLLR" and seen[-1] == "RLLR"
    editor.chips[1].click()  # cycles L -> R -> S -> L
    assert editor.route() == "RRLR"
    editor.chips[1].click()
    assert editor.route() == "RSLR"
    editor.chips[1].click()
    assert editor.route() == "RLLR"
    editor.chips[1].click()
    editor.add_buttons[""].click()  # remove last
    assert panel.values()["route"] == "RRL"
    editor.add_buttons["S"].click()
    assert panel.values()["route"] == "RRLS"
    for _ in range(20):
        editor.add_buttons["L"].click()
    assert len(editor.route()) == 10  # MAX_ROUTE_STEPS
    assert not editor.add_buttons["L"].isEnabled()


def test_route_is_line_only_and_locked_while_running(qapp) -> None:
    panel = TuningPanel()
    panel.set_values(TuningParams(route="RL"))
    assert panel.route.route() == "RL"
    panel.set_group("teleop")
    assert panel.route.isHidden()
    panel.set_group("line")
    panel.set_mode("live")
    assert not panel.route.chips[0].isEnabled()
    assert not panel.route.add_buttons["L"].isEnabled()
    panel.route.set_progress(1)
    assert panel.route.chips[0].property("step") == "done"
    assert panel.route.chips[1].property("step") == "next"


def test_group_buttons_lock_while_a_program_runs(qapp) -> None:
    panel = TuningPanel()
    panel.set_group("teleop")
    panel.set_mode("speed")
    assert not panel.group_buttons["line"].isEnabled()
    assert panel.rows["TURN"].slider.isEnabled()
    panel.set_mode("config")
    assert panel.group_buttons["drift"].isEnabled()


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


async def test_readout_shows_the_speed_the_hub_acknowledged(window) -> None:
    await running(window)
    window._tick_ui()
    assert window.readouts["speed"].text() == "50"
    assert window.readouts["turn"].text() == "20 / 60"
    window.tuning.rows["SPD"].set_value(100)
    await window.tuner.flush()
    window._tick_ui()
    assert window.readouts["speed"].text() == "50"  # not acknowledged yet
    window.fakes.hub.emit(b"E,ACK,900,0.0,0.0,SPD:100.0\n")
    await asyncio.sleep(0.01)
    window._tick_ui()
    assert window.readouts["speed"].text() == "100"
    assert window.readouts["turn"].text() == "20 / 60"


async def test_pivot_and_search_are_sent_live_and_acknowledged(window) -> None:
    await running(window)
    assert window.tuning.group == "line"
    window.tuning.rows["INNER"].set_value(35)
    window.tuning.rows["SRCH"].set_value(100)
    await window.tuner.flush()
    assert sorted(tuning_writes(window)) == ["INNER,35\r\n", "SRCH,100\r\n"]
    window.fakes.hub.emit(b"E,ACK,900,0.0,0.0,INNER:35.0\nE,ACK,901,0.0,0.0,SRCH:100.0\n")
    await asyncio.sleep(0.01)
    window._tick_ui()
    assert window.tuning.rows["INNER"].ack.text() == "hub 35"
    assert window.readouts["turn"].text() == "35 / 100"


async def test_teleop_only_knobs_are_never_sent_to_the_hub(window) -> None:
    await running(window)
    window.tuning.rows["TURN"].set_value(90)  # hidden in the line group, still no write
    await window.tuner.flush()
    assert not [c for c in window.fakes.hub.written if c.startswith(("TURN", "DSPD", "DTRN"))]


async def test_dropped_write_turns_red(window) -> None:
    await running(window)
    window.tuning.rows["KD"].set_value(-6.0)
    await window.tuner.flush()
    window.tuner.params["KD"].sent_at -= 5  # long ago, never acknowledged
    window._tick_ui()
    assert window.tuning.rows["KD"].ack.text() == "hub -5.00 · no reply"
    assert window.tuning.rows["KD"].ack.property("tone") == "danger"


async def test_tuning_off_for_drift_test_and_back_to_config_after(window) -> None:
    window.tuning.rows["DSPD"].set_value(100)
    await running(window, b"R,DRIFT_TEST,1\n", "drift_test", drift="straight")
    assert window.tuning.mode == "off"
    assert window.tuning.group == "drift"
    assert not window.tuning.rows["DSPD"].slider.isEnabled()  # locked for the whole test
    assert "STRAIGHT_SPEED = 100.0" in Path(window.fakes.hub.ran[-1]).read_text(encoding="utf-8")
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


async def test_route_runs_and_shows_progress(window) -> None:
    for turn in "RLLR":
        window.tuning.route.add_buttons[turn].click()
    await running(window)
    assert 'ROUTE = "RLLR"' in Path(window.fakes.hub.ran[-1]).read_text(encoding="utf-8")
    window._tick_ui()
    assert window.tuning.route.chips[0].property("step") == "next"
    window.fakes.hub.emit(b"E,TURN,5000,300.0,0.0,1/4 R\nE,TURN,9000,300.0,-400.0,2/4 L\n")
    await asyncio.sleep(0.01)
    window._tick_ui()
    assert [c.property("step") for c in window.tuning.route.chips] == ["done", "done", "next", ""]
    assert window.event_list.list.count() >= 2


async def test_fin_is_sent_live(window) -> None:
    await running(window)
    window.tuning.rows["FIN"].set_value(600)
    window.tuning.rows["THR"].set_value(80)
    await window.tuner.flush()
    assert sorted(c for c in window.fakes.hub.written if c.startswith(("FIN", "THR"))) == [
        "FIN,600\r\n",
        "THR,80\r\n",
    ]
