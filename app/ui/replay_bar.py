"""Replay controls: play/pause, timeline scrubber with event ticks, speed, exit.

Shown above the console only in replay mode, as in the mockup.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QWidget

from app.core.replay import SPEEDS
from app.ui import theme
from app.ui.theme import label

BAR_HEIGHT_PX = 38
TRACK_MARGIN_PX = 6


def fmt_ms(ms: float) -> str:
    s = max(ms, 0) / 1000
    return f"{int(s // 60):02d}:{s % 60:04.1f}"


class Timeline(QWidget):
    """Track with a fill up to the position, a head, and coloured event ticks."""

    seeked = Signal(float)  # ms from the start of the session

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.duration_ms = 0.0
        self.position_ms = 0.0
        self.ticks: list[tuple[float, str]] = []

    def set_position(self, ms: float) -> None:
        if ms != self.position_ms:
            self.position_ms = ms
            self.update()

    def _x(self, ms: float) -> float:
        width = self.width() - 2 * TRACK_MARGIN_PX
        frac = ms / self.duration_ms if self.duration_ms > 0 else 0
        return TRACK_MARGIN_PX + width * min(max(frac, 0), 1)

    def _ms(self, x: float) -> float:
        width = max(self.width() - 2 * TRACK_MARGIN_PX, 1)
        return min(max((x - TRACK_MARGIN_PX) / width, 0), 1) * self.duration_ms

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        mid = self.height() / 2
        left, right = self._x(0), self._x(self.duration_ms)
        p.fillRect(QRectF(left, mid - 2, right - left, 4), QColor(theme.LINE_STRONG))
        head = self._x(self.position_ms)
        p.fillRect(QRectF(left, mid - 2, head - left, 4), QColor(theme.ACCENT))
        for ms, color in self.ticks:
            x = self._x(ms)
            p.fillRect(QRectF(x, mid - 9, 1.5, 5), QColor(color))
        p.fillRect(QRectF(head - 1.5, mid - 7, 3, 14), QColor(theme.TEXT))
        p.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.seeked.emit(self._ms(QPointF(event.position()).x()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.seeked.emit(self._ms(QPointF(event.position()).x()))


class ReplayBar(QFrame):
    play_toggled = Signal()
    seeked = Signal(float)  # ms from session start
    speed_changed = Signal(float)
    exit_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("replayBar")
        self.setFixedHeight(BAR_HEIGHT_PX)
        self.setStyleSheet(
            f"QFrame#replayBar {{ background: {theme.SURFACE};"
            f" border-top: 1px solid {theme.LINE_STRONG}; }}"
        )
        self.play_button = QPushButton("▶")
        self.play_button.setProperty("role", "small")
        self.play_button.setFixedWidth(34)
        self.play_button.setToolTip("Play / pause")
        self.time = label("00:00.0", tone="muted", mono=True)
        self.total = label("00:00.0", tone="dim", mono=True)
        self.timeline = Timeline()
        self.speeds = QButtonGroup(self)
        speed_row = QHBoxLayout()
        speed_row.setSpacing(2)
        for speed in SPEEDS:
            button = QPushButton(f"{speed:g}×")
            button.setProperty("role", "tool")
            button.setCheckable(True)
            button.setFixedWidth(40)
            button.setChecked(speed == 1.0)
            self.speeds.addButton(button)
            button.clicked.connect(lambda _=False, s=speed: self.speed_changed.emit(s))
            speed_row.addWidget(button)
        exit_button = QPushButton("Exit replay")
        exit_button.setProperty("role", "small")

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(12)
        row.addWidget(label("REPLAY", tone="accent", mono=True))
        row.addWidget(self.play_button)
        row.addWidget(self.time)
        row.addWidget(self.timeline, 1)
        row.addWidget(self.total)
        row.addLayout(speed_row)
        row.addWidget(exit_button)

        self.play_button.clicked.connect(self.play_toggled.emit)
        self.timeline.seeked.connect(self.seeked.emit)
        exit_button.clicked.connect(self.exit_clicked.emit)

    def set_session(self, duration_ms: float, ticks: list[tuple[float, str]]) -> None:
        self.timeline.duration_ms = duration_ms
        self.timeline.ticks = ticks
        self.total.setText(fmt_ms(duration_ms))
        self.timeline.update()

    def set_position(self, ms: float, playing: bool) -> None:
        self.timeline.set_position(ms)
        self.time.setText(fmt_ms(ms))
        self.play_button.setText("❚❚" if playing else "▶")
