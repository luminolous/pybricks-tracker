# PyInstaller spec. Build with:  pyinstaller PybricksTracker.spec
# Output: dist/PybricksTracker.exe (one file, runs without a Python install).
# Check a build with:  dist\PybricksTracker.exe --selftest
# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

sys.path.insert(0, SPECPATH)
from app.ui.app_icon import write_ico  # noqa: E402

# The exe icon, rendered from app/ui/icons/app.svg on every build.
exe_icon = write_ico(Path(SPECPATH) / "build" / "app.ico")

datas = [
    # Loaded by path at runtime (Path(__file__).parent / ...), so they keep
    # their package-relative location inside the bundle.
    ("app/ui/fonts", "app/ui/fonts"),
    ("app/ui/icons", "app/ui/icons"),
    ("app/codegen/templates", "app/codegen/templates"),
]
binaries = []
hiddenimports = collect_submodules("bleak") + collect_submodules("qasync")

# mpy_cross_v6 ships mpy-cross.exe as package data; pybricksdev has resources;
# winrt backs bleak on Windows and is imported dynamically.
for package in ("mpy_cross_v6", "pybricksdev", "winrt"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    ["app/__main__.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "ruff"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PybricksTracker",
    icon=str(exe_icon),
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # roadmap M9: keep the console until the build is proven stable; it also
    # gives pybricksdev's upload progress bar a stderr to write to.
    console=True,
)
