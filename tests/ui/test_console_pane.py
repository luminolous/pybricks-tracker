"""ConsolePane filtering and cap."""

from __future__ import annotations

from app.ui.console_pane import MAX_LINES, ConsolePane


def test_appends_lines(qapp) -> None:
    pane = ConsolePane()
    pane.append("P,A,0")
    pane.append("dbg hello")
    assert pane.visible_text() == "P,A,0\ndbg hello"


def test_hide_protocol_keeps_debug_prints(qapp) -> None:
    pane = ConsolePane()
    for line in ("R,SCAN,1", "dbg edge=52", "T,1,2,3", "» note"):
        pane.append(line)
    pane.hide_protocol.setChecked(True)
    assert pane.visible_text() == "dbg edge=52\n» note"
    pane.hide_protocol.setChecked(False)
    assert "R,SCAN,1" in pane.visible_text()


def test_filter_is_case_insensitive_and_applies_to_new_lines(qapp) -> None:
    pane = ConsolePane()
    pane.append("P,A,0")
    pane.filter_edit.setText("dbg")
    pane.append("DBG late")
    pane.append("P,B,0")
    assert pane.visible_text() == "DBG late"


def test_caps_history(qapp) -> None:
    pane = ConsolePane()
    for i in range(MAX_LINES + 50):
        pane.append(f"line {i}")
    pane.filter_edit.setText("line")
    lines = pane.visible_text().splitlines()
    assert len(lines) == MAX_LINES
    assert lines[0] == "line 50"
