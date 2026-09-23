"""Header battery icon."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from app.core.protocol import decode_line
from app.ui.battery_gauge import BatteryGauge, battery_fraction, battery_tone
from app.ui.main_window import MainWindow
from tests.fakes import FakeHubs


@pytest.mark.parametrize(
    ("mv", "fraction"), [(8300, 1.0), (9000, 1.0), (6800, 0.0), (6000, 0.0), (7550, 0.5)]
)
def test_fraction_is_clamped_linear(mv: int, fraction: float) -> None:
    assert battery_fraction(mv) == pytest.approx(fraction)


@pytest.mark.parametrize(("fraction", "tone"), [(0.5, "text"), (0.15, "warn"), (0.05, "danger")])
def test_tone(fraction: float, tone: str) -> None:
    assert battery_tone(fraction) == tone


def test_gauge_paints_and_explains(qapp) -> None:
    gauge = BatteryGauge()
    gauge.set_voltage(7140)  # the real hub on 2026-09-23
    assert gauge.fraction == pytest.approx(0.2267, abs=1e-3)
    assert "23%" in gauge.toolTip() and "7.14 V" in gauge.toolTip()
    gauge.grab()
    gauge.set_voltage(None)
    assert gauge.fraction is None


def test_header_gauge_follows_s_lines(qapp) -> None:
    w = MainWindow(connection_factory=FakeHubs().connection)
    try:
        w.state.apply(decode_line("S,0,6900,120,1"))
        w._tick_ui()
        assert w.battery_label.text() == "6.90 V"
        assert w.battery_gauge.tone == "danger"
    finally:
        QApplication.instance().removeEventFilter(w)
