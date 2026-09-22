"""Wire protocol encode and decode.

Authoritative spec: .claude/docs/protocol.md. This module and the hub
templates both implement it; change the spec first.

Decodes `P`, `R`, `T` and `E`. `D` and `S` arrive with M5. Anything
unrecognised decodes to None and belongs in the console, never in an
exception.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

PROTO_VERSION = 1
PORT_LETTERS = ("A", "B", "C", "D", "E", "F")
# Every hub-to-PC prefix in protocol.md, decoded yet or not.
PROTOCOL_PREFIXES = frozenset({"T", "D", "E", "S", "P", "R"})


def is_protocol_line(line: str) -> bool:
    """True when the line carries a protocol prefix; debug prints return False."""
    return line.strip().partition(",")[0] in PROTOCOL_PREFIXES


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


@dataclass(frozen=True)
class Telemetry:
    """`T,<t_ms>,<x_mm>,<y_mm>,<heading_deg>,<reflection>,<steer>,<state>`"""

    t_ms: int
    x_mm: float
    y_mm: float
    heading_deg: float
    reflection: int
    steer: int
    state: str


EVENT_KINDS = frozenset({"LOST", "FOUND", "GIVEUP", "OBS", "STALL", "BUMP", "LAP", "WDOG"})


@dataclass(frozen=True)
class Event:
    """`E,<kind>,<t_ms>,<x_mm>,<y_mm>[,<detail>]`"""

    kind: str
    t_ms: int
    x_mm: float
    y_mm: float
    detail: str | None = None


Record = PortInfo | PortScanDone | Ready | Telemetry | Event


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
        if prefix == "T":
            return _decode_telemetry(fields)
        if prefix == "E":
            return _decode_event(fields)
    except (IndexError, ValueError):
        return None
    return None


def _decode_telemetry(fields: list[str]) -> Telemetry | None:
    state = fields[6]
    if not state:
        return None
    return Telemetry(
        t_ms=int(fields[0]),
        x_mm=float(fields[1]),
        y_mm=float(fields[2]),
        heading_deg=float(fields[3]),
        reflection=int(fields[4]),
        steer=int(fields[5]),
        state=state,
    )


def _decode_event(fields: list[str]) -> Event | None:
    kind = fields[0]
    if kind not in EVENT_KINDS:
        return None
    detail = fields[4] if len(fields) > 4 and fields[4] else None
    return Event(
        kind=kind,
        t_ms=int(fields[1]),
        x_mm=float(fields[2]),
        y_mm=float(fields[3]),
        detail=detail,
    )


COMMAND_KEYS = frozenset({"KP", "KD", "SPD", "THR", "MODE", "HB", "ORG"})
MODE_VALUES = frozenset({"STOP", "PAUSE", "RESUME"})


def encode_command(key: str, value: float | int | str | None = None) -> str:
    """Build one PC-to-hub command line, without the line ending (the connection adds it)."""
    if key not in COMMAND_KEYS:
        raise ValueError(f"unknown command {key!r}")
    if value is None:
        return key
    if key == "MODE" and value not in MODE_VALUES:
        raise ValueError(f"unknown mode {value!r}")
    if isinstance(value, float):
        value = f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{key},{value}"


def _decode_port(fields: list[str]) -> PortInfo | PortScanDone | None:
    port = fields[0]
    device_id = int(fields[1])
    if port == "DONE":
        return PortScanDone()
    if port not in PORT_LETTERS or device_id < 0:
        return None
    return PortInfo(port=port, device_id=device_id)
