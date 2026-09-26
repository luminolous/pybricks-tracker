"""Hub beeps: tones, BEEP lines, and the beep-and-end program."""

from __future__ import annotations

from pathlib import Path

from pybricksdev.compile import compile_file

from app.codegen.generator import SCAN_PORTS_PROGRAM, render, scan_program, write_beep_program
from app.core.beeps import MAX_BEEP_MS, TONES, beep_commands, beep_program
from app.core.config import RobotConfig
from app.core.protocol import encode_beep


def test_beep_lines() -> None:
    assert encode_beep(440, 150) == "BEEP,440,150"
    assert beep_commands("connect") == ["BEEP,660,80", "BEEP,990,120"]


def test_beep_program_plays_and_ends() -> None:
    source = beep_program("white")
    assert "hub.speaker.beep(1175, 150)" in source
    assert "while" not in source and "Motor" not in source  # ends, never drives


async def test_beep_program_compiles(tmp_path: Path) -> None:
    path = write_beep_program("connect", out_dir=tmp_path)
    assert path.name == "hub_beep_connect.py"
    assert len(await compile_file(str(tmp_path), path.name, 6)) > 0


def test_programs_play_their_own_tones() -> None:
    ((hz, ms),) = TONES["scan"]
    assert f"InventorHub().speaker.beep({hz}, {ms})" in SCAN_PORTS_PROGRAM.read_text("utf-8")
    source = render(RobotConfig(), "line_follower")
    ((hz, ms),) = TONES["run"]
    main = source[source.index("def main():") :]
    handshake = main.index('print("R,{},{}".format(MODE, PROTO_VERSION))')
    assert main.index(f"beep({hz}, {ms})") > handshake  # R first, then the tone


def test_hub_takes_beep_commands_clamped() -> None:
    source = render(RobotConfig(), "calibrate")
    assert f"BEEP_MAX_MS = {MAX_BEEP_MS}" in source
    assert "beep(int(hz), max(0, min(BEEP_MAX_MS, int(ms))))" in source


def test_speaker_button_mutes_every_hub_sound(tmp_path: Path) -> None:
    for mode in ("line_follower", "calibrate", "teleop"):
        loud = render(RobotConfig(), mode)
        quiet = render(RobotConfig(), mode, sound=False)
        assert "SOUND = True" in loud and "SOUND = False" in quiet
        # the only speaker call sits inside beep(), which checks SOUND
        assert quiet.count("hub.speaker.beep(") == 1
        assert "    if SOUND:\n        hub.speaker.beep(hz, ms)" in quiet
    assert scan_program(True) == SCAN_PORTS_PROGRAM
    quiet_scan = scan_program(False, out_dir=tmp_path).read_text(encoding="utf-8")
    assert ".speaker.beep(" not in quiet_scan and 'print("P,DONE,0")' in quiet_scan
