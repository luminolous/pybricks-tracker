"""Rendered hub programs, checked statically and with mpy-cross. Never executed here."""

from __future__ import annotations

import ast
import re
from dataclasses import replace
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
    assert "Motor(Port.A, Direction.COUNTERCLOCKWISE)" in source
    assert "Motor(Port.D, Direction.CLOCKWISE)" in source
    assert "ColorSensor(Port.F)" in source
    assert "UltrasonicSensor(Port.B)" in source
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


def test_line_follower_drives_without_gyro_control(source: str) -> None:
    # use_gyro(True) made the robot overshoot after every pivot (2026-09-24)
    assert "robot.use_gyro(False)" in source
    assert "return -hub.imu.heading()" in source  # heading still from the IMU
    assert "robot.use_gyro(True)" in render(DEFAULT, "teleop")


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
    assert "DRV_MAX_SPEED = 1000" in source and "DRV_MAX_TURN = 360" in source


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
        "INNER_PCT = 20.0",
        "SEARCH_RATE = 60.0",
        "LOST_MS = 150",
        "LOST_MM = 30",
        "SEARCH_FIRST_DEG = 45",
        "SEARCH_BACK_DEG = 180",
        "BLACK_BELOW = (BLACK + EDGE) // 2",
        "WHITE_ABOVE = (WHITE + EDGE) // 2",
    ):
        assert re.search(rf"^{re.escape(line)}\b", source, re.MULTILINE), line


def test_pivot_and_search_rates_are_live(source: str) -> None:
    """INNER and SRCH change the turns mid-run; each applied value is acknowledged."""
    commands = function(source, "check_commands")
    assert "INNER_PCT = max(-100.0, min(100.0, float(value)))" in commands
    assert 'emit_e("ACK", "INNER:{}".format(INNER_PCT))' in commands
    assert "SEARCH_RATE = max(0.0, min(DRV_MAX_TURN, float(value)))" in commands
    assert 'emit_e("ACK", "SRCH:{}".format(SEARCH_RATE))' in commands
    assert "global KP, KI, KD, BASE_SPEED, OBSTACLE_MM, INNER_PCT, SEARCH_RATE" in commands
    assert "STEER = _search_dir * SEARCH_RATE" in function(source, "search_step")


def test_turn_and_drift_speeds_come_from_the_config() -> None:
    tuning = TuningParams(inner_pct=35, search_deg_s=120, drift_speed_mm_s=100, drift_turn_deg_s=45)
    config = replace(RobotConfig(), tuning=tuning)
    lf = render(config, "line_follower")
    assert re.search(r"^INNER_PCT = 35\b", lf, re.MULTILINE)
    assert re.search(r"^SEARCH_RATE = 120\b", lf, re.MULTILINE)
    drift = render(config, "drift_test", drift="straight")
    assert re.search(r"^STRAIGHT_SPEED = 100\b", drift, re.MULTILINE)
    assert re.search(r"^TURN_RATE = 45\b", drift, re.MULTILINE)


def test_search_sweeps_forward_by_angle_without_backing_up(source: str) -> None:
    start = function(source, "start_search")
    assert "robot.straight(" not in source  # nothing ever backs up
    assert "_search_dir = correction_dir(error) if direction is None else direction" in start
    # sweeps are measured by the gyro: a wrong axle track cannot skew them
    assert "_sweep_start = _heading_deg" in start
    assert "robot.angle()" not in source
    step = function(source, "search_step")
    assert "abs(_heading_deg - _sweep_start) >= limit" in step
    # short first sweep, then back past the start: a corner and a hairpin both covered
    assert "limit = _sweep_deg if _search == 1 else _sweep_deg + _back_deg" in step
    assert "if refl < EDGE:" in step  # found, as the original: warna.reflection() < TEPI
    assert 'emit_e("GIVEUP")' in step
    # the sweep swings on the stopped inner wheel: forward, never back
    assert "robot.drive(swing_speed(SEARCH_RATE), STEER)" in step
    assert "return abs(turn_deg_s) / RAD_TO_DEG * AXLE_MM / 2" in function(source, "swing_speed")


def test_turns_never_run_a_wheel_backwards(source: str) -> None:
    control = function(source, "control_step")
    # full black or full white: the sharpest arc, inner wheel at INNER_PCT
    assert "if refl < BLACK_BELOW or refl > WHITE_ABOVE:" in control
    assert "STEER = correction_dir(error) * arc_turn(INNER_PCT / 100)" in control
    # PD on the edge never turns sharper than that
    # PD never reverses a wheel, even when INNER is below 0
    assert "limit = arc_turn(max(0.0, INNER_PCT) / 100)" in control
    assert "STEER = max(-limit, min(limit, STEER))" in control
    # both states drive the same way: outer wheel at SPD, only the inner slows
    assert "robot.drive(arc_speed(STEER), STEER)" in control
    # no pivot in place anywhere, except the wall turn: the robot stands at a wall
    assert source.count("robot.drive(0,") == 1
    assert "robot.drive(0, STEER)" in function(source, "wall_turn_step")
    arc = function(source, "arc_turn")
    assert "return abs(BASE_SPEED) * (1 - inner) / AXLE_MM * RAD_TO_DEG" in arc
    speed = function(source, "arc_speed")
    assert "return BASE_SPEED - abs(turn_deg_s) / RAD_TO_DEG * AXLE_MM / 2" in speed
    assert "AXLE_MM = 112.0" in source


