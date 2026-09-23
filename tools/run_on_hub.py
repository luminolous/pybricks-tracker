"""Upload any hub program, print its stdout, stop it. For hardware sessions.

    python tools/run_on_hub.py tools/hub/probe_api.py
    python tools/run_on_hub.py app/codegen/templates/scan_ports.py --timeout 15

Scans for Pybricks hubs, connects to the strongest (or --name), runs the file
through the same HubConnection the app uses, sends heartbeats so generated
programs' watchdogs stay fed, and stops the program on exit or Ctrl+C.
Reuses the app's code on purpose: this also proves the BLE chain.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.connection import (  # noqa: E402
    SINGLE_CONNECTION_HINT,
    HubConnection,
    HubConnectionError,
    run_heartbeat,
)

DONE_MARKERS = ("PROBE,DONE,", "P,DONE,")


async def run(path: Path, name: str | None, timeout_s: float) -> int:
    conn = HubConnection()
    print("scanning for Pybricks hubs...")
    hubs = await conn.scan()
    if name:
        hubs = [h for h in hubs if h.name == name or h.address == name]
    if not hubs:
        print(f"no hub found. {SINGLE_CONNECTION_HINT}")
        return 2
    hub = hubs[0]
    print(f"connecting to {hub.name} ({hub.address}, {hub.rssi_dbm} dBm)")
    await conn.connect(hub)
    heartbeat = asyncio.create_task(run_heartbeat(conn))
    try:
        print(f"running {path}")
        await conn.run_file(path)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while loop.time() < deadline:
            try:
                line = await asyncio.wait_for(conn.lines.get(), timeout=0.5)
            except TimeoutError:
                if not conn.program_running:
                    break
                continue
            print(line)
            if line.startswith(DONE_MARKERS):
                break
        else:
            print(f"(timeout after {timeout_s:.0f} s)")
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        if conn.program_running:
            with contextlib.suppress(HubConnectionError):
                await conn.write_line("MODE,STOP")
                await conn.stop()
        await conn.disconnect()
        print("disconnected")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("program", type=Path)
    parser.add_argument("--name", help="hub name or address (default: strongest signal)")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds (default 30)")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args.program, args.name, args.timeout))
    except HubConnectionError as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
