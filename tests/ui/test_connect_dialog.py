"""ConnectDialog against fake hubs."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog

from app.core.connection import SINGLE_CONNECTION_HINT
from app.ui.dialogs.connect import ConnectDialog
from tests.fakes import FakeHubs


async def test_scan_lists_hubs_and_connect_accepts(qapp) -> None:
    fakes = FakeHubs()
    conn = fakes.connection()
    dialog = ConnectDialog(conn.scan, conn.connect)
    await dialog.run_scan()
    assert dialog.hub_list.count() == 1
    assert "Pybricks Hub" in dialog.hub_list.item(0).text()
    await dialog.run_connect()
    assert conn.connected
    assert dialog.result() == QDialog.DialogCode.Accepted


async def test_no_hubs_found(qapp) -> None:
    fakes = FakeHubs(hubs=[])
    conn = fakes.connection()
    dialog = ConnectDialog(conn.scan, conn.connect)
    await dialog.run_scan()
    assert dialog.hub_list.count() == 0
    assert dialog.status.text().startswith("No Pybricks hub found")


async def test_connect_failure_stays_open_with_hint(qapp) -> None:
    fakes = FakeHubs(fail_connect=True)
    conn = fakes.connection()
    dialog = ConnectDialog(conn.scan, conn.connect)
    await dialog.run_scan()
    await dialog.run_connect()
    assert not conn.connected
    assert SINGLE_CONNECTION_HINT in dialog.status.text()
    assert dialog.result() != QDialog.DialogCode.Accepted
