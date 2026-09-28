# Line follower: how it runs

A map of everything that happens from the Run button to the motors, with links
to the code. Diagrams are Mermaid: they render on GitHub and in VS Code with a
Mermaid preview extension.

Line numbers were taken on 2026-09-28 (commit `6d54af0`). If the code moves,
search for the function name.

- [1. Two templates, one program](#1-two-templates-one-program)
- [2. From Run to a moving robot](#2-from-run-to-a-moving-robot)
- [3. The hub: main() and the 10 ms loop](#3-the-hub-main-and-the-10-ms-loop)
- [4. control_step(): one decision per loop](#4-control_step-one-decision-per-loop)
- [5. Reflection bands](#5-reflection-bands)
- [6. Steering maths](#6-steering-maths)
- [7. Which edge the robot follows](#7-which-edge-the-robot-follows)
- [8. track_route(): route steps L, R, S](#8-track_route-route-steps-l-r-s)
- [9. The S step across a crossing](#9-the-s-step-across-a-crossing)
- [10. Line search](#10-line-search)
- [11. Wall fallback](#11-wall-fallback)
- [12. The laptop while the robot drives](#12-the-laptop-while-the-robot-drives)
- [13. Walkthrough: route LRS with KP > 0](#13-walkthrough-route-lrs-with-kp--0)
- [14. Constants](#14-constants)

---

## 1. Two templates, one program

The hub runs one MicroPython file. It is built from two Jinja2 templates:

| File | Owns | Used by |
|---|---|---|
| [`_base.py.j2`](../app/codegen/templates/_base.py.j2) | devices, odometry, telemetry, command poll, **watchdog**, `main()`, `run_loop()` | every mode |
| [`line_follower.py.j2`](../app/codegen/templates/line_follower.py.j2) | `setup()` and `control_step()` plus their helpers | line follower only |

`line_follower.py.j2` starts with `{% extends "_base.py.j2" %}` and fills the
single `{% block control %}` hole in the base
([`_base.py.j2:326`](../app/codegen/templates/_base.py.j2#L326)). The other
modes (`teleop`, `drift_test`, `calibrate`) fill the same hole, so all four
share one loop, one protocol and one watchdog.

Why the split:

- **Safety.** CLAUDE.md requires a watchdog in every hub program. It lives once,
  in the base; a mode cannot ship without it and cannot redefine it.
- **One protocol.** `T`/`D`/`S`/`E` lines and the command parser are written
  once, so every mode speaks exactly what `app/core/protocol.py` decodes.
- **Small modes.** A mode only answers "what do I do this 10 ms?".

Why Jinja:

- **The hub cannot read the app's config.** Ports, motor directions,
  calibration, geometry, starting tuning values, the route and the sound switch
  are written into the program text (`{{ tuning.kp }}`, `{{ left.port }}`, ...).
- **Only the devices that exist.** `{% if distance %}` removes the ultrasonic
  code when no sensor is assigned; creating a device on an empty port raises
  `OSError` on the hub, and unused code costs RAM.
- **Errors show up on the laptop.** The environment uses `StrictUndefined`
  ([`generator.py:67`](../app/codegen/generator.py#L67)): a missing value fails
  at render time with a message in the UI, not as a crash on the robot.
- **One readable file.** The result, `build/hub_line_follower.py`, is complete
  and self-contained. It is what Ctrl+U shows, and hub traceback line numbers
  point into it.

Live changes (sliders) do not need a new render: they travel as commands
(`KP,1.5`) while the program runs. Jinja only sets the starting values.

```mermaid
flowchart LR
    subgraph UI["App (laptop)"]
        CFG["RobotConfig<br/>ports and directions, calibration,<br/>geometry, tuning sliders,<br/>route, sound"]
    end
    subgraph TPL["app/codegen/templates/"]
        BASE["_base.py.j2<br/>devices, pose, telemetry,<br/>commands, watchdog,<br/>main(), run_loop()"]
        LF["line_follower.py.j2<br/>extends _base<br/>block control: setup(),<br/>control_step()"]
    end
    CFG --> GEN["generator.render()<br/>Jinja fills values<br/>and drops unused devices"]
    BASE --> GEN
    LF --> GEN
    GEN --> OUT["build/hub_line_follower.py<br/>one MicroPython file"]
    OUT --> MPY["build_program()<br/>mpy-cross compile to .mpy"]
    MPY --> BLE["download_user_program()<br/>start_user_program()<br/>over BLE"]
    BLE --> HUB["Hub runs main()"]
```

Code: [`generate()`](../app/codegen/generator.py#L132),
[`render()`](../app/codegen/generator.py#L78),
[`build_program()`](../app/core/connection.py#L101),
[`run_file()`](../app/core/connection.py#L238).

---

## 2. From Run to a moving robot

```mermaid
sequenceDiagram
    actor User
    participant UI as App UI (Qt)
    participant BG as App background tasks
    participant Hub as Hub program

    User->>UI: Run (F5)
    UI->>UI: generate() writes build/hub_line_follower.py
    UI->>Hub: run_file(): compile, upload, start
    Hub-->>UI: R,LINE_FOLLOWER,1 (handshake, within 5 s)
    UI->>UI: clear map, start recording, sliders go live
    Note over Hub: beep, wait for IMU, reset origin, setup()

    loop every 10 ms on the hub
        Hub->>Hub: commands, watchdog, pose, sensors, control_step(), drive
    end

    par while the program runs
        BG->>Hub: HB every 500 ms
    and
        User->>UI: moves a slider
        BG->>Hub: KP,1.5 (at most 10 per s per key)
        Hub-->>BG: E,ACK,KP:1.5
    and
        Hub-->>UI: T 20 Hz, D 4 Hz, S 1 Hz, E on events
        UI->>UI: decode, record, redraw at ~30 fps
    end

    alt User presses Space (E-STOP) or Stop
        UI->>Hub: MODE,STOP then stop_user_program()
    else No command for 2 s
        Hub->>Hub: watchdog stops the robot, E,WDOG
    else Search fails, or finish reached
        Hub->>Hub: E,GIVEUP or E,FINISH, program ends
    end
```

Code: [`run_program()`](../app/ui/main_window.py#L636),
[`_handle_record()`](../app/ui/main_window.py#L1063) (the `Ready` branch),
[`stop_program()`](../app/ui/main_window.py#L678).

---

## 3. The hub: main() and the 10 ms loop

```mermaid
flowchart TD
    M0(["main()"]) --> M1["print R,LINE_FOLLOWER,1<br/>run beep"]
    M1 --> M2["wait_for_imu()<br/>stand still, keep serving commands<br/>and the watchdog"]
    M2 -->|"IMU ready"| M3["reset_origin()<br/>x = y = 0, heading = 0"]
    M2 -->|"STOP or watchdog"| MEND
    M3 --> M4["setup()<br/>STATE FOLLOW, first segment heading = now"]
    M4 --> L0

    subgraph LOOP["run_loop(): one pass every 10 ms"]
        L0["check_commands()<br/>HB, KP, KI, KD, SPD, INNER, IMIN, RAMP,<br/>SRCH, THR, FIN, LOCK, MODE, ORG, BEEP"]
        L0 --> L1{"STOPPED?"}
        L1 -->|"no"| L2{"command seen<br/>in the last 2 s?"}
        L2 -->|"yes"| L3["update_pose()<br/>wheel distance + gyro heading"]
        L3 --> L4["update_distance()<br/>ultrasonic every 10th pass"]
        L4 --> L5["read_reflection()"]
        L5 --> L6{"PAUSED?"}
        L6 -->|"no"| L7["control_step(n, refl)"]
        L6 -->|"yes"| L6B["robot.stop(), STATE IDLE"]
        L7 --> L8["telemetry<br/>every 5th: T + check_bump()<br/>every 25th: D + check_stall()<br/>every 100th: S"]
        L6B --> L8
        L8 --> L9["wait(10 ms minus the time used)"]
        L9 --> L0
    end

    L1 -->|"yes"| MEND
    L2 -->|"no"| WD["trip_watchdog()<br/>robot.stop(), E,WDOG"] --> MEND
    MEND(["robot.stop(), STATE STOP,<br/>last T line, program ends"])
```

Code: [`main()`](../app/codegen/templates/_base.py.j2#L332),
[`run_loop()`](../app/codegen/templates/_base.py.j2#L349),
[`check_commands()`](../app/codegen/templates/_base.py.j2#L228),
[`watchdog_ok()`](../app/codegen/templates/_base.py.j2#L293),
[`update_pose()`](../app/codegen/templates/_base.py.j2#L109).

Tuning commands are answered with `E,ACK,KEY:value`. A malformed value is
ignored: no ACK, the old value stays, the robot keeps driving.

---

## 4. control_step(): one decision per loop

Everything the line follower decides happens here, top to bottom, once per
10 ms. Each early `return` ends the pass; `run_loop()` then sends telemetry
and waits for the next one.

```mermaid
flowchart TD
    A(["control_step(n, refl)"]) --> W{"wall turn<br/>in progress?"}

    W -->|"yes"| W1["wall_turn_step()<br/>spin in place toward the target heading"]
    W1 --> W2{"within 3 degrees<br/>or 3 s passed?"}
    W2 -->|"no"| RET
    W2 -->|"yes"| W3["wall turn over: reset_steady()<br/>track_route() counts the step<br/>follow the edge of the turn just made<br/>STATE FOLLOW"]
    W3 --> W4{"sensor on<br/>full white?"}
    W4 -->|"yes"| W5["start_search()<br/>90 degrees back toward the old heading,<br/>then 45 past the start"] --> RET
    W4 -->|"no"| SR

    W -->|"no"| SR{"searching?"}
    SR -->|"no"| TR["track_route(refl)<br/>(section 8)"] --> OB
    SR -->|"yes"| OB

    OB{"distance below THR<br/>and wall armed?"}
    OB -->|"yes"| O1["stop, reset integral<br/>first time: E,OBS, magenta, beep"]
    O1 --> O2{"L or R step<br/>still pending?"}
    O2 -->|"yes"| O3["disarm this wall<br/>start_wall_turn()<br/>(section 11)"] --> RET
    O2 -->|"no (S or no route)"| O4["STATE OBSTACLE<br/>wait until it is gone"] --> RET
    OB -->|"no"| O5["distance at or above THR re-arms the wall<br/>clear the obstacle flag"] --> SE

    SE{"searching?"}
    SE -->|"yes"| SS["search_step(refl)<br/>(section 10)"] --> RET
    SE -->|"no"| E0["error = refl - EDGE"]

    E0 --> LW{"refl at or below<br/>WHITE_ABOVE?"}
    LW -->|"yes"| LW1["on_line()<br/>restart the lost clocks"] --> BAND
    LW -->|"no"| LOST{"white for more than 150 ms<br/>and 30 mm forward?"}
    LOST -->|"no"| BAND
    LOST -->|"yes"| FIN{"finish_reached()?<br/>FIN above 0, route done,<br/>FIN mm after the last step"}
    FIN -->|"yes"| F1["finish()<br/>stop, E,FINISH, green, beep"] --> RET
    FIN -->|"no"| F2["start_search(error)<br/>E,LOST, blue"] --> RET

    BAND{"full black or<br/>full white?"}
    BAND -->|"yes"| P1["FULL TURN<br/>direction = correction_dir(error)<br/>STEER = direction x arc_turn(full_turn_inner(direction))<br/>STATE PIVOT, red on black, green on white<br/>reset integral"]
    BAND -->|"no: grey edge band"| P2["PID<br/>edge switch pending: error = refl - SWITCH_TARGET<br/>integral += error x dt, capped at 50<br/>STEER = edge_flip() x (KP e + KI integral + KD delta e)<br/>clamped: never sharper than INNER, no wheel backwards<br/>STATE FOLLOW, yellow"]

    P1 --> LK{"S lock armed, or within<br/>60 mm after a crossing?"}
    P2 --> LK
    LK -->|"yes"| LK1["STEER = lock_heading(STEER)<br/>cut steering past LOCK degrees"] --> DRV
    LK -->|"no"| DRV["robot.drive(arc_speed(STEER), STEER)<br/>last_error = error"]
    DRV --> RET

    RET(["back to run_loop()"])
```

| Block | Lines |
|---|---|
| Wall turn in progress | [`458-472`](../app/codegen/templates/line_follower.py.j2#L458) |
| Route tracking | [`473-474`](../app/codegen/templates/line_follower.py.j2#L473) |
| Obstacle and wall fallback | [`476-498`](../app/codegen/templates/line_follower.py.j2#L476) (only rendered when a distance sensor is assigned) |
| Search | [`500-502`](../app/codegen/templates/line_follower.py.j2#L500) |
| Lost line and finish | [`504-512`](../app/codegen/templates/line_follower.py.j2#L504) |
| Full turn | [`514-521`](../app/codegen/templates/line_follower.py.j2#L514) |
| PID | [`522-531`](../app/codegen/templates/line_follower.py.j2#L522) |
| S lock | [`532-533`](../app/codegen/templates/line_follower.py.j2#L532) |
| Drive | [`534-535`](../app/codegen/templates/line_follower.py.j2#L534) |

The lost rule needs **both** time and distance: after a full turn the robot
sits on white next to the line while it swings back, which takes time but
barely moves it forward. Running off the line moves it forward.

---

## 5. Reflection bands

Computed from the calibration at
[`44-48`](../app/codegen/templates/line_follower.py.j2#L44). Example: black 3,
white 100.

```mermaid
flowchart LR
    B["0 to 26<br/>FULL BLACK<br/>full turn, red"] --- G["27 to 75<br/>GREY EDGE BAND<br/>PID, yellow<br/>target EDGE = 51"] --- Wh["76 to 100<br/>FULL WHITE<br/>full turn, green<br/>lost after 150 ms and 30 mm"]
```

| Name | Formula | Example |
|---|---|---|
| `EDGE` | (BLACK + WHITE) / 2 | 51 |
| `BLACK_BELOW` | (BLACK + EDGE) // 2 | 27 |
| `WHITE_ABOVE` | (WHITE + EDGE) // 2 | 75 |
| `SWITCH_TARGET` | BLACK_BELOW - 2 | 25 |

`error = refl - EDGE`: negative is too far onto the tape, positive is too far
onto the mat.

---

## 6. Steering maths

The outer wheel always runs at SPD; only the inner wheel slows. Steering is a
turn rate in deg/s (positive turns right).

| Function | Formula | Meaning |
|---|---|---|
| [`arc_turn(inner)`](../app/codegen/templates/line_follower.py.j2#L265) | SPD x (1 - inner) / axle, in deg/s | turn rate when the inner wheel runs at `inner` x SPD (1 = straight, 0 = stopped, below 0 = backwards) |
| [`arc_speed(turn)`](../app/codegen/templates/line_follower.py.j2#L271) | SPD - turn x axle / 2 | centre speed that keeps the outer wheel at SPD |
| [`swing_speed(turn)`](../app/codegen/templates/line_follower.py.j2#L277) | turn x axle / 2 | centre speed that pivots on a stopped inner wheel (search) |
| [`full_turn_inner(dir)`](../app/codegen/templates/line_follower.py.j2#L250) | INNER to IMIN over RAMP ms | the adaptive full turn |

Adaptive full turn:

```mermaid
flowchart LR
    S1["sensor goes full black or white"] --> S2["inner wheel at INNER %"]
    S2 -->|"stays off the edge, same direction"| S3["sharpens linearly<br/>toward IMIN % over RAMP ms"]
    S3 --> S4["held at IMIN %"]
    S2 -.->|"grey for more than 80 ms,<br/>or the direction flips"| S1
    S3 -.->|"grey for more than 80 ms,<br/>or the direction flips"| S1
```

A 90 degree corner is done before the turn sharpens much; a hairpin keeps
the sensor off the edge and gets the sharp turn.

PID output is clamped to `arc_turn(max(0, INNER) / 100)`
([`528`](../app/codegen/templates/line_follower.py.j2#L528)): never sharper
than the full turn and never with a wheel running backwards.

---

## 7. Which edge the robot follows

The robot follows one edge of the tape. **KP > 0 follows the left edge,
KP < 0 the right edge.** An edge follower takes its own side's branch at a
junction, which is how the route picks branches without a second sensor.

```mermaid
flowchart TD
    A["step i of ROUTE"] --> B{"side_of(i)"}
    B -->|"L"| L["left edge"]
    B -->|"R"| R["right edge"]
    B -->|"S, or past the last step"| K["None: KP's own edge"]
    L --> F["flip_for(i)<br/>+1 when that edge is KP's own edge<br/>-1 when it is the other one"]
    R --> F
    K --> F1["+1"]
    F --> E["edge_flip() = flip_for(_side_step)<br/>multiplies the PID steering"]
    F1 --> E
```

| KP sign | L step | R step | S step, after the route |
|---|---|---|---|
| KP > 0 (left edge) | +1 (left) | -1 (right) | +1 (left) |
| KP < 0 (right edge) | -1 (left) | +1 (right) | +1 (right) |

`_side_step` is the step whose edge is in use now. It trails `_step` until the
edge switch for the next step is done (section 8).

[`correction_dir(error)`](../app/codegen/templates/line_follower.py.j2#L282)
gives the direction of a full turn back to the edge, using the same KP sign
and `edge_flip()`, so full turns and PID always agree on the side.

Code: [`side_of()`](../app/codegen/templates/line_follower.py.j2#L170),
[`flip_for()`](../app/codegen/templates/line_follower.py.j2#L181),
[`edge_flip()`](../app/codegen/templates/line_follower.py.j2#L191).

---

## 8. track_route(): route steps L, R, S

Runs every pass unless a search is running
([`321`](../app/codegen/templates/line_follower.py.j2#L321)). Heading is in
the app frame: CCW-positive, so a right turn lowers it.

```mermaid
flowchart TD
    A(["track_route(refl)"]) --> T{"500 ms since<br/>the last steady test?"}
    T -->|"yes"| T1["steady = net heading change below 5 degrees<br/>remember the heading"] --> N
    T -->|"no"| N["near = heading within 30 degrees<br/>of the segment heading"]

    N --> AN{"near, steady and<br/>edge switch done?"}
    AN -->|"yes"| AN1["learn the real line heading:<br/>move the segment heading 1% toward the heading,<br/>kept within 15 degrees of the step's first guess"] --> SF
    AN -->|"no"| SF

    SF{"S next, not forced,<br/>edge switch not done?"}
    SF -->|"yes"| SF1{"120 mm or more<br/>since the last step?"}
    SF1 -->|"yes"| SF2["forced: drop the switch,<br/>arm the S lock on the current edge"] --> SW
    SF1 -->|"no"| SW
    SF -->|"no"| SW

    SW{"edge switch pending<br/>and not forced?"}
    SW -->|"no"| DN
    SW -->|"yes"| SA{"same physical edge?"}
    SA -->|"yes"| SA1["nothing to cross: switch done"] --> DN
    SA -->|"no"| RD{"near and steady?"}
    RD -->|"yes"| RD1["switch ready:<br/>PID aims at SWITCH_TARGET,<br/>the sensor walks into the tape"] --> BK
    RD -->|"no"| BK{"switch ready<br/>and full black?"}
    BK -->|"yes"| BK1["switch done: the new edge takes over<br/>and carries the sensor across the tape"] --> DN
    BK -->|"no"| DN

    DN{"route finished?"}
    DN -->|"yes"| RET(["return"])
    DN -->|"no"| K{"next step"}
    K -->|"S"| S1["mark the tape left after the switch<br/>mark settled when near and steady"]
    S1 --> S2{"straight_armed()?"}
    S2 -->|"yes"| S3["track_straight(refl)<br/>(section 9)"] --> RET
    S2 -->|"no"| RET
    K -->|"L or R"| C{"turned 60 degrees that way<br/>from the segment heading?"}
    C -->|"yes"| C1["segment heading -/+ 90 degrees: the next first guess<br/>step_taken(): E,TURN n/N"] --> RET
    C -->|"no"| RET
```

[`step_taken()`](../app/codegen/templates/line_follower.py.j2#L221) advances
`_step`, resets the switch, settle and force flags, stores the distance of the
step (for `S_FORCE_MM`) and, on the last step, the start of the finish
distance.

A turn is counted by the gyro, not by the junction: the edge makes the robot
take the branch, the heading change proves it did.

---

## 9. The S step across a crossing

At a four-way crossing the edge would pull the robot into a branch. S locks
the heading instead.

```mermaid
stateDiagram-v2
    [*] --> Settling: previous step taken
    Settling --> Switching: near and steady, the edge differs
    Settling --> Armed: near and steady, same edge
    Switching --> Armed: full black, new edge, then the sensor leaves black
    Settling --> Forced: 120 mm since the last step
    Switching --> Forced: 120 mm since the last step
    Forced --> Armed: near and steady
    Armed --> OnBlack: full black
    OnBlack --> Armed: black ends before 30 mm
    OnBlack --> Crossing: 30 mm of full black
    Crossing --> Hold: the sensor leaves black, step_taken()
    Hold --> [*]: 60 mm later the lock is released
```

While **Armed**, **OnBlack**, **Crossing** and **Hold**,
[`lock_heading()`](../app/codegen/templates/line_follower.py.j2#L209) sets to
zero any steering that would turn the robot further than LOCK degrees from
the segment heading. Steering back toward it is still allowed.

Code: [`straight_armed()`](../app/codegen/templates/line_follower.py.j2#L199),
[`track_straight()`](../app/codegen/templates/line_follower.py.j2#L233),
lock applied at [`532`](../app/codegen/templates/line_follower.py.j2#L532).

---

## 10. Line search

Started when the line is lost, or after a wall turn that ends on white. All
angles are measured by the gyro. The robot swings forward on the stopped inner
wheel at SRCH deg/s; it never backs up.

```mermaid
stateDiagram-v2
    [*] --> Sweep1: start_search(), E,LOST, blue
    Sweep1 --> Found: refl below EDGE
    Sweep1 --> Sweep2: turned the first sweep, stop, reverse
    Sweep2 --> Found: refl below EDGE
    Sweep2 --> GiveUp: turned first sweep plus back sweep
    Found --> [*]: E,FOUND, STATE FOLLOW, steady earned again
    GiveUp --> [*]: E,GIVEUP, beep, program ends
```

| Started by | First sweep | Direction | Return sweep |
|---|---|---|---|
| Lost line | 45 degrees | `correction_dir(error)`: the usual side of a corner | 45 + 180 degrees the other way |
| Wall turn ending on white | 90 degrees | back toward the old heading | 90 + 45 degrees the other way |

Code: [`start_search()`](../app/codegen/templates/line_follower.py.j2#L387),
[`search_step()`](../app/codegen/templates/line_follower.py.j2#L403).

---

## 11. Wall fallback

If the ultrasonic reads below THR while an L or R step is still pending, the
robot missed the branch and stands in front of the wall.

```mermaid
flowchart LR
    A["distance below THR,<br/>L or R pending"] --> B["stop, E,OBS<br/>disarm this wall"]
    B --> C["start_wall_turn()<br/>target = segment heading -/+ 90"]
    C --> D["wall_turn_step() every pass<br/>spin in place at 90 deg/s"]
    D -->|"within 3 degrees, or 3 s"| E["track_route() counts the step<br/>follow the new step's edge"]
    E -->|"sensor on the line"| F["follow"]
    E -->|"sensor on white"| G["search: 90 back, then 45 past"]
```

The wall is re-armed only once the distance reads THR or more again, so the
same wall cannot trigger a second turn. With S next, or no route, the robot
only waits (`STATE OBSTACLE`) until the way is clear.

Code: [`start_wall_turn()`](../app/codegen/templates/line_follower.py.j2#L432),
[`wall_turn_step()`](../app/codegen/templates/line_follower.py.j2#L442).

---

## 12. The laptop while the robot drives

All four tasks run on the qasync loop, started in
[`start()`](../app/ui/main_window.py#L566). No threads, and nothing blocks the
Qt thread.

```mermaid
flowchart LR
    subgraph APP["App (laptop)"]
        HB["run_heartbeat()<br/>HB every 500 ms"]
        TU["TuningSender.run()<br/>latest slider value per key,<br/>at most 10 per s, resend if no ACK in 1 s"]
        DR["_drain_lines()<br/>BLE chunks to lines,<br/>console, decode, record, state"]
        UI["_tick_ui() every 33 ms<br/>map, plots, readouts, events,<br/>battery, route progress, link banner"]
        ES["Space: E-STOP<br/>MODE,STOP then stop program"]
    end
    HUB["Hub run_loop()"]
    HB -->|"stdin"| HUB
    TU -->|"stdin"| HUB
    ES -->|"stdin + BLE stop"| HUB
    HUB -->|"stdout: T, D, S, E"| DR
    DR --> ST["RobotState"]
    DR --> REC["session recording"]
    ST --> UI
```

Code: [`run_heartbeat()`](../app/core/connection.py#L128),
[`TuningSender`](../app/core/tuning.py#L36),
[`_drain_lines()`](../app/ui/main_window.py#L1056),
[`_tick_ui()`](../app/ui/main_window.py#L1110).

If the laptop stalls, the robot keeps following the line on its own; the hub
watchdog stops it 2 s after the last command.

---

## 13. Walkthrough: route LRS with KP > 0

KP > 0 means the robot follows the **left** edge by default.

| Phase | Edge | What happens |
|---|---|---|
| Start, step 0 = **L** | left (KP's own) | No switch needed. At the junction the left edge leads into the left branch. At 60 degrees of left turn: `E,TURN 1/3 L`, segment heading +90. |
| Step 1 = **R** | right | After settling (within 30 degrees, steady for 500 ms), PID aims into the tape; on full black the right edge takes over. The right edge leads into the right branch: `E,TURN 2/3 R`. If a wall comes first: turn right on the spot. |
| Step 2 = **S** | left (KP's own) | Settle, switch back to the left edge (or force the lock after 120 mm). The lock arms. 30 mm of full black is the crossing; when the sensor leaves it, `E,TURN 3/3 S`. The lock holds for 60 mm more. |
| After the route | left (KP's own) | Plain line following. With FIN 0 there is no automatic finish: the run ends with Stop, E-STOP, or a search that gives up at the line end. |

---

## 14. Constants

Fixed in [`line_follower.py.j2`](../app/codegen/templates/line_follower.py.j2#L44):

| Constant | Value | Role |
|---|---|---|
| `LOST_MS` / `LOST_MM` | 150 / 30 | full white this long and this far means the line is lost |
| `SEARCH_FIRST_DEG` / `SEARCH_BACK_DEG` | 45 / 180 | search sweeps |
| `TURN_DONE_DEG` | 60 | heading change that counts an L or R step |
| `SETTLE_DEG` | 30 | "near" the segment heading |
| `STEADY_MS` / `STEADY_DEG` | 500 / 5 | steady: net heading change below 5 degrees in 500 ms |
| `ANCHOR_RATE` / `ANCHOR_MAX_DEG` | 0.01 / 15 | heading learning speed and limit |
| `SWITCH_TARGET` | BLACK_BELOW - 2 | PID target while walking into the tape |
| `WALL_TURN_RATE` / `WALL_TOL_DEG` / `WALL_TURN_MS` | 90 / 3 / 3000 | wall turn |
| `WALL_SEARCH_FIRST_DEG` / `WALL_SEARCH_BACK_DEG` | 90 / 45 | search after a wall turn |
| `CROSS_MM` | 30 | full black length that is a crossing |
| `LOCK_AFTER_MM` | 60 | lock held after the crossing |
| `S_FORCE_MM` | 120 | arm the S lock even if the edge switch is not done |
| `INTEGRAL_MAX` | 50 | KI anti-windup cap |
| `GRACE_MS` | 80 | grey time that restarts the adaptive full turn |

Live from the app (sliders, answered with `E,ACK`), declared in
[`_base.py.j2:56`](../app/codegen/templates/_base.py.j2#L56):

| Key | Variable | Role |
|---|---|---|
| `KP` `KI` `KD` | `KP` `KI` `KD` | PID in the grey band; KP sign picks the default edge |
| `SPD` | `BASE_SPEED` | outer wheel speed, mm/s |
| `INNER` `IMIN` `RAMP` | `INNER_PCT` `INNER_MIN_PCT` `INNER_RAMP_MS` | adaptive full turn |
| `SRCH` | `SEARCH_RATE` | search swing rate, deg/s |
| `THR` | `OBSTACLE_MM` | wall distance |
| `FIN` | `FINISH_MM` | finish distance after the last step, 0 = off |
| `LOCK` | `LOCK_DEG` | S heading lock, 5 to 60 degrees |

The route itself is fixed at Run.
