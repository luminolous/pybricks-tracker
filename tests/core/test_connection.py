"""HubConnection against a fake pybricksdev hub. No Bluetooth involved."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.connection import (
    SINGLE_CONNECTION_HINT,
    HubConnection,
    HubConnectionError,
    LineSplitter,
    LinkState,
)
from tests.fakes import HUB, FakeHub, FakeHubs


class Harness:
    def __init__(self, fail_connect: bool = False) -> None:
        self.fakes = FakeHubs(fail_connect)
        self.states: list[LinkState] = []
        self.running: list[bool] = []
        self.conn = self.fakes.connection(
            on_link_state=self.states.append, on_program_running=self.running.append
        )

    @property
    def hub(self) -> FakeHub:
        assert self.fakes.hub is not None
        return self.fakes.hub


def drain(conn: HubConnection) -> list[str]:
    out = []
    while not conn.lines.empty():
        out.append(conn.lines.get_nowait())
    return out


# -- LineSplitter -------------------------------------------------------


def test_splitter_joins_lines_cut_across_chunks() -> None:
    s = LineSplitter()
    assert s.feed(b"P,A,") == []
    assert s.feed(b"0\nP,B") == ["P,A,0"]
    assert s.feed(b",48\r\nP,DONE,0\n") == ["P,B,48", "P,DONE,0"]


def test_splitter_survives_invalid_utf8() -> None:
    assert LineSplitter().feed(b"\xff\xfe\n") == ["��"]


# -- discover_hubs ------------------------------------------------------


async def test_discover_filters_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from pybricksdev.ble.pybricks import PYBRICKS_SERVICE_UUID

    import app.core.connection as connection

    def adv(name: str | None, rssi: int, pybricks: bool) -> SimpleNamespace:
        uuids = [PYBRICKS_SERVICE_UUID] if pybricks else []
        return SimpleNamespace(local_name=name, rssi=rssi, service_uuids=uuids)

    def dev(address: str) -> SimpleNamespace:
        return SimpleNamespace(address=address, name=None)

    async def fake_discover(timeout: float, return_adv: bool, service_uuids: list[str]) -> dict:
        assert return_adv
        return {
            "1": (dev("1"), adv("far hub", -80, True)),
            "2": (dev("2"), adv("near hub", -40, True)),
            "3": (dev("3"), adv("headphones", -30, False)),
            "4": (dev("4"), adv(None, -60, True)),
        }

    monkeypatch.setattr(connection.BleakScanner, "discover", fake_discover)
    hubs = await connection.discover_hubs(1.0)
    assert [h.name for h in hubs] == ["near hub", "4", "far hub"]


# -- HubConnection ------------------------------------------------------


async def test_scan_returns_hubs() -> None:
    h = Harness()
    assert await h.conn.scan() == [HUB]


async def test_connect_reports_states() -> None:
    h = Harness()
    await h.conn.connect(HUB)
    assert h.conn.connected
    assert h.conn.hub_name == "Pybricks Hub"
    assert h.states == [LinkState.CONNECTING, LinkState.CONNECTED]


async def test_connect_failure_carries_single_connection_hint() -> None:
    h = Harness(fail_connect=True)
    with pytest.raises(HubConnectionError) as info:
        await h.conn.connect(HUB)
    assert SINGLE_CONNECTION_HINT in str(info.value)
    assert h.conn.link_state is LinkState.DISCONNECTED
    # a failed attempt must not block the next one
    h.conn._hub_factory = lambda device: FakeHub(device)
    await h.conn.connect(HUB)
    assert h.conn.connected


async def test_stdout_chunks_become_lines() -> None:
    h = Harness()
    await h.conn.connect(HUB)
    h.hub.emit(b"R,SCAN,1\nP,A")
    h.hub.emit(b",0\n")
    assert drain(h.conn) == ["R,SCAN,1", "P,A,0"]


async def test_run_file_does_not_wait_and_tracks_running(tmp_path: Path) -> None:
    h = Harness()
    await h.conn.connect(HUB)
    program = tmp_path / "scan_ports.py"
    await h.conn.run_file(program)
    assert h.hub.ran == [str(program)]
    assert h.conn.program_running
    await h.conn.stop()
    assert h.hub.stopped == 1
    assert not h.conn.program_running
    assert h.running == [True, False]


async def test_write_line_uses_crlf() -> None:
    h = Harness()
    await h.conn.connect(HUB)
    await h.conn.write_line("HB")
    assert h.hub.written == ["HB\r\n"]


async def test_commands_need_a_connection() -> None:
    h = Harness()
    with pytest.raises(HubConnectionError):
        await h.conn.write_line("HB")
    with pytest.raises(HubConnectionError):
        await h.conn.stop()


async def test_disconnect_is_clean() -> None:
    h = Harness()
    await h.conn.connect(HUB)
    hub = h.hub
    await h.conn.disconnect()
    assert h.states[-2:] == [LinkState.DISCONNECTING, LinkState.DISCONNECTED]
    assert h.conn.hub_name is None
    # stdout after disconnect is ignored
    hub.emit(b"late line\n")
    assert drain(h.conn) == []


async def test_dropped_link_resets_state(caplog: pytest.LogCaptureFixture) -> None:
    h = Harness()
    await h.conn.connect(HUB)
    await h.conn.run_file(Path("x.py"))
    h.hub.drop_link()
    assert h.conn.link_state is LinkState.DISCONNECTED
    assert not h.conn.program_running
    assert "lost" in caplog.text
    # reconnect works after a drop
    await h.conn.connect(HUB)
    assert h.conn.connected


async def test_drop_reports_link_before_program_end() -> None:
    # The UI tells "link lost while running" from "program ended" by this order.
    h = Harness()
    order: list[str] = []
    h.conn._on_link_state = lambda s: order.append(s.value)
    h.conn._on_program_running = lambda r: order.append(f"running={r}")
    await h.conn.connect(HUB)
    await h.conn.run_file(Path("x.py"))
    order.clear()
    h.hub.drop_link()
    assert order == ["disconnected", "running=False"]


async def test_build_program_is_one_main_module(tmp_path: Path) -> None:
    from app.codegen.generator import SCAN_PORTS_PROGRAM
    from app.core.connection import build_program

    program = await build_program(SCAN_PORTS_PROGRAM)
    size = int.from_bytes(program[:4], "little")
    assert program[4:13] == b"__main__\x00"
    assert len(program) == 13 + size


async def test_compile_failure_is_reported(tmp_path: Path) -> None:
    h = Harness()

    async def broken(path):
        raise RuntimeError("mpy-cross: SyntaxError")

    h.conn._compiler = broken
    await h.conn.connect(HUB)
    with pytest.raises(HubConnectionError, match="Could not compile"):
        await h.conn.run_file(Path("x.py"))
