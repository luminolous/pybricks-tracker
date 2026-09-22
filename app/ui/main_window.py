"""Main application window, laid out after docs/design/main-window-mockup.html.

Wires connect, port scan, run with handshake and heartbeat, presets, code
preview, map, plots, readouts, drift test and E-STOP. Events and live tuning
arrive in later milestones.
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
    QVBoxLayout,
    QWidget,
)

from app.codegen.generator import LOOP_MS, SCAN_PORTS_PROGRAM, GeneratorError, generate
from app.core.config import (
    CONFIGS_DIR,
    ConfigError,
    RobotConfig,
    RobotGeometry,
    SensorCalibration,
)
from app.core.connection import HubConnection, HubConnectionError, LinkState, run_heartbeat
from app.core.protocol import (
    Detail,
    Event,
    Ready,
    Status,
    Telemetry,
    decode_line,
    encode_command,
    parse_ack,
)
from app.core.state import PortScan, RobotState, TelemetryWatch
from app.core.tuning import TuningSender
from app.ui.code_preview import CodePreview
from app.ui.console_pane import ConsolePane
from app.ui.dialogs.calibration import CalibrationDialog
from app.ui.dialogs.connect import ConnectDialog
from app.ui.dialogs.drift_test import DriftTestDialog
from app.ui.link_banner import LinkBanner
from app.ui.map_view import MapView
from app.ui.plot_panel import DT_WARN, PlotPanel
from app.ui.port_panel import PortPanel
from app.ui.theme import caption, label, set_prop
from app.ui.tuning_panel import TuningPanel

logger = logging.getLogger(__name__)

APP_NAME = "Pybricks Tracker"
MIN_WIDTH_PX = 1280
MIN_HEIGHT_PX = 800
HEADER_PX = 44
LEFT_COL_PX = 276  # mockup had 252; port rows need the extra room at real font metrics
RIGHT_COL_PX = 340
SCAN_TIMEOUT_S = 10.0
HANDSHAKE_TIMEOUT_S = 5.0  # upload done -> R line; longer means the program crashed
DRAIN_GRACE_S = 0.3  # let queued stdout lines land after a program ends
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


def loop_dt_tone(dt_ms: float, nominal_ms: float) -> str:
    """Header colour for the measured loop time: amber above 1.5x, red above 2x (ui-spec)."""
    if dt_ms > 2 * nominal_ms:
        return "danger"
    if dt_ms > DT_WARN * nominal_ms:
        return "warn"
    return "text"


def _tool_button(text: str, tip: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("role", "tool")
    button.setToolTip(tip)
    return button


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
        self.state = RobotState()
        self._current_mode: str | None = None
        self._drift_dialog: DriftTestDialog | None = None
        self._calibration_dialog: CalibrationDialog | None = None
        self._tuning_live = False
        self._tuning_task: asyncio.Task | None = None
        self._dropped_at: float | None = None  # BLE lost while a program ran
        self._banner_dismissed = False
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(MIN_WIDTH_PX, MIN_HEIGHT_PX)
        self.conn = connection_factory(
            on_link_state=self._on_link_state, on_program_running=self._on_program_running
        )
        self.tuner = TuningSender(self.conn.write_line, clock=clock)
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
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.show_drift_test)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.show_calibration)
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
        self.calibrate_button = _action_button("Calibrate sensor", "Ctrl+K")
        self.calibrate_button.clicked.connect(self.show_calibration)
        box.addWidget(self.calibrate_button)
        self.drift_button = _action_button("Drift test", "Ctrl+D")
        self.drift_button.clicked.connect(self.show_drift_test)
        box.addWidget(self.drift_button)
        export = _action_button("Export run", "Ctrl+E")
        export.setEnabled(False)
        export.setToolTip("Arrives in M8")
        box.addWidget(export)
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

        self.map = MapView()
        self.map.follow_changed.connect(self._follow_changed)

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
        tools_layout.setSpacing(4)
        self.fit_button = _tool_button("Fit", "Fit the whole trail in view")
        self.fit_button.clicked.connect(lambda: self.map.fit(self.state))
        self.follow_button = _tool_button("Follow", "Keep the robot centred")
        self.follow_button.setCheckable(True)
        self.follow_button.setChecked(True)
        self.follow_button.toggled.connect(self.map.set_follow)
        self.origin_button = _tool_button("Origin", "Make the current pose the new origin")
        self.origin_button.clicked.connect(self._origin_clicked)
        for button in (self.fit_button, self.follow_button, self.origin_button):
            tools_layout.addWidget(button)
        tools_layout.addSpacing(14)
        for text, value, tip in (
            ("Grid", "10cm", ""),
            ("Trail", "plain", "More trail modes arrive in M8"),
            ("Overlay", "0", "Run overlays arrive in M8"),
        ):
            t = label(f"{text}\n{value}", tone="dim")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setToolTip(tip)
            tools_layout.addWidget(t)
        tools_layout.addStretch()

        grid.addWidget(self.map, 0, 0)
        grid.addWidget(readout, 1, 0)
        grid.addWidget(tools, 0, 1, 2, 1)
        grid.setRowStretch(0, 1)
        return wrap

    def _build_right(self) -> QFrame:
        col = _frame("rightCol")
        col.setFixedWidth(RIGHT_COL_PX)
        layout = QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        plots = _frame("section")
        plots_layout = QVBoxLayout(plots)
        plots_layout.setContentsMargins(0, 0, 0, 0)
        self.plots = PlotPanel(nominal_dt_ms=LOOP_MS)
        plots_layout.addWidget(self.plots)
        layout.addWidget(plots)

        self.tuning = TuningPanel()
        self.tuning.changed.connect(self._tuning_changed)
        layout.addWidget(self.tuning)

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
        t = self.tuning.values()
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
        self.tuning.set_values(config.tuning)

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
        self._tuning_task = asyncio.ensure_future(self.tuner.run(lambda: self._tuning_live))
        self._readout_timer.start()

    async def shutdown(self) -> None:
        """Stop the hub program if one runs, then disconnect. Never raises."""
        self._readout_timer.stop()
        for task in (self._drain_task, self._heartbeat_task, self._tuning_task, *self._tasks):
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

    async def run_program(self, mode: str = "line_follower", drift: str | None = None) -> bool:
        """Render, upload and start `mode`, then wait for its R handshake."""
        blocker = self.run_blocker()
        if blocker:
            self.note(blocker)
            return False
        try:
            path = generate(self.current_config(), mode, drift=drift)
        except GeneratorError as exc:
            self.note(str(exc))
            return False
        self._current_mode = mode
        self._set_tuning_mode("waiting")
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

    # -- tuning and calibration ------------------------------------------

    def _set_tuning_mode(self, mode: str) -> None:
        self._tuning_live = mode == "live"
        self.tuning.set_mode(mode)

    def _start_live_tuning(self, ready: Ready) -> None:
        if not ready.compatible:
            return  # run_program stops it; never send tuning to a mismatched program
        if ready.mode != "LINE_FOLLOWER":
            self._set_tuning_mode("off")  # drift test and calibration ignore KP/KD/SPD
            return
        # The hub starts with the values rendered into it: already acknowledged.
        self.tuner.reset()
        for key, row in self.tuning.rows.items():
            self.tuner.seed(key, row.value())
        self._set_tuning_mode("live")

    def _tuning_changed(self, key: str, value: float) -> None:
        if self._tuning_live:
            self.tuner.want(key, value)

    def show_calibration(self) -> None:
        if self._calibration_dialog is None:
            self._calibration_dialog = CalibrationDialog(
                start=lambda: self.run_program("calibrate"),
                stop=self._stop_calibration,
                samples=lambda window_ms: self.state.fast.recent(0, window_ms),
                current=lambda: self._base_config.calibration,
                apply=self.apply_calibration,
                parent=self,
            )
        self._calibration_dialog.show()
        self._calibration_dialog.raise_()

    async def _stop_calibration(self) -> None:
        if self._current_mode == "calibrate" and self.conn.program_running:
            await self.stop_program("calibration closed")

    def apply_calibration(self, calibration: SensorCalibration) -> None:
        self._base_config = replace(self._base_config, calibration=calibration)
        self.note(
            f"calibration set: black {calibration.black}, white {calibration.white}, "
            f"edge {calibration.edge}"
        )

    def show_drift_test(self) -> None:
        if self._drift_dialog is None:
            self._drift_dialog = DriftTestDialog(
                run=lambda key: self.run_program("drift_test", drift=key),
                config=self.current_config,
                apply_geometry=self.apply_geometry,
                parent=self,
            )
        self._drift_dialog.show()
        self._drift_dialog.raise_()

    def apply_geometry(self, geometry: RobotGeometry) -> None:
        for key, spin in self.geometry_fields.items():
            spin.setValue(getattr(geometry, key))
        self.note(
            f"geometry set: wheel {geometry.wheel_diameter_mm} mm, axle {geometry.axle_track_mm} mm"
        )

    async def _finish_drift_test(self) -> None:
        # The final T line can still sit in the queue when the running flag
        # drops; let the drain catch up before reading the final pose.
        await asyncio.sleep(DRAIN_GRACE_S)
        while not self.conn.lines.empty():
            await asyncio.sleep(0.01)
        if self._drift_dialog is not None:
            self._drift_dialog.program_finished(self.state.pose)

    def _origin_clicked(self) -> None:
        if self.conn.program_running:
            self._spawn(self.conn.write_line(encode_command("ORG")))
        self.state.reset_origin()
        self.note("origin reset")

    def _follow_changed(self, on: bool) -> None:
        self.follow_button.setChecked(on)

    def note(self, text: str) -> None:
        self.console.append(NOTE_PREFIX + text)

    async def _drain_lines(self) -> None:
        while True:
            line = await self.conn.lines.get()
            self._rx_count += 1
            self.console.append(line)
            self._handle_record(decode_line(line))

    def _handle_record(self, record: object) -> None:
        if isinstance(record, Status | Detail):
            self.state.apply(record)
        elif isinstance(record, Telemetry):
            self.state.apply(record)
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
                self.state.reset()
                self.map.clear()
                self.follow_button.setChecked(True)
                self._start_live_tuning(record)
        elif isinstance(record, Event):
            ack = parse_ack(record.detail) if record.kind == "ACK" else None
            if ack is not None:
                self.tuner.ack(*ack)
            elif record.kind == "WDOG":
                self.note(f"Hub watchdog stopped the robot: no command for {record.detail} ms.")
            elif record.kind == "GIVEUP":
                self.note("Line search failed in both directions. Robot stopped.")
        elif self.scan.apply(record) and self.scan.done:
            self.port_panel.apply_scan(self.scan)
            self._scan_done.set()

    def _tick_ui(self) -> None:
        self._refresh_readouts()
        calibration = self._base_config.calibration
        self.map.sensor_offset_mm = self.geometry_fields["sensor_offset_mm"].value()
        self.map.calibration = calibration
        self.map.refresh(self.state)
        self.plots.calibration = calibration
        self.plots.refresh(self.state)
        if self.state.battery_mv is not None:
            self.battery_label.setText(f"{self.state.battery_mv / 1000:.2f} V")
        self._show_loop_dt()
        if self._tuning_live:
            for key in self.tuning.rows:
                self.tuning.show_ack(
                    key, self.tuner.acked(key), self.tuner.pending(key), self.tuner.stale(key)
                )
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

    def _show_loop_dt(self) -> None:
        detail = self.state.detail
        if detail is None:
            return
        dt = detail.dt_ms
        self.loop_label.setText(f"{dt} ms")
        tone = loop_dt_tone(dt, LOOP_MS)
        if self.loop_label.property("tone") != tone:
            set_prop(self.loop_label, "tone", tone)

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
            if self._current_mode == "drift_test":
                self._spawn(self._finish_drift_test())
            self._current_mode = None
            self._set_tuning_mode("config")
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
        # Ports and geometry are frozen while a program runs; tuning goes live instead.
        for widget in (
            self.port_panel,
            *self.geometry_fields.values(),
        ):
            widget.setEnabled(not running)
