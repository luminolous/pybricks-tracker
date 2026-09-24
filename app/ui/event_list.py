"""Event list, newest first. Clicking a row selects its map marker and, in
replay, seeks to that moment."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout

from app.core.state import EventRecord
from app.ui import theme
from app.ui.theme import caption, label

KIND_COLORS = {
    "LOST": theme.WARN,
    "GIVEUP": theme.WARN,
    "FOUND": theme.OK,
    "OBS": theme.DANGER,
    "STALL": theme.DANGER,
    "BUMP": theme.DANGER,
    "WDOG": theme.DANGER,
    "LAP": theme.ACCENT,
    "TURN": theme.ACCENT,
    "FINISH": theme.OK,
}


def event_color(kind: str) -> str:
    return KIND_COLORS.get(kind, theme.MUTED)


class EventList(QFrame):
    event_clicked = Signal(object)  # EventRecord

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("section")
        self.count = label("", tone="dim")
        head = QHBoxLayout()
        head.addWidget(caption("Events"))
        head.addStretch()
        head.addWidget(self.count)
        self.list = QListWidget()
        self.list.setObjectName("eventList")
        self.list.itemClicked.connect(self._clicked)
        self._shown: list[EventRecord] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addLayout(head)
        layout.addWidget(self.list, 1)

    def set_events(self, events: list[EventRecord]) -> None:
        if events == self._shown:
            return
        if self._shown and events[: len(self._shown)] == self._shown:
            new = events[len(self._shown) :]  # live: only append, keep selection
        else:
            self.list.clear()
            new = events
        for event in new:
            self.list.insertItem(0, self._item(event))
        self._shown = list(events)
        self.count.setText(f"{len(events)}" if events else "")

    def select(self, event: EventRecord | None) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == event:
                self.list.setCurrentItem(item)
                return
        self.list.clearSelection()

    def _item(self, event: EventRecord) -> QListWidgetItem:
        text = f"{event.t_ms / 1000:6.1f}s  {event.kind:<6} {event.describe()}"
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, event)
        item.setForeground(QColor(event_color(event.kind)))
        return item

    def _clicked(self, item: QListWidgetItem) -> None:
        self.event_clicked.emit(item.data(Qt.ItemDataRole.UserRole))
