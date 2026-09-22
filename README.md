# Pybricks Tracker

Desktop telemetry and map-tracking application for a LEGO MINDSTORMS Robot
Inventor (51515) line-following robot running Pybricks.

The app connects to the hub over Bluetooth Low Energy, generates a MicroPython
program from your port configuration, uploads and runs it, and plots the
robot's path live while streaming sensor telemetry back.

## Features

- Map tracking from wheel odometry fused with the hub's gyroscope
- Port configuration for A through F, with device auto-detection
- Live PD tuning over Bluetooth, no re-upload
- Colour sensor readout with a live swatch, and trails coloured by what the
  sensor saw
- Motor load, loop timing and battery telemetry
- Event markers for lost line, obstacles, stalls and collisions
- Odometry drift validation with suggested geometry corrections
- Session recording, replay, and overlay comparison between runs
- PNG, CSV and JSONL export

## Requirements

- Windows with Bluetooth
- Python 3.12
- A LEGO Robot Inventor hub already flashed with Pybricks firmware

The hub accepts one Bluetooth connection at a time. Close any
`code.pybricks.com` tab before connecting.

## Setup

```powershell
git clone https://github.com/luminolous/pybricks-tracker
cd pybricks-tracker
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```powershell
python -m app.main
```

A window opens. Turn on the hub, click Connect, pick it from the list, click
Scan to detect what is plugged into each port, assign roles, then click Run.

## Development

```powershell
ruff check .
ruff format .
pytest
```

Tests run without a hub connected and without a display (Qt runs offscreen).

## How it works

The app has two layers that run in different places.

The desktop application is ordinary Python 3.12 on your laptop. The hub program
is MicroPython generated from a Jinja2 template, uploaded over Bluetooth, and
executed on the robot itself. Files under `app/codegen/templates/` never run on
the laptop.

See `.claude/docs/architecture.md` for the full picture.

## Calibration

Odometry accuracy determines whether the map means anything. Run the drift test
before trusting any recorded path, and apply the suggested `wheel_diameter` and
`axle_track` values.

Measured results for this robot:

| Test | Result |
|---|---|
| 500 mm square closure | not yet measured |
| 5 x 360 degree turns | not yet measured |

## Safety

The hub program stops the robot if no heartbeat arrives from the laptop for 2
seconds. The spacebar is a global E-STOP while a run is active.

## License

MIT
