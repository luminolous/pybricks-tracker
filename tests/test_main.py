"""Skeleton checks: every module imports, window builds, ticker ticks."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import pkgutil

import app
from app.main import run_ticker
from app.ui.main_window import MIN_HEIGHT_PX, MIN_WIDTH_PX, MainWindow


def test_every_module_imports() -> None:
    for module in pkgutil.walk_packages(app.__path__, prefix="app."):
        importlib.import_module(module.name)


def test_main_window_minimum_size(qapp) -> None:
    window = MainWindow()
    assert window.minimumWidth() == MIN_WIDTH_PX
    assert window.minimumHeight() == MIN_HEIGHT_PX
    assert window.windowTitle() == "Pybricks Tracker"


def test_main_window_shows_tick(qapp) -> None:
    window = MainWindow()
    window.set_loop_tick(7)
    assert window._loop_label.text() == "loop: tick 7"


async def test_ticker_counts_up_and_cancels() -> None:
    ticks: list[int] = []
    task = asyncio.create_task(run_ticker(ticks.append, interval_ms=1))
    while len(ticks) < 3:
        await asyncio.sleep(0.001)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert ticks[:3] == [1, 2, 3]
