"""Command-line integration tests for structpad."""

import importlib
import os
import random
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pytest

_SOURCE_DIRECTORY = str(Path(__file__).resolve().parents[1] / "src")
if _SOURCE_DIRECTORY not in sys.path:
    sys.path.insert(0, _SOURCE_DIRECTORY)
run = importlib.import_module("structpad.cli").run

_USAGE = (
    b"usage: structpad layout [--abi lp64|ilp32] FILE\n"
    b"       structpad suggest [--abi lp64|ilp32] FILE\n"
    b"       structpad check [--abi lp64|ilp32] [--max-padding N] FILE\n"
)
_MIXED = (
    b"struct Mixed {\n"
    b"u8 a;\n"
    b"u64 b;\n"
    b"u8 c;\n"
    b"u16 d;\n"
    b"}\n"
)
_SMALL = b"struct A {\nu8 a;\nu32 b;\n}\n"


def _run(args: list[str], source: bytes = _SMALL) -> tuple[int, bytes, bytes]:
    stdin = BytesIO(source)
    stdout = BytesIO()
    stderr = BytesIO()
    status = run(args, stdin, stdout, stderr)
    return status, stdout.getvalue(), stderr.getvalue()


def _assert_lf_only(stdout: bytes, stderr: bytes) -> None:
    assert b"\r" not in stdout + stderr
    for stream in (stdout, stderr):
        if stream:
            assert stream.endswith(b"\n")


def _assert_error(args: list[str], message: str, source: bytes = _SMALL) -> None:
    status, stdout, stderr = _run(args, source)
    assert status == 2
    assert stdout == b""
    assert stderr == f"structpad: {message}\n".encode()
    assert stderr.count(b"\n") == 1
    _assert_lf_only(stdout, stderr)


def test_help_alone_is_the_only_successful_help_form() -> None:
    status, stdout, stderr = _run(["--help"])
    assert (status, stdout, stderr) == (0, _USAGE, b"")
    _assert_lf_only(stdout, stderr)

    _assert_error(["layout", "--help"], 'unknown option "--help"')


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "missing command (layout, suggest or check)"),
        (["unknown"], 'unknown command "unknown"'),
        (["-x"], 'unknown command "-x"'),
        (["layout"], "missing FILE"),
        (["layout", "--abi"], "--abi needs a value"),
        (["layout", "--abi="], 'invalid --abi "" (use lp64 or ilp32)'),
        (["layout", "--abi", "--not-an-abi"], 'invalid --abi "--not-an-abi" (use lp64 or ilp32)'),
        (["layout", "--abi=other"], 'invalid --abi "other" (use lp64 or ilp32)'),
        (["layout", "--max-padding=0"], "layout does not take --max-padding"),
        (["suggest", "--max-padding"], "suggest does not take --max-padding"),
        (["check", "--max-padding"], "--max-padding needs a value"),
        (["check", "--max-padding="], 'invalid --max-padding ""'),
        (["check", "--max-padding", "1000000"], 'invalid --max-padding "1000000"'),
        (["check", "--max-padding", "-1"], 'invalid --max-padding "-1"'),
        (["check", "--max-padding", "1.0"], 'invalid --max-padding "1.0"'),
        (["layout", "--unknown"], 'unknown option "--unknown"'),
        (["layout", "first.sp", "second.sp"], "more than one FILE"),
        (["layout", "--abi=bad", "first.sp"], 'invalid --abi "bad" (use lp64 or ilp32)'),
        (["layout", "first.sp", "--unknown"], 'unknown option "--unknown"'),
        (["layout", "--abi=lp64"], "missing FILE"),
        (["check", "--max-padding", ""], 'invalid --max-padding ""'),
    ],
)
def test_reports_usage_errors_exactly_in_argument_order(args: list[str], message: str) -> None:
    _assert_error(args, message)


