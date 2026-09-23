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


def function(source: str, name: str) -> str:
    """Source of one top-level function in the rendered program."""
    start = source.index(f"\ndef {name}(") + 1
    end = source.find("\n\n\n", start)
    return source[start : end if end != -1 else len(source)]


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


def test_handshake_first_then_imu_wait_then_loop(source: str) -> None:
    main = function(source, "main")
    order = [
        main.index('print("R,{},{}".format(MODE, PROTO_VERSION))'),
        main.index("wait_for_imu()"),
        main.index("reset_origin()"),
        main.index("run_loop()"),
    ]
    assert order == sorted(order)


def test_watchdog_checked_every_iteration(source: str) -> None:
    loop = function(source, "run_loop")
    body = loop[loop.index("while True:") :]
    assert body.index("check_commands()") < body.index("if not watchdog_ok():")
    assert body.index("if not watchdog_ok():") < body.index("control_step(n, refl)")
    trip = body[body.index("if not watchdog_ok():") :]
    assert trip.split("\n")[1].strip() == "trip_watchdog()"
    assert trip.split("\n")[2].strip() == "break"


def test_watchdog_trip_stops_drivebase_and_emits_once(source: str) -> None:
    trip = function(source, "trip_watchdog")
    assert "robot.stop()" in trip
    assert 'emit_e("WDOG", _last_rx.time())' in trip
    assert source.count('emit_e("WDOG"') == 1
    assert "WATCHDOG_MS = 2000" in source


def test_imu_wait_keeps_serving_commands_and_watchdog(source: str) -> None:
    wait = function(source, "wait_for_imu")
    assert "while not hub.imu.ready():" in wait
    assert "check_commands()" in wait
    assert "trip_watchdog()" in wait
    assert "emit_s()" in wait
    assert "emit_t" not in wait  # no T before the IMU is ready (protocol.md)


def test_commands_reset_watchdog_clock(source: str) -> None:
    check = source[source.index("def check_commands():") : source.index("def watchdog_ok():")]
    assert check.index("_last_rx.reset()") < check.index("key, value = split_once(line)")
    assert "_poll.poll(0)" in check


def test_renders_config_values(source: str) -> None:
    assert "Motor(Port.C, Direction.CLOCKWISE)" in source
    assert "Motor(Port.F, Direction.COUNTERCLOCKWISE)" in source
    assert "ColorSensor(Port.D)" in source
    assert "UltrasonicSensor(Port.E)" in source
    assert "wheel_diameter=56.0" in source
    assert "KP = -1.5" in source
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
        (without(Role.LINE_SENSOR), "line follower program needs a line sensor"),
    ],
)
def test_invalid_configs_raise(config: RobotConfig, message: str) -> None:
    with pytest.raises(GeneratorError, match=message):
        render(config, "line_follower")


def test_unknown_mode_raises() -> None:
    with pytest.raises(GeneratorError):
        render(DEFAULT, "dance")


def test_generate_keeps_file_on_disk(tmp_path: Path) -> None:
    path = generate(DEFAULT, "line_follower", out_dir=tmp_path)
    assert path == tmp_path / "hub_line_follower.py"
    assert path.read_text(encoding="utf-8") == render(DEFAULT, "line_follower")


@pytest.mark.parametrize("drift", ["straight", "turns", "square"])
async def test_drift_tests_compile(tmp_path: Path, drift: str) -> None:
    path = generate(DEFAULT, "drift_test", out_dir=tmp_path, drift=drift)
    assert len(await compile_file(str(tmp_path), path.name, 6)) > 0


def test_turn_test_runs_with_gyro_off() -> None:
    assert "robot.use_gyro(False)" in render(DEFAULT, "drift_test", drift="turns")
    assert "robot.use_gyro(True)" in render(DEFAULT, "drift_test", drift="straight")


def test_square_renders_four_sides() -> None:
    source = render(DEFAULT, "drift_test", drift="square")
    assert source.count('("S", 500),') == 4
    assert source.count('("T", 90),') == 4
    assert "robot.straight(amount, wait=False)" in source


def test_drift_test_needs_no_line_sensor() -> None:
    assert "MOVES" in render(without(Role.LINE_SENSOR), "drift_test", drift="straight")


