"""Drift test definitions and odometry error analysis.

Three tests, run by drift_test.py.j2 and measured by hand afterwards:

- straight: drive 1000 mm. Encoders believe they drove the commanded
  distance; the ruler says otherwise, which corrects wheel_diameter.
- turns: five full turns with the gyro OFF, so the turn is executed by wheel
  geometry alone. The real rotation corrects axle_track; the IMU heading
  against the real rotation measures the map's heading error.
- square: a 500 mm square with the gyro on, as when following a line. The
  estimated end pose against the real one is the map's closure error.

Run the straight test and apply its wheel_diameter before the turn test: the
turn correction assumes the wheel diameter is already right.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.config import RobotGeometry
from app.core.state import RobotState

SQUARE_CLOSURE_LIMIT_PCT = 5.0  # roadmap M4 acceptance
TURNS_HEADING_LIMIT_DEG = 10.0  # roadmap M4 acceptance


@dataclass(frozen=True)
class DriftTest:
    key: str
    label: str
    moves: tuple[tuple[str, int], ...]  # ("S", mm) straight or ("T", deg) turn, Pybricks signs
    use_gyro: bool
    instructions: str

    @property
    def commanded_distance_mm(self) -> int:
        return sum(amount for kind, amount in self.moves if kind == "S")

    @property
    def commanded_rotation_deg(self) -> int:
        return sum(abs(amount) for kind, amount in self.moves if kind == "T")


DRIFT_TESTS: dict[str, DriftTest] = {
    "straight": DriftTest(
        key="straight",
        label="Straight 1000 mm",
        moves=(("S", 1000),),
        use_gyro=True,
        instructions="Mark the start at the axle. Needs 1.2 m of clear floor ahead.",
    ),
    "turns": DriftTest(
        key="turns",
        label="Turn 360° five times",
        moves=(("T", 1800),),
        use_gyro=False,
        instructions="Align the robot with a straight edge. It turns in place, gyro off.",
    ),
    "square": DriftTest(
        key="square",
        label="500 mm square",
        moves=(("S", 500), ("T", 90)) * 4,
        use_gyro=True,
        instructions="Mark the start at the axle. Needs 70 cm clear on every side.",
    ),
}


@dataclass(frozen=True)
class StraightResult:
    commanded_mm: float
    estimated_mm: float
    real_mm: float
    error_mm_per_m: float
    suggested: RobotGeometry


@dataclass(frozen=True)
class TurnsResult:
    commanded_deg: float
    imu_deg: float
    real_deg: float
    wheel_error_deg_per_rev: float
    heading_error_deg: float
    passed: bool
    suggested: RobotGeometry


@dataclass(frozen=True)
class SquareResult:
    perimeter_mm: float
    map_error_mm: float
    error_pct: float
    passed: bool


def _positive(name: str, value: float) -> None:
    if not value > 0:
        raise ValueError(f"{name} must be greater than zero.")


def analyze_straight(
    geometry: RobotGeometry, estimated_mm: float, real_mm: float
) -> StraightResult:
    """`estimated_mm`: odometry distance from the final T line. `real_mm`: ruler."""
    _positive("Measured distance", real_mm)
    _positive("Estimated distance", estimated_mm)
    test = DRIFT_TESTS["straight"]
    # Encoders count wheel turns; real distance per turn scales with diameter.
    suggested_d = geometry.wheel_diameter_mm * real_mm / estimated_mm
    return StraightResult(
        commanded_mm=test.commanded_distance_mm,
        estimated_mm=estimated_mm,
        real_mm=real_mm,
        error_mm_per_m=(estimated_mm - real_mm) / real_mm * 1000,
        suggested=RobotGeometry(
            wheel_diameter_mm=round(suggested_d, 2),
            axle_track_mm=geometry.axle_track_mm,
            sensor_offset_mm=geometry.sensor_offset_mm,
        ),
    )


def analyze_turns(geometry: RobotGeometry, imu_deg: float, real_deg: float) -> TurnsResult:
    """`imu_deg`: final heading from the last T line. `real_deg`: measured total rotation."""
    _positive("Measured rotation", real_deg)
    commanded = DRIFT_TESTS["turns"].commanded_rotation_deg
    revs = commanded / 360
    imu_abs = abs(imu_deg)
    # With the gyro off the wheels turned the commanded arc:
    # real = commanded * axle / axle_true  ->  axle_true = axle * commanded / real
    suggested_axle = geometry.axle_track_mm * commanded / real_deg
    heading_error = imu_abs - real_deg
    return TurnsResult(
        commanded_deg=commanded,
        imu_deg=imu_abs,
        real_deg=real_deg,
        wheel_error_deg_per_rev=(commanded - real_deg) / revs,
        heading_error_deg=heading_error,
        passed=abs(heading_error) <= TURNS_HEADING_LIMIT_DEG,
        suggested=RobotGeometry(
            wheel_diameter_mm=geometry.wheel_diameter_mm,
            axle_track_mm=round(suggested_axle, 2),
            sensor_offset_mm=geometry.sensor_offset_mm,
        ),
    )


def analyze_square(
    estimated_x_mm: float, estimated_y_mm: float, real_x_mm: float, real_y_mm: float
) -> SquareResult:
    """End pose, relative to the start, as the map saw it and as measured."""
    perimeter = DRIFT_TESTS["square"].commanded_distance_mm
    error = math.hypot(estimated_x_mm - real_x_mm, estimated_y_mm - real_y_mm)
    pct = error / perimeter * 100
    return SquareResult(
        perimeter_mm=perimeter,
        map_error_mm=error,
        error_pct=pct,
        passed=pct <= SQUARE_CLOSURE_LIMIT_PCT,
    )


# -- run metrics (overlay comparison, roadmap M8) ------------------------------


@dataclass(frozen=True)
class RunMetrics:
    duration_s: float
    path_mm: float
    rms_error: float  # reflection around the calibrated edge
    lost_count: int


def run_metrics(state: RobotState, edge: int) -> RunMetrics:
    """Metrics of the trail in `state`, from its running sums: O(1)."""
    trail = state.trail
    duration = (trail[-1].t_ms - trail[0].t_ms) / 1000 if len(trail) > 1 else 0.0
    n = state.reflection_n
    if n:
        mean = state.reflection_sum / n
        mean_sq = state.reflection_sq_sum / n
        # mean((r - e)^2) = mean(r^2) - 2e*mean(r) + e^2
        rms = math.sqrt(max(mean_sq - 2 * edge * mean + edge * edge, 0.0))
    else:
        rms = 0.0
    lost = sum(1 for e in state.events if e.kind == "LOST")
    return RunMetrics(duration, state.path_mm, rms, lost)
