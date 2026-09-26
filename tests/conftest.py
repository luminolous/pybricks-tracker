"""Shared fixtures. Qt runs offscreen so tests need no display and no hub."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_sessions(tmp_path, monkeypatch):
    """Recordings made by tests go to a temp dir, never the real sessions/."""
    target = tmp_path / "sessions"
    monkeypatch.setattr("app.core.recorder.SESSIONS_DIR", target)
    return target


@pytest.fixture(autouse=True)
def quiet_hub(monkeypatch):
    """No beep uploads in tests: they would consume the fake hub's program output."""
    monkeypatch.setattr("app.ui.main_window.MainWindow.HUB_BEEPS", False)
