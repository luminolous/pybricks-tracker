"""Session recording: one JSON object per line, header first (architecture.md).

    {"type":"header","version":1,"started_at":"...","mode":"line_follower","config":{...},...}
    {"type":"T","t":1532,"x":245.3,"y":88.1,"heading":93.0,"reflection":47,"steer":-12,...}
    {"type":"E","kind":"LOST","t":12400,"x":245.3,"y":88.1}

The header waits for the first S line so it carries the battery voltage;
records that arrive before it are buffered. Reading never trusts the file:
unreadable lines are counted and skipped.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from app.core.config import RobotConfig
from app.core.protocol import Detail, Event, Record, Status, Telemetry

SESSION_VERSION = 1
SESSIONS_DIR = Path(__file__).resolve().parents[2] / "sessions"
FLUSH_EVERY = 50  # lines; a crash loses at most ~2.5 s of T


class SessionError(ValueError):
    """A session file cannot be replayed. The message is safe to show in the UI."""


def record_to_json(record: Record) -> dict[str, Any] | None:
    if isinstance(record, Telemetry):
        return {
            "type": "T",
            "t": record.t_ms,
            "x": record.x_mm,
            "y": record.y_mm,
            "heading": record.heading_deg,
            "reflection": record.reflection,
            "steer": record.steer,
            "state": record.state,
        }
    if isinstance(record, Detail):
        return {
            "type": "D",
            "t": record.t_ms,
            "h": record.hue,
            "s": record.saturation,
            "v": record.value,
            "load_left": record.load_left,
            "load_right": record.load_right,
            "dt": record.dt_ms,
        }
    if isinstance(record, Status):
        return {
            "type": "S",
            "t": record.t_ms,
            "battery_mv": record.battery_mv,
            "battery_ma": record.battery_ma,
            "imu_ready": record.imu_ready,
        }
    if isinstance(record, Event):
        out = {
            "type": "E",
            "kind": record.kind,
            "t": record.t_ms,
            "x": record.x_mm,
            "y": record.y_mm,
        }
        if record.detail is not None:
            out["detail"] = record.detail
        return out
    return None


def record_from_json(data: dict[str, Any]) -> Record | None:
    kind = data.get("type")
    if kind == "T":
        return Telemetry(
            int(data["t"]),
            float(data["x"]),
            float(data["y"]),
            float(data["heading"]),
            int(data["reflection"]),
            int(data["steer"]),
            str(data["state"]),
        )
    if kind == "D":
        return Detail(
            int(data["t"]),
            int(data["h"]),
            int(data["s"]),
            int(data["v"]),
            int(data["load_left"]),
            int(data["load_right"]),
            int(data["dt"]),
        )
    if kind == "S":
        return Status(
            int(data["t"]),
            int(data["battery_mv"]),
            int(data["battery_ma"]),
            bool(data["imu_ready"]),
        )
    if kind == "E":
        detail = data.get("detail")
        return Event(
            str(data["kind"]),
            int(data["t"]),
            float(data["x"]),
            float(data["y"]),
            None if detail is None else str(detail),
        )
    return None


class SessionRecorder:
    def __init__(self, sessions_dir: Path | None = None) -> None:
        self._sessions_dir = sessions_dir
        self.path: Path | None = None
        self._file: IO[str] | None = None
        self._header: dict[str, Any] | None = None
        self._pending: list[dict[str, Any]] = []
        self._unflushed = 0
        self.lines_written = 0

    @property
    def recording(self) -> bool:
        return self.path is not None

    def start(self, mode: str, config: RobotConfig, started_at: datetime | None = None) -> Path:
        """Open a new session file. The header is written once the battery is known."""
        self.close()
        stamp = started_at or datetime.now(UTC)
        # Resolved per start, not at import, so tests can point it elsewhere.
        directory = self._sessions_dir or SESSIONS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{stamp:%Y%m%d-%H%M%S}_{mode}.jsonl"
        self._file = self.path.open("w", encoding="utf-8", newline="\n")
        self._header = {
            "type": "header",
            "version": SESSION_VERSION,
            "started_at": stamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "mode": mode,
            "config": config.to_json(),
            "tuning": asdict(config.tuning),
            "battery_mv": None,
        }
        self._pending = []
        self.lines_written = 0
        return self.path

    def write(self, record: Record) -> None:
        if self._file is None:
            return
        data = record_to_json(record)
        if data is None:
            return
        if self._header is not None:
            if isinstance(record, Status):
                self._header["battery_mv"] = record.battery_mv
                self._write_header()
            else:
                self._pending.append(data)
                return
        self._write_line(data)

    def close(self) -> Path | None:
        """Flush and close. Returns the file just finished, if any."""
        path = self.path
        if self._file is not None:
            if self._header is not None:  # no S line ever came
                self._write_header()
            self._file.flush()
            self._file.close()
        self._file = None
        self.path = None
        return path

    def _write_header(self) -> None:
        header, self._header = self._header, None
        self._write_line(header)
        for data in self._pending:
            self._write_line(data)
        self._pending = []

    def _write_line(self, data: dict[str, Any]) -> None:
        assert self._file is not None
        self._file.write(json.dumps(data, separators=(",", ":")) + "\n")
        self.lines_written += 1
        self._unflushed += 1
        if self._unflushed >= FLUSH_EVERY:
            self._file.flush()
            self._unflushed = 0


@dataclass
class Session:
    path: Path
    header: dict[str, Any]
    records: list[Record]
    skipped: int  # unreadable lines

    @property
    def mode(self) -> str:
        return str(self.header.get("mode", "unknown"))


def read_session(path: Path) -> Session:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SessionError(f"Cannot read {path.name}: {exc.strerror or exc}") from exc
    try:
        header = json.loads(lines[0]) if lines else None
    except json.JSONDecodeError:
        header = None
    if not isinstance(header, dict) or header.get("type") != "header":
        raise SessionError(f"{path.name} has no session header on its first line.")
    if header.get("version") != SESSION_VERSION:
        raise SessionError(f"{path.name} is session version {header.get('version')!r}.")
    records: list[Record] = []
    skipped = 0
    for line in lines[1:]:
        try:
            record = record_from_json(json.loads(line))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
            record = None
        if record is None:
            skipped += 1
        else:
            records.append(record)
    return Session(path, header, records, skipped)
