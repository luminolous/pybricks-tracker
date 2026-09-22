"""Skeleton checks: every module imports, the theme applies, the ticker ticks."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import pkgutil

import app
from app.main import run_ticker
from app.ui.theme import apply_theme


def test_every_module_imports() -> None:
    for module in pkgutil.walk_packages(app.__path__, prefix="app."):
        importlib.import_module(module.name)


def test_theme_applies(qapp) -> None:
    fonts = apply_theme(qapp)
    assert fonts.ui and fonts.mono
    assert "QPushButton" in qapp.styleSheet()


async def test_ticker_counts_up_and_cancels() -> None:
    ticks: list[int] = []
    task = asyncio.create_task(run_ticker(ticks.append, interval_ms=1))
    while len(ticks) < 3:
        await asyncio.sleep(0.001)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert ticks[:3] == [1, 2, 3]
