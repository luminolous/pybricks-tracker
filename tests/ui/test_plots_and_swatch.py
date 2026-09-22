"""Plot panel, colour swatch and the loop dt warning."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from app.core.config import SensorCalibration
from app.core.protocol import Detail, decode_line
from app.core.state import RobotState
from app.ui.color_swatch import ColorSwatch, classify, hsv_color
from app.ui.main_window import MainWindow, loop_dt_tone
from app.ui.plot_panel import PlotPanel
from tests.fakes import FakeHubs

CAL = SensorCalibration(black=8, white=96)  # edge 52, bands of 11


def fed(*lines: str) -> RobotState:
    state = RobotState()
    for line in lines:
        state.apply(decode_line(line))
    return state


@pytest.mark.parametrize(
    ("reflection", "expected"),
    [(8, "BLACK"), (19, "BLACK"), (20, "EDGE"), (84, "EDGE"), (85, "WHITE")],
)
def test_classify_matches_line_follower_bands(reflection: int, expected: str) -> None:
    assert classify(reflection, CAL) == expected


def test_hsv_color() -> None:
    assert hsv_color(0, 100, 100).name() == "#ff0000"
    assert hsv_color(0, 0, 100).name() == "#ffffff"
    assert hsv_color(370, 100, 100).name() == hsv_color(10, 100, 100).name()


def test_swatch_shows_reading(qapp) -> None:
    swatch = ColorSwatch()
    swatch.show_reading(90, Detail(0, 120, 100, 50, 0, 0, 10), CAL)
    assert swatch.cls.text() == "WHITE"
    assert swatch.refl.text() == "90"
    assert swatch.hsv.text() == "H 120  S 100  V 50"
    assert hsv_color(120, 100, 50).name() in swatch.chip.styleSheet()


@pytest.mark.parametrize(
    ("dt", "tone"), [(10, "text"), (15, "text"), (16, "warn"), (20, "warn"), (21, "danger")]
)
def test_loop_dt_tone(dt: int, tone: str) -> None:
    assert loop_dt_tone(dt, 10) == tone


def test_reflection_tab_plots_last_ten_seconds(qapp) -> None:
    panel = PlotPanel(nominal_dt_ms=10)
    panel.calibration = CAL
    panel.refresh(fed("T,1000,0,0,0,40,0,FOLLOW", "T,3000,0,0,0,60,0,FOLLOW"))
    xs, ys = panel.curves["reflection"].getData()
    assert list(xs) == [-2.0, 0.0]
    assert list(ys) == [40, 60]
    assert panel.big.text() == "60"
    assert "last 10 s" in panel.meta.text()
    assert [line.value() for line in panel.ref_lines] == [96, 52, 8]


def test_error_tab_uses_calibrated_edge(qapp) -> None:
    panel = PlotPanel(nominal_dt_ms=10)
    panel.calibration = CAL
    panel.tabs.setCurrentIndex(1)
    panel.refresh(fed("T,1000,0,0,0,40,-30,FOLLOW"))
    assert list(panel.curves["error"].getData()[1]) == [-12]
    assert list(panel.curves["steer ÷ 3"].getData()[1]) == [-10]


def test_load_and_dt_tabs_read_d_lines(qapp) -> None:
    panel = PlotPanel(nominal_dt_ms=10)
    state = fed("D,250,0,0,0,62,58,11", "D,500,0,0,0,64,57,13")
    panel.tabs.setCurrentIndex(2)
    panel.refresh(state)
    assert list(panel.curves["right"].getData()[1]) == [58, 57]
    assert panel.big.text() == "64 mNm"
    panel.tabs.setCurrentIndex(3)
    panel.refresh(state)
    assert panel.big.text() == "13 ms"
    assert [line.value() for line in panel.ref_lines] == [10, 15]
    legend = [
        panel.legend.itemAt(i).widget().text()
        for i in range(panel.legend.count())
        if panel.legend.itemAt(i).widget() and panel.legend.itemAt(i).widget().text()
    ]
    assert legend == ["loop dt"]


def test_empty_state_shows_dash(qapp) -> None:
    panel = PlotPanel(nominal_dt_ms=10)
    panel.refresh(RobotState())
    assert panel.big.text() == "—"


def test_header_loop_dt_turns_amber_then_red(qapp) -> None:
    w = MainWindow(connection_factory=FakeHubs().connection)
    try:
        w._handle_record(decode_line("D,250,0,0,0,62,58,16"))  # the real route
        w._tick_ui()
        assert w.loop_label.text() == "16 ms"
        assert w.loop_label.property("tone") == "warn"
        w._handle_record(decode_line("D,500,0,0,0,62,58,25"))
        w._tick_ui()
        assert w.loop_label.property("tone") == "danger"
        assert not w.map.swatch.isHidden()
    finally:
        QApplication.instance().removeEventFilter(w)
