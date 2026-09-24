"""RobotState, SessionState, Pose, EventRecord.

Holds the port scan result, the telemetry watch, and the live robot state:
pose, trail, events and plot history.
"""

from __future__ import annotations

import itertools
import math
from collections import deque
from dataclasses import dataclass, field

from app.core.protocol import (
    PORT_LETTERS,
    Detail,
    DeviceType,
    Event,
    PortInfo,
    PortScanDone,
    Status,
    Telemetry,
    device_type,
)


@dataclass
class PortScan:
    """Accumulates `P` lines from scan_ports.py into one result per port."""

    device_ids: dict[str, int] = field(default_factory=dict)
    done: bool = False

    def reset(self) -> None:
        self.device_ids.clear()
        self.done = False

    def apply(self, record: object) -> bool:
        """Apply a decoded record. Returns True when the record belonged to the scan."""
        if isinstance(record, PortInfo):
            self.device_ids[record.port] = record.device_id
            return True
        if isinstance(record, PortScanDone):
            self.done = True
            return True
        return False

    def device(self, port: str) -> DeviceType | None:
        """Detected device on `port`, or None when the scan has not reported it."""
        device_id = self.device_ids.get(port)
        return None if device_id is None else device_type(device_id)

    @property
    def missing_ports(self) -> list[str]:
        """Ports the finished scan never reported. Non-empty means a lost line."""
        return [p for p in PORT_LETTERS if p not in self.device_ids]


TELEMETRY_TIMEOUT_S = 2.0  # protocol.md: 2 s without T means the link is lost


class TelemetryWatch:
    """Tracks silence on the T stream of a running mode program.

    Armed by the mode's R handshake (scan_ports never sends T), disarmed when
    the program ends. Times are monotonic seconds supplied by the caller.
    """

    def __init__(self, timeout_s: float = TELEMETRY_TIMEOUT_S) -> None:
        self.timeout_s = timeout_s
        self.armed = False
        self._last_s = 0.0

    def arm(self, now_s: float) -> None:
        self.armed = True
        self._last_s = now_s

    def disarm(self) -> None:
        self.armed = False

    def saw_telemetry(self, now_s: float) -> None:
        self._last_s = now_s

    def silence_s(self, now_s: float) -> float:
        return now_s - self._last_s if self.armed else 0.0

    def lost(self, now_s: float) -> bool:
        return self.armed and self.silence_s(now_s) >= self.timeout_s


MAX_TRAIL_POINTS = 36_000  # 30 minutes of T at 20 Hz
MAX_EVENTS = 2_000
LISTED_EVENT_KINDS = frozenset(
    {"LOST", "FOUND", "GIVEUP", "OBS", "STALL", "BUMP", "LAP", "WDOG", "TURN", "FINISH"}
)
# One counter for every RobotState: the map and plots skip redraws by
# version, and replay swaps state objects, so versions must never repeat.
_versions = itertools.count(1)


@dataclass(frozen=True)
class EventRecord:
    kind: str
    t_ms: int
    x_mm: float
    y_mm: float
    heading_deg: float  # robot heading when it happened; places OBS points
    detail: str | None = None

    def route_step(self) -> int | None:
        """Turns taken so far, from a TURN detail like "2/4 L"; None otherwise."""
        if self.kind != "TURN" or not self.detail:
            return None
        try:
            return int(self.detail.split("/", 1)[0])
        except ValueError:
            return None

    def describe(self) -> str:
        d = self.detail
        return {
            "LOST": "Line lost, searching",
            "FOUND": "Line found",
            "GIVEUP": "Search failed, robot stopped",
            "OBS": f"Obstacle at {d} mm",
            "STALL": f"{'Left' if d == 'L' else 'Right' if d == 'R' else 'A'} motor stalled",
            "BUMP": f"Bump, {d} mm/s²",
            "LAP": f"Lap {d}",
            "WDOG": f"Watchdog stop after {d} ms without commands",
            "TURN": f"Route turn {d}",
            "FINISH": f"Finish, {d} mm after the last turn",
        }.get(self.kind, self.kind)


HISTORY_S = 10.0  # plots show the last 10 seconds (ui-spec)


class History:
    """Samples of one stream over the last HISTORY_S seconds, by hub time."""

    def __init__(self, window_s: float = HISTORY_S) -> None:
        self.window_ms = window_s * 1000
        self.t_ms: deque[int] = deque()
        self.values: deque[tuple[float, ...]] = deque()

    def add(self, t_ms: int, *values: float) -> None:
        if self.t_ms and t_ms < self.t_ms[-1]:
            self.clear()  # hub clock restarted: a new program
        self.t_ms.append(t_ms)
        self.values.append(values)
        while self.t_ms and self.t_ms[0] < t_ms - self.window_ms:
            self.t_ms.popleft()
            self.values.popleft()

    def clear(self) -> None:
        self.t_ms.clear()
        self.values.clear()

    def column(self, index: int) -> list[float]:
        return [v[index] for v in self.values]

    def recent(self, index: int, window_ms: float) -> list[float]:
        """Values of one column from the last `window_ms` before the newest sample."""
        if not self.t_ms:
            return []
        start = self.t_ms[-1] - window_ms
        return [v[index] for t, v in zip(self.t_ms, self.values, strict=True) if t >= start]


