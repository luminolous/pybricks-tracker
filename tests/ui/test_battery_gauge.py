"""Header battery icon, driven by the hub's status flags."""

from __future__ import annotations

from pybricksdev.ble.pybricks import StatusFlag
from PySide6.QtWidgets import QApplication

from app.core.protocol import decode_line
from app.ui.battery_gauge import BatteryGauge
from app.ui.main_window import MainWindow
from tests.fakes import HUB, FakeHubs


def test_gauge_levels_and_tooltip(qapp) -> None:
    gauge = BatteryGauge()
    gauge.set_state("ok", 7120)  # the real hub on 2026-09-23: healthy, not "23 %"
    assert gauge.level == "ok"
    assert gauge.toolTip() == "Hub battery OK (7.12 V)"
    gauge.grab()
    gauge.set_state("low")
    assert "charge soon" in gauge.toolTip()
    gauge.set_state(None)
    assert gauge.toolTip() == "Hub battery: not connected"
    gauge.grab()


async def test_hub_status_flags_drive_the_gauge(qapp) -> None:
    fakes = FakeHubs()
    w = MainWindow(connection_factory=fakes.connection)
    try:
        await w.conn.connect(HUB)
        w.state.apply(decode_line("S,0,7120,120,1"))
        w._tick_ui()
        assert w.battery_gauge.level == "ok"
        assert w.battery_label.text() == "7.12 V"
        fakes.hub.status_observable.on_next(StatusFlag.BATTERY_LOW_VOLTAGE_WARNING)
        w._tick_ui()
        assert w.battery_gauge.level == "low"
        fakes.hub.status_observable.on_next(StatusFlag.BATTERY_LOW_VOLTAGE_SHUTDOWN)
        w._tick_ui()
        assert w.battery_gauge.level == "critical"
        fakes.hub.drop_link()
        w._tick_ui()
        assert w.battery_gauge.level is None
    finally:
        QApplication.instance().removeEventFilter(w)
