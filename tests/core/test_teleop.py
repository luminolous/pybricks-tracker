"""Teleop key handling and DRV encoding."""

from __future__ import annotations

from app.core.protocol import encode_drive
from app.core.teleop import TURN_RATE_DEG_S, TeleopDriver


def rig() -> tuple[TeleopDriver, list[str]]:
    sent: list[str] = []

    async def send(line: str) -> None:
        sent.append(line)

    driver = TeleopDriver(send)
    driver.speed_mm_s = 120
    return driver, sent


def test_encode_drive_rounds() -> None:
    assert encode_drive(120.4, -89.6) == "DRV,120,-90"


def test_keys_to_setpoint() -> None:
    d, _ = rig()
    assert d.setpoint() == (0, 0)
    d.press("w")
    assert d.setpoint() == (120, 0)
    d.press("D")
    assert d.setpoint() == (120, TURN_RATE_DEG_S)  # curve right
    d.press("S")
    assert d.setpoint() == (0, TURN_RATE_DEG_S)  # W and S cancel: turn in place
    assert not d.press("Q")  # not a drive key


async def test_held_key_is_resent_and_release_sends_one_stop() -> None:
    d, sent = rig()
    assert await d.tick() is None  # idle: nothing to say
    d.press("W")
    await d.tick()
    await d.tick()  # resent: the hub's dead-man needs it
    d.release("W")
    await d.tick()
    await d.tick()
    assert sent == ["DRV,120,0", "DRV,120,0", "DRV,0,0"]


async def test_release_all_on_focus_loss() -> None:
    d, sent = rig()
    d.press("A")
    await d.tick()
    d.release_all()
    await d.tick()
    assert sent == [f"DRV,0,{-TURN_RATE_DEG_S}", "DRV,0,0"]


async def test_failed_write_is_retried_next_tick() -> None:
    calls: list[str] = []

    async def flaky(line: str) -> None:
        calls.append(line)
        if len(calls) == 1:
            raise RuntimeError("BLE busy")

    d = TeleopDriver(flaky)
    d.press("W")
    assert await d.tick() is None
    assert await d.tick() == "DRV,150,0"
