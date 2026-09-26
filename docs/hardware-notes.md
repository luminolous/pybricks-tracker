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
- Teleop at the line follower's 50 mm/s felt too slow. Teleop got its own
  150 mm/s and 120 deg/s. Later replaced: SPD changes seemed to do nothing
  because the line follower mostly pivots, and pivot (180 deg/s) and search
  (150 deg/s) were fixed. First fix: turn rates as ratios of SPD. Final: each
  rate has its own slider (PIV, SRCH live on the hub; TURN for teleop; DSPD
  and DTRN for the drift test), shown per program; turns capped at 360 deg/s.
- The header battery gauge (linear 6.8-8.3 V guess) showed ~23 % at 7.12 V
  while Pybricks Code showed a healthy pack. Replaced by the hub's own
  low-voltage status flags, as Pybricks Code does; the voltage stays as text.
- Map marker (110 mm long) felt too big; now 65 mm.
- W forward, S back, A left (left wheel back, right forward), D right: all
  correct. So `DriveBase.drive(speed, turn)` turns right for a positive turn
  rate, as protocol.md's DRV sign assumes.

## 2026-09-23 — stage 3 (part 2): stopping (M3)

Robot on a box, teleop driving forward, then each stop path in turn. The user
reported that every one stopped the wheels safely:

- releasing the keys (hub dead-man, 300 ms)
- Space (E-STOP)
- closing the app mid-drive (app stops the program; hub watchdog as backup)
- losing the BLE link (hub watchdog)

**M3 acceptance: PASSED.**

## 2026-09-24 — wiring and motor directions

The robot was rewired and the user confirmed this config drives correctly (W
forward, turns the right way):

| Port | Device | Role |
|---|---|---|
| A | motor | left wheel, `COUNTERCLOCKWISE` |
| B | ultrasonic | distance, facing forward |
| D | motor | right wheel, `CLOCKWISE` |
| F | colour sensor | line, pointing down |

This is the usual Pybricks drive base setup. The first default (left CW,
right CCW, taken from the original script) reversed both motors: `drive(s, t)`
became `drive(-s, -t)` physically, so W drove backwards and every turn was
mirrored. The app defaults now use the wiring above.

Turn sign chain with this wiring, checked in the code:

- `DriveBase.drive(speed, turn)` and `robot.turn(angle)`: positive = right
  (clockwise from above). Teleop D and route `R` both send positive.
- `hub.imu.heading()` grows clockwise; the app frame negates it, so a right
  turn lowers the map heading. Route turns are counted on that sign.
- KP -1.5 (from the original script) now tracks the line's right edge, so the
  robot takes right branches by default. The original, with mirrored motors,
  tracked the left edge with the same KP. Line following works either way.

## 2026-09-24 — first line follower runs: search loop after every pivot

Two recorded runs (`sessions/20260924-044427_line_follower.jsonl`,
`20260924-044632_line_follower.jsonl`), SPD 50, KP -1.5, KD -5, PIV 180,
calibration black 9 / white 74 (edge 41), no route. The user saw the robot
"find the line, then back up and turn" over and over.

- 35 `LOST` events in the two runs; SEARCH was the most common state in the
  second run (264 T lines, against 114 FOLLOW).
- The cycle, every time: `PIVOT` on black (turn right at 180 deg/s), then
  `FOLLOW` with a left correction, but the heading kept going right by 10-20
  degrees in the next 150 ms (40 transitions measured). The sensor ran deep
  into white, the 150 ms lost timer fired, the robot backed up 20 mm and swept.
- Difference from the original script: it never called `use_gyro(True)`; the
  line follower template did. Fix: the line follower now drives with
  `use_gyro(False)`. Map heading and route turns still read `hub.imu`.
- Loop dt stayed 10-11 ms, so the loop was not the cause.
- White read 57-74 on the mat and 88-90 where the second run started: the
  surface varies (printed graphics on the mat). Recalibrate on the track.
- `OBS` fired at 40-44 mm five times with THR 50: something was close to the
  ultrasonic sensor; worth watching.

To confirm on the robot: the heading should stop turning within a few degrees
once PIVOT ends. If it still overshoots, lower PIV (live) before anything else.

