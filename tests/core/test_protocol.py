"""Decoder tests. Every malformed variant must return None, never raise."""

from __future__ import annotations

import pytest

from app.core.protocol import (
    PROTO_VERSION,
    Detail,
    DeviceKind,
    Event,
    PortInfo,
    PortScanDone,
    Ready,
    Status,
    Telemetry,
    decode_line,
    device_type,
    encode_command,
    parse_ack,
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


# -- T and E lines ----------------------------------------------------------


def test_decode_telemetry() -> None:
    assert decode_line("T,1532,245.3,88.1,93.0,47,-12,FOLLOW") == Telemetry(
        t_ms=1532, x_mm=245.3, y_mm=88.1, heading_deg=93.0, reflection=47, steer=-12, state="FOLLOW"
    )


def test_decode_event_with_and_without_detail() -> None:
    assert decode_line("E,LOST,12400,245.3,88.1") == Event("LOST", 12400, 245.3, 88.1)
    assert decode_line("E,OBS,18100,1.0,2.0,48") == Event("OBS", 18100, 1.0, 2.0, "48")
    assert decode_line("E,WDOG,4000,0.0,0.0,2011").kind == "WDOG"


@pytest.mark.parametrize(
    "line",
    [
        "T,1532,245.3,88.1,93.0,47,-12",
        "T,1532,245.3,88.1,93.0,47,-12,",
        "T,abc,245.3,88.1,93.0,47,-12,FOLLOW",
        "T,1532,245.3,88.1,93.0,47.5,-12,FOLLOW",
        "E,NOPE,1,2,3",
        "E,LOST,1,2",
        "E,LOST,x,2,3",
    ],
)
def test_malformed_t_and_e_return_none(line: str) -> None:
    assert decode_line(line) is None


def test_encode_commands() -> None:
    assert encode_command("KP", -1.8) == "KP,-1.8"
    assert encode_command("SPD", 70.0) == "SPD,70"
    assert encode_command("INNER", 20.0) == "INNER,20"
    assert encode_command("SRCH", 150.0) == "SRCH,150"
    assert encode_command("THR", 50) == "THR,50"
    assert encode_command("MODE", "STOP") == "MODE,STOP"
    assert encode_command("HB") == "HB"


@pytest.mark.parametrize(("key", "value"), [("XX", 1), ("MODE", "FLY")])
def test_encode_rejects_unknown(key: str, value: object) -> None:
    with pytest.raises(ValueError):
        encode_command(key, value)


def test_decode_status() -> None:
    assert decode_line("S,1000,7820,142,1") == Status(1000, 7820, 142, True)
    assert decode_line("S,500,7820,142,0").imu_ready is False


@pytest.mark.parametrize("line", ["S,1000,7820,142", "S,1000,7820,142,2", "S,x,7820,142,1"])
def test_malformed_status_returns_none(line: str) -> None:
    assert decode_line(line) is None


def test_decode_detail() -> None:
    assert decode_line("D,1500,210,4,91,62,58,11") == Detail(1500, 210, 4, 91, 62, 58, 11)
    assert decode_line("D,1500,210,4,91,-5,58,11").load_left == -5  # load sign unverified


@pytest.mark.parametrize(
    "line",
    ["D,1500,210,4,91,62,58", "D,1500,400,4,91,62,58,11", "D,1500,210,4,91,62,58,-1", "D,x"],
)
def test_malformed_detail_returns_none(line: str) -> None:
    assert decode_line(line) is None


def test_pivot_and_search_acks() -> None:
    # real sample: the hub prints the float it parsed
    record = decode_line("E,ACK,900,0.0,0.0,INNER:35.0")
    assert parse_ack(record.detail) == ("INNER", 35.0)
    assert parse_ack("PIV:180.0") is None  # retired with the arc turns
    assert parse_ack("SRCH:150.0") == ("SRCH", 150.0)
    assert parse_ack("SRCH:fast") is None  # malformed value
    assert parse_ack("TURN:90.0") is None  # app-side knob, never acknowledged


def test_route_events_and_fin() -> None:
    turn = decode_line("E,TURN,15200,410.0,-620.5,2/4 L")
    assert (turn.kind, turn.detail) == ("TURN", "2/4 L")
    assert decode_line("E,FINISH,48000,1500.0,300.0,712").detail == "712"
    assert encode_command("FIN", 600.0) == "FIN,600"
    assert parse_ack("FIN:600.0") == ("FIN", 600.0)
    assert parse_ack("FIN:") is None
    assert decode_line("E,TURNED,1,0,0") is None  # unknown kind
