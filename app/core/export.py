"""Export a recorded run: telemetry CSV and the raw session JSONL (ui-spec, Export).

The map PNG needs the widget, so it lives in the UI layer.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from app.core.protocol import Detail, Telemetry
from app.core.recorder import Session

CSV_COLUMNS = (
    "t_ms",
    "x_mm",
    "y_mm",
    "heading_deg",
    "reflection",
    "steer",
    "state",
    "hue",
    "saturation",
    "value",
    "load_left",
    "load_right",
    "dt_ms",
)


def session_to_csv(session: Session, out: Path) -> int:
    """One row per T line with the most recent D values joined. Returns the row count."""
    rows = 0
    detail: Detail | None = None
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for record in session.records:
            if isinstance(record, Detail):
                detail = record
            elif isinstance(record, Telemetry):
                d = (
                    (detail.hue, detail.saturation, detail.value)
                    + (detail.load_left, detail.load_right, detail.dt_ms)
                    if detail
                    else ("",) * 6
                )
                writer.writerow(
                    (
                        record.t_ms,
                        record.x_mm,
                        record.y_mm,
                        record.heading_deg,
                        record.reflection,
                        record.steer,
                        record.state,
                        *d,
                    )
                )
                rows += 1
    return rows


def copy_session(source: Path, out: Path) -> None:
    if source.resolve() == out.resolve():
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, out)
