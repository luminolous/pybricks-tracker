"""Read-only view of the rendered hub program, with line numbers.

A hub SyntaxError reports a line number in the rendered file, so the numbers
shown here are the ones to match against.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from app.ui.theme import caption, label


def number_lines(source: str) -> str:
    lines = source.splitlines()
    width = len(str(len(lines)))
    return "\n".join(f"{i:>{width}}  {line}" for i, line in enumerate(lines, start=1))


class CodePreview(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hub program")
        self.resize(760, 640)
        self._source = ""

        self.path_label = label("", tone="muted", mono=True)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.copy_button = QPushButton("Copy source")
        self.copy_button.setProperty("role", "small")
        self.copy_button.clicked.connect(self.copy_source)
        close = QPushButton("Close")
        close.setProperty("role", "small")
        close.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addWidget(self.path_label, 1)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(caption("Rendered hub program · read only"))
        layout.addWidget(self.view, 1)
        layout.addLayout(buttons)

    def show_program(self, source: str, path: Path | None) -> None:
        self._source = source
        self.view.setPlainText(number_lines(source))
        self.path_label.setText(str(path) if path else "not written to disk")

    def show_error(self, message: str) -> None:
        self._source = ""
        self.view.setPlainText(message)
        self.path_label.setText("")

    def copy_source(self) -> None:
        QApplication.clipboard().setText(self._source)