def test_unknown_drift_test_raises() -> None:
    with pytest.raises(GeneratorError, match="Unknown drift test"):
        render(DEFAULT, "drift_test", drift="figure8")


def test_detail_line_is_throttled_to_4_hz(source: str) -> None:
    assert "D_EVERY = 25" in source and "LOOP_MS = 10" in source
    loop = function(source, "run_loop")
    assert "if n % D_EVERY == 0:" in loop
    assert "emit_d(dt_ms)" in loop
    # the expensive reads live only in emit_d, never in the loop body
    assert source.count("line_sensor.hsv()") == 1
    assert "line_sensor.hsv()" in function(source, "emit_d")
    assert "left_motor.load()" in function(source, "emit_d")


def test_loop_dt_is_the_full_period(source: str) -> None:
    loop = function(source, "run_loop")
    body = loop[loop.index("while True:") :]
    # read before reset, at the top of the iteration: includes the previous wait
    assert body.index("dt_ms = period.time()") < body.index("period.reset()")
    assert body.index("period.reset()") < body.index("check_commands()")


def test_every_tuning_command_is_acknowledged(source: str) -> None:
    check = function(source, "check_commands")
    for key, var in (("KP", "KP"), ("KD", "KD"), ("SPD", "BASE_SPEED"), ("THR", "OBSTACLE_MM")):
        assert f'emit_e("ACK", "{key}:{{}}".format({var}))' in check
    # the ACK follows the assignment, so a failed parse sends none
    assert check.index("KP = float(value)") < check.index('emit_e("ACK", "KP:')


async def test_calibrate_program_compiles_and_holds_still(tmp_path: Path) -> None:
    path = generate(DEFAULT, "calibrate", out_dir=tmp_path)
    assert len(await compile_file(str(tmp_path), path.name, 6)) > 0
    source = path.read_text(encoding="utf-8")
    control = function(source, "control_step")
    assert "drive" not in control and "STEER = 0" in control


def test_calibrate_needs_a_line_sensor() -> None:
    with pytest.raises(GeneratorError, match="calibrate program needs a line sensor"):
        render(without(Role.LINE_SENSOR), "calibrate")


def test_stall_and_bump_are_checked_at_slow_rates(source: str) -> None:
    loop = function(source, "run_loop")
    assert loop.index("if n % T_EVERY == 0:") < loop.index("check_bump()")
    assert loop.index("if n % D_EVERY == 0:") < loop.index("check_stall()")
    stall = function(source, "check_stall")
    assert "if left and not _stalled_left:" in stall  # onset only
    bump = function(source, "check_bump")
    assert "BUMP_COOLDOWN_MS" in bump and 'emit_e("BUMP", peak)' in bump


def test_drive_setpoint_is_clamped_on_the_hub(source: str) -> None:
    check = function(source, "check_commands")
    assert 'elif key == "DRV":' in check
    assert "max(-DRV_MAX_SPEED, min(DRV_MAX_SPEED, float(speed)))" in check
    assert "_drv_timer.reset()" in check
    assert "DRV_MAX_SPEED = 300" in source and "DRV_MAX_TURN = 180" in source


def test_teleop_has_a_dead_man_and_obstacle_stop() -> None:
    source = render(DEFAULT, "teleop")
    control = function(source, "control_step")
    assert "if _drv_timer.time() > DRIVE_TIMEOUT_MS:" in control
    assert "DRIVE_TIMEOUT_MS = 300" in source
    assert "blocked = speed > 0 and _distance_mm < OBSTACLE_MM" in control
    assert "robot.drive(speed, turn)" in control
    # the watchdog still guards teleop through the shared base
    assert "trip_watchdog()" in function(source, "run_loop")


def test_teleop_without_distance_sensor_has_no_obstacle_check() -> None:
    assert "_distance_mm < OBSTACLE_MM" not in render(without(Role.DISTANCE_SENSOR), "teleop")


# -- ported from the original hand-written line follower -------------------------


