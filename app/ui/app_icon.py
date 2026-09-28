"""The application icon: one SVG, used for the windows and the Windows exe."""

from __future__ import annotations

import struct
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QIcon, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from app.ui.theme import ICON_DIR

APP_ICON_SVG = ICON_DIR / "app.svg"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# Windows groups taskbar buttons by this id. Without one the process is
# python.exe and the taskbar shows Python's icon instead of the window's.
APP_USER_MODEL_ID = "PybricksTracker.App"


def app_icon() -> QIcon:
    return QIcon(str(APP_ICON_SVG))


def render_png(size_px: int, svg: Path = APP_ICON_SVG) -> bytes:
    """The SVG rendered to a square PNG with a transparent background."""
    image = QImage(size_px, size_px, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    QSvgRenderer(str(svg)).render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def write_ico(out: Path, svg: Path = APP_ICON_SVG, sizes: Sequence[int] = ICO_SIZES) -> Path:
    """Write a Windows .ico holding one PNG per size (exe, Explorer, taskbar)."""
    images = [render_png(size, svg) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))  # reserved, type 1 = icon, count
    offset = 6 + 16 * len(images)
    entries = b""
    for size, png in zip(sizes, images, strict=True):
        side = 0 if size >= 256 else size  # 0 means 256 in the directory entry
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(header + entries + b"".join(images))
    return out


def set_windows_app_id(app_id: str = APP_USER_MODEL_ID) -> bool:
    """Give the process its own taskbar identity. Call before the first window."""
    if sys.platform != "win32":
        return False
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):
        return False
    return True
