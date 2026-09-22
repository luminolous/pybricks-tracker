"""Event list, map markers, recording from the window, and replay mode."""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

import pytest
from pybricksdev.ble.pybricks import StatusFlag
from PySide6.QtWidgets import QApplication

from app.core.protocol import decode_line
from app.core.recorder import read_session
from app.core.state import EventRecord, RobotState
from app.ui.event_list import EventList
from app.ui.main_window import MainWindow
from app.ui.map_view import MapView, event_position
from app.ui.replay_bar import ReplayBar, fmt_ms
from tests.fakes import HUB, SCAN_OUTPUT, FakeHubs

RUN = (
    b"R,LINE_FOLLOWER,1\nS,0,7810,120,1\n"
    b"T,100,0.0,0.0,0.0,50,0,FOLLOW\nT,1100,100.0,0.0,0.0,48,4,FOLLOW\n"
    b"E,LOST,1500,150.0,0.0\nT,2100,200.0,10.0,90.0,90,120,SEARCH\n"
    b"E,FOUND,2400,210.0,12.0\nE,OBS,3000,220.0,20.0,48\nT,3100,300.0,30.0,90.0,52,-3,FOLLOW\n"
)


def ev(kind: str, t: int = 1000, heading: float = 0.0, detail: str | None = None) -> EventRecord:
    return EventRecord(kind, t, 100.0, 0.0, heading, detail)


@pytest.fixture
async def window(qapp, monkeypatch):
    monkeypatch.setattr("app.ui.main_window.DRAIN_GRACE_S", 0.0)
    fakes = FakeHubs()
    w = MainWindow(connection_factory=fakes.connection)
    w.fakes = fakes
    w.start()
    yield w
    await w.shutdown()
    QApplication.instance().removeEventFilter(w)


async def record_a_run(w) -> None:
    await w.conn.connect(HUB)
    w.fakes.program_output[:] = [SCAN_OUTPUT]
    await w.scan_ports()
    w.fakes.hub.status_observable.on_next(StatusFlag(0))
    w.fakes.program_output[:] = [RUN]
    assert await w.run_program()
    await asyncio.sleep(0.02)
    w.fakes.hub.status_observable.on_next(StatusFlag(0))  # program ends
    await asyncio.sleep(0.05)


# -- widgets -----------------------------------------------------------------


def test_event_list_newest_first_and_appends(qapp) -> None:
    lst = EventList()
    a, b = ev("LOST", 1500), ev("FOUND", 2400)
    lst.set_events([a])
    lst.set_events([a, b])
    assert lst.list.count() == 2
    assert "FOUND" in lst.list.item(0).text() and "2.4s" in lst.list.item(0).text()
    assert lst.count.text() == "2"
    clicked = []
    lst.event_clicked.connect(clicked.append)
    lst._clicked(lst.list.item(1))
    assert clicked == [a]


def test_obstacle_is_projected_ahead(qapp) -> None:
    x, y = event_position(ev("OBS", heading=90.0, detail="48"), sensor_offset_mm=40)
    assert x == pytest.approx(100.0) and y == pytest.approx(88.0)
    assert event_position(ev("LOST"), 40) == (100.0, 0.0)
    assert event_position(ev("OBS", detail="junk"), 40) == (100.0, 0.0)


def test_map_draws_and_selects_events(qapp) -> None:
    view = MapView()
    state = RobotState()
    for line in ("E,LOST,1,10.0,0.0", "E,FOUND,2,20.0,0.0"):
        state.apply(decode_line(line))
    view.refresh(state)
    assert len(view.events.points()) == 2
    picked = []
    view.event_clicked.connect(picked.append)
    view._event_clicked(None, [view.events.points()[1]])
    assert picked == [state.events[1]]
    assert list(view.selection.getData()[0]) == [20.0]


def test_timeline_maps_clicks_to_time(qapp) -> None:
    bar = ReplayBar()
    bar.resize(900, 38)
    bar.set_session(10_000, [(5000, "#ff0000")])
    tl = bar.timeline
    tl.resize(412, 22)
    assert tl._ms(6) == 0 and tl._ms(406) == 10_000 and tl._ms(206) == 5000
    bar.set_position(2500, True)
    assert bar.time.text() == "00:02.5" and bar.play_button.text() == "❚❚"
    assert fmt_ms(75_300) == "01:15.3"


# -- recording and replay through the window --------------------------------------


async def test_run_is_recorded_with_its_final_lines(window, isolated_sessions) -> None:
    await record_a_run(window)
    files = list(isolated_sessions.glob("*_line_follower.jsonl"))
    assert len(files) == 1
    session = read_session(files[0])
    assert session.header["battery_mv"] == 7810
    assert session.records[-1].t_ms == 3100  # last T made it before close
    assert not window.recorder.recording
    assert "saved" in window.console.visible_text()


async def test_live_events_fill_list_and_map(window) -> None:
    await record_a_run(window)
    window._tick_ui()
    assert window.event_list.list.count() == 3
    assert len(window.map.events.points()) == 3


async def test_replay_shows_same_trail_and_locks_live_controls(window, isolated_sessions) -> None:
    await record_a_run(window)
    live_trail = list(window.state.trail)
    path = next(isolated_sessions.glob("*.jsonl"))
    assert window.open_replay(path)
    window._tick_ui()
    assert window.view_state.trail == live_trail
    assert not window.replay_bar.isHidden()
    assert window.run_state.text() == "REPLAY"
    assert window.run_blocker() == "Exit replay to run."
    assert not window.scan_button.isEnabled()
    assert window.tuning.mode == "replay"
    assert window.rec_label.text().startswith("PLAY")


async def test_clicking_an_event_seeks_replay(window, isolated_sessions) -> None:
    await record_a_run(window)
    window.open_replay(next(isolated_sessions.glob("*.jsonl")))
    found = next(e for e in window._replay.state.events if e.kind == "FOUND")
    window._event_selected(found)
    assert window._replay.position_ms == 2400
    assert [p.t_ms for p in window.view_state.trail] == [100, 1100, 2100]
    window._tick_ui()
    assert window.readouts["state"].text() == "SEARCH"


async def test_exit_replay_restores_live(window, isolated_sessions) -> None:
    await record_a_run(window)
    window.open_replay(next(isolated_sessions.glob("*.jsonl")))
    window.exit_replay()
    assert window.replay_bar.isHidden()
    assert window.view_state is window.state
    assert window.run_blocker() is None
    assert window.tuning.mode == "config"


async def test_bad_session_is_reported(window, tmp_path) -> None:
    bad = tmp_path / "x.jsonl"
    bad.write_text("nope\n", encoding="utf-8")
    assert not window.open_replay(bad)
    assert "no session header" in window.console.visible_text()


async def test_replay_refused_while_running(window) -> None:
    await window.conn.connect(HUB)
    await window.conn.run_file(Path("x.py"))
    assert not window.open_replay(Path("whatever.jsonl"))
    assert "Stop the running program" in window.console.visible_text()


def test_marker_symbol_distance_matches_heading() -> None:
    x, y = event_position(ev("OBS", heading=180.0, detail="10"), 0)
    assert math.isclose(x, 90.0) and math.isclose(y, 0.0, abs_tol=1e-9)
