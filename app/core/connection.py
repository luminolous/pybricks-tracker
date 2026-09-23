"""HubConnection: scan, connect, run, stop, stdout and stdin over BLE.

Wraps pybricksdev 2.3.2 (see requirements.txt). No Qt imports here: the UI
drains `HubConnection.lines` and listens through plain callbacks.

pybricksdev API used, verified against the installed release:
- discovery: bleak `BleakScanner.discover(return_adv=True)`, filtered on the
  Pybricks service UUID (`pybricksdev.ble.find_device` returns one hub only)
- `PybricksHubBLE(device)`, `.connect()`, `.disconnect()`
- `pybricksdev.compile.compile_file` (mpy-cross only), then
  `.download_user_program()` and `.start_user_program()`. Not `.run()`: its
  multi-file compile finds imports by running `sys.executable -m mpy_tool`,
  which breaks inside a PyInstaller exe. Hub programs import nothing local,
  so the upload is one `__main__` module in the multi-file format.
- `.stdout_observable`: raw stdout bytes, split into lines here
- `.write_string()`: stdin
- `.stop_user_program()`
- `.status_observable`: `StatusFlag.USER_PROGRAM_RUNNING`
- `.connection_state_observable`: `ConnectionState`
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from bleak import BleakScanner
from pybricksdev.ble.pybricks import PYBRICKS_SERVICE_UUID, StatusFlag
from pybricksdev.compile import compile_file
from pybricksdev.connections import ConnectionState
from pybricksdev.connections.pybricks import PybricksHubBLE

logger = logging.getLogger(__name__)

SINGLE_CONNECTION_HINT = (
    "The hub accepts one Bluetooth connection at a time. "
    "Close code.pybricks.com or any other app connected to it, then try again."
)
DEFAULT_SCAN_TIMEOUT_S = 5.0
STDIN_EOL = "\r\n"  # protocol.md: PC to hub lines end with \r\n
HEARTBEAT_INTERVAL_S = 0.5  # protocol.md: HB every 500 ms, hub watchdog trips at 2 s
MPY_ABI = 6  # Pybricks 3.2+ firmware


class LinkState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"


_LINK_STATE = {
    ConnectionState.DISCONNECTED: LinkState.DISCONNECTED,
    ConnectionState.CONNECTING: LinkState.CONNECTING,
    ConnectionState.CONNECTED: LinkState.CONNECTED,
    ConnectionState.DISCONNECTING: LinkState.DISCONNECTING,
}


class HubConnectionError(RuntimeError):
    """A BLE operation failed. The message is safe to show in the UI."""


@dataclass(frozen=True)
class DiscoveredHub:
    name: str
    address: str
    rssi_dbm: int | None
    device: Any = field(compare=False, repr=False)


class Observable(Protocol):
    def subscribe(self, on_next: Callable[[Any], None]) -> Any: ...


class HubLike(Protocol):
    """The slice of pybricksdev's PybricksHub this module uses. Fakes implement it."""

    connection_state_observable: Observable
    status_observable: Observable

    @property
    def stdout_observable(self) -> Observable: ...
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def download_user_program(self, program: bytes) -> None: ...
    async def start_user_program(self) -> None: ...
    async def stop_user_program(self) -> None: ...
    async def write_string(self, value: str) -> None: ...


HubFactory = Callable[[Any], HubLike]
Compiler = Callable[[Path], Awaitable[bytes]]


async def build_program(path: Path) -> bytes:
    """Compile a hub program into the multi-file upload format with one module."""
    mpy = await compile_file(str(path.parent), path.name, MPY_ABI)
    return len(mpy).to_bytes(4, "little") + b"__main__\x00" + mpy


Scanner = Callable[[float], Awaitable[list[DiscoveredHub]]]


async def discover_hubs(timeout_s: float = DEFAULT_SCAN_TIMEOUT_S) -> list[DiscoveredHub]:
    """Return every advertising Pybricks hub, strongest signal first."""
    found = await BleakScanner.discover(
        timeout=timeout_s, return_adv=True, service_uuids=[PYBRICKS_SERVICE_UUID]
    )
    hubs = [
        DiscoveredHub(
            name=adv.local_name or device.name or device.address,
            address=device.address,
            rssi_dbm=adv.rssi,
            device=device,
        )
        for device, adv in found.values()
        if PYBRICKS_SERVICE_UUID in adv.service_uuids
    ]
    return sorted(hubs, key=lambda h: -(h.rssi_dbm if h.rssi_dbm is not None else -999))


async def run_heartbeat(conn: HubConnection, interval_s: float = HEARTBEAT_INTERVAL_S) -> None:
    """Send `HB` while a program runs. Cancel to stop.

    A failed write is logged and retried on the next beat: missing a few
    beats is exactly the case the hub watchdog exists for, so the sender
    must never crash out.
    """
    while True:
        if conn.connected and conn.program_running:
            try:
                await conn.write_line("HB")
            except HubConnectionError as exc:
                logger.warning("Heartbeat write failed: %s", exc)
        await asyncio.sleep(interval_s)


