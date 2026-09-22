"""Drift analysis maths, with numbers worked by hand."""

from __future__ import annotations

import pytest

from app.core.analysis import (
    DRIFT_TESTS,
    analyze_square,
    analyze_straight,
    analyze_turns,
)
from app.core.config import RobotGeometry

GEOMETRY = RobotGeometry(wheel_diameter_mm=56.0, axle_track_mm=112.0, sensor_offset_mm=40.0)


def test_test_definitions() -> None:
    assert DRIFT_TESTS["straight"].commanded_distance_mm == 1000
    assert DRIFT_TESTS["turns"].commanded_rotation_deg == 1800
    assert not DRIFT_TESTS["turns"].use_gyro
    assert DRIFT_TESTS["square"].commanded_distance_mm == 2000
    assert DRIFT_TESTS["square"].commanded_rotation_deg == 360


def test_straight_short_run_means_smaller_wheels() -> None:
    # Encoders said 1000 mm, the ruler says 980 mm: the wheel is 2 % smaller.
    r = analyze_straight(GEOMETRY, estimated_mm=1000, real_mm=980)
    assert r.error_mm_per_m == pytest.approx(20.408, abs=1e-3)
    assert r.suggested.wheel_diameter_mm == pytest.approx(54.88)
    assert r.suggested.axle_track_mm == GEOMETRY.axle_track_mm


def test_straight_perfect_run_keeps_geometry() -> None:
    r = analyze_straight(GEOMETRY, estimated_mm=1000, real_mm=1000)
    assert r.error_mm_per_m == 0
    assert r.suggested == GEOMETRY


def test_turns_overshoot_means_axle_is_narrower() -> None:
    # Commanded 1800 deg by wheel arc, robot really turned 1836 deg (+36).
    r = analyze_turns(GEOMETRY, imu_deg=-1830.0, real_deg=1836.0)
    assert r.wheel_error_deg_per_rev == pytest.approx(-7.2)
    assert r.suggested.axle_track_mm == pytest.approx(112 * 1800 / 1836, abs=0.01)
    assert r.imu_deg == 1830.0
    assert r.heading_error_deg == pytest.approx(-6.0)
    assert r.passed


def test_turns_heading_error_over_limit_fails() -> None:
    assert not analyze_turns(GEOMETRY, imu_deg=1789.0, real_deg=1800.0).passed


def test_square_closure_percent() -> None:
    r = analyze_square(estimated_x_mm=30, estimated_y_mm=40, real_x_mm=0, real_y_mm=0)
    assert r.map_error_mm == 50
    assert r.error_pct == 2.5
    assert r.passed
    assert not analyze_square(0, 0, 120, 0).passed  # 6 % of 2000 mm


@pytest.mark.parametrize("bad", [0, -5])
def test_rejects_non_positive_measurements(bad: float) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        analyze_straight(GEOMETRY, 1000, bad)
    with pytest.raises(ValueError, match="greater than zero"):
        analyze_turns(GEOMETRY, 1800, bad)
