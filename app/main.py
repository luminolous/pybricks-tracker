"""Entry point: `python -m app.main`.

Runs asyncio inside the Qt event loop via qasync, so BLE (bleak) coroutines and
Qt slots share one thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from collections.abc import Callable

import qasync
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme

TICK_INTERVAL_MS = 1000


async def run_ticker(on_tick: Callable[[int], None], interval_ms: int = TICK_INTERVAL_MS) -> None:
    """Call `on_tick` with an increasing count forever. Cancel to stop."""
    tick = 0
    while True:
        tick += 1
        on_tick(tick)
        await asyncio.sleep(interval_ms / 1000)


async def run_app(app: QApplication) -> None:
    """Run until the last window closes, then clean up while the loop still runs.

    Qt auto-quit is disabled on purpose: qasync stops the loop on aboutToQuit,
    which would skip async cleanup (stop the hub program, BLE disconnect).
    Close the window instead of calling app.quit().
    """
    app.setQuitOnLastWindowClosed(False)
    quit_event = asyncio.Event()
    app.lastWindowClosed.connect(quit_event.set)

    window = MainWindow()
    window.show()
    window.start()

    ticker = asyncio.create_task(run_ticker(window.tick_1hz))
    try:
        await quit_event.wait()
    finally:
        ticker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ticker
        await window.shutdown()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    with loop:
        loop.run_until_complete(run_app(app))
    return 0


if __name__ == "__main__":
    sys.exit(main())
