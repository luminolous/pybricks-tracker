<div align="center">
  <img src="app/ui/icons/app.svg" alt="Pybricks Tracker" width="160" />
  <h1>Pybricks Tracker</h1>
  <p><strong>Live map, telemetry and tuning for a Pybricks line-following robot</strong></p>
  <p>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
    <img src="https://img.shields.io/badge/python-3.12-3776AB.svg" alt="Python 3.12" />
    <img src="https://img.shields.io/badge/platform-Windows-0078D6.svg" alt="Platform: Windows" />
    <a href="https://pybricks.com"><img src="https://img.shields.io/badge/firmware-Pybricks-3FD0E6.svg" alt="Firmware: Pybricks" /></a>
    <a href="https://github.com/luminolous/pybricks-tracker/commits"><img src="https://img.shields.io/github/last-commit/luminolous/pybricks-tracker" alt="GitHub last commit" /></a>
  </p>
  <p>
    Made for the LEGO MINDSTORMS Robot Inventor 51515 hub running <a href="https://pybricks.com">Pybricks</a> firmware.
  </p>
</div>

<br/>

<!-- Screenshot: save it as docs/images/app.png, then remove this comment's markers.
<p align="center"><img src="docs/images/app.png" alt="Pybricks Tracker main window" /></p>
-->

```powershell
git clone https://github.com/luminolous/pybricks-tracker && cd pybricks-tracker
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python -m app.main
```

---

## Why

You tune a line follower by watching it drive, guessing at KP, uploading again and hoping. You see a wobble but you can't read the sensor value that caused it, or where on the track it happened.

Pybricks Tracker connects to the hub over Bluetooth and draws the robot's path on a map while it drives. Every point on the trail carries the reflection, the steering and the state behind it. You move a slider, the hub applies the new value within 100 ms, and the next corner shows you the result. Each run lands in `sessions/`, so you can lay yesterday's run over today's and compare.

## Features

- **Live map**: wheel odometry fused with the hub gyro, a trail coloured by what the sensor saw, a follow camera, and a ruler for distance, Δx/Δy and angle
- **Port setup**: scan ports A to F, detect motors and sensors, assign roles and CW/CCW direction
- **Generated hub program**: the app renders MicroPython from your config, compiles it and uploads it on Run (Ctrl+U shows the code)
- **Live tuning**: KP, KI, KD, speed, turn sharpness, search rate, wall distance and route lock change while the robot drives, and the hub acknowledges each value
- **Route planning**: steps like `LRS` pick the branch at each junction and drive straight across a crossing
- **Plots**: reflection, error and steering, motor load, and loop timing
- **Events**: lost line, line found, obstacle, stall, collision, route turns and watchdog stops, pinned on the map
- **Four modes**: line follower, teleop (W A S D), drift test and sensor calibration
- **Drift test**: drive a measured straight line or a set of turns, then apply the suggested `wheel_diameter` and `axle_track`
- **Recording and replay**: overlay earlier runs on the map; export PNG, CSV or JSONL
- **Battery gauge**: hub voltage with a warning before the hub cuts out
- **Hub sounds**: the hub beeps on connect, run, calibration samples, obstacles, finish and a failed search, and one button mutes them
- **Standalone exe**: one Windows file, no Python install needed

## Requirements

- Windows 10 or 11 with Bluetooth LE
- Python 3.12
- A LEGO Robot Inventor (51515) hub flashed with Pybricks firmware

The hub takes one Bluetooth connection at a time. Close any `code.pybricks.com` tab that holds it before you connect.

### Robot wiring

The default config matches this robot. Change any row in the Ports panel.

| Port | Device | Direction |
|---|---|---|
| A | Left wheel motor | Counterclockwise |
| D | Right wheel motor | Clockwise |
| F | Colour sensor, pointing down | - |
| B | Ultrasonic sensor, facing forward | - |

## Quick start

1. Turn on the hub.
2. Start the app with `python -m app.main`, click **Connect** and pick the hub.
3. Press **Ctrl+P** to scan the ports, then check the roles.
4. Press **Ctrl+K** and calibrate the colour sensor on black, then on white.
5. Put the robot on the line and press **F5**.

Press **Space** to stop the robot at any moment.

### Keyboard shortcuts

| Key | Action |
|---|---|
| Space | E-STOP (works inside text fields while a program runs) |
| F5 / Esc | Run the line follower / stop the program |
| Ctrl+P | Scan ports |
| Ctrl+K | Calibrate the line sensor |
| Ctrl+D | Drift test |
| Ctrl+T | Teleop; W A S D drive at SPD, turning at TURN |
| Ctrl+O | Replay a recorded run |
| Ctrl+E | Export the map (PNG), telemetry (CSV) or session (JSONL) |
| Ctrl+U | Show the generated hub program |

## Line follower

The robot follows one edge of the tape with a single colour sensor. A positive KP follows the left edge, a negative KP the right one.