def test_pivot_and_white_timer_follow_the_original(source: str) -> None:
    control = function(source, "control_step")
    assert "if refl < BLACK_BELOW or refl > WHITE_ABOVE:" in control
    assert "STEER = correction_dir(error) * arc_turn(INNER_PCT / 100)" in control
    assert "if refl <= WHITE_ABOVE:\n        on_line()" in control
    # lost needs time AND forward travel: swinging back after a pivot is not lost
    assert (
        "elif _white_timer.time() > LOST_MS and robot.distance() - _white_from >= LOST_MM:"
        in control
    )
    assert "_white_from = robot.distance()" in function(source, "on_line")
    assert "on_line()" in function(source, "search_step")  # found: clocks restart
    assert "correction_dir" in function(source, "correction_dir")
    assert "return edge_flip() if KP * error > 0 else -edge_flip()" in function(
        source, "correction_dir"
    )


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


# -- route ------------------------------------------------------------------------

ROUTED = replace(DEFAULT, tuning=replace(DEFAULT.tuning, route="RLLR", finish_mm=600.0))


async def test_routed_program_compiles(tmp_path: Path) -> None:
    path = generate(ROUTED, "line_follower", out_dir=tmp_path)
    assert len(await compile_file(str(tmp_path), path.name, 6)) > 0


def test_route_and_finish_are_rendered() -> None:
    source = render(ROUTED, "line_follower")
    assert re.search(r'^ROUTE = "RLLR"', source, re.MULTILINE)
    assert re.search(r"^FINISH_MM = 600.0\b", source, re.MULTILINE)
    assert re.search(r'^ROUTE = ""', render(DEFAULT, "line_follower"), re.MULTILINE)


@pytest.mark.parametrize("route", ["RLX", "rl", "R L", "L" * 11])
def test_bad_route_is_refused(route: str) -> None:
    config = replace(DEFAULT, tuning=replace(DEFAULT.tuning, route=route))
    with pytest.raises(GeneratorError):
        render(config, "line_follower")


def test_edge_follows_the_next_turn(source: str) -> None:
    flip = function(source, "edge_flip")
    assert "if not ROUTE:\n        return 1" in flip  # no route: the original behaviour
    assert "tuned = 1 if KP < 0 else -1" in flip  # negative KP tracks the right edge
    assert "step = ROUTE[min(_side_step, len(ROUTE) - 1)]" in flip
    assert "return tuned * turn_sign(step)" in flip
    control = function(source, "control_step")
    assert (
        "STEER = edge_flip() * (KP * error + KI * _integral + KD * (error - _last_error))"
        in control
    )


def test_turns_are_counted_by_gyro_heading(source: str) -> None:
    track = function(source, "track_route")
    assert "if (_step_heading - _heading_deg) * sign >= TURN_DONE_DEG:" in track
    assert "_step_heading -= sign * 90" in track
    assert "step_taken()" in track
    taken = function(source, "step_taken")
    assert 'emit_e("TURN", "{}/{} {}".format(_step, len(ROUTE), ROUTE[_step - 1]))' in taken
    assert "_finish_from = robot.distance()" in taken
    # the edge switches only once the heading settled on the new line
    assert "if _side_step < _step and abs(_heading_deg - _step_heading) < SETTLE_DEG:" in track
    # search sweeps must not count as turns
    assert "if not _search:\n        track_route(refl)" in function(source, "control_step")


def test_wall_turns_the_planned_way_without_blocking(source: str) -> None:
    control = function(source, "control_step")
    assert "if _step < len(ROUTE) and not straight_pending():" in control
    assert "start_wall_turn()" in control
    assert 'STATE = "WALL"' in function(source, "start_wall_turn")
    # after a wall turn the same wall may still be in view: no second turn until clear
    assert "_wall_armed = False" in control
    assert "if _distance_mm >= OBSTACLE_MM:\n        _wall_armed = True" in control
    assert "elif _wall_armed:" in control
    assert "if not wall_turn_step():\n            return" in control


