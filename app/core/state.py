"""RobotState, SessionState, Pose, EventRecord.

Holds the port scan result and the telemetry watch. Pose history arrives
with M4.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.protocol import PORT_LETTERS, DeviceType, PortInfo, PortScanDone, device_type


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
