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
DEFAULT_DEVICES = {
    "A": EMPTY,
    "B": EMPTY,
    "C": M,
    "D": DeviceKind.COLOR_SENSOR,
    "E": DeviceKind.ULTRASONIC_SENSOR,
    "F": M,
}


def with_(port: str, role: Role) -> dict[str, PortAssignment]:
    return {**DEFAULT_ASSIGNMENTS, port: PortAssignment(role, Direction.CLOCKWISE)}


def test_default_robot_is_valid() -> None:
    assert validate_ports(DEFAULT_ASSIGNMENTS, DEFAULT_DEVICES) is None


def test_requires_scan() -> None:
    assert validate_ports(DEFAULT_ASSIGNMENTS, {}) == "Scan ports before running."


def test_role_on_empty_port() -> None:
    error = validate_ports(with_("A", Role.AUX_MOTOR), DEFAULT_DEVICES)
    assert error == "Port A is empty but has the role aux motor."


def test_wheel_must_be_on_motor_port() -> None:
    assignments = {**with_("C", Role.UNUSED), "D": PortAssignment(Role.WHEEL_LEFT)}
    assert validate_ports(assignments, DEFAULT_DEVICES) == "Port D: left wheel needs a motor."


def test_exactly_one_left_wheel() -> None:
    error = validate_ports(with_("C", Role.UNUSED), DEFAULT_DEVICES)
    assert error == "Assign exactly one left wheel (now 0)."


def test_two_right_wheels_rejected() -> None:
    devices = {**DEFAULT_DEVICES, "A": M}
    error = validate_ports(with_("A", Role.WHEEL_RIGHT), devices)
    assert error == "Assign exactly one right wheel (now 2)."


def test_at_most_one_line_sensor() -> None:
    devices = {**DEFAULT_DEVICES, "B": DeviceKind.COLOR_SENSOR}
    error = validate_ports(with_("B", Role.LINE_SENSOR), devices)
    assert error == "Assign at most one line sensor."


def test_unplugged_sensor_after_rescan() -> None:
    devices = {**DEFAULT_DEVICES, "D": EMPTY}
    assert validate_ports(DEFAULT_ASSIGNMENTS, devices) == "Port D is empty but has the role line."


# -- RobotConfig JSON ---------------------------------------------------------


def test_json_roundtrip(tmp_path) -> None:
    config = RobotConfig(
        geometry=RobotGeometry(wheel_diameter_mm=55.2, axle_track_mm=118.0),
        tuning=TuningParams(kp=-2.0, obstacle_threshold_mm=80),
        calibration=SensorCalibration(black=10, white=90),
    )
    path = tmp_path / "presets" / "robot.json"
    config.save(path)
    assert RobotConfig.load(path) == config


def test_default_config_matches_claude_md() -> None:
    config = RobotConfig()
    assert config.port_for(Role.WHEEL_LEFT) == ("C", PortAssignment(Role.WHEEL_LEFT))
    right = config.port_for(Role.WHEEL_RIGHT)
    assert right is not None and right[1].direction is Direction.COUNTERCLOCKWISE
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
