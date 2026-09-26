"""Port role validation rules from ui-spec.md."""

from __future__ import annotations

import pytest

from app.core.config import (
    DEFAULT_ASSIGNMENTS,
    ConfigError,
    Direction,
    PortAssignment,
    RobotConfig,
    RobotGeometry,
    Role,
    SensorCalibration,
    TuningParams,
    validate_ports,
)
from app.core.protocol import DeviceKind

M = DeviceKind.MOTOR
EMPTY = DeviceKind.EMPTY
DEFAULT_DEVICES = {  # the real robot
    "A": M,
    "B": DeviceKind.ULTRASONIC_SENSOR,
    "C": EMPTY,
    "D": M,
    "E": EMPTY,
    "F": DeviceKind.COLOR_SENSOR,
}


def with_(port: str, role: Role) -> dict[str, PortAssignment]:
    return {**DEFAULT_ASSIGNMENTS, port: PortAssignment(role, Direction.CLOCKWISE)}


def test_default_robot_is_valid() -> None:
    assert validate_ports(DEFAULT_ASSIGNMENTS, DEFAULT_DEVICES) is None


def test_requires_scan() -> None:
    assert validate_ports(DEFAULT_ASSIGNMENTS, {}) == "Scan ports before running."


def test_role_on_empty_port() -> None:
    error = validate_ports(with_("C", Role.AUX_MOTOR), DEFAULT_DEVICES)
    assert error == "Port C is empty but has the role aux motor."


def test_wheel_must_be_on_motor_port() -> None:
    assignments = {**with_("A", Role.UNUSED), "F": PortAssignment(Role.WHEEL_LEFT)}
    assert validate_ports(assignments, DEFAULT_DEVICES) == "Port F: left wheel needs a motor."


def test_exactly_one_left_wheel() -> None:
    error = validate_ports(with_("A", Role.UNUSED), DEFAULT_DEVICES)
    assert error == "Assign exactly one left wheel (now 0)."


def test_two_right_wheels_rejected() -> None:
    devices = {**DEFAULT_DEVICES, "C": M}
    error = validate_ports(with_("C", Role.WHEEL_RIGHT), devices)
    assert error == "Assign exactly one right wheel (now 2)."


def test_at_most_one_line_sensor() -> None:
    devices = {**DEFAULT_DEVICES, "E": DeviceKind.COLOR_SENSOR}
    error = validate_ports(with_("E", Role.LINE_SENSOR), devices)
    assert error == "Assign at most one line sensor."


def test_unplugged_sensor_after_rescan() -> None:
    devices = {**DEFAULT_DEVICES, "F": EMPTY}
    assert validate_ports(DEFAULT_ASSIGNMENTS, devices) == "Port F is empty but has the role line."


# -- RobotConfig JSON ---------------------------------------------------------


def test_json_roundtrip(tmp_path) -> None:
    config = RobotConfig(
        geometry=RobotGeometry(wheel_diameter_mm=55.2, axle_track_mm=118.0),
        tuning=TuningParams(kp=-2.0, obstacle_threshold_mm=80, route="RLLR", finish_mm=600),
        calibration=SensorCalibration(black=10, white=90),
    )
    path = tmp_path / "presets" / "robot.json"
    config.save(path)
    assert RobotConfig.load(path) == config


def test_default_config_matches_claude_md() -> None:
    config = RobotConfig()
    # the real wiring (2026-09-24): left CCW, right CW, as Pybricks drive bases expect
    left = PortAssignment(Role.WHEEL_LEFT, Direction.COUNTERCLOCKWISE)
    assert config.port_for(Role.WHEEL_LEFT) == ("A", left)
    assert config.port_for(Role.WHEEL_RIGHT) == ("D", PortAssignment(Role.WHEEL_RIGHT))
    assert config.port_for(Role.DISTANCE_SENSOR)[0] == "B"
    assert config.port_for(Role.LINE_SENSOR)[0] == "F"
    assert config.calibration.edge == 52


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{oops", "not valid JSON"),
        ('{"version": 7}', "Unsupported config version 7"),
        ('{"version": 1, "ports": {}}', "malformed"),
        ('{"version": 1, "ports": {"C": {"role": "wing"}}}', "malformed"),
        ("[]", "malformed"),
    ],
)
def test_bad_files_raise_config_error(tmp_path, content: str, message: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        RobotConfig.load(path)


def test_missing_file_raises_config_error(tmp_path) -> None:
    with pytest.raises(ConfigError, match="Cannot read"):
        RobotConfig.load(tmp_path / "nope.json")


# -- drive profile readout ----------------------------------------------------


def test_drive_profile_per_mode() -> None:
    from app.core.config import IDLE_PROFILE, drive_profile

    knobs = {"SPD": 50, "INNER": 20, "SRCH": 60, "TURN": 120, "DSPD": 150, "DTRN": 90}
    lf = drive_profile("line_follower", knobs)
    assert (lf.speed, lf.turn_caption, lf.turn) == ("50", "inner % / search °/s", "20 / 60")
    tele = drive_profile("teleop", knobs)
    assert (tele.speed, tele.turn) == ("50", "120")
    drift = drive_profile("drift_test", knobs)
    assert (drift.speed, drift.turn) == ("150", "90")
    assert drive_profile(None, knobs) is IDLE_PROFILE


def test_old_presets_get_the_new_speed_defaults() -> None:
    data = RobotConfig().to_json()
    for key in ("inner_pct", "search_deg_s", "teleop_turn_deg_s"):
        del data["tuning"][key]
    tuning = RobotConfig.from_json(data).tuning
    assert (tuning.inner_pct, tuning.search_deg_s, tuning.teleop_turn_deg_s) == (20, 60, 180)
    # a preset from before the arc turns still loads; its pivot rate is ignored
    data["tuning"]["pivot_deg_s"] = 180.0
    assert RobotConfig.from_json(data).tuning.inner_pct == 20


def test_route_error() -> None:
    from app.core.config import route_error

    assert route_error("") is None and route_error("RLLR") is None
    assert route_error("LRS") is None
    assert "L, R or S" in route_error("RX")
    assert "more than" in route_error("R" * 11)
