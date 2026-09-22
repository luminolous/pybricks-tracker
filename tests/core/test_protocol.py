"""Decoder tests. Every malformed variant must return None, never raise."""

from __future__ import annotations

import pytest

from app.core.protocol import (
    PROTO_VERSION,
    DeviceKind,
    PortInfo,
    PortScanDone,
    Ready,
    decode_line,
    device_type,
)


def test_decode_port_line() -> None:
    assert decode_line("P,C,48") == PortInfo(port="C", device_id=48)


def test_decode_empty_port() -> None:
    assert decode_line("P,A,0") == PortInfo(port="A", device_id=0)


def test_decode_scan_done() -> None:
    assert decode_line("P,DONE,0") == PortScanDone()


def test_decode_ready() -> None:
    record = decode_line(f"R,SCAN,{PROTO_VERSION}")
    assert record == Ready(mode="SCAN", proto_version=PROTO_VERSION)
    assert record.compatible


def test_ready_with_other_version_is_incompatible() -> None:
    record = decode_line(f"R,SCAN,{PROTO_VERSION + 1}")
    assert isinstance(record, Ready)
    assert not record.compatible


def test_strips_cr_and_whitespace() -> None:
    assert decode_line("  P,D,61\r") == PortInfo(port="D", device_id=61)


def test_tolerates_extra_trailing_fields() -> None:
    assert decode_line("P,E,62,extra") == PortInfo(port="E", device_id=62)


@pytest.mark.parametrize(
    "line",
    [
        "",
        "hello from the hub",
        "dbg edge=52",
        "P",
        "P,",
        "P,C",
        "P,C,abc",
        "P,G,48",
        "P,C,-1",
        "R",
        "R,SCAN",
        "R,SCAN,x",
        "R,,1",
        "X,1,2,3",
        "\x00\xff garbage",
    ],
)
def test_malformed_lines_return_none(line: str) -> None:
    assert decode_line(line) is None


def test_known_device_ids() -> None:
    assert device_type(0).kind is DeviceKind.EMPTY
    assert device_type(61).kind is DeviceKind.COLOR_SENSOR
    assert device_type(62).kind is DeviceKind.ULTRASONIC_SENSOR
    assert device_type(48).kind is DeviceKind.MOTOR


def test_unknown_device_id_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    result = device_type(999)
    assert result.kind is DeviceKind.UNKNOWN
    assert "999" in caplog.text
