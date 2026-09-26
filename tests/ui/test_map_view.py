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


# -- ruler ----------------------------------------------------------------------


def test_measurement_values() -> None:
    from app.ui.map_view import Measurement

    m = Measurement(100.0, 100.0, 400.0, 500.0)
    assert (m.dx_mm, m.dy_mm, m.distance_mm) == (300.0, 400.0, 500.0)
    assert round(m.angle_deg, 1) == 53.1
    assert m.text() == "50.0 cm\nΔx 30.0 · Δy 40.0 cm\n53°"
    assert round(Measurement(0, 0, -100, 0).angle_deg) == 180


def test_ruler_two_clicks_then_restart(qapp) -> None:
    from app.ui.map_view import MapView

    view = MapView()
    view.ruler_click(0, 0)  # ignored by the scene handler while off; direct call still works
    view.set_ruler(True)
    assert view.ruler_button.isChecked()
    view.ruler_click(0, 0)
    assert view.measurement is None and view.ruler_label.isVisible() is False
    view.ruler_click(0, 200)
    assert view.measurement.distance_mm == 200
    assert "20.0 cm" in view.ruler_label.toPlainText()
    view.ruler_click(50, 50)  # third click: a new first point
    assert view.measurement is None
    view.set_ruler(False)
    assert view.measurement is None
    assert len(view.ruler_line.getData()[0] or []) == 0


def test_event_markers_do_not_select_while_measuring(qapp) -> None:
    from app.core.state import EventRecord
    from app.ui.map_view import MapView

    view = MapView()
    picked = []
    view.event_clicked.connect(picked.append)
    view._draw_events([EventRecord("LOST", 0, 10.0, 10.0, 0.0)])
    view.set_ruler(True)
    view._event_clicked(None, view.events.points())
    assert picked == []
    view.set_ruler(False)
    view._event_clicked(None, view.events.points())
    assert len(picked) == 1
