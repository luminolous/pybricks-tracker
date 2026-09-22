"""Port role validation rules from ui-spec.md."""

from __future__ import annotations

from app.core.config import (
    DEFAULT_ASSIGNMENTS,
    Direction,
    PortAssignment,
    Role,
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
