"""Teleop: WASD held keys -> DRV setpoints (protocol.md, Teleop drive).

W/S drive forward/back, A/D turn left/right, combinations curve. While a key
is held the setpoint is resent every SEND_INTERVAL_S to keep the hub's 300 ms
dead-man switch fed; releasing everything sends one DRV,0,0.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.core.protocol import encode_drive

logger = logging.getLogger(__name__)

SEND_INTERVAL_S = 0.1  # well inside the hub's 300 ms dead-man timeout
# Own speeds, not the line follower's SPD: 50 mm/s felt sluggish on the real
# robot (2026-09-23). The hub still clamps to 300 mm/s and 180 deg/s.
TELEOP_SPEED_MM_S = 150.0
TURN_RATE_DEG_S = 120
DRIVE_KEYS = frozenset("WASD")


class TeleopDriver:
    def __init__(self, send: Callable[[str], Awaitable[None]]) -> None:
        self._send = send
        self.keys: set[str] = set()
        self.speed_mm_s = TELEOP_SPEED_MM_S
        self._last_sent: tuple[float, float] | None = None

    def press(self, key: str) -> bool:
        """Returns True when the key is a drive key (and so was consumed)."""
        key = key.upper()
        if key not in DRIVE_KEYS:
            return False
        self.keys.add(key)
        return True

    def release(self, key: str) -> bool:
        key = key.upper()
        if key not in DRIVE_KEYS:
            return False
        self.keys.discard(key)
        return True

    def release_all(self) -> None:
        self.keys.clear()

    def setpoint(self) -> tuple[float, float]:
        forward = ("W" in self.keys) - ("S" in self.keys)
        right = ("D" in self.keys) - ("A" in self.keys)
        return forward * self.speed_mm_s, right * TURN_RATE_DEG_S

    async def tick(self) -> str | None:
        """Send the setpoint if it moves the robot or just returned to rest."""
        setpoint = self.setpoint()
        if setpoint == (0, 0) and self._last_sent in (None, (0, 0)):
            return None
        line = encode_drive(*setpoint)
        try:
            await self._send(line)
        except Exception as exc:  # noqa: BLE001 - the dead-man stops the robot anyway
            logger.warning("Teleop write failed: %s", exc)
            return None
        self._last_sent = setpoint
        return line

    def reset(self) -> None:
        self.keys.clear()
        self._last_sent = None

    async def run(self, active: Callable[[], bool], interval_s: float = SEND_INTERVAL_S) -> None:
        while True:
            if active():
                await self.tick()
            await asyncio.sleep(interval_s)