def test_original_constants(source: str) -> None:
    for line in (
        "KP = -1.5",
        "KD = -5.0",
        "BASE_SPEED = 50.0",
        "OBSTACLE_MM = 50",
        "PIVOT_RATE = 180",
        "SEARCH_RATE = 150",
        "LOST_MS = 150",
        "SEARCH_DEG = 120",
        "BACKUP_MM = 20",
        "BLACK_BELOW = (BLACK + EDGE) // 2",
        "WHITE_ABOVE = (WHITE + EDGE) // 2",
    ):
        assert re.search(rf"^{re.escape(line)}\b", source, re.MULTILINE), line


def test_search_backs_up_then_sweeps_by_angle(source: str) -> None:
    start = function(source, "start_search")
    assert "robot.straight(-BACKUP_MM, wait=False)" in start  # non-blocking back-up
    assert "_search_dir = correction_dir(error)" in start
    step = function(source, "search_step")
    assert "if robot.done():" in step
    assert "abs(robot.angle() - _sweep_start) >= limit" in step
    assert "limit = SEARCH_DEG if _search == 2 else 2 * SEARCH_DEG" in step
    assert "if refl < EDGE:" in step  # found, as the original: warna.reflection() < TEPI
    assert 'emit_e("GIVEUP")' in step


def test_pivot_and_white_timer_follow_the_original(source: str) -> None:
    control = function(source, "control_step")
    assert "if refl < BLACK_BELOW:" in control
    assert "STEER = correction_dir(error) * PIVOT_RATE" in control
    assert "if refl <= WHITE_ABOVE:" in control and "_white_timer.reset()" in control
    assert "elif _white_timer.time() > LOST_MS:" in control
    assert "correction_dir" in function(source, "correction_dir")
    assert "return 1 if KP * error > 0 else -1" in function(source, "correction_dir")


def test_hub_light_shows_state(source: str) -> None:
    assert "from pybricks.parameters import Color" in source
    for color in ("RED", "GREEN", "YELLOW", "BLUE", "MAGENTA"):
        assert f"Color.{color}" in source
    assert "if color != _light:" in function(source, "light")  # only on change


async def test_probe_tool_compiles_and_never_drives() -> None:
    probe = Path(__file__).resolve().parents[2] / "tools" / "hub" / "probe_api.py"
    assert len(await compile_file(str(probe.parent), probe.name, 6)) > 0
    text = probe.read_text(encoding="utf-8")
    for moving in (".drive(", ".straight(", ".turn(", ".run(", ".dc("):
        assert moving not in text, moving


# Pybricks MicroPython builds str without these (found on the real hub:
# "'str' object has no attribute 'partition'" killed every mode program on the
# first command). mpy-cross cannot catch a missing method, so ban them here.
MISSING_STR_METHODS = (
    "partition",
    "rpartition",
    "splitlines",
    "zfill",
    "ljust",
    "rjust",
    "removeprefix",
    "removesuffix",
    "casefold",
    "title",
    "capitalize",
    "swapcase",
    "expandtabs",
)


def all_hub_sources() -> list[tuple[str, str]]:
    from app.codegen.generator import SCAN_PORTS_PROGRAM
    from app.core.analysis import DRIFT_TESTS

    out = [(mode, render(DEFAULT, mode)) for mode in ("line_follower", "calibrate", "teleop")]
    out += [(f"drift_{k}", render(DEFAULT, "drift_test", drift=k)) for k in DRIFT_TESTS]
    out.append(("scan_ports", SCAN_PORTS_PROGRAM.read_text(encoding="utf-8")))
    probe = Path(__file__).resolve().parents[2] / "tools" / "hub" / "probe_api.py"
    out.append(("probe", probe.read_text(encoding="utf-8")))
    return out


@pytest.mark.parametrize(("name", "text"), all_hub_sources())
def test_no_str_methods_missing_on_the_hub(name: str, text: str) -> None:
    code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())  # skip comments
    used = [m for m in MISSING_STR_METHODS if re.search(rf"\.{m}\(", code)]
    assert used == [], f"{name} uses {used}"


def test_split_once_is_what_commands_use(source: str) -> None:
    helper = function(source, "split_once")
    assert 'i = text.find(",")' in helper
    assert "split_once(value)" in function(source, "check_commands")  # DRV speed,turn