Follow-up, same day: with `use_gyro(False)` (run `20260924-045427`, robot
started on the black line, route empty) the loop was unchanged: PIVOT, then
7-10 degrees of overshoot, LOST after 150 ms, back-up, sweep. So the gyro was
not the cause. The real one:

- The tape edge is sharp: leaving black, the sensor goes from ~8 straight to
  90+ within one 50 ms sample, so there is almost no edge band for the PD.
- After a 180 deg/s pivot the robot needs ~0.2-0.3 s to stop turning and swing
  back. The 150 ms lost timer is shorter, so every pivot exit counted as a lost
  line, although the line was right next to the sensor. The robot moved only
  ~5 mm forward in that time.

Fix: lost now needs 150 ms on white **and** 30 mm of forward travel on white
(`LOST_MM`). Swinging back after a pivot barely moves the robot forward; a
real line end or 90 degree corner does. `use_gyro(False)` stays, as in the
original script.

Second change, on request: no wheel runs backwards in the line follower. The
pivot in place (one wheel back) and the 20 mm back-up before a search made the
robot look like it reversed every time it flipped between black and white.

- Every turn keeps the outer wheel at SPD and only slows the inner one.
- On black: the sharpest turn, inner wheel at INNER % of SPD (default 20),
  both forward. At SPD 50 and a 112 mm axle track that is ~20 deg/s (the old
  pivot was 180). `INNER` replaces the old `PIV` command and slider.
- FOLLOW: the PD turn rate is capped at that same turn, so black always turns
  hardest. Without a wheel going backwards the turn rate is bounded by
  SPD / axle track: raise SPD or lower INNER for sharper corners.
- Search: no back-up; it swings on the stopped inner wheel at SRCH (default
  now 60 deg/s, ~59 mm/s forward). Old presets keep their SRCH 150, which
  swings at ~150 mm/s: set it back to ~60.
- The wall fallback turn (route) still turns in place, with the robot stopped
  in front of the wall.

KP sign and the edge (with the real wiring): negative KP turns right on black
and left on white, so the robot runs along the line's right edge, black on
its left. Positive KP runs the left edge.

## 2026-09-25 — review of the arc-turn runs

Recordings `20260924-0502..0525`, the last ones with INNER 20 at SPD 250.

- The LOST_MM fix worked: a 60 s run at SPD 160 (still pivoting) had 4 LOST,
  against 17 in 30 s before.
- At SPD 250 the arc runs lost the line often (19 LOST in 41 s). The robot
  reached only ~60-65 % of the commanded turn rate (motor acceleration), and
  moves 150-250 mm/s forward. Suggested SPD 100-150 for now.
- On full white the PD turned at KP * error = 73 deg/s, on black at the full
  102 deg/s: coming back from white was slower than leaving black, and nearly
  every LOST started there. Full white now gets the same sharpest arc as full
  black (state PIVOT, hub light green); PD only works in the grey band.
- One 13 s stretch read reflection 0 with the heading wandering while a right
  turn was commanded: the robot was lifted. Reflection 0 means no surface
  under the sensor, which the line follower takes as black.

## 2026-09-26 — battery ran flat at 6.0 V

A calibration run (`sessions/20260926-085612_calibrate.jsonl`) started at
6.02 V and the hub switched itself off at 6.00 V. The line follower runs on
2026-09-24 were already at 6.8 V. The readings were right: the hub protects
the Li-ion pack. Pybricks thresholds for LEGO rechargeable packs (from the
firmware, matching what we saw): full 8.19 V, OK above 7.2 V, low-voltage
warning below 6.8 V, shutdown at 6.0 V. Voltage sags under motor load, so the
hub can cut out mid-run around 6.1-6.2 V at rest.

The header icon used to show only the flags, so it stayed orange from 6.8 V
until the hub died. Now the fill follows the voltage from 6.0 V (empty) to
8.19 V (full), turns red below 6.3 V, and the console warns once: charge now.

## 2026-09-26 — top route, U-turn at the yellow junction

Route `LRS`, KP +1.5 (left edge), SPD 70-100, THR 140. In most runs the robot
U-turned at the yellow junction; LOCK (10-20) made no difference, it only acts
before an `S`. The recording (`20260926-104804`) shows why:

