"""Replay a recorded session into a RobotState at any point in time.

Seeking forward applies records incrementally; seeking backwards rebuilds
from the start, which is cheap at session sizes (tens of thousands of lines).
The replayed state is a separate RobotState, so live data never mixes in.
"""

from __future__ import annotations

from app.core.protocol import Event
from app.core.recorder import Session
from app.core.state import LISTED_EVENT_KINDS, RobotState

SPEEDS = (0.5, 1.0, 2.0, 4.0)


def _t(record) -> int:
    return record.t_ms


class Replay:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.records = [r for r in session.records if hasattr(r, "t_ms")]
        times = [_t(r) for r in self.records]
        self.start_ms = min(times) if times else 0
        self.end_ms = max(times) if times else 0
        self.events = [
            r for r in self.records if isinstance(r, Event) and r.kind in LISTED_EVENT_KINDS
        ]
        self.state = RobotState()
        self.position_ms = self.start_ms
        self._index = 0
        self.playing = False
        self.speed = 1.0
        self.seek(self.start_ms)

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def at_end(self) -> bool:
        return self.position_ms >= self.end_ms

    def seek(self, t_ms: float) -> None:
        t_ms = min(max(t_ms, self.start_ms), self.end_ms)
        if t_ms < self.position_ms or self._index == 0:
            self.state = RobotState()
            self._index = 0
        while self._index < len(self.records) and _t(self.records[self._index]) <= t_ms:
            self.state.apply(self.records[self._index])
            self._index += 1
        self.position_ms = t_ms

    def advance(self, wall_s: float) -> None:
        """Move forward by `wall_s` seconds of real time at the current speed."""
        if not self.playing:
            return
        self.seek(self.position_ms + wall_s * 1000 * self.speed)
        if self.at_end:
            self.playing = False

    def play(self) -> None:
        if self.at_end:
            self.seek(self.start_ms)
        self.playing = True

    def pause(self) -> None:
        self.playing = False
