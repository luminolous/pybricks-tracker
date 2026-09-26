# Design

`main-window-mockup.html` is the approved main window layout (revision 3,
2026-09-23). Open it in a browser. It replays sample telemetry; the buttons
above the window toggle overlay, replay mode and link loss.

The Qt implementation in `app/ui/` follows this file. Where it disagrees with
`.claude/docs/ui-spec.md`, the mockup wins and the spec gets corrected.

Known deviations in the Qt build:

- Left column is 296 px, not 252. Port rows (device, role, direction) did not
  fit at real font metrics; at 276 px the direction combo covered the role
  combo's arrow. The device name now shrinks first.
- The readout strip has two more cells after state: `speed mm/s` and the turn
  rate (`inner % / search` for the line follower, `turn` for teleop and the
  drift test). They show what the running program drives at, using the
  values the hub acknowledged.
- The tuning panel shows one program's knobs at a time, with `Line / Teleop /
  Drift` buttons (small role, checked = accent) next to the caption. The line
  group ends with a route row of small mono chips (`chip` role): taken = accent
  fill, next = accent outline.
- Map ruler (not in the mockup): a small `role="small"` icon button pinned
  top-left of the plot, checked = accent. Measurement: dashed accent line,
  hollow end points, mono label on a surface-coloured box beside the midpoint.
- Header speaker button (not in the mockup), left of the battery: checked =
  hub sounds on (accent box), unchecked = muted (dim icon with a cross).
- Device names are shortened in the port table (`Motor`, `Ultrasonic`); the
  full name is the tooltip.

## Tokens

| Token | Hex | Use |
|---|---|---|
| window | `#0C1015` | window background |
| surface | `#0F141A` | header, side columns, readout strip |
| sunken | `#090D11` | map canvas, plot area, console |
| field | `#141A21` | inputs, dropdowns |
| line | `#1C242D` | hairline dividers |
| line-strong | `#2A343F` | control borders, major dividers |
| text | `#E4EAF0` | primary text |
| muted | `#8994A0` | labels |
| dim | `#5A6571` | tertiary text, axis labels |
| accent | `#3FD0E6` | interactive and active UI only, robot marker |
| trail | `#F4EFE4` | live trail |
| overlay | `#A48CFF` | previous-run overlay trail |
| warn | `#F2B344` | loop dt over 1.5x, unacknowledged tuning, SEARCH |
| danger | `#FF4D57` | E-STOP, REC, link loss, loop dt over 2x |
| ok | `#5FD39A` | connected, acknowledged, config valid |

## Type

- IBM Plex Sans for labels and text.
- IBM Plex Mono for every number, the console and protocol codes.
- Both are OFL licensed and bundled in `app/ui/fonts/` (from google/fonts;
  Plex Sans is the variable font). `OFL.txt` sits next to them.

## Rules

- One flat surface split by 1 px hairlines. No floating cards, no glow, no
  gradients. Corner radius 2 to 3 px at most.
- Uppercase letter-spaced text only for section titles.
- Cyan never marks data. The trail is warm white so it cannot blend with
  chrome or with the `color` trail mode.
- Red is reserved for stopping and danger.
- Plots live in tabs (Reflection, Error / steer, Motor load, Loop dt), not
  stacked with per-plot toggles.