class LineSplitter:
    """Turn BLE stdout chunks into complete lines. Chunks cut lines in half routinely."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, chunk: bytes) -> list[str]:
        self._buf += chunk.decode("utf-8", errors="replace")
        *complete, self._buf = self._buf.split("\n")
        return [line.rstrip("\r") for line in complete]

    def reset(self) -> None:
        self._buf = ""


class HubConnection:
    """One hub, one BLE link. All methods are awaited on the qasync loop.

    Complete stdout lines are put on `lines`. State changes go to the
    optional callbacks, which must be cheap.
    """

    def __init__(
        self,
        hub_factory: HubFactory = PybricksHubBLE,
        scanner: Scanner = discover_hubs,
        compiler: Compiler = build_program,
        on_link_state: Callable[[LinkState], None] | None = None,
        on_program_running: Callable[[bool], None] | None = None,
    ) -> None:
        self._hub_factory = hub_factory
        self._scanner = scanner
        self._compiler = compiler
        self._on_link_state = on_link_state
        self._on_program_running = on_program_running
        self._hub: HubLike | None = None
        self._subscriptions: list[Any] = []
        self._splitter = LineSplitter()
        self._link_state = LinkState.DISCONNECTED
        self._program_running = False
        # From the hub's status flags, as Pybricks Code shows it: "ok", "low",
        # "critical", or None before the first status report.
        self.battery: str | None = None
        self.hub_name: str | None = None
        self.lines: asyncio.Queue[str] = asyncio.Queue()

    @property
    def link_state(self) -> LinkState:
        return self._link_state

    @property
    def connected(self) -> bool:
        return self._link_state is LinkState.CONNECTED

    @property
    def program_running(self) -> bool:
        return self._program_running

    async def scan(self, timeout_s: float = DEFAULT_SCAN_TIMEOUT_S) -> list[DiscoveredHub]:
        try:
            return await self._scanner(timeout_s)
        except Exception as exc:
            raise HubConnectionError(f"Bluetooth scan failed: {exc}") from exc

    async def connect(self, hub: DiscoveredHub) -> None:
        if self._hub is not None:
            raise HubConnectionError("Already connected. Disconnect first.")
        client = self._hub_factory(hub.device)
        # Set before connecting: the CONNECTED callback fires inside connect().
        self.hub_name = hub.name
        self._subscribe(client)
        try:
            await client.connect()
        except Exception as exc:
            self._dispose()
            self.hub_name = None
            self._set_link_state(LinkState.DISCONNECTED)
            raise HubConnectionError(
                f"Could not connect to {hub.name}: {exc}. {SINGLE_CONNECTION_HINT}"
            ) from exc
        self._hub = client

    async def disconnect(self) -> None:
        client = self._hub
        if client is None:
            return
        # Unsubscribe first so our own disconnect is not reported as a lost link.
        self._dispose()
        self._set_link_state(LinkState.DISCONNECTING)
        try:
            await client.disconnect()
        finally:
            self._drop_hub()

    async def run_file(self, path: Path) -> None:
        """Compile, upload and start a hub program. Returns once it has started."""
        client = self._require_hub()
        self._splitter.reset()
        try:
            program = await self._compiler(path)
        except Exception as exc:
            raise HubConnectionError(f"Could not compile {path.name}: {exc}") from exc
        try:
            await client.download_user_program(program)
            await client.start_user_program()
        except Exception as exc:
            raise HubConnectionError(f"Could not start {path.name} on the hub: {exc}") from exc

    async def stop(self) -> None:
        client = self._require_hub()
        try:
            await client.stop_user_program()
        except Exception as exc:
            raise HubConnectionError(f"Could not stop the hub program: {exc}") from exc

    async def write_line(self, text: str) -> None:
        """Send one command line to the hub's stdin."""
        client = self._require_hub()
        try:
            await client.write_string(text + STDIN_EOL)
        except Exception as exc:
            raise HubConnectionError(f"Write to hub failed: {exc}") from exc

    # -- internals --------------------------------------------------------

    def _require_hub(self) -> HubLike:
        if self._hub is None or not self.connected:
            raise HubConnectionError("Not connected to a hub.")
        return self._hub

    def _subscribe(self, client: HubLike) -> None:
        self._subscriptions = [
            client.stdout_observable.subscribe(self._handle_stdout),
            client.status_observable.subscribe(self._handle_status),
            client.connection_state_observable.subscribe(self._handle_connection_state),
        ]

    def _dispose(self) -> None:
        for sub in self._subscriptions:
            sub.dispose()
        self._subscriptions = []

    def _drop_hub(self) -> None:
        self._dispose()
        self._hub = None
        self.hub_name = None
        self._splitter.reset()
        # Link state first: listeners must see "disconnected while running",
        # not a program that ended normally.
        self.battery = None
        self._set_link_state(LinkState.DISCONNECTED)
        self._set_program_running(False)

    def _handle_stdout(self, chunk: bytes) -> None:
        for line in self._splitter.feed(bytes(chunk)):
            self.lines.put_nowait(line)

    def _handle_status(self, flags: StatusFlag) -> None:
        if flags & StatusFlag.BATTERY_LOW_VOLTAGE_SHUTDOWN:
            self.battery = "critical"
        elif flags & StatusFlag.BATTERY_LOW_VOLTAGE_WARNING:
            self.battery = "low"
        else:
            self.battery = "ok"
        self._set_program_running(bool(flags & StatusFlag.USER_PROGRAM_RUNNING))

    def _handle_connection_state(self, state: ConnectionState) -> None:
        link_state = _LINK_STATE.get(state, LinkState.DISCONNECTED)
        if link_state is LinkState.DISCONNECTED and self._hub is not None:
            # Dropped by the hub or out of range, not by disconnect().
            logger.warning("BLE link to %s lost", self.hub_name)
            self._drop_hub()
            return
        self._set_link_state(link_state)

    def _set_link_state(self, state: LinkState) -> None:
        if state is self._link_state:
            return
        self._link_state = state
        if self._on_link_state:
            self._on_link_state(state)

    def _set_program_running(self, running: bool) -> None:
        if running is self._program_running:
            return
        self._program_running = running
        if self._on_program_running:
            self._on_program_running(running)
