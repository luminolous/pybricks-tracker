"""Fake pybricksdev hub shared by core and UI tests. No Bluetooth involved."""

from __future__ import annotations

from collections.abc import Callable

from pybricksdev.ble.pybricks import StatusFlag
from pybricksdev.connections import ConnectionState
from reactivex.subject import BehaviorSubject, Subject

from app.core.connection import DiscoveredHub, HubConnection

HUB = DiscoveredHub(name="Pybricks Hub", address="AA:BB", rssi_dbm=-50, device=object())

SCAN_OUTPUT = b"R,SCAN,1\nP,A,0\nP,B,0\nP,C,48\nP,D,61\nP,E,62\nP,F,48\nP,DONE,0\n"


class FakeHub:
    def __init__(self, device: object, fail_connect: bool = False) -> None:
        self.device = device
        self.fail_connect = fail_connect
        self.connection_state_observable = BehaviorSubject(ConnectionState.DISCONNECTED)
        self.status_observable = BehaviorSubject(StatusFlag(0))
        self._stdout = Subject()
        self.written: list[str] = []
        self.ran: list[str] = []  # program paths, in start order
        self._downloaded = b""
        self.stopped = 0
        # Bytes the "program" prints when run() is called, in chunks.
        self.program_output: list[bytes] = []

    @property
    def stdout_observable(self) -> Subject:
        return self._stdout

    async def connect(self) -> None:
        self.connection_state_observable.on_next(ConnectionState.CONNECTING)
        if self.fail_connect:
            self.connection_state_observable.on_next(ConnectionState.DISCONNECTED)
            raise OSError("device busy")
        self.connection_state_observable.on_next(ConnectionState.CONNECTED)

    async def disconnect(self) -> None:
        self.connection_state_observable.on_next(ConnectionState.DISCONNECTING)
        self.connection_state_observable.on_next(ConnectionState.DISCONNECTED)

    async def download_user_program(self, program: bytes) -> None:
        self._downloaded = program

    async def start_user_program(self) -> None:
        self.ran.append(self._downloaded.removeprefix(b"PROGRAM:").decode())
        self.status_observable.on_next(StatusFlag.USER_PROGRAM_RUNNING)
        for chunk in self.program_output:
            self._stdout.on_next(chunk)

    async def stop_user_program(self) -> None:
        self.stopped += 1
        self.status_observable.on_next(StatusFlag(0))

    async def write_string(self, value: str) -> None:
        self.written.append(value)

    # test helpers
    def emit(self, chunk: bytes) -> None:
        self._stdout.on_next(chunk)

    def drop_link(self) -> None:
        self.connection_state_observable.on_next(ConnectionState.DISCONNECTED)


class FakeHubs:
    """Builds HubConnections backed by FakeHub and remembers the last hub made."""

    def __init__(self, fail_connect: bool = False, hubs: list[DiscoveredHub] | None = None) -> None:
        self.hub: FakeHub | None = None
        self.fail_connect = fail_connect
        self.hubs = [HUB] if hubs is None else hubs
        self.program_output: list[bytes] = []

    def make_hub(self, device: object) -> FakeHub:
        self.hub = FakeHub(device, self.fail_connect)
        self.hub.program_output = self.program_output
        return self.hub

    async def scan(self, timeout_s: float) -> list[DiscoveredHub]:
        return self.hubs

    def connection(self, **callbacks: Callable) -> HubConnection:
        return HubConnection(
            hub_factory=self.make_hub, scanner=self.scan, compiler=fake_compile, **callbacks
        )


async def fake_compile(path) -> bytes:
    """Skip mpy-cross in UI tests; FakeHub records the path it was given."""
    return b"PROGRAM:" + str(path).encode()
