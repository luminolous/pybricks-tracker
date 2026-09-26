"""Dark instrument theme. Tokens and rules come from docs/design/README.md."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QWidget

WINDOW = "#0C1015"
SURFACE = "#0F141A"
SUNKEN = "#090D11"
FIELD = "#141A21"
LINE = "#1C242D"
LINE_STRONG = "#2A343F"
TEXT = "#E4EAF0"
MUTED = "#8994A0"
DIM = "#5A6571"
ACCENT = "#3FD0E6"
ACCENT_DIM = "rgba(63, 208, 230, 36)"
ON_ACCENT = "#062026"
TRAIL = "#F4EFE4"
OVERLAY = "#A48CFF"
WARN = "#F2B344"
DANGER = "#FF4D57"
OK = "#5FD39A"

FONT_DIR = Path(__file__).parent / "fonts"
ICON_DIR = Path(__file__).parent / "icons"
UI_FONT_PREFS = ("IBM Plex Sans", "Segoe UI")
MONO_FONT_PREFS = ("IBM Plex Mono", "Cascadia Mono", "Consolas")


@dataclass(frozen=True)
class Fonts:
    ui: str
    mono: str


@functools.cache
def load_fonts() -> Fonts:
    """Register bundled fonts from app/ui/fonts once, then pick the best available family."""
    if FONT_DIR.is_dir():
        for path in sorted(FONT_DIR.glob("*.[ot]tf")):
            QFontDatabase.addApplicationFont(str(path))
    families = set(QFontDatabase.families())

    def pick(prefs: tuple[str, ...]) -> str:
        return next((f for f in prefs if f in families), prefs[-1])

    return Fonts(ui=pick(UI_FONT_PREFS), mono=pick(MONO_FONT_PREFS))


def stylesheet(fonts: Fonts) -> str:
    return f"""
* {{ font-family: "{fonts.ui}"; font-size: 12px; color: {TEXT}; }}
QMainWindow, QWidget#central, QDialog {{ background: {WINDOW}; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {LINE_STRONG}; padding: 4px; }}

QLabel {{ background: transparent; }}
QLabel[tone="muted"] {{ color: {MUTED}; }}
QLabel[tone="dim"] {{ color: {DIM}; }}
QLabel[tone="accent"] {{ color: {ACCENT}; }}
QLabel[tone="ok"] {{ color: {OK}; }}
QLabel[tone="warn"] {{ color: {WARN}; }}
QLabel[tone="danger"] {{ color: {DANGER}; }}
QLabel:disabled {{ color: {DIM}; }}
QLabel[mono="true"], QPlainTextEdit, QListWidget#hubList {{ font-family: "{fonts.mono}"; }}
QLabel[cap="true"] {{ color: {MUTED}; font-size: 10px; font-weight: 600; }}
QLabel[big="true"] {{ font-family: "{fonts.mono}"; font-size: 20px; }}

QFrame#header {{ background: {SURFACE}; border-bottom: 1px solid {LINE_STRONG}; }}
QFrame#headerSeg {{ border-right: 1px solid {LINE}; }}
QFrame#leftCol {{ background: {SURFACE}; border-right: 1px solid {LINE}; }}
QFrame#rightCol {{ background: {SURFACE}; border-left: 1px solid {LINE}; }}
QFrame#section {{ border-bottom: 1px solid {LINE}; }}
QFrame#tape, QFrame#readout {{ background: {SURFACE}; }}
QFrame#tape {{ border-bottom: 1px solid {LINE}; }}
QFrame#readout {{ border-top: 1px solid {LINE_STRONG}; }}
QFrame#readoutCell {{ border-right: 1px solid {LINE}; }}
QFrame#mapCanvas, QFrame#plotArea {{ background: {SUNKEN}; }}
QFrame#plotArea {{ border: 1px solid {LINE}; }}
QFrame#console {{ background: {SUNKEN}; border-top: 1px solid {LINE_STRONG}; }}
QFrame#consoleSide {{ border-left: 1px solid {LINE}; }}
QFrame#portRow {{ border-top: 1px solid {LINE}; }}
QFrame#dot {{ border-radius: 3px; background: {DIM}; }}
QFrame#dot[tone="ok"] {{ background: {OK}; }}
QFrame#dot[tone="warn"] {{ background: {WARN}; }}
QFrame#dot[tone="danger"] {{ background: {DANGER}; }}

