# Hub program (MicroPython, Pybricks). Never imported on the laptop.
# Answers the "API facts to verify" list in .claude/docs/hub-programs.md.
# STATIONARY: constructs motors but never drives them. Safe on a table.
#
# Output: one line per fact, "PROBE,<name>,<result>", then "PROBE,DONE,0".
# Run with:  python tools/run_on_hub.py tools/hub/probe_api.py

from pybricks.hubs import InventorHub
from pybricks.iodevices import PUPDevice
from pybricks.parameters import Direction, Port
from pybricks.pupdevices import ColorSensor, Motor, UltrasonicSensor
from pybricks.robotics import DriveBase
from pybricks.tools import StopWatch, wait
import usys


def report(name, value):
    print("PROBE,{},{}".format(name, value))


def attempt(name, fn):
    try:
        report(name, fn())
    except Exception as e:  # noqa: BLE001 - every failure is a finding
        # repr(), not type(e).__name__: MicroPython types have no __name__
        report(name, "ERROR {}".format(repr(e)))


hub = InventorHub()
report("firmware", usys.version)
report("implementation", usys.implementation)

# PUPDevice ids on every port (motors included?). Remember where things are,
# so the rest of the probe does not assume the default wiring.
PORTS = (("A", Port.A), ("B", Port.B), ("C", Port.C), ("D", Port.D), ("E", Port.E), ("F", Port.F))
ids = {}
for name, port in PORTS:
    try:
        ids[name] = PUPDevice(port).info()["id"]
        report("pup_id_" + name, ids[name])
    except OSError as e:
        report("pup_id_" + name, "none (OSError {})".format(e.args[0]))
COLOR_ID = 61
ULTRASONIC_ID = 62


def port_with(device_id):
    for name, port in PORTS:
        if ids.get(name) == device_id:
            return name, port
    return None, None

# IMU: ready() and how long it takes, heading and reset
clock = StopWatch()
attempt("imu_ready_now", lambda: hub.imu.ready())
waited = 0
try:
    while not hub.imu.ready() and clock.time() < 10000:
        wait(10)
    waited = clock.time()
    report("imu_ready_after_ms", waited)
except Exception as e:  # noqa: BLE001
    report("imu_ready_after_ms", "ERROR {}".format(e))
attempt("imu_heading", lambda: hub.imu.heading())
attempt("imu_reset_heading", lambda: hub.imu.reset_heading(0) or "ok")
attempt("imu_acceleration", lambda: tuple(hub.imu.acceleration()))
attempt("battery_voltage", lambda: hub.battery.voltage())
attempt("battery_current", lambda: hub.battery.current())

# Drivebase: methods the templates use
left = Motor(Port.C, Direction.CLOCKWISE)
right = Motor(Port.F, Direction.COUNTERCLOCKWISE)
robot = DriveBase(left, right, wheel_diameter=56, axle_track=112)
attempt("drivebase_use_gyro", lambda: robot.use_gyro(True) or "ok")
attempt("drivebase_done", lambda: robot.done())
attempt("drivebase_angle", lambda: robot.angle())
attempt("drivebase_settings", lambda: robot.settings(straight_speed=150, turn_rate=90) or "ok")
attempt("motor_load", lambda: (left.load(), right.load()))
attempt("motor_stalled", lambda: (left.stalled(), right.stalled()))

# Sensors, wherever they are plugged in
color_port_name, color_port = port_with(COLOR_ID)
report("color_port", color_port_name)
color = ColorSensor(color_port) if color_port else None
if color:
    attempt("color_reflection", lambda: color.reflection())
    attempt("color_hsv", lambda: (color.hsv().h, color.hsv().s, color.hsv().v))
us_port_name, us_port = port_with(ULTRASONIC_ID)
report("ultrasonic_port", us_port_name)
if us_port:
    distance = UltrasonicSensor(us_port)
    attempt("ultrasonic_mm", lambda: distance.distance())

# Loop cost: 100 iterations of the line follower's per-loop reads
t = StopWatch()
for _ in range(100):
    if color:
        color.reflection()
    hub.imu.heading()
    robot.distance()
report("loop_reads_us_per_iter", t.time() * 10)
t.reset()
for _ in range(20):
    if color:
        color.hsv()
    left.load()
    right.load()
report("slow_reads_us_per_iter", t.time() * 50)

print("PROBE,DONE,0")