def test_abi_forms_and_last_value_win() -> None:
    source = b"struct Pointer {\nu8 tag;\nptr value;\n}\n"
    status, stdout, stderr = _run(["layout", "--abi=ilp32", "-"], source)
    assert status == 0
    assert stdout == (
        b"struct Pointer: size 8, align 4, padding 3\n"
        b"offset   size  field\n"
        b"     0      1  tag: u8\n"
        b"     1      3  (padding)\n"
        b"     4      4  value: ptr\n"
    )
    assert stderr == b""
    _assert_lf_only(stdout, stderr)

    status, stdout, stderr = _run(
        ["layout", "--abi=lp64", "--abi", "ilp32", "-"], source
    )
    assert status == 0
    assert stdout.startswith(b"struct Pointer: size 8, align 4, padding 3\n")
    assert stderr == b""
    _assert_lf_only(stdout, stderr)


def test_cli_renders_layout_suggest_and_check_bytes(tmp_path: Path) -> None:
    source_path = tmp_path / "mixed.sp"
    source_path.write_bytes(_MIXED)

    status, stdout, stderr = _run(["layout", str(source_path)])
    assert status == 0
    assert stdout == (
        b"struct Mixed: size 24, align 8, padding 12\n"
        b"offset   size  field\n"
        b"     0      1  a: u8\n"
        b"     1      7  (padding)\n"
        b"     8      8  b: u64\n"
        b"    16      1  c: u8\n"
        b"    17      1  (padding)\n"
        b"    18      2  d: u16\n"
        b"    20      4  (padding)\n"
    )
    assert stderr == b""
    _assert_lf_only(stdout, stderr)

    status, stdout, stderr = _run(["suggest", str(source_path)])
    assert status == 0
    assert stdout == (
        b"struct Mixed: size 24 -> 16 (saves 8)\n"
        b"  u64 b;\n"
        b"  u16 d;\n"
        b"  u8 a;\n"
        b"  u8 c;\n"
    )
    assert stderr == b""
    _assert_lf_only(stdout, stderr)

    status, stdout, stderr = _run(["check", "--max-padding=11", str(source_path)])
    assert status == 1
    assert stdout == (
        b"Mixed: 12 bytes of padding (limit 11)\n"
        b"1 of 1 structs over the padding limit\n"
    )
    assert stderr == b""
    _assert_lf_only(stdout, stderr)

    status, stdout, stderr = _run(["check", "--max-padding", "12", str(source_path)])
    assert status == 0
    assert stdout == b"ok, 1 structs\n"
    assert stderr == b""
    _assert_lf_only(stdout, stderr)


def test_check_uses_singular_byte_at_one_padding_byte() -> None:
    source = b"struct A {\nu8 first;\nu16 second;\n}\n"
    status, stdout, stderr = _run(["check", "--max-padding=0", "-"], source)
    assert status == 1
    assert stdout == b"A: 1 byte of padding (limit 0)\n1 of 1 structs over the padding limit\n"
    assert stderr == b""
    _assert_lf_only(stdout, stderr)


def test_stdin_marker_and_input_diagnostics() -> None:
    status, stdout, stderr = _run(["check", "-"], _SMALL)
    assert status == 1
    assert stdout == b"A: 3 bytes of padding (limit 0)\n1 of 1 structs over the padding limit\n"
    assert stderr == b""
    _assert_lf_only(stdout, stderr)

    _assert_error(["layout", "-"], "<stdin>: no structs found", b"// empty\n")
    _assert_error(
        ["layout", "-"],
        '<stdin>:2: expected "TYPE NAME;" or "TYPE NAME[N];", found "u8 value;\\r"',
        b"struct A {\nu8 value;\r",
    )


def test_missing_file_uses_normalized_display_name(tmp_path: Path) -> None:
    missing = f"{tmp_path}\\missing\\record.sp"
    shown = missing.replace("\\", "/")
    _assert_error(["layout", missing], f"{shown}: cannot read the file")


def test_invalid_utf8_file_is_an_input_error(tmp_path: Path) -> None:
    path = tmp_path / "invalid.sp"
    path.write_bytes(b"struct A {\n\xff\n}\n")
    shown = str(path).replace("\\", "/")
    _assert_error(["layout", str(path)], f"{shown}: input is not valid UTF-8")


