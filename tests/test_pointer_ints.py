"""Tests for pointer-width integer primitives."""

import importlib
import json
import sys
from io import BytesIO
from pathlib import Path

_SOURCE_DIRECTORY = str(Path(__file__).resolve().parents[1] / "src")
if _SOURCE_DIRECTORY not in sys.path:
    sys.path.insert(0, _SOURCE_DIRECTORY)

from structpad.types import get_primitive

run = importlib.import_module("structpad.cli").run

_BUF = b"struct Buf {\n    u8 tag;\n    usize len;\n    isize off;\n    u16 flags;\n}\n"


def _run(args: list[str], source: bytes = _BUF) -> tuple[int, bytes, bytes]:
    stdin = BytesIO(source)
    stdout = BytesIO()
    stderr = BytesIO()
    status = run(args, stdin, stdout, stderr)
    return status, stdout.getvalue(), stderr.getvalue()


def test_usize_and_isize_have_the_size_and_alignment_of_ptr() -> None:
    pointer = get_primitive("ptr")
    assert pointer is not None

    for name in ("usize", "isize"):
        primitive = get_primitive(name)
        assert primitive is not None
        for abi, expected in (("lp64", (8, 8)), ("ilp32", (4, 4))):
            expected_size, expected_alignment = expected
            assert primitive.size(abi) == expected_size
            assert primitive.alignment(abi) == expected_alignment
            assert primitive.size(abi) == pointer.size(abi)
            assert primitive.alignment(abi) == pointer.alignment(abi)


def test_layout_under_lp64() -> None:
    status, stdout, stderr = _run(["layout", "-"])

    assert status == 0
    assert stdout == (
        b"struct Buf: size 32, align 8, padding 13\n"
        b"offset   size  field\n"
        b"     0      1  tag: u8\n"
        b"     1      7  (padding)\n"
        b"     8      8  len: usize\n"
        b"    16      8  off: isize\n"
        b"    24      2  flags: u16\n"
        b"    26      6  (padding)\n"
    )
    assert stderr == b""


def test_layout_under_ilp32() -> None:
    status, stdout, stderr = _run(["layout", "--abi", "ilp32", "-"])

    assert status == 0
    assert stdout == (
        b"struct Buf: size 16, align 4, padding 5\n"
        b"offset   size  field\n"
        b"     0      1  tag: u8\n"
        b"     1      3  (padding)\n"
        b"     4      4  len: usize\n"
        b"     8      4  off: isize\n"
        b"    12      2  flags: u16\n"
        b"    14      2  (padding)\n"
    )
    assert stderr == b""


def test_suggest_and_check_use_the_pointer_width() -> None:
    status, stdout, stderr = _run(["suggest", "-"])

    assert status == 0
    assert stdout == (
        b"struct Buf: size 32 -> 24 (saves 8)\n"
        b"  usize len;\n"
        b"  isize off;\n"
        b"  u16 flags;\n"
        b"  u8 tag;\n"
    )
    assert stderr == b""

    status, stdout, stderr = _run(["check", "--max-padding", "8", "-"])

    assert status == 1
    assert stdout == (
        b"Buf: 13 bytes of padding (limit 8)\n1 of 1 structs over the padding limit\n"
    )
    assert stderr == b""


def test_json_layout_names_the_type_and_other_names_stay_unknown() -> None:
    status, stdout, stderr = _run(["layout", "--format", "json", "-"])

    assert status == 0
    layout = json.loads(stdout)
    len_field = next(field for field in layout[0]["fields"] if field["name"] == "len")
    assert len_field["type"] == "usize"
    assert len_field["offset"] == 8
    assert len_field["size"] == 8
    assert stderr == b""

    invalid_source = b"struct Buf {\n    size_t n;\n}\n"
    status, stdout, stderr = _run(["layout", "-"], invalid_source)

    assert status == 2
    assert stdout == b""
    assert stderr == b'structpad: <stdin>:2: unknown type "size_t"\n'