- The robot had started the left turn on its own (PIVOT left on black) when
  the ultrasonic saw the yellow wall at 125 mm (THR 140) and started the wall
  fallback turn.
- `robot.turn(90)` did 64 degrees by the gyro (the axle track is still wrong),
  leaving the sensor on white just left of the branch line.
- The robot then tracked the next step's edge, took the line to be on its
  left, turned left on white, lost the line and swept left: 170 degrees, a
  U-turn.

Fix: the wall turn now runs by the gyro to the planned heading, and if the
sensor is off the line it sweeps 45 degrees back toward the old heading first.
Search sweeps are measured by the gyro too. Keep THR small (50-80 mm) so the
fallback only fires when the branch was really missed.

## 2026-09-26 — the hairpin after the zigzag

Run `20260926-110245` (route `LRS`, KP +1.5, SPD 100, INNER 20). The zigzag
went through with many LOST/FOUND; at the hairpin (~135 degrees left) the
robot cut through the line's arm and lost it, then swept right, the wrong way,
until stopped.

- Without a wheel going backwards the tightest radius is fixed by geometry:
  R = axle/2 * (1 + inner) / (1 - inner). INNER 20 % gives 84 mm with the
  configured 112 mm axle (~120 mm with the real ~160 mm). Too wide for the
  hairpin. Speed does not change the radius.
- From one sensor, "cut through a hairpin" and "reached a corner" look the
  same when the line is lost (same black-then-white pattern in the zigzag).

Changes: INNER may go below 0 (inner wheel backwards, -100 = spin in place),
only for the full turn on black or white; PD steering never reverses a wheel.
The search sweeps 45 degrees to the usual side first, then back to 180 past
the start, instead of 120 then 240. The drift test gave axle 159.49 mm three
times; apply it (after the straight test) before tuning INNER.

## 2026-09-26 — off the track after the green-wall corner

Run `20260926-120219` (route `LRS`, KP +1.5, INNER -10, SPD 70, axle 158.8
applied). After the R corner at the green wall the robot drifted right off
the line. Two bugs in the route logic, not INNER:

- The S heading lock armed as soon as the R turn counted (at 60 degrees),
  with the heading still 30 degrees from the new segment. Steering back left
  toward the line was cut to 0.
