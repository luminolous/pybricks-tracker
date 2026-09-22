"""PortScan accumulation from decoded P lines."""

from __future__ import annotations

from app.core.protocol import DeviceKind, Ready, decode_line
from app.core.state import PortScan

SCAN_OUTPUT = ["R,SCAN,1", "P,A,0", "P,B,0", "P,C,48", "P,D,61", "P,E,62", "P,F,48", "P,DONE,0"]


def run_scan(lines: list[str]) -> PortScan:
    scan = PortScan()
    for line in lines:
        scan.apply(decode_line(line))
    return scan


def test_full_scan() -> None:
    scan = run_scan(SCAN_OUTPUT)
    assert scan.done
    assert scan.missing_ports == []
    assert scan.device("A").kind is DeviceKind.EMPTY
    assert scan.device("C").kind is DeviceKind.MOTOR
    assert scan.device("D").kind is DeviceKind.COLOR_SENSOR
    assert scan.device("E").kind is DeviceKind.ULTRASONIC_SENSOR


def test_rescan_shows_unplugged_sensor() -> None:
    scan = run_scan(SCAN_OUTPUT)
    scan.reset()
    for line in ["P,A,0", "P,B,0", "P,C,48", "P,D,0", "P,E,62", "P,F,48", "P,DONE,0"]:
        scan.apply(decode_line(line))
    assert scan.device("D").kind is DeviceKind.EMPTY


def test_lost_line_shows_as_missing_port() -> None:
    scan = run_scan([line for line in SCAN_OUTPUT if not line.startswith("P,E")])
    assert scan.done
    assert scan.missing_ports == ["E"]
    assert scan.device("E") is None


def test_ignores_non_scan_records() -> None:
    scan = PortScan()
    assert not scan.apply(Ready(mode="SCAN", proto_version=1))
    assert not scan.apply(None)
    assert scan.device_ids == {}
