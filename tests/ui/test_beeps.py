"""Beeps through the main window: a BEEP line while a mode program runs, the
beep-and-end program while the hub is idle, silence without a hub."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pybricksdev.ble.pybricks import StatusFlag
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from tests.fakes import HUB, SCAN_OUTPUT, FakeHubs

LF_OUTPUT = b"R,LINE_FOLLOWER,1\nS,0,7800,120,1\n"


@pytest.fixture
async def window(qapp, monkeypatch):
    monkeypatch.setattr(MainWindow, "HUB_BEEPS", True)
    monkeypatch.setattr("app.ui.main_window.BEEP_PROGRAM_TIMEOUT_S", 0.2)
    fakes = FakeHubs()
    w = MainWindow(connection_factory=fakes.connection)
    w.fakes = fakes
    w.start()
    yield w
    await w.shutdown()
    QApplication.instance().removeEventFilter(w)


def beeps(w) -> list[str]:
    return [c for c in w.fakes.hub.written if c.startswith("BEEP")]


async def test_no_hub_no_beep(window) -> None:
    window.beep("mode")
    assert window._beep_task is None


async def test_idle_hub_runs_the_beep_program(window) -> None:
    await window._connect_and_beep(HUB)
    await window._beep_task
    assert window.fakes.hub.ran[-1].endswith("hub_beep_connect.py")


async def test_group_button_beeps_when_idle(window) -> None:
    await window.conn.connect(HUB)
    window.tuning.group_buttons["teleop"].click()
    await window._beep_task
    assert window.fakes.hub.ran[-1].endswith("hub_beep_mode.py")
    window.tuning.set_group("line")  # set by the app, not the user: silent
    assert window._beep_task.done()


async def test_running_mode_program_gets_beep_lines(window) -> None:
    await window.conn.connect(HUB)
    window.fakes.program_output[:] = [SCAN_OUTPUT]
    await window.scan_ports()
    window.fakes.hub.status_observable.on_next(StatusFlag(0))
    window.fakes.program_output[:] = [LF_OUTPUT]
    assert await window.run_program("line_follower")
    window.beep("black")
    await asyncio.sleep(0.01)
    assert beeps(window) == ["BEEP,440,150\r\n"]
    assert window.fakes.hub.ran[-1].endswith("hub_line_follower.py")  # no extra upload


async def test_run_waits_for_a_beep_program(window) -> None:
    await window.conn.connect(HUB)
    window.beep("mode")  # the fake program never ends by itself
    window.fakes.program_output[:] = [SCAN_OUTPUT]
    task = asyncio.ensure_future(window.scan_ports())
    await asyncio.sleep(0.05)
    window.fakes.hub.status_observable.on_next(StatusFlag(0))  # beep program ended
    assert await task
    assert window.fakes.hub.ran[-2:][0].endswith("hub_beep_mode.py")
    assert window.fakes.hub.ran[-1].endswith("scan_ports.py")


async def test_calibration_samples_beep(window) -> None:
    await window.conn.connect(HUB)
    window.show_calibration()
    dialog = window._calibration_dialog
    window.state.fast.recent = lambda *_a: [8.0] * 20  # type: ignore[method-assign]
    dialog.sample("black")
    await window._beep_task
    assert window.fakes.hub.ran[-1].endswith("hub_beep_black.py")
    dialog.close()


async def test_speaker_button_mutes(window) -> None:
    await window.conn.connect(HUB)
    assert window.sound_on
    window.sound_button.click()
    assert not window.sound_on
    assert "muted" in window.sound_button.toolTip()
    window.beep("mode")
    assert window._beep_task is None  # nothing uploaded
    window.fakes.program_output[:] = [SCAN_OUTPUT]
    await window.scan_ports()
    assert window.fakes.hub.ran[-1].endswith("scan_ports_quiet.py")
    window.fakes.hub.status_observable.on_next(StatusFlag(0))
    window.fakes.program_output[:] = [LF_OUTPUT]
    assert await window.run_program("line_follower")
    program = Path(window.fakes.hub.ran[-1])
    assert "SOUND = False" in program.read_text(encoding="utf-8")
