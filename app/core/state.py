"""RobotState, SessionState, Pose, EventRecord.

Holds the port scan result and the telemetry watch. Pose history arrives
with M4.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.protocol import (
    PORT_LETTERS,
    DeviceType,
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


@dataclass(frozen=True)
class Pose:
    t_ms: int
    x_mm: float
    y_mm: float
    heading_deg: float


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
        self.version = 0

    def reset(self) -> None:
        """New run: forget the trail and the IMU state, keep the battery reading."""
        self.trail.clear()
        self.pose = None
        self.imu_ready = False
        self.version += 1

    def reset_origin(self) -> None:
        """The hub moved its origin (ORG): the old trail is in another frame."""
        self.trail.clear()
        self.version += 1

    def apply(self, record: object) -> bool:
        """Apply a decoded record. Returns True when it changed the state."""
        if isinstance(record, Status):
            self.imu_ready = record.imu_ready
            self.battery_mv = record.battery_mv
            self.version += 1
            return True
        if isinstance(record, Telemetry):
            pose = Pose(record.t_ms, record.x_mm, record.y_mm, record.heading_deg)
            self.pose = pose
            if self.imu_ready:
                self.trail.append(pose)
                if len(self.trail) > self.max_points:
                    del self.trail[: len(self.trail) - self.max_points]
            self.version += 1
            return True
        return False
