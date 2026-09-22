"""Connection-lost banner, driven by a fake clock."""

from __future__ import annotations

import pytest
from pybricksdev.ble.pybricks import StatusFlag
from PySide6.QtWidgets import QApplication

from app.core.protocol import decode_line
from app.ui.main_window import MainWindow
from tests.fakes import HUB, SCAN_OUTPUT, FakeHubs


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def rig(qapp):
    fakes = FakeHubs()
    clock = Clock()
    w = MainWindow(connection_factory=fakes.connection, clock=clock)
    w.resize(1280, 800)
    w.show()
    w.fakes, w.clock = fakes, clock
    w.start()
    yield w
    await w.shutdown()
    QApplication.instance().removeEventFilter(w)


async def running(w) -> None:
    await w.conn.connect(HUB)
    w.fakes.program_output[:] = [SCAN_OUTPUT]
    await w.scan_ports()
    w.fakes.hub.status_observable.on_next(StatusFlag(0))
    w.fakes.program_output[:] = [b"R,LINE_FOLLOWER,1\nT,0,0.0,0.0,0.0,50,0,FOLLOW\n"]
    assert await w.run_program()


def t_line(w) -> None:
    w._handle_record(decode_line("T,1,0.0,0.0,0.0,50,0,FOLLOW"))


async def test_banner_after_two_seconds_without_telemetry(rig) -> None:
    await running(rig)
    rig.clock.now += 1.9
    rig._check_link()
    assert rig.banner.isHidden()
    rig.clock.now += 0.2
    rig._check_link()
    assert not rig.banner.isHidden()
    assert rig.banner.title.text() == "LINK LOST"
    assert rig.banner.silence.text() == "last T 2.1 s ago"
    assert rig.banner.width() == rig.width()


async def test_banner_clears_when_telemetry_returns(rig) -> None:
    await running(rig)
    rig.clock.now += 3
    rig._check_link()
    assert not rig.banner.isHidden()
    t_line(rig)
    rig._check_link()
    assert rig.banner.isHidden()


async def test_scan_program_never_arms_the_watch(rig) -> None:
    await rig.conn.connect(HUB)
    rig.fakes.program_output[:] = [SCAN_OUTPUT]
    await rig.scan_ports()  # scan keeps "running" in the fake, but sends no T
    rig.clock.now += 10
    rig._check_link()
    assert rig.banner.isHidden()


async def test_ble_drop_while_running_shows_banner_until_reconnect(rig) -> None:
    await running(rig)
    rig.fakes.hub.drop_link()
    assert not rig.banner.isHidden()
    assert "Bluetooth link lost" in rig.banner.message.text()
    rig.clock.now += 1.5
    rig._check_link()
    assert rig.banner.silence.text() == "1.5 s ago"
    await rig.conn.connect(HUB)
    rig._check_link()
    assert rig.banner.isHidden()


async def test_normal_program_end_shows_no_banner(rig) -> None:
    await running(rig)
    rig.fakes.hub.status_observable.on_next(StatusFlag(0))
    rig.clock.now += 5
    rig._check_link()
    assert rig.banner.isHidden()


async def test_dismiss_holds_until_telemetry_returns(rig) -> None:
    await running(rig)
    rig.clock.now += 3
    rig._check_link()
    rig.banner.dismiss.click()
    rig.clock.now += 1
    rig._check_link()
    assert rig.banner.isHidden()
    t_line(rig)
    rig.clock.now += 3
    rig._check_link()
    assert not rig.banner.isHidden()
