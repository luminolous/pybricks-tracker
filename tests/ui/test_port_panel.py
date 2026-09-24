"""PortPanel shows scan results and blocks invalid configs."""

from __future__ import annotations

from app.core.config import Role
from app.core.protocol import decode_line
from app.core.state import PortScan
from app.ui.port_panel import PortPanel


def scanned(*lines: str) -> PortScan:
    scan = PortScan()
    for line in lines:
        scan.apply(decode_line(line))
    return scan


FULL = ("P,A,48", "P,B,62", "P,C,0", "P,D,48", "P,E,0", "P,F,61", "P,DONE,0")  # the real robot


def test_unscanned_panel_asks_for_scan(qapp) -> None:
    panel = PortPanel()
    assert panel.validation_error() == "Scan ports before running."
    assert panel.rows["C"].device.text() == "not scanned"


def test_scan_fills_rows_and_default_config_is_valid(qapp) -> None:
    panel = PortPanel()
    panel.apply_scan(scanned(*FULL))
    assert panel.rows["C"].device.text() == "empty"
    assert panel.rows["F"].device.text() == "Color sensor"
    assert panel.validation_error() is None
    assert panel.validation.text() == "Config valid. Ready to run."


def test_rescan_after_unplugging_shows_change(qapp) -> None:
    panel = PortPanel()
    panel.apply_scan(scanned(*FULL))
    panel.apply_scan(scanned("P,A,48", "P,B,62", "P,C,0", "P,D,48", "P,E,0", "P,F,0", "P,DONE,0"))
    assert panel.rows["F"].device.text() == "empty"
    assert panel.validation_error() == "Port F is empty but has the role line."


def test_role_change_revalidates_and_emits(qapp) -> None:
    panel = PortPanel()
    panel.apply_scan(scanned(*FULL))
    emitted = []
    panel.changed.connect(lambda: emitted.append(True))
    row = panel.rows["A"]
    row.role.setCurrentIndex(row.role.findData(Role.UNUSED))
    assert emitted
    assert panel.validation_error() == "Assign exactly one left wheel (now 0)."


def test_direction_only_for_motor_roles(qapp) -> None:
    panel = PortPanel()
    assert panel.rows["F"].direction.isHidden()
    assert not panel.rows["A"].direction.isHidden()
