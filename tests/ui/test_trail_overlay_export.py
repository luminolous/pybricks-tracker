"""Trail colouring, overlays with metrics, and export from the window."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest
from pybricksdev.ble.pybricks import StatusFlag
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.core.config import RobotConfig, TuningParams
from app.core.protocol import decode_line
from app.core.recorder import SessionRecorder
from app.core.state import Pose, RobotState
from app.ui import theme
from app.ui.main_window import MainWindow
from app.ui.map_view import MapView, scale_bar_length
from app.ui.trail_colors import (
    COLOR_PALETTE,
    GRADIENT_BINS,
    SENSED_DARK,
    segment_masks,
    trail_bins,
)
from tests.fakes import HUB, SCAN_OUTPUT, FakeHubs


def npoints(curve) -> int:
    data = curve.getData()[0]
    return 0 if data is None else len(data)


def pose(i: int, speed: float = 0, steer: int = 0, hsv=None) -> Pose:
    return Pose(i * 50, float(i), 0.0, 0.0, 50, steer, speed, hsv)


# -- colouring -------------------------------------------------------------------


def test_plain_is_one_bin_without_legend() -> None:
    bins, palette, text = trail_bins([pose(0), pose(1)], "plain")
    assert list(bins) == [0, 0] and palette == [theme.TRAIL] and text is None


def test_speed_bins_run_slow_to_fast() -> None:
    trail = [pose(i, speed=s) for i, s in enumerate((0, 50, 100, 1000))]
    bins, palette, text = trail_bins(trail, "speed")
    assert bins[0] == 0 and bins[-1] == GRADIENT_BINS - 1
    assert list(bins) == sorted(bins)
    assert len(palette) == GRADIENT_BINS and text.startswith("speed 0–")


def test_steer_uses_magnitude() -> None:
    bins, _, _ = trail_bins([pose(0, steer=-120), pose(1, steer=120), pose(2, steer=0)], "steer")
    assert bins[0] == bins[1] and bins[2] == 0


def test_color_bins_dark_neutral_and_hue() -> None:
    trail = [pose(0, hsv=(0, 90, 10)), pose(1, hsv=(0, 5, 90)), pose(2, hsv=(125, 90, 90))]
    bins, palette, _ = trail_bins(trail + [pose(3)], "color")
    assert palette[bins[0]] == SENSED_DARK  # black stays visible on the dark map
    assert palette[bins[1]] == theme.TRAIL
    assert bins[2] == 2 + 4  # 125 deg in 30 deg bins
    assert palette[bins[3]] == theme.TRAIL  # no reading yet
    assert len(palette) == len(COLOR_PALETTE)


def test_segment_masks_colour_by_destination_point() -> None:
    masks = segment_masks(np.array([0, 1, 1, 0]), 2)
    assert list(masks[0]) == [False, False, True, False]
    assert list(masks[1]) == [True, True, False, False]


def test_scale_bar_picks_round_lengths() -> None:
    assert scale_bar_length(1.0) == 100  # 100 px is closest to 110
    assert scale_bar_length(10.0) == 1000
    assert scale_bar_length(0.1) == 10


def test_map_draws_one_curve_per_used_bin(qapp) -> None:
    view = MapView()
    state = RobotState()
    for line in (
        "S,0,0,0,1",
        "T,0,0.0,0.0,0.0,50,0,F",
        "T,50,1.0,0.0,0.0,50,0,F",
        "T,100,50.0,0.0,0.0,50,0,F",
    ):
        state.apply(decode_line(line))
    view.set_trail_mode("speed")
    view.refresh(state)
    drawn = [c for c in view.trail_bins if npoints(c)]
    assert len(drawn) == 2  # slow and fast segments
    assert npoints(view.trail) == 0
    assert view.legend.mode_line.text().startswith("speed")


def test_png_export_writes_an_image(qapp, tmp_path) -> None:
    view = MapView()
    view.resize(600, 500)
    out = tmp_path / "map.png"
    view.render_png(out)
    assert not QImage(str(out)).isNull()


# -- window: overlays, acceptance-style comparison, export ---------------------------


def record(tmp_path, kp: float, name: str, xs: tuple[float, ...]):
    rec = SessionRecorder(tmp_path / name)
    rec.start("line_follower", RobotConfig(tuning=TuningParams(kp=kp)))
    rec.write(decode_line("S,0,7800,120,1"))
    for i, x in enumerate(xs):
        rec.write(decode_line(f"T,{i * 1000},{x},0.0,0.0,{50 + i},0,FOLLOW"))
    return rec.close()


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


async def test_two_runs_at_different_kp_side_by_side(window, tmp_path) -> None:
    a = record(tmp_path, -1.2, "a", (0.0, 100.0, 300.0))
    b = record(tmp_path, -2.4, "b", (0.0, 200.0))
    assert window.add_overlay(a) and window.add_overlay(b)
    assert not window.add_overlay(a)  # same run twice is ignored
    window._tick_ui()
    rows = window.map.legend._structure
    assert [text.split(" · ")[1] for _, text in rows[1:]] == ["KP -1.20", "KP -2.40"]
    assert rows[1][0] != rows[2][0]  # distinct colours
    assert window.overlay_button.text() == "Overlay\n2"
    cells = [c.text() for c in window.map.legend._cells[1]]
    assert cells[1] == "0.30 m"
    window.clear_overlays()
    assert window.map.overlay_curves == [] and window.overlay_button.text() == "Overlay\n0"


async def test_trail_mode_from_the_window(window) -> None:
    window.set_trail_mode("steer")
    assert window.map.trail_mode == "steer"
    assert window.trail_button.text() == "Trail\nsteer"


async def test_export_needs_a_run_first(window, tmp_path) -> None:
    assert not window.export_csv(tmp_path / "x.csv")
    assert "Record or replay a run" in window.console.visible_text()


async def test_export_last_recording(window, tmp_path) -> None:
    await window.conn.connect(HUB)
    window.fakes.program_output[:] = [SCAN_OUTPUT]
    await window.scan_ports()
    window.fakes.hub.status_observable.on_next(StatusFlag(0))
    window.fakes.program_output[:] = [
        b"R,LINE_FOLLOWER,1\nS,0,7800,120,1\nT,100,0.0,0.0,0.0,50,0,FOLLOW\n"
    ]
    await window.run_program()
    await asyncio.sleep(0.02)
    window.fakes.hub.status_observable.on_next(StatusFlag(0))
    await asyncio.sleep(0.05)
    assert window.export_source() is not None
    assert window.export_csv(tmp_path / "run.csv")
    assert (tmp_path / "run.csv").read_text(encoding="utf-8").count("\n") == 2
    assert window.export_jsonl(tmp_path / "run.jsonl")
    window.export_png(tmp_path / "map.png")
    assert (tmp_path / "map.png").stat().st_size > 0


async def test_replay_is_the_export_source(window, tmp_path) -> None:
    path = record(tmp_path, -1.5, "r", (0.0, 10.0))
    window.open_replay(path)
    assert window.export_source() == path
    assert window._current_run_label().endswith("KP -1.50")
