"""scan_ports.py is MicroPython. It is compiled with mpy-cross, never imported."""

from __future__ import annotations

import ast
import re

from pybricksdev.compile import compile_file

from app.codegen.generator import SCAN_PORTS_PROGRAM
from app.core.protocol import PORT_LETTERS, PROTO_VERSION


async def test_compiles_with_mpy_cross() -> None:
    mpy = await compile_file(str(SCAN_PORTS_PROGRAM.parent), SCAN_PORTS_PROGRAM.name, 6)
    assert len(mpy) > 0


def test_proto_version_matches_app() -> None:
    source = SCAN_PORTS_PROGRAM.read_text(encoding="utf-8")
    match = re.search(r"^PROTO_VERSION = (\d+)$", source, re.MULTILINE)
    assert match is not None
    assert int(match.group(1)) == PROTO_VERSION


def test_probes_every_port_and_uses_no_fstrings() -> None:
    source = SCAN_PORTS_PROGRAM.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not any(isinstance(node, ast.JoinedStr) for node in ast.walk(tree))
    for letter in PORT_LETTERS:
        assert f"Port.{letter}" in source
    assert 'print("P,DONE,0")' in source
