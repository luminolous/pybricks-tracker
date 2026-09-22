"""Connection-lost banner. Overlays the top of the body so it cannot be missed.

Laid out after the link-loss state in docs/design/main-window-mockup.html:
hazard stripes, a bold title, what happened, and a live silence counter.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from app.ui import theme

BANNER_HEIGHT_PX = 38
BANNER_BG = "#2A0C10"
STRIPE_PX = 10


class HazardStripes(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(120)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BANNER_BG))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.DANGER))
        h = self.height()
        x = -h
        while x < self.width():
            p.drawPolygon(
                QPolygonF(
                    [
                        QPointF(x, h),
                        QPointF(x + STRIPE_PX, h),
                        QPointF(x + STRIPE_PX + h, 0),
                        QPointF(x + h, 0),
                    ]
                )
            )
            x += 2 * STRIPE_PX
        p.end()


class LinkBanner(QFrame):
    def __init__(self, parent: QWidget, top_px: int) -> None:
        super().__init__(parent)
        self._top_px = top_px
        self.setObjectName("linkBanner")
        self.setFixedHeight(BANNER_HEIGHT_PX)
        self.setStyleSheet(
            f"QFrame#linkBanner {{ background: {BANNER_BG};"
            f" border-bottom: 1px solid {theme.DANGER}; }}"
            f" QLabel {{ color: #FFD9DC; font-size: 13px; }}"
            f" QLabel#bannerTitle {{ color: #FFFFFF; font-weight: 600; }}"
            f" QLabel#bannerTime {{ color: #FF9AA1; font-size: 12px; }}"
            f" QPushButton {{ color: #FFD9DC; border: 1px solid #7A2A31; padding: 3px 10px;"
            f" text-align: center; }}"
            f" QPushButton:hover {{ background: #45131A; }}"
        )
        self.title = QLabel("LINK LOST")
        self.title.setObjectName("bannerTitle")
        self.message = QLabel()
        self.silence = QLabel()
        self.silence.setObjectName("bannerTime")
        self.silence.setProperty("mono", True)
        self.dismiss = QPushButton("Dismiss")
        self.dismiss.clicked.connect(self.hide)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 12, 0)
        row.setSpacing(14)
        row.addWidget(HazardStripes())
        row.addWidget(self.title)
        row.addWidget(self.message, 1)
        row.addWidget(self.silence)
        row.addWidget(self.dismiss)
        self.hide()

    def show_message(self, message: str, silence: str = "") -> None:
        self.message.setText(message)
        self.silence.setText(silence)
        self.place()
        if self.isHidden():
            self.show()
            self.raise_()

    def place(self) -> None:
        """Span the parent's width just below the header."""
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(0, self._top_px, parent.width(), BANNER_HEIGHT_PX)