def test_wall_turn_runs_by_gyro_then_sweeps_back_first(source: str) -> None:
    start = function(source, "start_wall_turn")
    assert "_wall_target = _step_heading - _wall_sign * 90" in start
    step = function(source, "wall_turn_step")
    assert "remaining = (_wall_target - _heading_deg) * -_wall_sign" in step
    assert "if remaining <= WALL_TOL_DEG or _wall_timer.time() > WALL_TURN_MS:" in step
    control = function(source, "control_step")
    # after the turn: the step counts, and off the line it sweeps back toward
    # the old heading first, 45 degrees, instead of following the next edge
    after = control[control.index("if not wall_turn_step():") :]
    assert after.index("track_route(refl)") < after.index(
        "start_search(0, -_wall_sign, WALL_SEARCH_DEG, WALL_SEARCH_DEG)"
    )
    assert "WALL_SEARCH_DEG = 45" in source


def test_finish_only_after_the_route_and_fin_distance(source: str) -> None:
    control = function(source, "control_step")
    assert "if finish_reached():" in control
    reached = function(source, "finish_reached")
    # opt-in: FIN 0 (the default) never finishes, every line end is searched
    assert "if FINISH_MM <= 0 or _finish_from is None:\n        return False" in reached
    assert "return robot.distance() - _finish_from >= FINISH_MM" in reached
    assert re.search(r"^FINISH_MM = 0.0", source, re.MULTILINE)
    finish = function(source, "finish")
    assert 'emit_e("FINISH", int(robot.distance() - _finish_from))' in finish
    assert "STOPPED = True" in finish


def test_fin_command_is_live_and_acknowledged(source: str) -> None:
    commands = function(source, "check_commands")
    assert "FINISH_MM = max(0.0, float(value))" in commands
    assert 'emit_e("ACK", "FIN:{}".format(FINISH_MM))' in commands


def test_ki_runs_only_in_the_grey_band_with_anti_windup(source: str) -> None:
    assert re.search(r"^KI = 0.0$", source, re.MULTILINE)  # off by default
    control = function(source, "control_step")
    assert "KP * error + KI * _integral + KD * (error - _last_error)" in control
    assert (
        "_integral = max(-INTEGRAL_MAX, min(INTEGRAL_MAX, _integral + error * LOOP_MS / 1000))"
        in control
    )
    # restarts on full turns, searches and walls
    assert control.count("reset_integral()") >= 2
    assert "reset_integral()" in function(source, "start_search")
    commands = function(source, "check_commands")
    assert 'emit_e("ACK", "KI:{}".format(KI))' in commands


def test_straight_step_locks_heading_across_a_crossing() -> None:
    config = replace(DEFAULT, tuning=replace(DEFAULT.tuning, route="LRS", route_lock_deg=25.0))
    source = render(config, "line_follower")
    assert re.search(r'^ROUTE = "LRS"', source, re.MULTILINE)
    assert re.search(r"^LOCK_DEG = 25.0", source, re.MULTILINE)
    assert "CROSS_MM = 30" in source
    # S keeps the KP edge and the ideal heading; the lock cuts steering past it
    assert 'if step == "S":\n        return 1' in function(source, "edge_flip")
    lock = function(source, "lock_heading")
    assert "off = _heading_deg - _step_heading" in lock
    assert "if off >= LOCK_DEG and steer < 0:" in lock
    assert "if off <= -LOCK_DEG and steer > 0:" in lock
    control = function(source, "control_step")
    assert "if straight_pending():\n        STEER = lock_heading(STEER)" in control
    # the crossing: CROSS_MM of full black, taken once the sensor leaves it
    cross = function(source, "track_straight")
    assert "robot.distance() - _black_from >= CROSS_MM" in cross
    assert "if _crossing:\n        _crossing = False\n        step_taken()" in cross
    track = function(source, "track_route")
    assert 'if ROUTE[_step] == "S":\n        track_straight(refl)' in track


def test_lock_command_is_live_and_clamped(source: str) -> None:
    commands = function(source, "check_commands")
    assert "LOCK_DEG = max(5.0, min(60.0, float(value)))" in commands
    assert 'emit_e("ACK", "LOCK:{}".format(LOCK_DEG))' in commands


def test_negative_inner_allows_sharper_turns_on_black_or_white_only() -> None:
    # arc_turn / arc_speed with the outer wheel at v and the inner at k * v:
    # centre speed v(1+k)/2, turn v(1-k)/L. k = -1 spins in place.
    v, axle = 100.0, 112.0
    for k, centre in ((0.2, 60.0), (0.0, 50.0), (-0.3, 35.0), (-1.0, 0.0)):
        turn_rad = v * (1 - k) / axle
        assert round(v - turn_rad * axle / 2, 6) == centre  # arc_speed(arc_turn(k))
    source = render(
        replace(DEFAULT, tuning=replace(DEFAULT.tuning, inner_pct=-30.0)), "line_follower"
    )
    assert re.search(r"^INNER_PCT = -30.0", source, re.MULTILINE)
