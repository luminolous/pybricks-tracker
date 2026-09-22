"""Teleop from the window, and the --selftest entry point."""

from __future__ import annotations

import asyncio

import pytest
from pybricksdev.ble.pybricks import StatusFlag
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from app.main import selftest
from app.ui.main_window import MainWindow
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


async def driving(w) -> None:
    await w.conn.connect(HUB)
    w.fakes.program_output[:] = [SCAN_OUTPUT]
    await w.scan_ports()
    w.fakes.hub.status_observable.on_next(StatusFlag(0))
    w.fakes.program_output[:] = [b"R,TELEOP,1\nS,0,7800,120,1\n"]
    await w._start_teleop()


def key(w, qt_key, press: bool = True, target=None) -> None:
    kind = QEvent.Type.KeyPress if press else QEvent.Type.KeyRelease
    QApplication.sendEvent(target or w, QKeyEvent(kind, qt_key, Qt.KeyboardModifier.NoModifier))


def drives(w) -> list[str]:
    return [c for c in w.fakes.hub.written if c.startswith("DRV")]


async def test_drive_button_starts_teleop(window) -> None:
    await driving(window)
    assert window.fakes.hub.ran[-1].endswith("hub_teleop.py")
    assert window.teleop_active()
    assert window.drive_button.isChecked()
    assert window.tuning.mode == "off"


async def test_wasd_sends_drive_commands(window) -> None:
    await driving(window)
    window.teleop.speed_mm_s = 80
    key(window, Qt.Key.Key_W)
    await window.teleop.tick()
    key(window, Qt.Key.Key_W, press=False)
    await window.teleop.tick()
    assert drives(window) == ["DRV,80,0\r\n", "DRV,0,0\r\n"]


async def test_typing_in_a_field_does_not_drive(window, monkeypatch) -> None:
    await driving(window)
    field = window.console.filter_edit
    monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: field))
    key(window, Qt.Key.Key_W, target=field)
    assert window.teleop.keys == set()


async def test_focus_loss_releases_keys(window) -> None:
    await driving(window)
    key(window, Qt.Key.Key_D)
    assert window.teleop.keys == {"D"}
    QApplication.sendEvent(window, QEvent(QEvent.Type.WindowDeactivate))
    assert window.teleop.keys == set()


async def test_keys_ignored_when_not_driving(window) -> None:
    await window.conn.connect(HUB)
    key(window, Qt.Key.Key_W)
    assert window.teleop.keys == set()


async def test_program_end_resets_teleop(window) -> None:
    await driving(window)
    key(window, Qt.Key.Key_A)
    window.fakes.hub.status_observable.on_next(StatusFlag(0))
    assert window.teleop.keys == set()
    assert not window.drive_button.isChecked()


async def test_drive_button_again_stops(window) -> None:
    await driving(window)
    window._drive_clicked()
    await asyncio.sleep(0.02)
    assert window.fakes.hub.stopped == 1


async def test_selftest_compiles_every_program(capsys) -> None:
    assert await selftest() == 0
    out = capsys.readouterr().out
    assert "hub_teleop.py" in out and "scan_ports.py" in out
    assert "selftest passed" in out