def test_embedded_control_characters_are_escaped_in_single_line_diagnostics(
    tmp_path: Path,
) -> None:
    _assert_error(
        ["layout", "-unknown\r\noption"],
        'unknown option "-unknown\\r\\noption"',
    )

    bad_path = f"{tmp_path}\\missing\r\nrecord.sp"
    shown = bad_path.replace("\\", "/").replace("\r", r"\r").replace("\n", r"\n")
    _assert_error(["layout", bad_path], f"{shown}: cannot read the file")


def test_seeded_unknown_option_strings_keep_diagnostics_single_line() -> None:
    rng = random.Random(90210)
    alphabet = list("abcXYZ 0129-_=./\t\r\n") + ["é", "λ", "雪", "🙂"]
    values = ["", "\r", "\n", "\r\n", "雪", "é", "🙂", "x" * 4095]
    values.extend(
        "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 128)))
        for _ in range(112)
    )
    for value in values:
        argument = "-property-" + value
        escaped = value.replace("\r", r"\r").replace("\n", r"\n")
        status, stdout, stderr = _run(["layout", argument])
        assert status == 2, f"counterexample={argument!r}"
        assert stdout == b"", f"counterexample={argument!r}"
        assert stderr == f'structpad: unknown option "-property-{escaped}"\n'.encode(), f"counterexample={argument!r}"
        assert stderr.count(b"\n") == 1, f"counterexample={argument!r}"
        _assert_lf_only(stdout, stderr)


def test_seeded_padding_value_domain_and_ascii_digit_boundaries() -> None:
    rng = random.Random(4771)
    valid_values = ["0", "8", "004096", "999999", "000000", "1", "3", "4"]
    valid_values.extend(
        "".join(str(rng.randrange(10)) for _ in range(rng.randint(1, 6)))
        for _ in range(112)
    )
    for value in valid_values:
        status, stdout, stderr = _run(["check", f"--max-padding={value}", "-"])
        limit = int(value)
        expected_status = 1 if 3 > limit else 0
        expected_stdout = (
            b"A: 3 bytes of padding (limit "
            + str(limit).encode("ascii")
            + b")\n1 of 1 structs over the padding limit\n"
            if expected_status == 1
            else b"ok, 1 structs\n"
        )
        assert status == expected_status, f"counterexample={value!r}"
        assert stdout == expected_stdout, f"counterexample={value!r}"
        assert stderr == b"", f"counterexample={value!r}"
        _assert_lf_only(stdout, stderr)

    invalid_values = [
        "",
        "1000000",
        "-1",
        "+1",
        "1.0",
        " 1",
        "1 ",
        "١",
        "\r",
        "\n",
        "\r\n",
        "abc",
    ]
    for _ in range(100):
        value = "".join(
            rng.choice("0123456789abcdef+- .\\r\\n") for _ in range(rng.randint(1, 12))
        )
        if value.isascii() and value.isdigit() and len(value) <= 6:
            value += "x"
        invalid_values.append(value)
    for value in invalid_values:
        escaped = value.replace("\r", r"\r").replace("\n", r"\n")
        status, stdout, stderr = _run(["check", f"--max-padding={value}", "-"])
        assert status == 2, f"counterexample={value!r}"
        assert stdout == b"", f"counterexample={value!r}"
        assert stderr == f'structpad: invalid --max-padding "{escaped}"\n'.encode(), f"counterexample={value!r}"
        assert stderr.count(b"\n") == 1, f"counterexample={value!r}"
        _assert_lf_only(stdout, stderr)


def test_maximum_argument_and_path_lengths_have_safe_output() -> None:
    argument = "-property-" + "x" * (4096 - len("-property-"))
    _assert_error(["layout", argument], f'unknown option "{argument}"')

    path = "missing\\" + "x" * (4096 - len("missing\\") - 3) + "\r\n\0"
    assert len(path) == 4096
    shown = path.replace("\\", "/").replace("\r", r"\r").replace("\n", r"\n")
    _assert_error(["layout", path], f"{shown}: cannot read the file")


def test_module_help_runs_in_a_subprocess(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    src_path = (project_root / "src").resolve()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(src_path)

    result = subprocess.run(
        [sys.executable, "-m", "structpad", "--help"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    assert result.stdout == _USAGE
    assert result.stderr == b""
    _assert_lf_only(result.stdout, result.stderr)
