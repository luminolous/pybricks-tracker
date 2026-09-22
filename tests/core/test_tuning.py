"""TuningSender: rate limit, collapse to latest, acknowledgement tracking."""

from __future__ import annotations

from app.core.protocol import decode_line, parse_ack
from app.core.tuning import TuningSender


class Clock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


def rig():
    clock = Clock()
    sent: list[str] = []

    async def send(line: str) -> None:
        sent.append(line)

    return TuningSender(send, clock=clock), clock, sent


async def test_sends_latest_value_at_most_ten_per_second() -> None:
    tuner, clock, sent = rig()
    tuner.want("KP", -1.0)
    assert await tuner.flush() == ["KP"]
    for v in (-1.1, -1.2, -1.3):  # a drag faster than the limit
        tuner.want("KP", v)
        clock.now += 0.03
        await tuner.flush()
    assert sent == ["KP,-1"]  # nothing within 100 ms
    clock.now += 0.02
    await tuner.flush()
    assert sent == ["KP,-1", "KP,-1.3"]  # intermediates collapsed to the latest


async def test_parameters_are_limited_independently() -> None:
    tuner, _, sent = rig()
    tuner.want("KP", -1.8)
    tuner.want("KD", -4.5)
    tuner.want("SPD", 70)
    await tuner.flush()
    assert sent == ["KP,-1.8", "KD,-4.5", "SPD,70"]


async def test_unchanged_value_is_not_resent() -> None:
    tuner, clock, sent = rig()
    tuner.want("KP", -1.8)
    await tuner.flush()
    clock.now += 0.5
    await tuner.flush()
    assert sent == ["KP,-1.8"]


async def test_pending_until_hub_acknowledges() -> None:
    tuner, _, _ = rig()
    tuner.want("KD", -4.5)
    await tuner.flush()
    assert tuner.pending("KD")
    tuner.ack(*parse_ack(decode_line("E,ACK,100,0.0,0.0,KD:-4.5").detail))
    assert not tuner.pending("KD")
    assert tuner.acked("KD") == -4.5


async def test_single_precision_echo_counts_as_acknowledged() -> None:
    tuner, _, _ = rig()
    tuner.want("KP", -1.8)
    tuner.ack("KP", -1.7999999523)  # float32 on the hub
    assert not tuner.pending("KP")


async def test_lost_write_goes_stale_and_is_retried() -> None:
    tuner, clock, sent = rig()
    tuner.want("KP", -2.0)
    await tuner.flush()
    clock.now += 0.5
    assert not tuner.stale("KP")
    clock.now += 0.6
    assert tuner.stale("KP")
    await tuner.flush()
    assert sent == ["KP,-2", "KP,-2"]


async def test_failed_write_stays_pending_and_retries() -> None:
    clock = Clock()
    calls: list[str] = []

    async def flaky(line: str) -> None:
        calls.append(line)
        if len(calls) == 1:
            raise RuntimeError("BLE busy")

    tuner = TuningSender(flaky, clock=clock)
    tuner.want("SPD", 90)
    assert await tuner.flush() == []
    assert await tuner.flush() == ["SPD"]


def test_parse_ack_rejects_garbage() -> None:
    assert parse_ack("KP:-1.8") == ("KP", -1.8)
    for bad in (None, "", "KP", "XX:1", "KP:abc"):
        assert parse_ack(bad) is None


async def test_seeded_values_are_not_sent() -> None:
    tuner, clock, sent = rig()
    tuner.seed("KP", -1.8)
    clock.now += 5
    assert await tuner.flush() == []
    assert not tuner.pending("KP") and not tuner.stale("KP")
    tuner.want("KP", -2.0)
    assert await tuner.flush() == ["KP"]
