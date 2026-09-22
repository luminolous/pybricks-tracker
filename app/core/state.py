"""RobotState, SessionState, Pose, EventRecord.

M1 holds only the port scan result. Pose and telemetry arrive with M2/M4.
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
