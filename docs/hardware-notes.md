# Hardware notes

Raw observations from sessions with the real robot. Values that belong in a
reference document are moved there; the raw record stays here.

## 2026-09-23 — stage 1: stationary probe and port scan (M1)

Robot on the table, motors never driven. Run from the laptop with
`tools/run_on_hub.py` (same `HubConnection` the app uses).

**Setup**

- Hub: SPIKE Prime / Robot Inventor hub, `Pybricks MicroPython ci-release-86-v3.6.1
  on 2025-03-11` (MicroPython 1.20, `sys.version` reports `3.4.0`).
- Wiring differs from the CLAUDE.md default: colour sensor on **A** (not D),
  motors on **C** and **F**, no ultrasonic sensor fitted.
- Battery 7176–7179 mV, 89–130 mA at rest.

**BLE**

- Scan, connect, compile (mpy-cross via `build_program`), download, start and
  stdout all work end to end. Upload of a 2.2 kB program ~0.3 s.
- The hub's BLE address changes on every reconnect (seen: `0F:95:F8…`,
  `3F:65:86…`, `03:69:54…`, `05:32:2B…`, `30:52:B4…`). Identify a hub by name,
  never by address. Name advertised: `Pybricks Hub`.
- A sleeping hub does not advertise at all: wake it with the centre button.
- The lab has ~70 BLE advertisers in range; only one Pybricks hub.

**Device IDs (`PUPDevice(port).info()["id"]`)**

| Device | ID |
|---|---|
| 51515 motor (medium angular, grey) | 75 |
| Colour sensor | 61 |
| Empty port | `OSError` errno 19 (ENODEV) |

`PUPDevice` identifies motors too, not only sensors.

**API facts**

| Call | Result |
|---|---|
| `hub.imu.ready()` | exists; `True` 1–9 ms after start on a hub already awake |
| `hub.imu.heading()`, `reset_heading(0)` | exist |
| `hub.imu.acceleration()` | exists, mm/s² (z ≈ 9711 at rest = gravity) |
| `hub.battery.current()` | exists, mA |
| `DriveBase.use_gyro(True)`, `done()`, `angle()`, `settings(...)` | exist |
| `Motor.load()`, `Motor.stalled()` | exist; `(0, 0)` / `(False, False)` at rest |
| `ColorSensor.hsv()` | returns an object with `.h .s .v` |
| per-loop reads (reflection + heading + distance) | ~100 µs |
| slow reads (hsv + 2× load) | ~100 µs |

StopWatch resolution is 1 ms, so the loop costs are upper bounds from 100 and
20 iterations. Either way they are far inside the 10 ms loop budget.

**Open**

- Colour sensor read reflection 0 and HSV (0, 0, 0) during the probe. Unknown
  yet whether the sensor was facing air or a surface.
- `Motor.load()` units and sign need the motors turning (stage 3).

**M1 acceptance: PASSED.** `scan_ports.py` reported A=61, C=75, F=75, rest 0;
after unplugging the colour sensor a rescan reported A=0 with the rest
unchanged.

## 2026-09-23 — stage 2 attempt: calibration crashed every mode program

In the app, the calibration stream and a line follower run both died about
0.5 s after start, at the first command from the laptop (the heartbeat):

```
File "hub_line_follower.py", line 190, in check_commands
AttributeError: 'str' object has no attribute 'partition'
```

Pybricks MicroPython has no `str.partition()`. Every generated program used
it in `check_commands()`, so none survived its first `HB`. mpy-cross only
checks syntax, and the rule that hub programs never run on the laptop meant
no test executed it. Fixed with a `split_once()` helper (`find()` + slicing);
`test_no_str_methods_missing_on_the_hub` now bans the str methods Pybricks
lacks in every hub program.

Before the crash the line follower did run: `R`, `S` (battery 7158 mV, IMU
ready) and two `T` lines arrived, reflection 6 and 10, state `PIVOT` at
180 deg/s. So the colour sensor on A does read, and the robot turned briefly
on the table: the calibration reading 0 was the crash, not the sensor.

## 2026-09-23 — stage 2: calibration, heading sign (after the fix)

Robot held by hand, calibrate program streaming, in the app.

- Calibration worked end to end; black/white gap comfortably above 30, no
  warning. (Exact values not recorded; they are in the saved config.)
- **Heading sign confirmed**: turning the robot left by hand raised the
  heading readout and rotated the map marker left. `_base.py.j2`'s
  `-hub.imu.heading()` is right; Pybricks heading is clockwise-positive.
- Header: battery 7.14 V, loop 10 ms (calibrate program, all telemetry on).
- No battery gauge in the header, only text: the approved mockup has one.
  Added.

## 2026-09-23 — stage 3 (part 1): teleop, wheels lifted

Robot on a box, wheels free, teleop from the app.

- W and S move the map trail forward and back: the encoder distance counts
  even with the wheels in the air.
- A and D spin the wheels but the map marker does not turn. Expected: heading
  comes from the gyro and the body does not rotate on a box. Turning is only
  visible on the floor (stage 4).
- Teleop at the line follower's 50 mm/s felt too slow. Teleop now has its own
  150 mm/s and 120 deg/s (hub clamps stay 300 mm/s, 180 deg/s).
- The header battery gauge (linear 6.8-8.3 V guess) showed ~23 % at 7.12 V
  while Pybricks Code showed a healthy pack. Replaced by the hub's own
  low-voltage status flags, as Pybricks Code does; the voltage stays as text.
- Map marker (110 mm long) felt too big; now 65 mm.
