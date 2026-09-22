"""Entry point: `python -m app.main`.

Runs asyncio inside the Qt event loop via qasync, so BLE (bleak) coroutines and
Qt slots share one thread.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

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


async def selftest() -> int:
    """Render and compile every hub program, without a hub or a window.

    Proves the install (or the packaged exe) can build what it uploads:
    Jinja templates, bundled template files and the mpy-cross binary.
    """
    from app.codegen.generator import SCAN_PORTS_PROGRAM, generate
    from app.core.analysis import DRIFT_TESTS
    from app.core.config import RobotConfig
    from app.core.connection import build_program

    jobs = [("line_follower", None), ("calibrate", None), ("teleop", None)]
    jobs += [("drift_test", key) for key in DRIFT_TESTS]
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        paths = [SCAN_PORTS_PROGRAM]
        for mode, drift in jobs:
            out = Path(tmp) / (drift or mode)
            paths.append(generate(RobotConfig(), mode, out_dir=out, drift=drift))
        for path in paths:
            try:
                size = len(await build_program(path))
                print(f"ok    {path.parent.name}/{path.name}  {size} bytes")
            except Exception as exc:  # noqa: BLE001 - report every failure, then fail
                failures += 1
                print(f"FAIL  {path.name}: {exc}")
    print("selftest passed" if not failures else f"selftest failed: {failures}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="PybricksTracker")
    parser.add_argument(
        "--selftest", action="store_true", help="compile every hub program and exit"
    )
    args, _qt_args = parser.parse_known_args()
    if args.selftest:
        return asyncio.run(selftest())
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
