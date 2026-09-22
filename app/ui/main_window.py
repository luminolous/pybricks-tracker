"""Main application window, laid out after docs/design/main-window-mockup.html.

Wires connect, port scan, run with handshake and heartbeat, presets, code
preview, readouts and E-STOP. Map, plots and events are placeholders filled by
later milestones.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QLocale, QObject, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from app.codegen.generator import SCAN_PORTS_PROGRAM, GeneratorError, generate
from app.core.config import CONFIGS_DIR, ConfigError, RobotConfig, RobotGeometry
from app.core.connection import HubConnection, HubConnectionError, LinkState, run_heartbeat
from app.core.protocol import Event, Ready, Telemetry, decode_line, encode_command
from app.core.state import PortScan, TelemetryWatch
from app.ui.code_preview import CodePreview
from app.ui.console_pane import ConsolePane
from app.ui.dialogs.connect import ConnectDialog
from app.ui.link_banner import LinkBanner
from app.ui.port_panel import PortPanel
from app.ui.theme import caption, label, set_prop

logger = logging.getLogger(__name__)

APP_NAME = "Pybricks Tracker"
MIN_WIDTH_PX = 1280
MIN_HEIGHT_PX = 800
HEADER_PX = 44
LEFT_COL_PX = 276  # mockup had 252; port rows need the extra room at real font metrics
RIGHT_COL_PX = 340
SCAN_TIMEOUT_S = 10.0
HANDSHAKE_TIMEOUT_S = 5.0  # upload done -> R line; longer means the program crashed
READOUT_REFRESH_MS = 33  # ~30 fps; widgets never redraw per incoming line
STATE_TONES = {
    "FOLLOW": "accent",
    "PIVOT": "accent",
    "SEARCH": "warn",
    "OBSTACLE": "danger",
    "STOP": "danger",
}
NOTE_PREFIX = "» "  # app messages in the console; never a protocol prefix

ConnectionFactory = Callable[..., HubConnection]


def _frame(name: str) -> QFrame:
    f = QFrame()
    f.setObjectName(name)
    return f


def _spin(low: float, high: float, decimals: int, suffix: str = "") -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setLocale(QLocale.c())  # decimal point, not the OS comma
    spin.setRange(low, high)
    spin.setDecimals(decimals)
    spin.setSuffix(suffix)
    spin.setAlignment(Qt.AlignmentFlag.AlignRight)
    return spin


def _segment(*widgets: QWidget, width: int | None = None) -> QFrame:
    seg = _frame("headerSeg")
    row = QHBoxLayout(seg)
    row.setContentsMargins(16, 0, 16, 0)
    row.setSpacing(8)
    for w in widgets:
        row.addWidget(w)
    if width:
        seg.setFixedWidth(width)
    return seg


def _action_button(text: str, key: str, role: str | None = None) -> QPushButton:
    """Button with its keyboard shortcut shown right-aligned."""
    button = QPushButton()
    if role:
        button.setProperty("role", role)
    row = QHBoxLayout(button)
    row.setContentsMargins(10, 0, 10, 0)
    name = QLabel(text)
    hint = label(key, tone="dim", mono=True)
    for w in (name, hint):
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    row.addWidget(name)
    row.addStretch()
    row.addWidget(hint)
    button.setMinimumHeight(30)
    button.name_label = name  # type: ignore[attr-defined]
    return button


class MainWindow(QMainWindow):
    def __init__(
        self,
        connection_factory: ConnectionFactory = HubConnection,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._clock = clock
        self._watch = TelemetryWatch()
        self._dropped_at: float | None = None  # BLE lost while a program ran
        self._banner_dismissed = False
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(MIN_WIDTH_PX, MIN_HEIGHT_PX)
        self.conn = connection_factory(
            on_link_state=self._on_link_state, on_program_running=self._on_program_running
        )
        self.scan = PortScan()
        self._scan_done = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._drain_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._rx_count = 0
        self._dialog: ConnectDialog | None = None
        self._preview: CodePreview | None = None
        self._preview_auto_opened = False
        self._base_config = RobotConfig()
        self._ready: Ready | None = None
        self._ready_event = asyncio.Event()
        self._latest_t: Telemetry | None = None
        self._shown_t: Telemetry | None = None
        self._readout_timer = QTimer(self)
        self._readout_timer.setInterval(READOUT_REFRESH_MS)
        self._readout_timer.timeout.connect(self._tick_ui)

        central = _frame("central")
        central.setObjectName("central")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self._build_left())
        body.addWidget(self._build_map(), 1)
        body.addWidget(self._build_right())
        root.addLayout(body, 1)
        self.console = ConsolePane()
        self.console.setFixedHeight(112)
        root.addWidget(self.console)
        self.setCentralWidget(central)
        self.banner = LinkBanner(central, top_px=HEADER_PX)
        self.banner.dismiss.clicked.connect(self._dismiss_banner)

        QShortcut(QKeySequence("F5"), self, activated=self._run_clicked)
        QShortcut(QKeySequence("Ctrl+U"), self, activated=self.show_code_preview)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self._scan_clicked)
        QShortcut(QKeySequence("Esc"), self, activated=self._stop_clicked)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.apply_config(self._base_config)
        self._on_link_state(LinkState.DISCONNECTED)
        self._on_program_running(False)

    # -- layout -------------------------------------------------------------

    def _build_header(self) -> QFrame:
        header = _frame("header")
        header.setFixedHeight(HEADER_PX)
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        title = QLabel(APP_NAME)
        title.setStyleSheet("font-weight: 600; font-size: 13px;")
        self.connect_button = QPushButton("Connect")
        self.connect_button.setProperty("role", "small")
        self.connect_button.clicked.connect(self._connect_clicked)
        name_seg = _segment(title, width=LEFT_COL_PX)
        name_seg.layout().addStretch()
        name_seg.layout().addWidget(self.connect_button)

        self.link_dot = _frame("dot")
        self.link_dot.setFixedSize(6, 6)
        self.hub_label = QLabel("no hub")
        self.link_label = label("disconnected", tone="muted")
        self.run_state = label("IDLE", tone="muted", mono=True)
        self.mode_label = label("", tone="muted")
        self.battery_label = label("— V", mono=True)
        self.battery_label.setToolTip("Hub battery, from S lines (M5)")
        self.loop_label = label("— ms", mono=True)
        self.loop_label.setToolTip("Measured hub loop time, from D lines (M5)")
        self.rx_label = label("0 Hz", mono=True)
        self.rx_label.setToolTip("Lines received from the hub per second")

        self.estop_button = QPushButton("E-STOP   Space")
        self.estop_button.setProperty("role", "estop")
        self.estop_button.setMinimumWidth(150)
        self.estop_button.clicked.connect(self._estop_clicked)
        estop_wrap = QWidget()
        estop_row = QHBoxLayout(estop_wrap)
        estop_row.setContentsMargins(6, 5, 6, 5)
        estop_row.addWidget(self.estop_button)

        row.addWidget(name_seg)
        row.addWidget(_segment(self.link_dot, self.hub_label, self.link_label))
        row.addWidget(_segment(self.run_state, self.mode_label))
        row.addStretch()
        row.addWidget(_segment(label("battery", tone="muted"), self.battery_label))
        row.addWidget(_segment(label("loop", tone="muted"), self.loop_label))
        row.addWidget(_segment(label("rx", tone="muted"), self.rx_label))
        row.addWidget(estop_wrap)
        return header

    def _build_left(self) -> QFrame:
        col = _frame("leftCol")
        col.setFixedWidth(LEFT_COL_PX)
        layout = QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.port_panel = PortPanel()
        self.port_panel.changed.connect(self._update_actions)
        layout.addWidget(self.port_panel)

        geometry = _frame("section")
        grid = QGridLayout(geometry)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setVerticalSpacing(8)
        grid.addWidget(caption("Geometry"), 0, 0, 1, 2)
        self.geometry_fields: dict[str, QDoubleSpinBox] = {}
        for i, (key, text) in enumerate(
            (
                ("wheel_diameter_mm", "Wheel diameter"),
                ("axle_track_mm", "Axle track"),
                ("sensor_offset_mm", "Sensor offset"),
            ),
            start=1,
        ):
            spin = _spin(0, 1000, 1, " mm")
            spin.setFixedWidth(96)
            self.geometry_fields[key] = spin
            grid.addWidget(label(text, tone="muted"), i, 0)
            grid.addWidget(spin, i, 1)
        self.preset_label = label("unsaved", tone="dim", mono=True)
        save = QPushButton("Save")
        save.setProperty("role", "small")
        save.clicked.connect(self._save_preset_clicked)
        load = QPushButton("Load")
        load.setProperty("role", "small")
        load.clicked.connect(self._load_preset_clicked)
        presets = QHBoxLayout()
        presets.setSpacing(6)
        presets.addWidget(self.preset_label, 1)
        presets.addWidget(save)
        presets.addWidget(load)
        grid.addLayout(presets, 4, 0, 1, 2)
        layout.addWidget(geometry)

        actions = QWidget()
        box = QVBoxLayout(actions)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(6)
        run_row = QHBoxLayout()
        run_row.setSpacing(6)
        self.run_button = _action_button("Run", "F5", role="run")
        self.run_button.clicked.connect(self._run_clicked)
        self.stop_button = _action_button("Stop", "Esc")
        self.stop_button.clicked.connect(self._stop_clicked)
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.stop_button)
        box.addLayout(run_row)
        self.run_hint = label("", tone="dim")
        self.run_hint.setWordWrap(True)
        box.addWidget(self.run_hint)
        self.scan_button = _action_button("Scan ports", "Ctrl+P")
        self.scan_button.clicked.connect(self._scan_clicked)
        box.addWidget(self.scan_button)
        for text, key, milestone in (
            ("Calibrate sensor", "Ctrl+K", "M6"),
            ("Drift test", "Ctrl+D", "M4"),
            ("Export run", "Ctrl+E", "M8"),
        ):
            button = _action_button(text, key)
            button.setEnabled(False)
            button.setToolTip(f"Arrives in {milestone}")
            box.addWidget(button)
        self.code_button = _action_button("Hub program", "Ctrl+U")
        self.code_button.clicked.connect(self.show_code_preview)
        box.addWidget(self.code_button)
        box.addStretch()
        layout.addWidget(actions, 1)
        return col

    def _build_map(self) -> QWidget:
        wrap = QWidget()
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        tape = _frame("tape")
        tape.setFixedHeight(30)
        canvas = _frame("mapCanvas")
        canvas_layout = QVBoxLayout(canvas)
        hint = label("Map · trail, robot and events arrive in M4", tone="dim")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        canvas_layout.addWidget(hint)

        readout = _frame("readout")
        readout.setFixedHeight(66)
        ro_row = QHBoxLayout(readout)
        ro_row.setContentsMargins(0, 0, 0, 0)
        ro_row.setSpacing(0)
        self.readouts: dict[str, QLabel] = {}
        for key in ("x", "y", "heading", "reflection", "steer", "state"):
            cell = _frame("readoutCell")
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(16, 0, 16, 0)
            cell_layout.setSpacing(4)
            cell_layout.addStretch()
            cell_layout.addWidget(label(key, tone="muted"))
            value = label("—")
            value.setProperty("big", True)
            cell_layout.addWidget(value)
            cell_layout.addStretch()
            self.readouts[key] = value
            ro_row.addWidget(cell, 1)

        tools = _frame("rightCol")
        tools.setFixedWidth(64)
        tools_layout = QVBoxLayout(tools)
        tools_layout.setContentsMargins(0, 12, 0, 12)
        tools_layout.setSpacing(18)
        for text in ("Fit", "Follow", "Origin", "Grid", "Trail", "Overlay"):
            t = label(text, tone="dim")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tools_layout.addWidget(t)
        tools_layout.addStretch()

        grid.addWidget(tape, 0, 0)
        grid.addWidget(canvas, 1, 0)
        grid.addWidget(readout, 2, 0)
        grid.addWidget(tools, 0, 1, 3, 1)
        grid.setRowStretch(1, 1)
        return wrap

    def _build_right(self) -> QFrame:
        col = _frame("rightCol")
        col.setFixedWidth(RIGHT_COL_PX)
        layout = QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs_wrap = _frame("section")
        tabs_layout = QVBoxLayout(tabs_wrap)
        tabs_layout.setContentsMargins(8, 0, 16, 14)
        self.plot_tabs = QTabBar()
        self.plot_tabs.setDrawBase(False)
        for name in ("Reflection", "Error / steer", "Motor load", "Loop dt"):
            self.plot_tabs.addTab(name)
        plot_area = _frame("plotArea")
        plot_area.setFixedHeight(150)
        plot_hint = QVBoxLayout(plot_area)
        p = label("Plots arrive in M5", tone="dim")
        p.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plot_hint.addWidget(p)
        tabs_layout.addWidget(self.plot_tabs)
        tabs_layout.addSpacing(8)
        tabs_layout.addWidget(plot_area)
        layout.addWidget(tabs_wrap)

        tuning = _frame("section")
        t_layout = QGridLayout(tuning)
        t_layout.setContentsMargins(16, 14, 16, 14)
        t_layout.setVerticalSpacing(8)
        t_layout.addWidget(caption("Tuning"), 0, 0, 1, 2)
        self.tuning_hint = label("sent with Run; live in M6", tone="dim")
        t_layout.addWidget(self.tuning_hint, 0, 2, Qt.AlignmentFlag.AlignRight)
        self.tuning_fields: dict[str, QDoubleSpinBox] = {
            "kp": _spin(-50, 50, 2),
            "kd": _spin(-50, 50, 2),
            "base_speed_mm_s": _spin(0, 500, 0, " mm/s"),
        }
        for i, (key, name) in enumerate(
            (("kp", "KP"), ("kd", "KD"), ("base_speed_mm_s", "SPD")), start=1
        ):
            t_layout.addWidget(label(name, tone="muted", mono=True), i, 0)
            t_layout.addWidget(self.tuning_fields[key], i, 2)
        t_layout.setColumnStretch(1, 1)
        layout.addWidget(tuning)

        events = _frame("section")
        e_layout = QVBoxLayout(events)
        e_layout.setContentsMargins(16, 14, 16, 14)
        e_layout.addWidget(caption("Events"))
        hint = label("Event list arrives in M7. Events show in the console.", tone="dim")
        hint.setWordWrap(True)
        e_layout.addWidget(hint)
        e_layout.addStretch()
        layout.addWidget(events, 1)
        return col

    # -- config ---------------------------------------------------------------

    def current_config(self) -> RobotConfig:
        """The config the UI shows. Fields without a widget come from the loaded preset."""
        g = {key: spin.value() for key, spin in self.geometry_fields.items()}
        t = {key: spin.value() for key, spin in self.tuning_fields.items()}
        return RobotConfig(
            ports=self.port_panel.assignments(),
            geometry=RobotGeometry(**g),
            tuning=replace(self._base_config.tuning, **t),
            calibration=self._base_config.calibration,
        )

    def apply_config(self, config: RobotConfig) -> None:
        self._base_config = config
        self.port_panel.set_assignments(config.ports)
        for key, spin in self.geometry_fields.items():
            spin.setValue(getattr(config.geometry, key))
        for key, spin in self.tuning_fields.items():
            spin.setValue(getattr(config.tuning, key))

    def save_preset(self, path: Path) -> None:
        self.current_config().save(path)
        self.preset_label.setText(path.name)
        self.note(f"saved preset {path}")

    def load_preset(self, path: Path) -> bool:
        try:
            config = RobotConfig.load(path)
        except ConfigError as exc:
            self.note(str(exc))
            return False
        self.apply_config(config)
        self.preset_label.setText(path.name)
        self.note(f"loaded preset {path}")
        return True

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        """Start background tasks. Call once the qasync loop is running."""
        self._drain_task = asyncio.ensure_future(self._drain_lines())
        self._heartbeat_task = asyncio.ensure_future(run_heartbeat(self.conn))
        self._readout_timer.start()

    async def shutdown(self) -> None:
        """Stop the hub program if one runs, then disconnect. Never raises."""
        self._readout_timer.stop()
        for task in (self._drain_task, self._heartbeat_task, *self._tasks):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        if self.conn.connected:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.stop_program("app closing"), timeout=2)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.conn.disconnect(), timeout=3)

    def tick_1hz(self, _tick: int) -> None:
        self.rx_label.setText(f"{self._rx_count} Hz")
        self._rx_count = 0

    # -- hub actions ----------------------------------------------------------

    async def scan_ports(self) -> bool:
        """Run scan_ports.py and wait for P,DONE. Returns True when the scan finished."""
        if not self.conn.connected:
            self.note("Connect to a hub before scanning.")
            return False
        self.scan.reset()
        self._scan_done.clear()
        self.port_panel.set_scanning()
        self.note(f"running {SCAN_PORTS_PROGRAM.name}")
        try:
            await self.conn.run_file(SCAN_PORTS_PROGRAM)
            await asyncio.wait_for(self._scan_done.wait(), timeout=SCAN_TIMEOUT_S)
        except HubConnectionError as exc:
            self.note(str(exc))
            return False
        except TimeoutError:
            self.note(f"Port scan did not finish within {SCAN_TIMEOUT_S:.0f} s.")
            self.port_panel.apply_scan(self.scan)
            return False
        if self.scan.missing_ports:
            self.note(f"Scan lost lines for ports {', '.join(self.scan.missing_ports)}. Rescan.")
        return True

    def run_blocker(self) -> str | None:
        """Why Run is not possible right now, or None."""
        if not self.conn.connected:
            return "Connect to a hub to run."
        if self.conn.program_running:
            return "A program is running. Stop it first."
        return self.port_panel.validation_error()

    async def run_program(self, mode: str = "line_follower") -> bool:
        """Render, upload and start `mode`, then wait for its R handshake."""
        blocker = self.run_blocker()
        if blocker:
            self.note(blocker)
            return False
        try:
            path = generate(self.current_config(), mode)
        except GeneratorError as exc:
            self.note(str(exc))
            return False
        self._ready = None
        self._ready_event.clear()
        self.note(f"uploading {path}")
        try:
            await self.conn.run_file(path)
            await asyncio.wait_for(self._ready_event.wait(), timeout=HANDSHAKE_TIMEOUT_S)
        except HubConnectionError as exc:
            self.note(str(exc))
            return False
        except TimeoutError:
            self.note(
                f"No handshake from the hub program within {HANDSHAKE_TIMEOUT_S:.0f} s. "
                "It probably crashed; check the console and the program."
            )
            if not self._preview_auto_opened:
                self._preview_auto_opened = True
                self.show_code_preview()
            return False
        ready = self._ready
        if ready is None or not ready.compatible:
            self.note("Hub program protocol does not match this app. Stopping it.")
            await self.stop_program("protocol mismatch")
            return False
        self.mode_label.setText(ready.mode.lower())
        return True

    async def stop_program(self, reason: str) -> None:
        """Tell the program to stop, then stop it. Both are tried even if one fails."""
        self.note(reason)
        if not self.conn.connected:
            return
        with contextlib.suppress(HubConnectionError):
            await self.conn.write_line(encode_command("MODE", "STOP"))
        try:
            await self.conn.stop()
        except HubConnectionError as exc:
            self.note(str(exc))

    async def emergency_stop(self) -> None:
        await self.stop_program("E-STOP")

    def show_code_preview(self) -> None:
        if self._preview is None:
            self._preview = CodePreview(self)
        try:
            path = generate(self.current_config(), "line_follower")
        except GeneratorError as exc:
            self._preview.show_error(str(exc))
        else:
            self._preview.show_program(path.read_text(encoding="utf-8"), path)
        self._preview.show()
        self._preview.raise_()

    def note(self, text: str) -> None:
        self.console.append(NOTE_PREFIX + text)

    async def _drain_lines(self) -> None:
        while True:
            line = await self.conn.lines.get()
            self._rx_count += 1
            self.console.append(line)
            self._handle_record(decode_line(line))

    def _handle_record(self, record: object) -> None:
        if isinstance(record, Telemetry):
            self._latest_t = record
            self._watch.saw_telemetry(self._clock())
            self._banner_dismissed = False
        elif isinstance(record, Ready):
            if not record.compatible:
                self.note(
                    f"Hub program speaks protocol {record.proto_version}, app expects a "
                    "different version. Stop it and run again."
                )
            if record.mode != "SCAN":
                self._ready = record
                self._ready_event.set()
                self._watch.arm(self._clock())
                self._dropped_at = None
        elif isinstance(record, Event):
            if record.kind == "WDOG":
                self.note(f"Hub watchdog stopped the robot: no command for {record.detail} ms.")
            elif record.kind == "GIVEUP":
                self.note("Line search failed in both directions. Robot stopped.")
        elif self.scan.apply(record) and self.scan.done:
            self.port_panel.apply_scan(self.scan)
            self._scan_done.set()

    def _tick_ui(self) -> None:
        self._refresh_readouts()
        self._check_link()

    def _check_link(self) -> None:
        """Show the banner while the link is lost; hide it once telemetry is back."""
        now = self._clock()
        if self._dropped_at is not None:
            self._show_banner(
                "Bluetooth link lost while a program was running. The hub watchdog stops "
                "the robot 2 s after the last heartbeat. Go and check it.",
                f"{now - self._dropped_at:.1f} s ago",
            )
        elif self._watch.lost(now):
            self._show_banner(
                "No telemetry for 2 s while the program runs. The robot may still be "
                "moving: press Space for E-STOP, or go and check it.",
                f"last T {self._watch.silence_s(now):.1f} s ago",
            )
        else:
            self.banner.hide()

    def _show_banner(self, message: str, silence: str) -> None:
        if self._banner_dismissed:
            return
        self.banner.show_message(message, silence)

    def _dismiss_banner(self) -> None:
        self._banner_dismissed = True
        self.banner.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.banner.place()

    def _refresh_readouts(self) -> None:
        t = self._latest_t
        if t is None or t is self._shown_t:
            return
        self._shown_t = t
        r = self.readouts
        r["x"].setText(f"{t.x_mm:.1f}")
        r["y"].setText(f"{t.y_mm:.1f}")
        r["heading"].setText(f"{t.heading_deg:.1f}°")
        r["reflection"].setText(str(t.reflection))
        r["steer"].setText(str(t.steer))
        r["state"].setText(t.state)
        set_prop(r["state"], "tone", STATE_TONES.get(t.state, "text"))

    # -- slots ----------------------------------------------------------------

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)

        def done(t: asyncio.Task) -> None:
            self._tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                logger.error("UI task failed", exc_info=t.exception())
                self.note(f"Error: {t.exception()}")

        task.add_done_callback(done)

    def _connect_clicked(self) -> None:
        if self.conn.link_state is not LinkState.DISCONNECTED:
            self._spawn(self.conn.disconnect())
            return
        self._dialog = ConnectDialog(self.conn.scan, self.conn.connect, self)
        self._dialog.open()
        self._spawn(self._dialog.run_scan())

    def _scan_clicked(self) -> None:
        if self.scan_button.isEnabled():
            self._spawn(self.scan_ports())

    def _run_clicked(self) -> None:
        if self.run_button.isEnabled():
            self._spawn(self.run_program())

    def _stop_clicked(self) -> None:
        if self.conn.program_running:
            self._spawn(self.stop_program("Stop"))

    def _estop_clicked(self) -> None:
        self._spawn(self.emergency_stop())

    def _save_preset_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save preset", str(CONFIGS_DIR / "robot.json"), "Preset (*.json)"
        )
        if path:
            self.save_preset(Path(path))

    def _load_preset_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load preset", str(CONFIGS_DIR), "Preset (*.json)"
        )
        if path:
            self.load_preset(Path(path))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        # Spacebar is a global E-STOP while a program runs, even inside text fields.
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Space
            and not event.isAutoRepeat()
            and self.conn.program_running
        ):
            self._estop_clicked()
            return True
        return super().eventFilter(watched, event)

    # -- connection callbacks -------------------------------------------------

    def _on_link_state(self, state: LinkState) -> None:
        connected = state is LinkState.CONNECTED
        tone = {LinkState.CONNECTED: "ok", LinkState.CONNECTING: "warn"}.get(state, "danger")
        set_prop(self.link_dot, "tone", tone)
        self.link_label.setText(state.value)
        self.hub_label.setText(self.conn.hub_name or "no hub")
        self.connect_button.setText("Connect" if state is LinkState.DISCONNECTED else "Disconnect")
        if not connected:
            self._rx_count = 0
        if state is LinkState.DISCONNECTED and self._watch.armed:
            self._dropped_at = self._clock()
            self._banner_dismissed = False
            self._watch.disarm()
            self._check_link()
        elif connected:
            self._dropped_at = None
        self._update_actions()

    def _on_program_running(self, running: bool) -> None:
        self.run_state.setText("RUNNING" if running else "IDLE")
        set_prop(self.run_state, "tone", "ok" if running else "muted")
        if not running:
            self.mode_label.setText("")
            self._watch.disarm()  # program ended; a BLE drop was handled first
            self._check_link()
        self._update_actions()

    def _update_actions(self) -> None:
        connected = self.conn.connected
        running = self.conn.program_running
        blocker = self.run_blocker()
        self.run_button.setEnabled(blocker is None)
        self.run_hint.setText(blocker or "")
        self.run_hint.setVisible(bool(blocker))
        self.scan_button.setEnabled(connected and not running)
        self.stop_button.setEnabled(running)
        self.estop_button.setEnabled(connected)
        # Config is frozen while a program runs; live tuning is M6.
        for widget in (
            self.port_panel,
            *self.geometry_fields.values(),
            *self.tuning_fields.values(),
        ):
            widget.setEnabled(not running)
