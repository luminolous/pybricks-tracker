"""Run metrics, overlay loading and CSV/JSONL export."""

from __future__ import annotations

import csv
import math

import pytest

from app.core.analysis import run_metrics
from app.core.config import RobotConfig, SensorCalibration, TuningParams
from app.core.export import CSV_COLUMNS, copy_session, session_to_csv
from app.core.overlay import OVERLAY_COLORS, load_overlay, next_color
from app.core.protocol import decode_line
from app.core.recorder import SessionError, SessionRecorder, read_session
from app.core.state import RobotState

LINES = [
    "S,0,7800,120,1",
    "T,0,0.0,0.0,0.0,40,0,FOLLOW",
    "D,10,120,80,60,62,58,11",
    "T,1000,300.0,0.0,0.0,60,10,FOLLOW",
    "E,LOST,1200,310.0,0.0",
    "T,2000,300.0,400.0,90.0,50,-5,SEARCH",
    "E,LOST,2500,300.0,410.0",
]


def feed(state: RobotState) -> RobotState:
    for line in LINES:
        state.apply(decode_line(line))
    return state


def recorded(tmp_path, kp: float = -1.8, name: str = "run") -> tuple:
    config = RobotConfig(
        tuning=TuningParams(kp=kp), calibration=SensorCalibration(black=10, white=90)
    )
    rec = SessionRecorder(tmp_path / name)
    rec.start("line_follower", config)
    for line in LINES:
        rec.write(decode_line(line))
    return rec.close(), config


def test_run_metrics_from_running_sums() -> None:
    m = run_metrics(feed(RobotState()), edge=50)
    assert m.duration_s == 2.0
    assert m.path_mm == 700.0  # 300 then 400
    direct = math.sqrt(((40 - 50) ** 2 + (60 - 50) ** 2 + (50 - 50) ** 2) / 3)
    assert m.rms_error == pytest.approx(direct)
    assert m.lost_count == 2


def test_empty_run_metrics() -> None:
    m = run_metrics(RobotState(), edge=50)
    assert (m.duration_s, m.path_mm, m.rms_error, m.lost_count) == (0.0, 0.0, 0.0, 0)


def test_overlay_uses_the_runs_own_calibration(tmp_path) -> None:
    path, _ = recorded(tmp_path, kp=-1.2)
    overlay = load_overlay(path, OVERLAY_COLORS[0])
    assert overlay.label.endswith("KP -1.20")
    assert len(overlay.trail) == 3
    assert overlay.metrics.path_mm == 700.0
    # edge from the header (10+90)/2 = 50, not the app's default 52
    assert overlay.metrics.rms_error == pytest.approx(math.sqrt(200 / 3))


def test_overlay_colours_do_not_repeat(tmp_path) -> None:
    path, _ = recorded(tmp_path)
    first = load_overlay(path, next_color([]))
    assert next_color([first]) == OVERLAY_COLORS[1]


def test_bad_overlay_raises_session_error(tmp_path) -> None:
    bad = tmp_path / "x.jsonl"
    bad.write_text("nope", encoding="utf-8")
    with pytest.raises(SessionError):
        load_overlay(bad, OVERLAY_COLORS[0])


def test_csv_joins_latest_detail(tmp_path) -> None:
    path, _ = recorded(tmp_path)
    out = tmp_path / "out" / "run.csv"
    assert session_to_csv(read_session(path), out) == 3
    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    assert tuple(rows[0]) == CSV_COLUMNS
    assert rows[1][CSV_COLUMNS.index("hue")] == ""  # no D line yet
    second = dict(zip(CSV_COLUMNS, rows[2], strict=True))
    assert second["x_mm"] == "300.0" and second["hue"] == "120" and second["dt_ms"] == "11"


def test_copy_session(tmp_path) -> None:
    path, _ = recorded(tmp_path)
    out = tmp_path / "copy" / "run.jsonl"
    copy_session(path, out)
    assert out.read_bytes() == path.read_bytes()
    copy_session(out, out)  # same file: no error
