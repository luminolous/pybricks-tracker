"""MainWindow wiring against fake hubs: connect, scan, E-STOP, shutdown."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pybricksdev.ble.pybricks import StatusFlag
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MIN_HEIGHT_PX, MIN_WIDTH_PX, MainWindow
from tests.fakes import HUB, SCAN_OUTPUT, FakeHubs


@pytest.fixture
async def window(qapp):
    fakes = FakeHubs()
    w = MainWindow(connection_factory=fakes.connection)
    w.fakes = fakes
    w.start()
    yield w
    await w.shutdown()
    QApplication.instance().removeEventFilter(w)


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def test_window_basics(qapp) -> None:
    w = MainWindow(connection_factory=FakeHubs().connection)
    assert w.windowTitle() == "Pybricks Tracker"
    assert w.minimumWidth() == MIN_WIDTH_PX
    assert w.minimumHeight() == MIN_HEIGHT_PX
    assert w.connect_button.text() == "Connect"
    assert not w.scan_button.isEnabled()
    assert not w.run_button.isEnabled()
    QApplication.instance().removeEventFilter(w)


async def test_connect_updates_header(window) -> None:
    await window.conn.connect(HUB)
    assert window.connect_button.text() == "Disconnect"
    assert window.hub_label.text() == "Pybricks Hub"
    assert window.link_label.text() == "connected"
    assert window.scan_button.isEnabled()


async def test_scan_fills_ports_across_split_chunks(window) -> None:
    window.fakes.program_output[:] = [SCAN_OUTPUT[:13], SCAN_OUTPUT[13:]]
    await window.conn.connect(HUB)
    assert await window.scan_ports()
    panel = window.port_panel
    assert panel.rows["D"].device.text() == "Color sensor"
    assert panel.rows["E"].device.text() == "Ultrasonic"
    assert panel.validation_error() is None
    assert "P,DONE,0" in window.console.visible_text()
    assert window.run_state.text() == "RUNNING"


async def test_rescan_shows_unplugged_sensor(window) -> None:
    await window.conn.connect(HUB)
    window.fakes.program_output[:] = [SCAN_OUTPUT]
    await window.scan_ports()
    window.fakes.hub.status_observable.on_next(StatusFlag(0))  # program ended
    window.fakes.program_output[:] = [SCAN_OUTPUT.replace(b"P,D,61", b"P,D,0")]
    await window.scan_ports()
    assert window.port_panel.rows["D"].device.text() == "empty"
    assert window.port_panel.validation_error() == "Port D is empty but has the role line."


async def test_scan_timeout_is_reported(window, monkeypatch) -> None:
    monkeypatch.setattr("app.ui.main_window.SCAN_TIMEOUT_S", 0.05)
    await window.conn.connect(HUB)
    window.fakes.program_output[:] = [b"P,A,0\n"]  # never sends DONE
    assert not await window.scan_ports()
    assert "did not finish" in window.console.visible_text()


async def test_estop_sends_stop_then_stops_program(window) -> None:
    await window.conn.connect(HUB)
    await window.conn.run_file(Path("x.py"))
    await window.emergency_stop()
    assert window.fakes.hub.written == ["MODE,STOP\r\n"]
    assert window.fakes.hub.stopped == 1
    assert window.run_state.text() == "IDLE"


async def test_spacebar_triggers_estop_only_while_running(window) -> None:
    await window.conn.connect(HUB)
    press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " ")
    QApplication.sendEvent(window.console.filter_edit, press)
    await settle()
    assert window.fakes.hub.stopped == 0
    assert window.console.filter_edit.text() == " "  # idle: space types normally

    await window.conn.run_file(Path("x.py"))
    QApplication.sendEvent(window.console.filter_edit, press)
    await settle()
    assert window.fakes.hub.stopped == 1
    assert window.console.filter_edit.text() == " "  # running: space swallowed


async def test_dropped_link_resets_header(window) -> None:
    await window.conn.connect(HUB)
    window.fakes.hub.drop_link()
    assert window.connect_button.text() == "Connect"
    assert window.link_label.text() == "disconnected"
    assert not window.scan_button.isEnabled()


async def test_shutdown_stops_running_program_and_disconnects(window) -> None:
    await window.conn.connect(HUB)
    hub = window.fakes.hub
    await window.conn.run_file(Path("x.py"))
    await window.shutdown()
    assert hub.stopped == 1
    assert not window.conn.connected


def test_rx_rate_resets_every_tick(qapp) -> None:
    w = MainWindow(connection_factory=FakeHubs().connection)
    w._rx_count = 20
    w.tick_1hz(1)
    assert w.rx_label.text() == "20 Hz"
    w.tick_1hz(2)
    assert w.rx_label.text() == "0 Hz"
    QApplication.instance().removeEventFilter(w)
