"""Session recording round trip and replay."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.core.config import RobotConfig
from app.core.protocol import decode_line
from app.core.recorder import (
    SessionError,
    SessionRecorder,
    read_session,
    record_from_json,
    record_to_json,
)
from app.core.replay import Replay
from app.core.state import RobotState

LINES = [
    "T,40,0.0,0.0,0.0,50,0,IDLE",  # before the S line: buffered until the header
    "S,50,7810,120,1",
    "T,100,0.0,0.0,0.0,50,0,FOLLOW",
    "D,250,210,4,91,62,58,11",
    "T,1100,100.0,0.0,0.0,48,4,FOLLOW",
    "E,LOST,1500,150.0,0.0",
    "T,2100,200.0,10.0,5.0,90,120,SEARCH",
    "E,ACK,2200,200.0,10.0,KP:-2",
    "E,FOUND,2400,210.0,12.0",
    "T,3100,300.0,30.0,10.0,52,-3,FOLLOW",
    "E,OBS,3200,310.0,31.0,48",
]
RECORDS = [decode_line(line) for line in LINES]


def record(tmp_path) -> SessionRecorder:
    rec = SessionRecorder(tmp_path)
    rec.start(
        "line_follower", RobotConfig(), started_at=datetime(2026, 9, 23, 10, 4, 11, tzinfo=UTC)
    )
    for r in RECORDS:
        rec.write(r)
    return rec


def test_every_record_type_round_trips() -> None:
    for r in RECORDS:
        assert record_from_json(json.loads(json.dumps(record_to_json(r)))) == r


def test_header_first_with_battery_and_config(tmp_path) -> None:
    rec = record(tmp_path)
    path = rec.close()
    assert path.name == "20260923-100411_line_follower.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    assert header["type"] == "header" and header["version"] == 1
    assert header["started_at"] == "2026-09-23T10:04:11Z"
    assert header["battery_mv"] == 7810
    assert header["config"]["ports"]["C"]["role"] == "wheel_left"
    assert header["tuning"]["kp"] == -1.8
    assert json.loads(lines[1])["t"] == 40  # buffered record kept its place
    assert len(lines) == 1 + len(RECORDS)


def test_header_written_even_without_status(tmp_path) -> None:
    rec = SessionRecorder(tmp_path)
    rec.start("calibrate", RobotConfig())
    rec.write(RECORDS[0])
    session = read_session(rec.close())
    assert session.header["battery_mv"] is None
    assert session.records == [RECORDS[0]]


def test_read_back_equals_written(tmp_path) -> None:
    session = read_session(record(tmp_path).close())
    assert session.mode == "line_follower"
    assert session.records == RECORDS
    assert session.skipped == 0


def test_bad_lines_are_skipped_and_counted(tmp_path) -> None:
    path = record(tmp_path).close()
    with path.open("a", encoding="utf-8") as f:
        f.write("{not json\n")
        f.write('{"type":"T","t":"x"}\n')
        f.write('{"type":"Q"}\n')
    assert read_session(path).skipped == 3


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "no session header"),
        ('{"type":"T"}\n', "no session header"),
        ('{"type":"header","version":9}\n', "session version 9"),
    ],
)
def test_unreadable_sessions(tmp_path, content: str, message: str) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SessionError, match=message):
        read_session(path)


def test_replay_matches_live_state(tmp_path) -> None:
    live = RobotState()
    for r in RECORDS:
        live.apply(r)
    replay = Replay(read_session(record(tmp_path).close()))
    replay.seek(replay.end_ms)
    assert replay.state.trail == live.trail  # roadmap M7: same trail shape
    assert replay.state.events == live.events
    assert [e.kind for e in replay.events] == ["LOST", "FOUND", "OBS"]  # no ACK


def test_replay_seek_back_and_forth(tmp_path) -> None:
    replay = Replay(read_session(record(tmp_path).close()))
    assert (replay.start_ms, replay.end_ms, replay.duration_ms) == (40, 3200, 3160)
    replay.seek(1600)
    assert [p.t_ms for p in replay.state.trail] == [100, 1100]
    assert [e.kind for e in replay.state.events] == ["LOST"]
    replay.seek(500)  # backwards rebuilds
    assert [p.t_ms for p in replay.state.trail] == [100]
    assert replay.state.events == []


def test_replay_playback_speed_and_end(tmp_path) -> None:
    replay = Replay(read_session(record(tmp_path).close()))
    replay.advance(1.0)
    assert replay.position_ms == replay.start_ms  # paused: nothing moves
    replay.play()
    replay.speed = 2.0
    replay.advance(0.5)
    assert replay.position_ms == replay.start_ms + 1000
    replay.advance(10)
    assert replay.at_end and not replay.playing
    replay.play()  # from the end, play restarts at the top
    assert replay.position_ms == replay.start_ms


def test_state_events_keep_heading_and_skip_ack() -> None:
    state = RobotState()
    for r in RECORDS:
        state.apply(r)
    obs = state.events[-1]
    assert obs.kind == "OBS" and obs.heading_deg == 10.0 and obs.detail == "48"
    assert "ACK" not in [e.kind for e in state.events]
    assert obs.describe() == "Obstacle at 48 mm"


def test_runs_in_the_same_second_get_their_own_files(tmp_path) -> None:
    stamp = datetime(2026, 9, 23, 10, 4, 11, tzinfo=UTC)
    rec = SessionRecorder(tmp_path)
    paths = []
    for _ in range(3):
        rec.start("line_follower", RobotConfig(), started_at=stamp)
        paths.append(rec.close())
    assert [p.name for p in paths] == [
        "20260923-100411_line_follower.jsonl",
        "20260923-100411_line_follower-2.jsonl",
        "20260923-100411_line_follower-3.jsonl",
    ]
