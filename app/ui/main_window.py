"""Main application window, laid out after docs/design/main-window-mockup.html.

M1 wires connect, port scan, console and E-STOP. Map, plots, tuning and
events are placeholders filled by later milestones.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QEvent, QLocale, QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
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

from app.codegen.generator import SCAN_PORTS_PROGRAM
from app.core.connection import HubConnection, HubConnectionError, LinkState
from app.core.protocol import Ready, decode_line
from app.core.state import PortScan
from app.ui.console_pane import ConsolePane
from app.ui.dialogs.connect import ConnectDialog
from app.ui.port_panel import PortPanel
from app.ui.theme import caption, label, set_prop

logger = logging.getLogger(__name__)

APP_NAME = "Pybricks Tracker"
MIN_WIDTH_PX = 1280
MIN_HEIGHT_PX = 800
LEFT_COL_PX = 276  # mockup had 252; port rows need the extra room at real font metrics
RIGHT_COL_PX = 340
SCAN_TIMEOUT_S = 10.0
NOTE_PREFIX = "» "  # app messages in the console; never a protocol prefix

ConnectionFactory = Callable[..., HubConnection]


def _frame(name: str) -> QFrame:
    f = QFrame()
    f.setObjectName(name)
    return f


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
    def __init__(self, connection_factory: ConnectionFactory = HubConnection) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(MIN_WIDTH_PX, MIN_HEIGHT_PX)
        self.conn = connection_factory(
            on_link_state=self._on_link_state, on_program_running=self._on_program_running
        )
        self.scan = PortScan()
        self._scan_done = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._drain_task: asyncio.Task | None = None
        self._rx_count = 0
        self._dialog: ConnectDialog | None = None

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

        QShortcut(QKeySequence("Ctrl+P"), self, activated=self._scan_clicked)
        QShortcut(QKeySequence("Esc"), self, activated=self._stop_clicked)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._on_link_state(LinkState.DISCONNECTED)
        self._on_program_running(False)

    # -- layout -------------------------------------------------------------

    def _build_header(self) -> QFrame:
        header = _frame("header")
        header.setFixedHeight(44)
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
        for i, (key, text, value) in enumerate(
            (
                ("wheel_diameter", "Wheel diameter", 56.0),
                ("axle_track", "Axle track", 112.0),
                ("sensor_offset", "Sensor offset", 40.0),
            ),
            start=1,
        ):
            spin = QDoubleSpinBox()
            spin.setLocale(QLocale.c())  # decimal point, not the OS comma
            spin.setRange(0, 1000)
            spin.setDecimals(1)
            spin.setSuffix(" mm")
            spin.setValue(value)
            spin.setAlignment(Qt.AlignmentFlag.AlignRight)
            spin.setFixedWidth(96)
            self.geometry_fields[key] = spin
            grid.addWidget(label(text, tone="muted"), i, 0)
            grid.addWidget(spin, i, 1)
        layout.addWidget(geometry)

        actions = QWidget()
        box = QVBoxLayout(actions)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(6)
        run_row = QHBoxLayout()
        run_row.setSpacing(6)
        self.run_button = _action_button("Run", "F5", role="run")
        self.run_button.setToolTip("Line follower program arrives in M2")
        self.stop_button = _action_button("Stop", "Esc")
        self.stop_button.clicked.connect(self._stop_clicked)
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.stop_button)
        box.addLayout(run_row)
        self.scan_button = _action_button("Scan ports", "Ctrl+P")
        self.scan_button.clicked.connect(self._scan_clicked)
        box.addWidget(self.scan_button)
        for text, key, milestone in (
            ("Calibrate sensor", "Ctrl+K", "M6"),
            ("Drift test", "Ctrl+D", "M4"),
            ("Export run", "Ctrl+E", "M8"),
            ("Hub program", "Ctrl+U", "M2"),
        ):
            button = _action_button(text, key)
            button.setEnabled(False)
            button.setToolTip(f"Arrives in {milestone}")
            box.addWidget(button)
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
        t_layout.addWidget(label("enabled after the hub handshake", tone="dim"), 0, 2)
        for i, name in enumerate(("KP", "KD", "SPD"), start=1):
            t_layout.addWidget(label(name, tone="muted", mono=True), i, 0)
            spin = QDoubleSpinBox()
            spin.setLocale(QLocale.c())
            spin.setEnabled(False)
            spin.setSpecialValueText("—")
            t_layout.addWidget(spin, i, 2)
        t_layout.setColumnStretch(1, 1)
        layout.addWidget(tuning)

        events = _frame("section")
        e_layout = QVBoxLayout(events)
        e_layout.setContentsMargins(16, 14, 16, 14)
        e_layout.addWidget(caption("Events"))
        e_layout.addWidget(label("No events yet.", tone="dim"))
        e_layout.addStretch()
        layout.addWidget(events, 1)
        return col

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        """Start background tasks. Call once the qasync loop is running."""
        self._drain_task = asyncio.ensure_future(self._drain_lines())

    async def shutdown(self) -> None:
        """Stop the hub program if one runs, then disconnect. Never raises."""
        if self._drain_task:
            self._drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._drain_task
        for task in list(self._tasks):
            task.cancel()
        if self.conn.connected:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.emergency_stop(), timeout=2)
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

    async def emergency_stop(self) -> None:
        """Tell the program to stop, then stop it. Both are tried even if one fails."""
        self.note("E-STOP")
        if not self.conn.connected:
            return
        with contextlib.suppress(HubConnectionError):
            await self.conn.write_line("MODE,STOP")
        try:
            await self.conn.stop()
        except HubConnectionError as exc:
            self.note(str(exc))

    def note(self, text: str) -> None:
        self.console.append(NOTE_PREFIX + text)

    async def _drain_lines(self) -> None:
        while True:
            line = await self.conn.lines.get()
            self._rx_count += 1
            self.console.append(line)
            record = decode_line(line)
            if isinstance(record, Ready) and not record.compatible:
                self.note(
                    f"Hub program speaks protocol {record.proto_version}, app expects a "
                    "different version. Stop it and run again."
                )
            if self.scan.apply(record) and self.scan.done:
                self.port_panel.apply_scan(self.scan)
                self._scan_done.set()

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

    def _stop_clicked(self) -> None:
        if self.conn.program_running:
            self._spawn(self.conn.stop())

    def _estop_clicked(self) -> None:
        self._spawn(self.emergency_stop())

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
        self._update_actions()

    def _on_program_running(self, running: bool) -> None:
        self.run_state.setText("RUNNING" if running else "IDLE")
        set_prop(self.run_state, "tone", "ok" if running else "muted")
        self.mode_label.setText("")
        self._update_actions()

    def _update_actions(self) -> None:
        connected = self.conn.connected
        running = self.conn.program_running
        self.scan_button.setEnabled(connected and not running)
        self.stop_button.setEnabled(running)
        self.estop_button.setEnabled(connected)
        # Run needs a valid config and the M2 program; until then it stays off.
        self.run_button.setEnabled(False)
