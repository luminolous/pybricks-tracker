"""Render config plus mode into a hub program on disk.

M1 only exposes static programs. Jinja rendering arrives with M2.
"""

from __future__ import annotations

from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"
SCAN_PORTS_PROGRAM = TEMPLATES_DIR / "scan_ports.py"
