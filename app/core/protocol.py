"""Wire protocol encode and decode.

Authoritative spec: .claude/docs/protocol.md. This module and the hub
templates both implement it; change the spec first.

M1 decodes `P` (port scan) and `R` (ready handshake). Other prefixes are
added with the templates that emit them. Anything unrecognised decodes to
None and belongs in the console, never in an exception.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

PROTO_VERSION = 1
PORT_LETTERS = ("A", "B", "C", "D", "E", "F")


class DeviceKind(Enum):
    EMPTY = "empty"
    MOTOR = "motor"
    COLOR_SENSOR = "color_sensor"
    ULTRASONIC_SENSOR = "ultrasonic_sensor"
    FORCE_SENSOR = "force_sensor"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DeviceType:
    name: str
    kind: DeviceKind


# PUPDevice(port).info()["id"] -> device. PROVISIONAL: taken from the LEGO
# Powered Up type IDs used by Pybricks, not yet observed on this kit. Confirm
# with a real scan and record the result (see /hardware-log).
DEVICE_IDS: dict[int, DeviceType] = {
    0: DeviceType("empty", DeviceKind.EMPTY),
    48: DeviceType("Medium motor", DeviceKind.MOTOR),
    49: DeviceType("Large motor", DeviceKind.MOTOR),
    65: DeviceType("Small motor", DeviceKind.MOTOR),
    75: DeviceType("Medium angular motor", DeviceKind.MOTOR),
    76: DeviceType("Large angular motor", DeviceKind.MOTOR),
    61: DeviceType("Color sensor", DeviceKind.COLOR_SENSOR),
    62: DeviceType("Ultrasonic sensor", DeviceKind.ULTRASONIC_SENSOR),
    63: DeviceType("Force sensor", DeviceKind.FORCE_SENSOR),
}


def device_type(device_id: int) -> DeviceType:
    """Look up a device ID. Unknown IDs are logged so the table can grow."""
    known = DEVICE_IDS.get(device_id)
    if known is not None:
        return known
    logger.warning("Unknown PUP device id %d, add it to DEVICE_IDS", device_id)
    return DeviceType(f"unknown device ({device_id})", DeviceKind.UNKNOWN)


@dataclass(frozen=True)
class PortInfo:
    """`P,<port_letter>,<device_id>`"""

    port: str
    device_id: int


@dataclass(frozen=True)
class PortScanDone:
    """`P,DONE,0`"""


@dataclass(frozen=True)
class Ready:
    """`R,<mode>,<proto_version>`"""

    mode: str
    proto_version: int

    @property
    def compatible(self) -> bool:
        return self.proto_version == PROTO_VERSION


Record = PortInfo | PortScanDone | Ready


def decode_line(line: str) -> Record | None:
    """Decode one stdout line. Returns None for anything that is not a valid record."""
    text = line.strip()
    prefix, _, rest = text.partition(",")
    fields = rest.split(",") if rest else []
    try:
        if prefix == "P":
            return _decode_port(fields)
        if prefix == "R":
            mode = fields[0]
            return Ready(mode=mode, proto_version=int(fields[1])) if mode else None
    except (IndexError, ValueError):
        return None
    return None


def _decode_port(fields: list[str]) -> PortInfo | PortScanDone | None:
    port = fields[0]
    device_id = int(fields[1])
    if port == "DONE":
        return PortScanDone()
    if port not in PORT_LETTERS or device_id < 0:
        return None
    return PortInfo(port=port, device_id=device_id)
