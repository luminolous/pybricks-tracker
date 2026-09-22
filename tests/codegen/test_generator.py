"""Rendered hub programs, checked statically and with mpy-cross. Never executed here."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from pybricksdev.compile import compile_file, compile_multi_file

from app.codegen.generator import GeneratorError, generate, render
from app.core.config import DEFAULT_ASSIGNMENTS, PortAssignment, RobotConfig, Role, TuningParams
from app.core.protocol import PROTO_VERSION

DEFAULT = RobotConfig()


def without(role: Role) -> RobotConfig:
    ports = {p: (PortAssignment() if a.role is role else a) for p, a in DEFAULT_ASSIGNMENTS.items()}
    return RobotConfig(ports=ports)


@pytest.fixture(scope="module")
def source() -> str:
    return render(DEFAULT, "line_follower")


def main_loop(source: str) -> str:
    start = source.index("def main():")
    return source[start : source.index("\nmain()", start)]


async def test_compiles_with_mpy_cross(tmp_path: Path) -> None:
    path = generate(DEFAULT, "line_follower", out_dir=tmp_path)
    assert len(await compile_file(str(tmp_path), path.name, 6)) > 0


async def test_upload_bundle_contains_only_the_program(tmp_path: Path) -> None:
    # hub.run() compiles with compile_multi_file, which bundles local imports.
    # The program must import nothing local, so the bundle holds one module.
    path = generate(DEFAULT, "line_follower", out_dir=tmp_path)
    bundle = await compile_multi_file(str(path), 6)
    size = int.from_bytes(bundle[:4], "little")
    assert len(bundle) == 4 + len(b"__main__\x00") + size


def test_micropython_rules(source: str) -> None:
    tree = ast.parse(source)
    assert not any(isinstance(n, ast.JoinedStr) for n in ast.walk(tree)), "no f-strings on the hub"
    imported = {
        (n.module if isinstance(n, ast.ImportFrom) else a.name).split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in n.names
    }
    assert imported <= {"pybricks", "uselect", "umath", "usys"}
    assert "import umath as math" in source


def test_proto_version_matches_app(source: str) -> None:
    assert f"PROTO_VERSION = {PROTO_VERSION}\n" in source


def test_handshake_before_loop_and_watchdog_every_iteration(source: str) -> None:
    loop = main_loop(source)
    assert loop.index('print("R,{},{}".format(MODE, PROTO_VERSION))') < loop.index("while True:")
    body = loop[loop.index("while True:") :]
    assert "if not watchdog_ok():" in body
    assert body.index("check_commands()") < body.index("if not watchdog_ok():")
    assert body.index("if not watchdog_ok():") < body.index("control_step(n, refl)")


def test_watchdog_stops_drivebase_emits_once_and_ends(source: str) -> None:
    body = main_loop(source)
    trip = body[body.index("if not watchdog_ok():") :]
    trip = trip[: trip.index("break") + len("break")]
    assert "robot.stop()" in trip
    assert 'emit_e("WDOG", _last_rx.time())' in trip
    assert source.count('emit_e("WDOG"') == 1
    assert "WATCHDOG_MS = 2000" in source


def test_commands_reset_watchdog_clock(source: str) -> None:
    check = source[source.index("def check_commands():") : source.index("def watchdog_ok():")]
    assert check.index("_last_rx.reset()") < check.index('key, _, value = line.partition(",")')
    assert "_poll.poll(0)" in check


def test_renders_config_values(source: str) -> None:
    assert "Motor(Port.C, Direction.CLOCKWISE)" in source
    assert "Motor(Port.F, Direction.COUNTERCLOCKWISE)" in source
    assert "ColorSensor(Port.D)" in source
    assert "UltrasonicSensor(Port.E)" in source
    assert "wheel_diameter=56.0" in source
    assert "KP = -1.8" in source
    assert "EDGE = 52" in source


def test_only_assigned_devices_are_constructed() -> None:
    source = render(without(Role.DISTANCE_SENSOR), "line_follower")
    assert "UltrasonicSensor(Port" not in source
    assert "_distance_mm < OBSTACLE_MM" not in source


def test_live_tuning_values_are_rendered() -> None:
    config = RobotConfig(tuning=TuningParams(kp=-2.5, kd=-6.0, base_speed_mm_s=90.0))
    source = render(config, "line_follower")
    assert re.search(r"^KP = -2\.5$", source, re.MULTILINE)
    assert re.search(r"^BASE_SPEED = 90\.0$", source, re.MULTILINE)


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (without(Role.WHEEL_LEFT), "Assign a left and a right wheel"),
        (without(Role.LINE_SENSOR), "needs a line sensor"),
    ],
)
def test_invalid_configs_raise(config: RobotConfig, message: str) -> None:
    with pytest.raises(GeneratorError, match=message):
        render(config, "line_follower")


def test_unknown_mode_raises() -> None:
    with pytest.raises(GeneratorError):
        render(DEFAULT, "teleop")


def test_generate_keeps_file_on_disk(tmp_path: Path) -> None:
    path = generate(DEFAULT, "line_follower", out_dir=tmp_path)
    assert path == tmp_path / "hub_line_follower.py"
    assert path.read_text(encoding="utf-8") == render(DEFAULT, "line_follower")
