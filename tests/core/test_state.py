"""PortScan accumulation from decoded P lines."""

from __future__ import annotations

from app.core.protocol import DeviceKind, Ready, decode_line
from app.core.state import PortScan, Pose, RobotState, TelemetryWatch

SCAN_OUTPUT = ["R,SCAN,1", "P,A,0", "P,B,0", "P,C,48", "P,D,61", "P,E,62", "P,F,48", "P,DONE,0"]


def run_scan(lines: list[str]) -> PortScan:
    scan = PortScan()
    for line in lines:
        scan.apply(decode_line(line))
    return scan


def test_full_scan() -> None:
    scan = run_scan(SCAN_OUTPUT)
    assert scan.done
    assert scan.missing_ports == []
    assert scan.device("A").kind is DeviceKind.EMPTY
    assert scan.device("C").kind is DeviceKind.MOTOR
    assert scan.device("D").kind is DeviceKind.COLOR_SENSOR
    assert scan.device("E").kind is DeviceKind.ULTRASONIC_SENSOR


def test_rescan_shows_unplugged_sensor() -> None:
    scan = run_scan(SCAN_OUTPUT)
    scan.reset()
    for line in ["P,A,0", "P,B,0", "P,C,48", "P,D,0", "P,E,62", "P,F,48", "P,DONE,0"]:
        scan.apply(decode_line(line))
    assert scan.device("D").kind is DeviceKind.EMPTY


def test_lost_line_shows_as_missing_port() -> None:
    scan = run_scan([line for line in SCAN_OUTPUT if not line.startswith("P,E")])
    assert scan.done
    assert scan.missing_ports == ["E"]
    assert scan.device("E") is None


def test_ignores_non_scan_records() -> None:
    scan = PortScan()
    assert not scan.apply(Ready(mode="SCAN", proto_version=1))
    assert not scan.apply(None)
    assert scan.device_ids == {}


# -- TelemetryWatch -----------------------------------------------------------


def test_watch_is_quiet_until_armed() -> None:
    watch = TelemetryWatch()
    assert not watch.lost(100.0)
    assert watch.silence_s(100.0) == 0.0


def test_watch_trips_after_two_seconds_of_silence() -> None:
    watch = TelemetryWatch()
    watch.arm(10.0)
    watch.saw_telemetry(10.5)
    assert not watch.lost(12.4)
    assert watch.lost(12.5)
    assert watch.silence_s(12.5) == 2.0
    watch.saw_telemetry(12.6)
    assert not watch.lost(12.7)


def test_disarmed_watch_never_trips() -> None:
    watch = TelemetryWatch()
    watch.arm(0.0)
    watch.disarm()
    assert not watch.lost(60.0)


# -- RobotState ---------------------------------------------------------------


def feed(state: RobotState, *lines: str) -> None:
    for line in lines:
        state.apply(decode_line(line))


def test_trail_waits_for_imu_ready() -> None:
    state = RobotState()
    feed(state, "S,0,7800,150,0", "T,50,0.0,0.0,0.0,50,0,IDLE")
    assert state.trail == []
    assert state.pose == Pose(50, 0.0, 0.0, 0.0)
    feed(state, "S,600,7800,150,1", "T,650,10.0,2.0,5.0,50,0,FOLLOW")
    assert state.trail == [Pose(650, 10.0, 2.0, 5.0)]
    assert state.battery_mv == 7800


def test_version_moves_on_every_change() -> None:
    state = RobotState()
    v0 = state.version
    feed(state, "S,0,7800,150,1")
    feed(state, "T,50,1.0,0.0,0.0,50,0,FOLLOW")
    assert state.version == v0 + 2
    assert not state.apply(decode_line("P,A,0"))
    assert state.version == v0 + 2


def test_reset_and_reset_origin() -> None:
    state = RobotState()
    feed(state, "S,0,7800,150,1", "T,50,1.0,0.0,0.0,50,0,FOLLOW")
    state.reset_origin()
    assert state.trail == [] and state.imu_ready
    state.reset()
    assert state.pose is None and not state.imu_ready
    assert state.battery_mv == 7800  # battery survives a new run


def test_trail_is_capped() -> None:
    state = RobotState(max_points=3)
    feed(state, "S,0,7800,150,1")
    for i in range(5):
        feed(state, f"T,{i},{i}.0,0.0,0.0,50,0,FOLLOW")
    assert [p.x_mm for p in state.trail] == [2.0, 3.0, 4.0]
