"""Example-based tests for the suggest command's minimum-saving option."""

import importlib
import sys
from io import BytesIO
from pathlib import Path

import pytest

_SOURCE_DIRECTORY = str(Path(__file__).resolve().parents[1] / "src")
if _SOURCE_DIRECTORY not in sys.path:
    sys.path.insert(0, _SOURCE_DIRECTORY)
run = importlib.import_module("structpad.cli").run

_NET_SOURCE = (
    b"struct Packet {\n"
    b"    u8 tag;\n"
    b"    u32 length;\n"
    b"    u16 flags;\n"
    b"    char name[10];\n"
    b"    ptr next;\n"
    b"}\n"
    b"\n"
    b"packed struct Wire {\n"
    b"    u8 kind;\n"
    b"    u32 value;\n"
    b"}\n"
    b"\n"
    b"struct Frame {\n"
    b"    u8 version;\n"
    b"    struct Packet head;\n"
    b"    struct Wire tail[2];\n"
    b"    bool ok;\n"
    b"}\n"
)
_TWO_SAVINGS = (
    b"struct Small {\n"
    b"    u8 a;\n"
    b"    u16 b;\n"
    b"    u8 c;\n"
    b"    u16 d;\n"
    b"}\n"
    b"\n"
    b"struct Big {\n"
    b"    u8 a;\n"
    b"    u64 b;\n"
    b"    u8 c;\n"
    b"    u64 d;\n"
    b"}\n"
)
_FRAME_BLOCK = (
    b"struct Frame: size 56 -> 48 (saves 8)\n"
    b"  struct Packet head;\n"
    b"  u8 version;\n"
    b"  struct Wire tail[2];\n"
    b"  bool ok;\n"
)


def _run(args: list[str], source: bytes = _NET_SOURCE) -> tuple[int, bytes, bytes]:
    stdout = BytesIO()
    stderr = BytesIO()
    status = run(args, BytesIO(source), stdout, stderr)
    return status, stdout.getvalue(), stderr.getvalue()


def test_default_output_is_unchanged() -> None:
    status, default_out, stderr = _run(["suggest", "-"])
    assert status == 0
    assert stderr == b""
    assert default_out == (
        b"struct Packet: size 32, already compact\n"
        b"\n"
        b"struct Wire: packed, size 5, nothing to reorder\n"
        b"\n" + _FRAME_BLOCK
    )
    assert _run(["suggest", "--min-saving", "0", "-"]) == (0, default_out, b"")
    assert _run(["suggest", "--min-saving=0", "-"]) == (0, default_out, b"")


def test_one_byte_leaves_out_compact_and_packed_structs() -> None:
    assert _run(["suggest", "--min-saving", "1", "-"]) == (0, _FRAME_BLOCK, b"")


def test_the_limit_is_inclusive() -> None:
    assert _run(["suggest", "--min-saving", "8", "-"]) == (0, _FRAME_BLOCK, b"")
    assert _run(["suggest", "--min-saving=9", "-"]) == (0, b"no struct saves at least 9 bytes\n", b"")


def test_one_byte_message_uses_the_singular() -> None:
    source = b"struct Tight {\n    u32 a;\n}\n"
    assert _run(["suggest", "--min-saving", "1", "-"], source) == (
        0,
        b"no struct saves at least 1 byte\n",
        b"",
    )


def test_only_structs_with_a_large_enough_saving_remain() -> None:
    status, small_and_big, _ = _run(["suggest", "--min-saving", "1", "-"], _TWO_SAVINGS)
    assert status == 0
    assert small_and_big.startswith(b"struct Small: size 8 -> 6 (saves 2)\n")
    assert b"struct Big: size 32 -> 24 (saves 8)\n" in small_and_big
    status, only_big, _ = _run(["suggest", "--min-saving", "3", "-"], _TWO_SAVINGS)
    assert status == 0
    assert only_big.startswith(b"struct Big: size 32 -> 24 (saves 8)\n")
    assert b"Small" not in only_big


def test_option_works_with_abi_and_after_the_file() -> None:
    status, out, stderr = _run(["suggest", "-", "--abi=ilp32", "--min-saving=1"])
    assert (status, stderr) == (0, b"")
    assert out == (
        b"struct Frame: size 40 -> 36 (saves 4)\n"
        b"  struct Packet head;\n"
        b"  u8 version;\n"
        b"  struct Wire tail[2];\n"
        b"  bool ok;\n"
    )


def test_the_last_value_wins() -> None:
    assert _run(["suggest", "--min-saving", "9", "--min-saving", "8", "-"]) == (
        0,
        _FRAME_BLOCK,
        b"",
    )


@pytest.mark.parametrize("value", ["1", "999999", "000001", "007"])
def test_accepts_one_to_six_digits(value: str) -> None:
    status, _out, stderr = _run(["suggest", f"--min-saving={value}", "-"])
    assert (status, stderr) == (0, b"")


@pytest.mark.parametrize("value", ["", "-1", "+1", "1.0", "x", "1000000", " 1", "1 "])
def test_rejects_other_values(value: str) -> None:
    assert _run(["suggest", f"--min-saving={value}", "-"]) == (
        2,
        b"",
        f'structpad: invalid --min-saving "{value}"\n'.encode(),
    )


def test_needs_a_value() -> None:
    assert _run(["suggest", "--min-saving"]) == (2, b"", b"structpad: --min-saving needs a value\n")


@pytest.mark.parametrize("command", ["layout", "check"])
def test_other_commands_do_not_take_it(command: str) -> None:
    for args in ([command, "--min-saving", "1", "-"], [command, "--min-saving=1", "-"]):
        assert _run(args) == (2, b"", f"structpad: {command} does not take --min-saving\n".encode())


def test_value_is_escaped_in_the_error() -> None:
    assert _run(["suggest", "--min-saving=a\nb", "-"]) == (
        2,
        b"",
        b'structpad: invalid --min-saving "a\\nb"\n',
    )
