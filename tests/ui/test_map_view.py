"""MapView drawing from RobotState. Offscreen, no hub."""

from __future__ import annotations

import pytest

from app.core.protocol import decode_line
from app.core.state import RobotState
from app.ui.map_view import MARKER_NOSE_MM, HeadingTape, MapView, marker_polygon


def state_with(*lines: str) -> RobotState:
    state = RobotState()
    for line in lines:
        state.apply(decode_line(line))
    return state


def test_marker_points_along_heading() -> None:
    xs, ys = marker_polygon(100.0, 0.0, 90.0)  # facing +y (left)
    assert xs[0] == pytest.approx(100.0)
    assert ys[0] == pytest.approx(MARKER_NOSE_MM)
    assert (xs[0], ys[0]) == (xs[-1], ys[-1])  # closed outline


def test_nothing_drawn_before_imu_ready(qapp) -> None:
    view = MapView()
    view.refresh(state_with("S,0,7800,150,0", "T,50,5.0,0.0,0.0,50,0,IDLE"))
    assert len(view.trail.getData()[0] or []) == 0
    assert view.tape.heading_deg is None


def test_trail_robot_sensor_and_tape(qapp) -> None:
    view = MapView()
    view.sensor_offset_mm = 40
    state = state_with(
        "S,0,7800,150,1",
        "T,50,0.0,0.0,0.0,50,0,FOLLOW",
        "T,100,100.0,0.0,0.0,50,0,FOLLOW",
    )
    view.refresh(state)
    xs, _ = view.trail.getData()
    assert list(xs) == [0.0, 100.0]
    sx, sy = view.sensor.getData()
    assert sx[0] == pytest.approx(140.0) and sy[0] == pytest.approx(0.0)
    assert view.tape.heading_deg == 0.0


def test_follow_centres_on_robot_and_manual_pan_stops_it(qapp) -> None:
    view = MapView()
    changes = []
    view.follow_changed.connect(changes.append)
    view.refresh(state_with("S,0,7800,150,1", "T,50,2000.0,1000.0,0.0,50,0,FOLLOW"))
    (x0, x1), (y0, y1) = view.plot.getViewBox().viewRange()
    assert (x0 + x1) / 2 == pytest.approx(2000.0, abs=1)
    assert (y0 + y1) / 2 == pytest.approx(1000.0, abs=1)
    view._manual_range()
    assert not view.follow and changes == [False]


def test_fit_includes_origin_and_trail(qapp) -> None:
    view = MapView()
    state = state_with("S,0,7800,150,1", "T,50,1500.0,0.0,0.0,50,0,FOLLOW")
    view.fit(state)
    (x0, x1), _ = view.plot.getViewBox().viewRange()
    assert x0 <= 0 and x1 >= 1500
    assert not view.follow


def test_redraw_skipped_when_unchanged(qapp) -> None:
    view = MapView()
    state = state_with("S,0,7800,150,1", "T,50,10.0,0.0,0.0,50,0,FOLLOW")
    view.refresh(state)
    view.trail.setData([], [])  # would be restored by a real redraw
    view.refresh(state)
    assert len(view.trail.getData()[0] or []) == 0


def test_tape_paints_without_errors(qapp) -> None:
    tape = HeadingTape()
    tape.resize(600, 30)
    tape.grab()
    tape.set_heading(-725.4)
    tape.grab()