QPushButton {{
    background: transparent; border: 1px solid {LINE}; border-radius: 2px;
    padding: 6px 10px; text-align: left;
}}
QPushButton:hover {{ background: {FIELD}; border-color: {LINE_STRONG}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {DIM}; border-color: {LINE}; background: transparent; }}
QPushButton[role="run"] {{
    background: {ACCENT}; border-color: {ACCENT}; color: {ON_ACCENT}; font-weight: 600;
}}
QPushButton[role="run"]:disabled {{ background: transparent; border-color: {LINE}; color: {DIM}; }}
QPushButton[role="small"] {{
    padding: 3px 8px; color: {MUTED}; border-color: {LINE_STRONG}; text-align: center;
}}
QPushButton[role="small"]:checked {{
    color: {ACCENT}; border-color: rgba(63, 208, 230, 110); background: {ACCENT_DIM};
}}
QPushButton[role="small"]:checked:disabled {{
    color: {MUTED}; border-color: {LINE_STRONG}; background: {FIELD};
}}
QPushButton[role="section"] {{
    border: 0; background: transparent; color: {MUTED}; padding: 6px 0 2px 0;
    text-align: left; font-family: "{fonts.mono}"; font-size: 11px;
}}
QPushButton[role="section"]:hover {{ color: {TEXT}; }}
QPushButton[role="section"]:checked {{ color: {TEXT}; }}
QPushButton[role="chip"] {{
    padding: 2px 0; min-width: 22px; max-width: 26px; text-align: center;
    font-family: "{fonts.mono}"; border-color: {LINE_STRONG};
}}
QPushButton[role="chip"][step="done"] {{
    color: {ACCENT}; border-color: rgba(63, 208, 230, 110); background: {ACCENT_DIM};
}}
QPushButton[role="chip"][step="next"] {{ color: {TEXT}; border-color: {ACCENT}; }}
QPushButton[role="tool"] {{
    border: 1px solid transparent; color: {MUTED}; padding: 8px 0; text-align: center;
    font-size: 11px;
}}
QPushButton[role="tool"]:checked {{
    color: {ACCENT}; border-color: rgba(63, 208, 230, 110); background: {ACCENT_DIM};
}}
QPushButton[role="estop"] {{
    background: {DANGER}; border: 0; color: #FFFFFF; font-weight: 600; font-size: 13px;
    padding: 0 18px; text-align: center;
}}
QPushButton[role="estop"]:hover {{ background: #FF6770; }}
QPushButton[role="estop"]:disabled {{ background: {FIELD}; color: {DIM}; }}

QComboBox, QLineEdit, QDoubleSpinBox {{
    background: {FIELD}; border: 1px solid {LINE_STRONG}; border-radius: 2px;
    padding: 2px 6px; selection-background-color: {ACCENT}; selection-color: {ON_ACCENT};
}}
QComboBox:disabled, QLineEdit:disabled, QDoubleSpinBox:disabled {{
    color: {DIM}; background: transparent;
}}
QComboBox:focus, QLineEdit:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox {{ padding-right: 14px; }}
QComboBox::drop-down {{ border: 0; width: 14px; }}
QComboBox::down-arrow {{
    image: url("{ICON_DIR.as_posix()}/chevron-down.svg"); width: 8px; height: 8px;
}}
QComboBox::down-arrow:disabled {{ image: none; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {LINE_STRONG}; outline: 0;
    selection-background-color: {ACCENT_DIM}; selection-color: {TEXT};
}}
QDoubleSpinBox {{ font-family: "{fonts.mono}"; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: 0; }}

QSlider::groove:horizontal {{ height: 2px; background: {LINE_STRONG}; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; }}
QSlider::sub-page:horizontal:disabled {{ background: {LINE_STRONG}; }}
QSlider::handle:horizontal {{ width: 4px; height: 12px; margin: -5px 0; background: {TEXT}; }}
QSlider::handle:horizontal:disabled {{ background: {DIM}; }}

QCheckBox {{ color: {MUTED}; spacing: 6px; }}
QCheckBox::indicator {{ width: 10px; height: 10px; border: 1px solid {MUTED}; border-radius: 1px; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QPlainTextEdit {{
    background: {SUNKEN}; border: 0; color: {MUTED}; font-size: 11px; padding: 6px 10px;
}}

QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {MUTED}; padding: 11px 8px 9px 8px;
    border: 0; border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

QMenu {{ background: {SURFACE}; border: 1px solid {LINE_STRONG}; padding: 4px 0; }}
QMenu::item {{ padding: 5px 18px 5px 22px; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QMenu::item:disabled {{ color: {DIM}; }}
QMenu::indicator {{ width: 8px; height: 8px; left: 8px; }}
QMenu::indicator:checked {{ background: {ACCENT}; }}

QListWidget {{ background: {SUNKEN}; border: 1px solid {LINE}; outline: 0; }}
QListWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {LINE}; }}
QListWidget::item:selected {{ background: {ACCENT_DIM}; color: {TEXT}; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {LINE_STRONG}; min-height: 20px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; }}
QScrollBar::handle:horizontal {{ background: {LINE_STRONG}; min-width: 20px; }}
"""


def apply_theme(app: QApplication) -> Fonts:
    """Fusion style plus a dark palette so native bits (combo arrows) follow the theme."""
    fonts = load_fonts()
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, WINDOW),
        (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Base, FIELD),
        (QPalette.ColorRole.AlternateBase, SURFACE),
        (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.Button, FIELD),
        (QPalette.ColorRole.ButtonText, TEXT),
        (QPalette.ColorRole.Highlight, ACCENT),
        (QPalette.ColorRole.HighlightedText, ON_ACCENT),
        (QPalette.ColorRole.PlaceholderText, DIM),
        (QPalette.ColorRole.ToolTipBase, SURFACE),
        (QPalette.ColorRole.ToolTipText, TEXT),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setFont(QFont(fonts.ui, 9))
    app.setStyleSheet(stylesheet(fonts))
    return fonts


# -- small widget helpers ---------------------------------------------------


def set_prop(widget: QWidget, name: str, value: object) -> None:
    """Set a dynamic property and re-apply the stylesheet rules that match it."""
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def label(text: str = "", *, tone: str | None = None, mono: bool = False) -> QLabel:
    w = QLabel(text)
    if tone:
        w.setProperty("tone", tone)
    if mono:
        w.setProperty("mono", True)
    return w


def caption(text: str) -> QLabel:
    """Uppercase section title with letter spacing. The only uppercase text allowed."""
    w = QLabel(text.upper())
    w.setProperty("cap", True)
    font = w.font()
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
    w.setFont(font)
    return w