- The edge switch (R step: right edge, then KP's left edge for S) happened
  on white, with the sensor right of the line. The left-edge control took the
  line to be on its right and turned right, away from it.

Fix: the edge switch waits until the robot has settled AND the sensor is on
full black, so the new edge's control carries it across the tape. The S lock
and crossing detection arm only after that switch and once the sensor has left
black again. INNER below 0 makes every full turn sharper, the green corner
included: keep it at 0-20 unless a hairpin needs more.

## 2026-09-26 — INNER -20/-25/-30 runs

Runs `20260926-1248..1252` (route `LRS`, KP +1.5, SPD 75, THR 100). With
INNER -25 and -30 the robot never reached the green wall: every failure was
step 1, the first junction wall.

- The natural left turn is too slow to finish before the wall, so the wall
  fallback turns the robot in every run (OBS at 96-99 mm).
- After the in-place turn the branch is ahead and to the old-heading side.
  In the run that worked, the line appeared 40-45 degrees into the 45 degree
  first sweep: luck. In the others the sweep ended just short, the return
  sweep went the wrong way, and the robot gave up.
- Fix: first sweep 90 degrees toward the old heading, then 45 past the start
  the other way. Telemetry now keeps SEARCH during that search (it showed
  FOLLOW once the wall was out of range).
- INNER is still one value for every full turn: -20 reached the hairpin but
  did not take it cleanly.
- Added an adaptive full turn: it starts at INNER and sharpens toward IMIN
  (default -40 %) over RAMP ms (default 400) while the sensor stays on full
  black or white turning the same way; grey for 80 ms or a direction flip
  starts it over. Suggested start: INNER 20, IMIN -40, RAMP 400.

## 2026-09-26 — green wall: late turn, and headings that are not square

Runs `20260926-1322..1331`, same settings. The three that failed at the green
wall all turned there by the wall fallback (OBS 70-78 mm), then lost the line
about a second later; the three that turned naturally went on.

By the gyro, the top line (green wall to crossing) runs at about +10 degrees,
not the ideal 0, and the start heading varies by a few degrees per run. With
LOCK 12 around 0, the S lock left 2 degrees of room on the real line and cut
the steering when the robot needed it; the wall turn aimed at 0 too.

Fix: the segment heading is learnt from the gyro while the robot follows a
line steadily (~1 s), and the ideal heading after a turn is only a first
guess. The edge switch needs the heading within 30 degrees and steady (< 6
degrees per 100 ms); S arms after 100 mm on the new line; the wall turn and
turn counting use the learnt heading.

Regression, same day (runs `20260926-1339..1343`): the robot turned LEFT at
the green wall. The heading learning followed the slow natural L turn at the
yellow junction (~20 deg/s passed the 100 ms steady test), the segment heading
trailed ~20 degrees behind, and the turn never reached 60 degrees, so it was
never counted. At the green wall the fallback then turned the step still
pending: L. Run 1341 missed the R the same way and turned at the crossing.
Fix: steady is a net change under 5 degrees over 500 ms, and the learnt
heading stays within 15 degrees of the step's first guess. Replaying the
recorded headings through the new rule counts the L in 1343 (19.0 s, before
the green wall) and the L and R in 1341.

Run `20260926-135003`: the L at the yellow junction now counted by itself,
and the green-wall fallback turned right as planned. Right after it the robot
turned round: the steady flag was stale (set while it drove north before the
wall; nothing updates it during the wall turn), so the edge switch to the S
edge fired at the end of the turn while the robot still rotated. The sensor
slid off the right side of the top line and the left-edge control turned right
to -49 degrees. Fix: steady is reset at the end of every wall turn and when a
search starts or finds the line, so it has to be earned over 500 ms again.
Note: INNER was -40 (= IMIN) in this run, which makes every full turn sharp.

## 2026-09-26 — review against the version that kept working

The runs that "kept working" (13:10 and 13:22-13:31 UTC) were on commit
3731e0a, before heading learning. Even there 3 of 6 runs failed at the green
wall. Comparing the vertical segment (yellow junction to green wall) in all
runs: the good runs had switched to the right edge (39-60 full-black
samples), the failed ones were still on the left edge (2-3 full-black
samples) and ran past the right branch into the wall. The edge switch waited
for the sensor to reach full black by chance, which never happens when the
edge is tracked smoothly (bug since 50c2d0a). That also explains the robot
getting very close to the wall in failed runs: it had already passed the
branch; THR worked (OBS at 77 mm with THR 80).

Run 13:54 reached the crossing but turned into its left branch: the S lock
waited for the edge switch plus 100 mm, too late on the short top segment.

Fixes: the edge switch is active (once settled, the old edge aims darker so
the sensor walks into the tape, switching on black; the replay of three
failed runs gives ~2 s of margin before the green wall); S keeps the edge of
the turn before it and arms as soon as the robot is settled (no 100 mm); after
a wall turn the robot follows the edge of the turn it just made.

## 2026-09-26 — first finish with the active edge switch

Run `20260926-141553`: L, R and S all counted and the robot reached the
finish. Two bugs showed:

- After the last step it stayed on the right edge (the R edge that S keeps)
  all the way to the finish: 153 white samples, all corrected to the left.
  After the route the robot now switches back to KP's own edge.
- The S lock was released the moment the sensor left the crossing, with the
  heading at -16 degrees. It lost the line and during the search the gyro
  barely moved while the wheels ran (STALL L): pushing against a wall stand.
  The lock now holds 60 mm past the crossing.

Also: the test ids for the hub source checks were the whole program; the line
follower grew past Windows' 32767-character environment limit
(PYTEST_CURRENT_TEST). The ids are now the program names.

Correction, same day (run `20260926-142702`): letting S borrow the R edge was
wrong. From the green wall on the robot ran on the right edge (steer vs error
sign: 0 % same-sign on the top segment), and right after the crossing it lost
the line and pushed into a stand (4 x STALL L, gyro still, wheels turning) in
both runs that way. The runs on 3731e0a used KP's own edge for S and went
through the crossing cleanly. S now uses KP's edge again; the switch after
the R is active, and if it is not done 120 mm after the R the lock arms on the
current edge and the switch follows after the crossing. The same/different
edge test now compares physical edges (for KP > 0, L is KP's edge), not step
letters.
