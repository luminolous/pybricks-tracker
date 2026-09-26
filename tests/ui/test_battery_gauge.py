"""Header battery icon: colour from the hub's status flags, fill from the voltage."""

from __future__ import annotations

from pybricksdev.ble.pybricks import StatusFlag
from PySide6.QtWidgets import QApplication

from app.core.protocol import decode_line
from app.ui import theme
from app.ui.battery_gauge import BatteryGauge, charge_fraction
from app.ui.main_window import MainWindow
from tests.fakes import HUB, FakeHubs


def test_charge_fraction_follows_pybricks_thresholds() -> None:
    assert charge_fraction(6000) == 0  # the hub switches off here
    assert charge_fraction(8190) == 1
    assert round(charge_fraction(7120), 2) == 0.51  # the healthy pack from 2026-09-23
    assert charge_fraction(5800) == 0 and charge_fraction(8400) == 1


def test_gauge_levels_and_tooltip(qapp) -> None:
    gauge = BatteryGauge()
    gauge.set_state("ok", 7120)
    assert gauge.color == theme.OK
    assert gauge.toolTip() == ("Hub battery OK\n7.12 V, about 51%\n1.12 V above the 6.0 V shutdown")
    gauge.grab()
    gauge.set_state("low", 6800)  # the hub's warning comes at 6.8 V
    assert gauge.color == theme.WARN
    assert "charge soon" in gauge.toolTip()
    gauge.set_state("low", 6020)  # the pack that died on 2026-09-26
    assert gauge.color == theme.DANGER
    assert gauge.toolTip().startswith("Hub battery nearly empty: charge now")
    assert "0.02 V above the 6.0 V shutdown" in gauge.toolTip()
    gauge.grab()
    gauge.set_state(None)
    assert gauge.toolTip() == "Hub battery: not connected"
    assert gauge.fraction == 0
    gauge.set_state(None, 7500)  # replay: voltage only, neutral colour
    assert gauge.color == theme.DIM and gauge.fraction > 0.6


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
        assert w.battery_gauge.toolTip() == "Hub battery: not connected"
    finally:
        QApplication.instance().removeEventFilter(w)


async def test_nearly_empty_warns_once_per_discharge(qapp) -> None:
    fakes = FakeHubs()
    w = MainWindow(connection_factory=fakes.connection)
    try:
        await w.conn.connect(HUB)
        for mv in (6250, 6240):
            w.state.apply(decode_line(f"S,0,{mv},120,1"))
            w._tick_ui()
        text = w.console.visible_text()
        assert text.count("Battery nearly empty (6.25 V)") == 1
        assert "Battery nearly empty (6.24 V)" not in text
    finally:
        QApplication.instance().removeEventFilter(w)
