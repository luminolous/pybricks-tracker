"""BLE device picker. Scans, lists hubs, connects to the chosen one.

Async work runs as tasks on the qasync loop; the dialog is opened with
open(), never exec(), so no nested event loop is started.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from app.core.connection import DiscoveredHub, HubConnectionError
from app.ui.theme import caption, label, set_prop

ScanFn = Callable[[], Awaitable[list[DiscoveredHub]]]
ConnectFn = Callable[[DiscoveredHub], Awaitable[None]]


class ConnectDialog(QDialog):
    def __init__(self, scan: ScanFn, connect: ConnectFn, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect to hub")
        self.setMinimumSize(420, 340)
        self._scan = scan
        self._connect = connect
        self._task: asyncio.Task | None = None

        self.hub_list = QListWidget()
        self.hub_list.setObjectName("hubList")
        self.status = QLabel("Turn on the hub, then scan.")
        self.status.setWordWrap(True)
        set_prop(self.status, "tone", "muted")
        self.scan_button = QPushButton("Scan")
        self.scan_button.setProperty("role", "small")
        self.connect_button = QPushButton("Connect")
        self.connect_button.setProperty("role", "run")
        self.connect_button.setEnabled(False)
        cancel = QPushButton("Cancel")
        cancel.setProperty("role", "small")

        buttons = QHBoxLayout()
        buttons.addWidget(self.scan_button)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.connect_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(caption("Pybricks hubs nearby"))
        layout.addWidget(self.hub_list, 1)
        layout.addWidget(self.status)
        layout.addWidget(
            label("One connection at a time: close code.pybricks.com first.", tone="dim")
        )
        layout.addLayout(buttons)

        self.scan_button.clicked.connect(lambda: self._start(self.run_scan()))
        self.connect_button.clicked.connect(lambda: self._start(self.run_connect()))
        self.hub_list.itemDoubleClicked.connect(lambda _: self._start(self.run_connect()))
        self.hub_list.currentItemChanged.connect(lambda *_: self._update_buttons())
        cancel.clicked.connect(self.reject)

    def selected_hub(self) -> DiscoveredHub | None:
        item = self.hub_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    async def run_scan(self) -> None:
        self._set_status("Scanning for 5 s…", "muted")
        self.hub_list.clear()
        try:
            hubs = await self._scan()
        except HubConnectionError as exc:
            self._set_status(str(exc), "danger")
            return
        for hub in hubs:
            rssi = f"{hub.rssi_dbm} dBm" if hub.rssi_dbm is not None else "? dBm"
            item = QListWidgetItem(f"{hub.name}    {hub.address}    {rssi}")
            item.setData(Qt.ItemDataRole.UserRole, hub)
            self.hub_list.addItem(item)
        if hubs:
            self.hub_list.setCurrentRow(0)
            self._set_status(f"Found {len(hubs)} hub(s).", "ok")
        else:
            self._set_status(
                "No Pybricks hub found. Is it on, and not connected to another app?", "warn"
            )

    async def run_connect(self) -> None:
        hub = self.selected_hub()
        if hub is None:
            return
        self._set_status(f"Connecting to {hub.name}…", "muted")
        try:
            await self._connect(hub)
        except HubConnectionError as exc:
            self._set_status(str(exc), "danger")
            return
        self.accept()

    def _start(self, coro) -> None:
        if self._task and not self._task.done():
            coro.close()
            return
        self._task = asyncio.ensure_future(coro)
        self._update_buttons()
        self._task.add_done_callback(lambda _: self._update_buttons())

    def _busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def _update_buttons(self) -> None:
        busy = self._busy()
        self.scan_button.setEnabled(not busy)
        self.connect_button.setEnabled(not busy and self.selected_hub() is not None)

    def _set_status(self, text: str, tone: str) -> None:
        self.status.setText(text)
        set_prop(self.status, "tone", tone)
