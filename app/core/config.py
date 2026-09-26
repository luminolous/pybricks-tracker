"""RobotConfig: port roles, geometry, tuning and sensor calibration.

Saved as JSON presets under configs/. Loading never trusts the file: every
problem becomes a ConfigError with a message fit for the UI.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

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


# The real robot's wiring, confirmed on 2026-09-24. Left CCW / right CW is the
# usual Pybricks drive base setup: with it, positive speed drives forward and
# positive turn rate turns right. The first guess (left CW, right CCW) drove
# backwards and mirrored every turn.
DEFAULT_ASSIGNMENTS: dict[str, PortAssignment] = {
    "A": PortAssignment(Role.WHEEL_LEFT, Direction.COUNTERCLOCKWISE),
    "B": PortAssignment(Role.DISTANCE_SENSOR),
    "C": PortAssignment(),
    "D": PortAssignment(Role.WHEEL_RIGHT, Direction.CLOCKWISE),
    "E": PortAssignment(),
    "F": PortAssignment(Role.LINE_SENSOR),
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


# -- full robot config --------------------------------------------------------

CONFIG_VERSION = 1
CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"


class ConfigError(ValueError):
    """A config file could not be read. The message is safe to show in the UI."""


@dataclass(frozen=True)
class RobotGeometry:
    wheel_diameter_mm: float = 56.0
    axle_track_mm: float = 112.0
    sensor_offset_mm: float = 40.0  # colour sensor ahead of the wheel axis


ROUTE_TURNS = frozenset("LR")
MAX_ROUTE_STEPS = 10


def route_error(route: str) -> str | None:
    """Why a route string is invalid, or None."""
    if set(route) - ROUTE_TURNS:
        return "Route turns must be L or R."
    if len(route) > MAX_ROUTE_STEPS:
        return f"Route has more than {MAX_ROUTE_STEPS} turns."
    return None


# Hub clamps, rendered into every program, and the slider limits. Speed raised
# to 1000 on request (2026-09-24). The motors top out well below that: about
# 1000 deg/s at the wheel, so ~490 mm/s with 56 mm wheels. How the firmware
# treats a request above that is not yet checked on the hub (hub-programs.md,
# open questions).
MAX_TURN_DEG_S = 360
MAX_SPEED_MM_S = 1000


@dataclass(frozen=True)
class DriveProfile:
    """Speeds a program drives at, for the readout row. Text, ready to show."""

    speed: str  # mm/s
    turn_caption: str
    turn: str  # deg/s


IDLE_PROFILE = DriveProfile("—", "turn °/s", "—")


def drive_profile(mode: str | None, knobs: Mapping[str, float]) -> DriveProfile:
    """What the running program drives at, from tuning knob values by key
    (SPD, INNER, SRCH, TURN, DSPD, DTRN), as the hub has them where it acknowledges."""

    def fmt(key: str) -> str:
        return f"{knobs[key]:.0f}"

    if mode == "line_follower":
        return DriveProfile(fmt("SPD"), "inner % / search °/s", f"{fmt('INNER')} / {fmt('SRCH')}")
    if mode == "teleop":
        return DriveProfile(fmt("SPD"), "turn °/s", fmt("TURN"))
    if mode == "drift_test":
        return DriveProfile(fmt("DSPD"), "turn °/s", fmt("DTRN"))
    if mode == "calibrate":
        return DriveProfile("0", "turn °/s", "0")  # holds still
    return IDLE_PROFILE


@dataclass(frozen=True)
class TuningParams:
    # Defaults from the original hand-written line follower (KECEPATAN, KP, KD, BATAS).
    kp: float = -1.5
    # Not in the original script. 0 = off; same sign as KP (protocol.md, KI).
    ki: float = 0.0
    kd: float = -5.0
    base_speed_mm_s: float = 50.0
    obstacle_threshold_mm: int = 50
    # Line follower turns, live like SPD. On black: arc with the inner wheel at
    # inner_pct of the outer (SPD), both forward; the original pivoted in place
    # at 180 deg/s. Lost line: swing on the stopped inner wheel at
    # search_deg_s (the original spun in place at 150 after backing up).
    inner_pct: float = 20.0
    search_deg_s: float = 60.0
    # Teleop drives forward at SPD and turns at this rate.
    teleop_turn_deg_s: float = 180.0
    # Drift test: fixed for the whole test so runs stay comparable.
    drift_speed_mm_s: float = 150.0
    drift_turn_deg_s: float = 90.0
    # Line follower route (protocol.md): planned turns in order, e.g. "RLLR".
    # Empty: plain line following. finish_mm: after the last turn, the first
    # line end at least this far on is the finish.
    route: str = ""
    finish_mm: float = 0.0


@dataclass(frozen=True)
class SensorCalibration:
    """Reflection on black and on white. Measured by the M6 calibration dialog."""

    black: int = 8
    white: int = 96

    @property
    def edge(self) -> int:
        return (self.black + self.white) // 2


CALIBRATION_MIN_GAP = 30  # ui-spec: a smaller gap usually means the sensor sits too high


def check_calibration(black: int, white: int) -> tuple[SensorCalibration, str | None]:
    """Validate a black/white pair. Returns the calibration and a warning, if any."""
    if not 0 <= black < white <= 100:
        raise ValueError(f"White ({white}) must read higher than black ({black}), both 0-100.")
    gap = white - black
    warning = None
    if gap < CALIBRATION_MIN_GAP:
        warning = (
            f"Gap is only {gap} (want {CALIBRATION_MIN_GAP}+). "
            "The sensor is probably mounted too high above the floor."
        )
    return SensorCalibration(black=black, white=white), warning


@dataclass(frozen=True)
class RobotConfig:
    ports: dict[str, PortAssignment] = field(default_factory=lambda: dict(DEFAULT_ASSIGNMENTS))
    geometry: RobotGeometry = field(default_factory=RobotGeometry)
    tuning: TuningParams = field(default_factory=TuningParams)
    calibration: SensorCalibration = field(default_factory=SensorCalibration)

    def port_for(self, role: Role) -> tuple[str, PortAssignment] | None:
        """First port holding `role`, or None."""
        for port in PORT_LETTERS:
            assignment = self.ports.get(port, PortAssignment())
            if assignment.role is role:
                return port, assignment
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "version": CONFIG_VERSION,
            "ports": {
                port: {"role": a.role.value, "direction": a.direction.value}
                for port, a in sorted(self.ports.items())
            },
            "geometry": asdict(self.geometry),
            "tuning": asdict(self.tuning),
            "calibration": asdict(self.calibration),
        }

    @classmethod
    def from_json(cls, data: Any) -> RobotConfig:
        try:
            if data.get("version") != CONFIG_VERSION:
                raise ConfigError(f"Unsupported config version {data.get('version')!r}.")
            ports = {
                port: PortAssignment(Role(p["role"]), Direction(p["direction"]))
                for port, p in data["ports"].items()
                if port in PORT_LETTERS
            }
            return cls(
                ports={p: ports.get(p, PortAssignment()) for p in PORT_LETTERS},
                geometry=RobotGeometry(**_floats(data["geometry"], RobotGeometry)),
                tuning=TuningParams(**_floats(data["tuning"], TuningParams)),
                calibration=SensorCalibration(**_floats(data["calibration"], SensorCalibration)),
            )
        except ConfigError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"Config file is malformed: {exc!r}") from exc

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> RobotConfig:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(f"Cannot read {path.name}: {exc.strerror or exc}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path.name} is not valid JSON: {exc.msg}") from exc
        return cls.from_json(data)


def _floats(section: Mapping[str, Any], kind: type) -> dict[str, Any]:
    """Keep only known fields and coerce them to the dataclass field's type."""
    out: dict[str, Any] = {}
    for name, f in kind.__dataclass_fields__.items():
        if name in section:
            # field types are strings under `from __future__ import annotations`
            caster = {"int": int, "str": str}.get(str(f.type), float)
            out[name] = caster(section[name])
    return out
