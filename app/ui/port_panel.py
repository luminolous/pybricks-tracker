"""Port rows A-F: detected device, role and motor direction, with validation."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from app.core.config import (
    DEFAULT_ASSIGNMENTS,
    MOTOR_ROLES,
    ROLE_LABELS,
    Direction,
    PortAssignment,
    Role,
    validate_ports,
)
from app.core.protocol import PORT_LETTERS, DeviceKind
from app.core.state import PortScan
from app.ui.theme import caption, label, set_prop

# Short names fit the 276 px column; the full name goes in the tooltip.
SHORT_DEVICE_NAMES = {
    DeviceKind.MOTOR: "Motor",
    DeviceKind.COLOR_SENSOR: "Color sensor",
    DeviceKind.ULTRASONIC_SENSOR: "Ultrasonic",
    DeviceKind.FORCE_SENSOR: "Force sensor",
    DeviceKind.UNKNOWN: "Unknown",
}


class PortRow:
    def __init__(self, port: str, grid: QGridLayout, row: int) -> None:
        self.port = port
        self.letter = label(port, tone="muted", mono=True)
        self.letter.setFixedWidth(12)
        self.device = label("not scanned", tone="dim")
        self.role = QComboBox()
        for role in Role:
            self.role.addItem(ROLE_LABELS[role], role)
        self.role.setFixedWidth(96)
        self.direction = QComboBox()
        for direction in Direction:
            self.direction.addItem(direction.value, direction)
        self.direction.setFixedWidth(62)
        grid.addWidget(self.letter, row, 0)
        grid.addWidget(self.device, row, 1)
        grid.addWidget(self.role, row, 2)
        grid.addWidget(self.direction, row, 3)

    def assignment(self) -> PortAssignment:
        return PortAssignment(self.role.currentData(), self.direction.currentData())

    def set_assignment(self, assignment: PortAssignment) -> None:
        self.role.setCurrentIndex(self.role.findData(assignment.role))
        self.direction.setCurrentIndex(self.direction.findData(assignment.direction))
        self.refresh()

    def set_device(self, name: str | None, kind: DeviceKind | None) -> None:
        self.device.setToolTip(name or "")
        if kind is None:
            self.device.setText("not scanned")
            set_prop(self.device, "tone", "dim")
        elif kind is DeviceKind.EMPTY:
            self.device.setText("empty")
            set_prop(self.device, "tone", "dim")
        else:
            self.device.setText(SHORT_DEVICE_NAMES[kind])
            set_prop(self.device, "tone", "warn" if kind is DeviceKind.UNKNOWN else "text")
        self.refresh()

    def refresh(self) -> None:
        role = self.role.currentData()
        self.direction.setVisible(role in MOTOR_ROLES)
        set_prop(self.letter, "tone", "muted" if role is Role.UNUSED else "accent")


class PortPanel(QFrame):
    """Emits `changed` whenever a role, direction or scan result changes."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("section")
        self._kinds: dict[str, DeviceKind | None] = dict.fromkeys(PORT_LETTERS)

        self.scan_age = label("", tone="dim")
        head = QHBoxLayout()
        head.addWidget(caption("Ports"))
        head.addStretch()
        head.addWidget(self.scan_age)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        self.rows = {port: PortRow(port, grid, i) for i, port in enumerate(PORT_LETTERS)}

        self.validation = QLabel()
        self.validation.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addLayout(head)
        layout.addLayout(grid)
        layout.addWidget(self.validation)

        for port, row in self.rows.items():
            row.set_assignment(DEFAULT_ASSIGNMENTS[port])
            row.role.currentIndexChanged.connect(lambda _=0, r=row: self._on_edit(r))
            row.direction.currentIndexChanged.connect(lambda _=0: self._emit())
        self._emit()

    def apply_scan(self, scan: PortScan) -> None:
        for port, row in self.rows.items():
            device = scan.device(port)
            self._kinds[port] = device.kind if device else None
            row.set_device(device.name if device else None, self._kinds[port])
        self.scan_age.setText("scan complete" if scan.done else "scanning…")
        self._emit()

    def set_scanning(self) -> None:
        self.scan_age.setText("scanning…")

    def assignments(self) -> dict[str, PortAssignment]:
        return {port: row.assignment() for port, row in self.rows.items()}

    def validation_error(self) -> str | None:
        return validate_ports(self.assignments(), self._kinds)

    def _on_edit(self, row: PortRow) -> None:
        row.refresh()
        self._emit()

    def _emit(self) -> None:
        error = self.validation_error()
        self.validation.setText(error or "Config valid. Ready to run.")
        set_prop(self.validation, "tone", "warn" if error else "ok")
        self.changed.emit()