| Sensor reads | The robot does |
|---|---|
| Grey, on the edge | PID steering around the calibrated edge value |
| Full black or full white | A full turn back to the edge that sharpens from INNER to IMIN over RAMP ms |
| White for 150 ms and 30 mm | Line lost: swing 45° toward the likely side, then sweep the other way to 180° past the start |
| Obstacle closer than THR | Stop, or turn 90° on the spot when a planned turn is still pending |

The outer wheel holds SPD and only the inner wheel slows, so the robot keeps moving forward through corners.

### Routes

A route is a string of steps, one per junction:

- `L` and `R` switch the robot to that edge of the tape, so it takes that branch. The gyro counts the turn at 60°.
- `S` locks the heading within LOCK degrees and drives straight across a four-way crossing.

`LRS` takes the left branch, then the right one, then goes straight over the crossing. An empty route follows the line with no plan.

[docs/line-follower-flow.md](docs/line-follower-flow.md) maps the full decision flow in diagrams, with links to each function.

### Tuning parameters

| Key | Controls | Unit |
|---|---|---|
| KP, KI, KD | PID gains on the edge error | - |
| SPD | Outer wheel speed | mm/s |
| INNER, IMIN, RAMP | Inner wheel share at the start and end of a full turn, and the time between | %, %, ms |
| SRCH | Swing rate while searching for the line | deg/s |
| THR | Wall distance | mm |
| LOCK | Heading lock for an `S` step | deg |
| FIN | Finish distance after the last route step, 0 turns it off | mm |

## How it works

The code runs in two places.

| Layer | Language | Runs on | Code |
|---|---|---|---|
| Desktop app | CPython 3.12 | Your laptop | `app/` |
| Hub program | MicroPython (Pybricks) | The robot | `app/codegen/templates/` |

When you click Run, the app fills a Jinja2 template with your ports, calibration, geometry, route and starting tuning values. It writes the result to `build/hub_line_follower.py`, compiles it with `mpy-cross` and uploads it over Bluetooth. The laptop never imports or executes the templates.

```
 Laptop (PySide6 + qasync)                      Hub (MicroPython, 10 ms loop)
 ─────────────────────────                      ─────────────────────────────
 heartbeat HB every 500 ms       ── stdin ──►   read commands, answer E,ACK
 slider changes KP,1.5 ...                      watchdog: 2 s without a command stops
                                                pose from wheels + gyro
 decode, record, draw at 30 fps  ◄─ stdout ──   sensors → control_step() → motors
                                                T 20 Hz · D 4 Hz · S 1 Hz · E on events
```

`_base.py.j2` holds what every mode shares: devices, odometry, telemetry, the command parser and the watchdog. Each mode template extends it and supplies `setup()` and `control_step()`.

### Project layout

```
app/
├── main.py              entry point, qasync loop
├── core/                connection, protocol, config, recorder, replay, tuning sender
├── codegen/
│   ├── generator.py     renders templates into build/
│   └── templates/       hub programs (MicroPython, never run on the laptop)
└── ui/                  main window, map, plots, panels, dialogs, theme
docs/                    line follower flow, hardware notes, UI design
tests/                   pytest suite, runs without a hub or a display
tools/                   one-off hub probes
```

## Safety

The robot can drive off a table, so two stops stay on in every mode:

- **Watchdog**: the hub stops the drive base when 2 s pass without any command from the laptop. A lost Bluetooth link or a frozen laptop ends the run within 2 s.
- **E-STOP**: Space sends `MODE,STOP` and terminates the hub program.

In teleop the robot also stops 300 ms after the last drive command, refuses to drive forward into an obstacle, and releases every key when the window loses focus.

## Calibration

Run the drift test before you trust a recorded path, then apply the suggested geometry. Results for this robot on 2026-09-26:

| Test | Result |
|---|---|
| 1000 mm straight | 5 mm/m error at `wheel_diameter` 55.7 mm |
| 5 × 360° turns | 0.3° heading error at `axle_track` 158.8 mm |

The drift test saves each result as JSON in `configs/drift/`.

## Build a standalone exe

```powershell
pyinstaller PybricksTracker.spec
dist\PybricksTracker.exe --selftest
```

The spec renders the exe icon from `app/ui/icons/app.svg`. `--selftest` renders and compiles every hub program with the bundled `mpy-cross`, with no hub and no window, and exits non-zero on any failure.

## Development

```powershell
ruff check .
ruff format .
pytest
```

The tests mock the Bluetooth layer and run Qt offscreen, so you need neither a hub nor a display. `requirements.txt` pins every version: `pybricksdev` renames methods between releases, so bump it on purpose.

## Credits

- [Pybricks](https://pybricks.com): the firmware and MicroPython API on the hub
- [pybricksdev](https://github.com/pybricks/pybricksdev): Bluetooth, compile and upload
- [PySide6](https://doc.qt.io/qtforpython-6/), [pyqtgraph](https://www.pyqtgraph.org), [qasync](https://github.com/CabbageDevelopment/qasync) and [Jinja2](https://jinja.palletsprojects.com)

## License

MIT
