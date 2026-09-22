"""Previous runs loaded for side-by-side comparison on the map (roadmap M8)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.analysis import RunMetrics, run_metrics
from app.core.config import ConfigError, RobotConfig, SensorCalibration
from app.core.recorder import Session, read_session
from app.core.replay import Replay
from app.core.state import Pose

# Distinct from the UI accent (cyan), the live trail (warm white) and the
# semantic warn/danger colours, so an overlay never reads as a status.
OVERLAY_COLORS = ("#A48CFF", "#6FB7FF", "#F08BD0", "#9BD26B")
MAX_OVERLAYS = len(OVERLAY_COLORS)


@dataclass(frozen=True)
class Overlay:
    path: Path
    label: str
    color: str
    trail: list[Pose]
    metrics: RunMetrics


def session_calibration(session: Session) -> SensorCalibration:
    """The calibration the run used, from its header; defaults if unreadable."""
    try:
        return RobotConfig.from_json(session.header["config"]).calibration
    except (ConfigError, KeyError, TypeError):
        return SensorCalibration()


def session_label(session: Session) -> str:
    started = str(session.header.get("started_at", ""))
    try:
        when = datetime.fromisoformat(started.replace("Z", "+00:00")).strftime("%H:%M")
    except ValueError:
        when = session.path.stem[:13]
    kp = session.header.get("tuning", {}).get("kp")
    return f"{when} · KP {kp:.2f}" if isinstance(kp, int | float) else when


def load_overlay(path: Path, color: str) -> Overlay:
    """Read a session and reduce it to what the map needs. Raises SessionError."""
    session = read_session(path)
    replay = Replay(session)
    replay.seek(replay.end_ms)
    edge = session_calibration(session).edge
    return Overlay(
        path=path,
        label=session_label(session),
        color=color,
        trail=list(replay.state.trail),
        metrics=run_metrics(replay.state, edge),
    )


def next_color(overlays: list[Overlay]) -> str:
    used = {o.color for o in overlays}
    return next((c for c in OVERLAY_COLORS if c not in used), OVERLAY_COLORS[0])
