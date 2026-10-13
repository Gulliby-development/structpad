"""Example-based tests for the check command's ignore option."""

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
    b"// wire structs\n"
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


def _run(
    args: list[str], source: bytes = _NET_SOURCE
) -> tuple[int, bytes, bytes]:
    stdin = BytesIO(source)
    stdout = BytesIO()
    stderr = BytesIO()
    status = run(args, stdin, stdout, stderr)
    return status, stdout.getvalue(), stderr.getvalue()


def _assert_error(
    args: list[str], message: str, source: bytes = _NET_SOURCE
) -> None:
    status, stdout, stderr = _run(args, source)
    assert status == 2
    assert stdout == b""
    assert stderr == f"structpad: {message}\n".encode()
    assert stderr.count(b"\n") == 1
    assert b"\r" not in stderr


@pytest.mark.parametrize(
    ("args", "expected_status", "expected_stdout"),
    [
        (
            ["check", "--ignore", "Packet", "-"],
            1,
            (
                b"Frame: 12 bytes of padding (limit 0)\n"
                b"1 of 3 structs over the padding limit (1 ignored)\n"
            ),
        ),
        (
            ["check", "--ignore", "Packet", "--ignore=Frame", "-"],
            0,
            b"ok, 3 structs (2 ignored)\n",
        ),
        (
            ["check", "--ignore", "Frame", "--ignore", "Frame", "--max-padding", "8", "-"],
            0,
            b"ok, 3 structs (1 ignored)\n",
        ),
        (
            ["check", "--ignore", "Wire", "--max-padding=8", "-"],
            1,
            (
                b"Frame: 12 bytes of padding (limit 8)\n"
                b"1 of 3 structs over the padding limit (1 ignored)\n"
            ),
        ),
        (
            ["check", "--max-padding=8", "-"],
            1,
            (
                b"Frame: 12 bytes of padding (limit 8)\n"
                b"1 of 3 structs over the padding limit\n"
            ),
        ),
    ],
)
def test_ignore_matches_worked_examples_and_preserves_no_ignore_output(
    args: list[str], expected_status: int, expected_stdout: bytes
) -> None:
    status, stdout, stderr = _run(args)
    assert (status, stdout, stderr) == (expected_status, expected_stdout, b"")


def test_ignore_spellings_work_before_between_and_after_file() -> None:
    expected_packet_ignored = (
        b"Frame: 12 bytes of padding (limit 0)\n"
        b"1 of 3 structs over the padding limit (1 ignored)\n"
    )
    for args in (
        ["check", "--ignore=Packet", "-"],
        ["check", "-", "--ignore", "Packet"],
    ):
        status, stdout, stderr = _run(args)
        assert (status, stdout, stderr) == (
            1,
            expected_packet_ignored,
            b"",
        )

    expected_wire_ignored = (
        b"Frame: 12 bytes of padding (limit 8)\n"
        b"1 of 3 structs over the padding limit (1 ignored)\n"
    )
    for args in (
        ["check", "--max-padding", "8", "--ignore", "Wire", "-"],
        ["check", "--max-padding=8", "-", "--ignore=Wire"],
    ):
        status, stdout, stderr = _run(args)
        assert (status, stdout, stderr) == (1, expected_wire_ignored, b"")


def test_duplicate_ignore_names_only_count_once() -> None:
    status, stdout, stderr = _run(
        ["check", "--ignore=Packet", "--ignore", "Packet", "--ignore", "Wire", "-"]
    )
    assert status == 1
    assert stdout == (
        b"Frame: 12 bytes of padding (limit 0)\n"
        b"1 of 3 structs over the padding limit (2 ignored)\n"
    )
    assert stderr == b""


def test_all_structs_can_be_ignored() -> None:
    status, stdout, stderr = _run(
        [
            "check",
            "--ignore",
            "Packet",
            "--ignore=Wire",
            "--ignore",
            "Frame",
            "-",
        ]
    )
    assert status == 0
    assert stdout == b"ok, 3 structs (3 ignored)\n"
    assert stderr == b""


def test_ignore_uses_ascii_name_grammar_at_both_length_boundaries() -> None:
    longest_name = "A" + "x" * 62 + "9"
    source = (
        b"struct _ {\nu8 value;\n}\n"
        + f"struct {longest_name} {{\nu8 value;\n}}\n".encode()
    )
    status, stdout, stderr = _run(
        ["check", "--ignore", "_", "--ignore=" + longest_name, "-"], source
    )
    assert status == 0
    assert stdout == b"ok, 2 structs (2 ignored)\n"
    assert stderr == b""


@pytest.mark.parametrize("value", ("", "1x", "A" + "x" * 64, "é", "A-B", "A\r\nB"))
def test_invalid_ignore_names_are_escaped(value: str) -> None:
    escaped = value.replace("\r", r"\r").replace("\n", r"\n")
    _assert_error(
        ["check", "--ignore=" + value, "-"],
        f'invalid --ignore "{escaped}"',
    )


def test_ignore_option_errors_are_exact_and_ordered() -> None:
    _assert_error(["check", "--ignore"], "--ignore needs a value")
    _assert_error(
        ["check", "--ignore", "--unknown", "-"],
        'invalid --ignore "--unknown"',
    )
    _assert_error(
        ["check", "--ignore", "1x", "--unknown", "-"],
        'invalid --ignore "1x"',
    )
    _assert_error(
        ["check", "--ignore", "Nope", "--unknown", "-"],
        'unknown option "--unknown"',
    )
    _assert_error(["check", "--ignore", "Frame"], "missing FILE")

    for command, value in (("layout", "Packet"), ("suggest", "Packet")):
        _assert_error(
            [command, "--ignore", value, "-"],
            f"{command} does not take --ignore",
        )
        _assert_error(
            [command, "--ignore=" + value, "-"],
            f"{command} does not take --ignore",
        )


def test_unknown_names_are_case_sensitive_and_checked_in_argument_order() -> None:
    _assert_error(
        ["check", "--ignore", "Nope", "--ignore=frame", "-"],
        'unknown struct "Nope" in --ignore',
    )
    _assert_error(
        ["check", "--ignore=frame", "-"],
        'unknown struct "frame" in --ignore',
    )


def test_parse_errors_precede_unknown_ignore_names() -> None:
    _assert_error(
        ["check", "--ignore", "Nope", "-"],
        "<stdin>: no structs found",
        b"// empty\n",
    )


def test_ignore_works_with_ilp32_abi_spelling() -> None:
    status, stdout, stderr = _run(
        ["check", "--abi=ilp32", "--ignore", "Frame", "-"]
    )
    assert status == 1
    assert stdout == (
        b"Packet: 3 bytes of padding (limit 0)\n"
        b"1 of 3 structs over the padding limit (1 ignored)\n"
    )
    assert stderr == b""
