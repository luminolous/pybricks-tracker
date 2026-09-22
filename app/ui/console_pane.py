"""Raw hub stdout console with filter and a protocol-line toggle."""

from __future__ import annotations

from collections import deque

from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLineEdit, QPlainTextEdit, QVBoxLayout

from app.core.protocol import is_protocol_line

MAX_LINES = 2000


class ConsolePane(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("console")
        self._lines: deque[str] = deque(maxlen=MAX_LINES)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(MAX_LINES)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("filter…")
        self.hide_protocol = QCheckBox("Hide protocol lines")
        self.auto_scroll = QCheckBox("Auto-scroll")
        self.auto_scroll.setChecked(True)

        side = QFrame()
        side.setObjectName("consoleSide")
        side.setFixedWidth(300)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(16, 10, 16, 10)
        side_layout.setSpacing(8)
        side_layout.addWidget(self.filter_edit)
        checks = QHBoxLayout()
        checks.setSpacing(16)
        checks.addWidget(self.hide_protocol)
        checks.addWidget(self.auto_scroll)
        checks.addStretch()
        side_layout.addLayout(checks)
        side_layout.addStretch()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view, 1)
        layout.addWidget(side)

        self.filter_edit.textChanged.connect(self._rebuild)
        self.hide_protocol.toggled.connect(self._rebuild)

    def append(self, line: str) -> None:
        self._lines.append(line)
        if self._visible(line):
            self.view.appendPlainText(line)
            if self.auto_scroll.isChecked():
                bar = self.view.verticalScrollBar()
                bar.setValue(bar.maximum())

    def visible_text(self) -> str:
        return self.view.toPlainText()

    def _visible(self, line: str) -> bool:
        needle = self.filter_edit.text().strip().lower()
        if needle and needle not in line.lower():
            return False
        return not (self.hide_protocol.isChecked() and is_protocol_line(line))

    def _rebuild(self) -> None:
        self.view.setPlainText("\n".join(line for line in self._lines if self._visible(line)))
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())
