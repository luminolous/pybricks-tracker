"""PortConfig, RobotGeometry, TuningParams.

M1 holds port roles and their validation. JSON save/load and the other
config types arrive with M2.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from app.core.protocol import PORT_LETTERS, DeviceKind


class Role(Enum):
    UNUSED = "unused"
    WHEEL_LEFT = "wheel_left"
    WHEEL_RIGHT = "wheel_right"
    LINE_SENSOR = "line_sensor"
    DISTANCE_SENSOR = "distance_sensor"
    AUX_MOTOR = "aux_motor"


class Direction(Enum):
    CLOCKWISE = "CW"
    COUNTERCLOCKWISE = "CCW"


MOTOR_ROLES = frozenset({Role.WHEEL_LEFT, Role.WHEEL_RIGHT, Role.AUX_MOTOR})

# Device kind each role needs.
ROLE_DEVICE: dict[Role, DeviceKind] = {
    Role.WHEEL_LEFT: DeviceKind.MOTOR,
    Role.WHEEL_RIGHT: DeviceKind.MOTOR,
    Role.AUX_MOTOR: DeviceKind.MOTOR,
    Role.LINE_SENSOR: DeviceKind.COLOR_SENSOR,
    Role.DISTANCE_SENSOR: DeviceKind.ULTRASONIC_SENSOR,
}

ROLE_LABELS: dict[Role, str] = {
    Role.UNUSED: "unused",
    Role.WHEEL_LEFT: "left wheel",
    Role.WHEEL_RIGHT: "right wheel",
    Role.LINE_SENSOR: "line",
    Role.DISTANCE_SENSOR: "distance",
    Role.AUX_MOTOR: "aux motor",
}


@dataclass(frozen=True)
class PortAssignment:
    role: Role = Role.UNUSED
    direction: Direction = Direction.CLOCKWISE


# Default robot from CLAUDE.md, to be confirmed by calibration.
DEFAULT_ASSIGNMENTS: dict[str, PortAssignment] = {
    "A": PortAssignment(),
    "B": PortAssignment(),
    "C": PortAssignment(Role.WHEEL_LEFT, Direction.CLOCKWISE),
    "D": PortAssignment(Role.LINE_SENSOR),
    "E": PortAssignment(Role.DISTANCE_SENSOR),
    "F": PortAssignment(Role.WHEEL_RIGHT, Direction.COUNTERCLOCKWISE),
}


def validate_ports(
    assignments: Mapping[str, PortAssignment],
    devices: Mapping[str, DeviceKind | None],
) -> str | None:
    """Return the first broken rule as a sentence for the UI, or None when valid.

    `devices` maps port letter to the scanned kind; None means not scanned.
    """
    if any(devices.get(p) is None for p in PORT_LETTERS):
        return "Scan ports before running."

    counts: dict[Role, int] = {}
    for port in PORT_LETTERS:
        role = assignments.get(port, PortAssignment()).role
        if role is Role.UNUSED:
            continue
        counts[role] = counts.get(role, 0) + 1
        kind = devices[port]
        if kind is DeviceKind.EMPTY:
            return f"Port {port} is empty but has the role {ROLE_LABELS[role]}."
        if kind is not ROLE_DEVICE[role]:
            needed = ROLE_DEVICE[role].value.replace("_", " ")
            return f"Port {port}: {ROLE_LABELS[role]} needs a {needed}."

    for role in (Role.WHEEL_LEFT, Role.WHEEL_RIGHT):
        n = counts.get(role, 0)
        if n != 1:
            return f"Assign exactly one {ROLE_LABELS[role]} (now {n})."
    for role in (Role.LINE_SENSOR, Role.DISTANCE_SENSOR):
        if counts.get(role, 0) > 1:
            return f"Assign at most one {ROLE_LABELS[role]} sensor."
    return None
