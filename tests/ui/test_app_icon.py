"""App icon: the SVG loads, the .ico holds every size, the taskbar id is set."""

from __future__ import annotations

import struct
import sys

from app.ui.app_icon import APP_ICON_SVG, ICO_SIZES, app_icon, set_windows_app_id, write_ico

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def test_icon_svg_loads(qapp) -> None:
    assert APP_ICON_SVG.is_file()
    icon = app_icon()
    assert not icon.isNull()
    assert not icon.pixmap(32, 32).isNull()


def test_ico_holds_one_png_per_size(qapp, tmp_path) -> None:
    data = write_ico(tmp_path / "app.ico").read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind, count) == (0, 1, len(ICO_SIZES))
    for i, size in enumerate(ICO_SIZES):
        width, height, _, _, planes, bpp, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * i
        )
        side = 0 if size >= 256 else size
        assert (width, height, planes, bpp) == (side, side, 1, 32)
        assert data[offset : offset + 8] == PNG_SIGNATURE
        assert offset + length <= len(data)


def test_taskbar_id_only_on_windows() -> None:
    assert set_windows_app_id() is (sys.platform == "win32")
