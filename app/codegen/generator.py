"""Render config plus mode into a hub program on disk.

Templates under templates/ are MicroPython for the hub. They are rendered to
text here and never imported or executed on the laptop.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.core.analysis import DRIFT_TESTS
from app.core.config import MOTOR_ROLES, PortAssignment, RobotConfig, Role
from app.core.protocol import PROTO_VERSION

TEMPLATES_DIR = Path(__file__).parent / "templates"
SCAN_PORTS_PROGRAM = TEMPLATES_DIR / "scan_ports.py"
BUILD_DIR = Path(__file__).resolve().parents[2] / "build"

# Hub-side timing, shared by every mode through _base.py.j2.
LOOP_MS = 10
WATCHDOG_MS = 2000  # protocol.md: stop after 2 s without any command
T_EVERY_LOOPS = 5  # 10 ms loop -> T at 20 Hz
D_EVERY_LOOPS = 25  # D at 4 Hz
S_EVERY_LOOPS = 100  # S at 1 Hz
DISTANCE_EVERY_LOOPS = 10  # ultrasonic at 10 Hz (hub-programs.md)

MODES = ("line_follower", "drift_test")


class GeneratorError(ValueError):
    """The config cannot produce a program. The message is safe to show in the UI."""


@dataclass(frozen=True)
class Device:
    port: str
    direction: str  # Pybricks Direction member name


def _device(entry: tuple[str, PortAssignment] | None) -> Device | None:
    if entry is None:
        return None
    port, assignment = entry
    direction = "CLOCKWISE" if assignment.direction.value == "CW" else "COUNTERCLOCKWISE"
    return Device(port=port, direction=direction)


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,  # output is Python source, not HTML
    )


def render(config: RobotConfig, mode: str, drift: str | None = None) -> str:
    """Render the hub program for `mode` as MicroPython source text.

    `drift` picks the test for mode "drift_test" (a key of DRIFT_TESTS).
    """
    if mode not in MODES:
        raise GeneratorError(f"Unknown program mode {mode!r}.")
    drift_test = None
    if mode == "drift_test":
        if drift not in DRIFT_TESTS:
            raise GeneratorError(f"Unknown drift test {drift!r}.")
        drift_test = DRIFT_TESTS[drift]
    left = _device(config.port_for(Role.WHEEL_LEFT))
    right = _device(config.port_for(Role.WHEEL_RIGHT))
    if left is None or right is None:
        raise GeneratorError("Assign a left and a right wheel before running.")
    line = _device(config.port_for(Role.LINE_SENSOR))
    if mode == "line_follower" and line is None:
        raise GeneratorError("The line follower needs a line sensor.")
    for port, assignment in config.ports.items():
        if assignment.role in MOTOR_ROLES - {Role.WHEEL_LEFT, Role.WHEEL_RIGHT}:
            raise GeneratorError(f"Port {port}: aux motors are not supported yet.")

    context = {
        "mode": mode,
        "proto_version": PROTO_VERSION,
        "left": left,
        "right": right,
        "line": line,
        "distance": _device(config.port_for(Role.DISTANCE_SENSOR)),
        "geometry": config.geometry,
        "tuning": config.tuning,
        "calibration": config.calibration,
        "loop_ms": LOOP_MS,
        "watchdog_ms": WATCHDOG_MS,
        "t_every": T_EVERY_LOOPS,
        "s_every": S_EVERY_LOOPS,
        "d_every": D_EVERY_LOOPS,
        "use_gyro": drift_test.use_gyro if drift_test else True,
        "drift": drift_test,
        "distance_every": DISTANCE_EVERY_LOOPS,
    }
    return _environment().get_template(f"{mode}.py.j2").render(context)


def generate(
    config: RobotConfig, mode: str, out_dir: Path = BUILD_DIR, drift: str | None = None
) -> Path:
    """Render and write the program. The file is kept so hub line numbers can be traced."""
    source = render(config, mode, drift=drift)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"hub_{mode}.py"
    path.write_text(source, encoding="utf-8")
    return path