@dataclass(frozen=True)
class Pose:
    t_ms: int
    x_mm: float
    y_mm: float
    heading_deg: float
    # What the trail colouring modes need, captured per sample:
    reflection: int = 0
    steer: int = 0
    speed_mm_s: float = 0.0  # from the distance to the previous sample (T has no speed)
    hsv: tuple[int, int, int] | None = None  # latest D reading at this moment


class RobotState:
    """Live pose, trail and hub status, fed by decoded records.

    The trail only grows once the IMU reports ready: heading is meaningless
    before that (protocol.md, S line). `version` changes whenever something
    drawable changed, so the UI can skip redraws.
    """

    def __init__(self, max_points: int = MAX_TRAIL_POINTS) -> None:
        self.max_points = max_points
        self.trail: list[Pose] = []
        self.pose: Pose | None = None
        self.imu_ready = False
        self.battery_mv: int | None = None
        self.detail: Detail | None = None
        self.reflection: int | None = None
        self.last_t: Telemetry | None = None
        self.events: list[EventRecord] = []
        self._clear_run_totals()
        # (reflection, steer) from T at 20 Hz; (load_left, load_right, dt_ms) from D at 4 Hz
        self.fast = History()
        self.slow = History()
        self.version = next(_versions)

    def _changed(self) -> None:
        self.version = next(_versions)

    def _clear_run_totals(self) -> None:
        # Running sums over the trail, so run metrics cost O(1) at 30 fps.
        self.path_mm = 0.0
        self.reflection_n = 0
        self.reflection_sum = 0.0
        self.reflection_sq_sum = 0.0

    def reset(self) -> None:
        """New run: forget the trail and the IMU state, keep the battery reading."""
        self.trail.clear()
        self.pose = None
        self.imu_ready = False
        self.detail = None
        self.reflection = None
        self.last_t = None
        self.events.clear()
        self.fast.clear()
        self.slow.clear()
        self._clear_run_totals()
        self._changed()

    def reset_origin(self) -> None:
        """The hub moved its origin (ORG): the old trail is in another frame."""
        self.trail.clear()
        self._clear_run_totals()
        self._changed()

    def apply(self, record: object) -> bool:
        """Apply a decoded record. Returns True when it changed the state."""
        if isinstance(record, Status):
            self.imu_ready = record.imu_ready
            self.battery_mv = record.battery_mv
            self._changed()
            return True
        if isinstance(record, Detail):
            self.detail = record
            self.slow.add(record.t_ms, record.load_left, record.load_right, record.dt_ms)
            self._changed()
            return True
        if isinstance(record, Event):
            if record.kind not in LISTED_EVENT_KINDS:
                return False  # ACK is bookkeeping, not an event (protocol.md)
            heading = self.pose.heading_deg if self.pose else 0.0
            self.events.append(
                EventRecord(
                    record.kind, record.t_ms, record.x_mm, record.y_mm, heading, record.detail
                )
            )
            del self.events[:-MAX_EVENTS]
            self._changed()
            return True
        if isinstance(record, Telemetry):
            previous = self.pose
            step_mm = 0.0
            speed = 0.0
            if previous is not None:
                step_mm = math.hypot(record.x_mm - previous.x_mm, record.y_mm - previous.y_mm)
                dt_ms = record.t_ms - previous.t_ms
                speed = step_mm / dt_ms * 1000 if dt_ms > 0 else previous.speed_mm_s
            d = self.detail
            pose = Pose(
                record.t_ms,
                record.x_mm,
                record.y_mm,
                record.heading_deg,
                record.reflection,
                record.steer,
                speed,
                (d.hue, d.saturation, d.value) if d else None,
            )
            self.pose = pose
            self.reflection = record.reflection
            self.last_t = record
            self.fast.add(record.t_ms, record.reflection, record.steer)
            if self.imu_ready:
                if self.trail:
                    self.path_mm += step_mm
                self.reflection_n += 1
                self.reflection_sum += record.reflection
                self.reflection_sq_sum += record.reflection**2
                self.trail.append(pose)
                if len(self.trail) > self.max_points:
                    del self.trail[: len(self.trail) - self.max_points]
            self._changed()
            return True
        return False
