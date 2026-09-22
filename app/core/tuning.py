"""Live tuning: rate-limited sends with acknowledgement tracking.

Slider moves arrive far faster than BLE should carry them. Each parameter
sends at most once per MIN_INTERVAL_S, and only its latest wanted value:
intermediate values are dropped, never queued (architecture.md). The hub
answers each applied value with `E,ACK,...`; until then the parameter is
pending, which is how a dropped write becomes visible.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.protocol import encode_command

logger = logging.getLogger(__name__)

MIN_INTERVAL_S = 0.1  # at most 10 messages per second per parameter
TICK_S = 0.02
ACK_TOLERANCE = 1e-3  # the hub parses into single precision floats
STALE_AFTER_S = 1.0  # sent but unacknowledged this long: likely dropped


@dataclass
class ParamState:
    wanted: float | None = None
    sent: float | None = None
    sent_at: float = -1e9
    acked: float | None = None


class TuningSender:
    def __init__(
        self,
        send: Callable[[str], Awaitable[None]],
        clock: Callable[[], float] = time.monotonic,
        min_interval_s: float = MIN_INTERVAL_S,
    ) -> None:
        self._send = send
        self._clock = clock
        self._min_interval_s = min_interval_s
        self.params: dict[str, ParamState] = {}

    def reset(self) -> None:
        """New program: nothing sent, nothing acknowledged yet."""
        self.params.clear()

    def seed(self, key: str, value: float) -> None:
        """A value the hub already runs with (rendered into the program): nothing to send."""
        # sent_at stays in the past: nothing went over BLE, so the first real
        # change must not wait out the rate limit.
        self.params[key] = ParamState(wanted=value, sent=value, acked=value)

    def want(self, key: str, value: float) -> None:
        self.params.setdefault(key, ParamState()).wanted = value

    def ack(self, key: str, value: float) -> None:
        self.params.setdefault(key, ParamState()).acked = value

    def acked(self, key: str) -> float | None:
        param = self.params.get(key)
        return param.acked if param else None

    def pending(self, key: str) -> bool:
        """The hub has not confirmed the latest wanted value."""
        param = self.params.get(key)
        if param is None or param.wanted is None:
            return False
        return param.acked is None or abs(param.acked - param.wanted) > ACK_TOLERANCE

    def stale(self, key: str) -> bool:
        """Pending long after the last send: the write or its ACK was probably lost."""
        param = self.params.get(key)
        return (
            self.pending(key)
            and param is not None
            and (self._clock() - param.sent_at > STALE_AFTER_S)
        )

    async def flush(self) -> list[str]:
        """Send every parameter that is due. Returns the keys sent."""
        now = self._clock()
        sent = []
        for key, param in self.params.items():
            if param.wanted is None or now - param.sent_at < self._min_interval_s:
                continue
            resend = self.stale(key)  # retry a lost write once per STALE_AFTER_S
            if param.wanted == param.sent and not resend:
                continue
            try:
                await self._send(encode_command(key, float(param.wanted)))
            except Exception as exc:  # noqa: BLE001 - a failed write stays pending
                logger.warning("Tuning write %s failed: %s", key, exc)
                continue
            param.sent = param.wanted
            param.sent_at = now
            sent.append(key)
        return sent

    async def run(self, active: Callable[[], bool], tick_s: float = TICK_S) -> None:
        """Flush forever while `active()` is true. Cancel to stop."""
        while True:
            if active():
                await self.flush()
            await asyncio.sleep(tick_s)
