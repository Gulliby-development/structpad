"""Example-based tests for selecting layout structs."""

import importlib
import sys
from io import BytesIO
from pathlib import Path

_SOURCE_DIRECTORY = str(Path(__file__).resolve().parents[1] / "src")
if _SOURCE_DIRECTORY not in sys.path:
    sys.path.insert(0, _SOURCE_DIRECTORY)
run = importlib.import_module("structpad.cli").run
_NET_SOURCE = importlib.import_module("test_ignore")._NET_SOURCE

_EXPECTED_FRAME_WIRE = (
    b"struct Wire: size 5, align 1, padding 0, packed\n"
    b"offset   size  field\n"
    b"     0      1  kind: u8\n"
    b"     1      4  value: u32\n"
    b"\n"
    b"struct Frame: size 56, align 8, padding 12\n"
    b"offset   size  field\n"
    b"     0      1  version: u8\n"
    b"     1      7  (padding)\n"
    b"     8     32  head: struct Packet\n"
    b"    40     10  tail: struct Wire[2]\n"
    b"    50      1  ok: bool\n"
    b"    51      5  (padding)\n"
)


def _run(
    args: list[str], source: bytes = _NET_SOURCE
) -> tuple[int, bytes, bytes]:
    stdin = BytesIO(source)
    stdout = BytesIO()
    stderr = BytesIO()
    status = run(args, stdin, stdout, stderr)
    return status, stdout.getvalue(), stderr.getvalue()


def _assert_error(args: list[str], message: str, source: bytes = _NET_SOURCE) -> None:
    status, stdout, stderr = _run(args, source)
    assert status == 2
    assert stdout == b""
    assert stderr == f"structpad: {message}\n".encode()
    assert stderr.count(b"\n") == 1
    assert b"\r" not in stderr


def test_requested_frame_and_wire_output_is_exact() -> None:
    status, stdout, stderr = _run(
        ["layout", "--struct", "Frame", "--struct", "Wire", "-"]
    )
    assert status == 0
    assert stdout == _EXPECTED_FRAME_WIRE
    assert stderr == b""
    assert b"\r" not in stdout


def test_equals_form_selects_only_packet_from_full_listing() -> None:
    status, full_output, stderr = _run(["layout", "-"])
    assert (status, stderr) == (0, b"")

    status, selected_output, stderr = _run(["layout", "--struct=Packet", "-"])
    assert status == 0
    assert selected_output == full_output.split(b"\n\n")[0] + b"\n"
    assert b"struct Wire:" not in selected_output
    assert b"struct Frame:" not in selected_output
    assert stderr == b""


def test_selection_matches_full_listing_under_both_abis() -> None:
    for abi in ("lp64", "ilp32"):
        status, full_output, stderr = _run(["layout", "--abi", abi, "-"])
        assert (status, stderr) == (0, b"")
        full_blocks = full_output.rstrip(b"\n").split(b"\n\n")
        expected = b"\n\n".join((full_blocks[1], full_blocks[2])) + b"\n"

        status, selected_output, stderr = _run(
            ["layout", "--abi", abi, "--struct", "Frame", "--struct", "Wire", "-"]
        )
        assert status == 0
        assert selected_output == expected
        assert stderr == b""
        if abi == "ilp32":
            assert b"struct Frame: size 40, align 4, padding 4\n" in selected_output
            assert b"     4     24  head: struct Packet\n" in selected_output
            assert b"    38      1  ok: bool\n    39      1  (padding)\n" in selected_output


def test_repeats_are_unique_and_output_stays_in_file_order() -> None:
    status, stdout, stderr = _run(
        [
            "layout",
            "--struct",
            "Frame",
            "--struct=Wire",
            "--struct",
            "Frame",
            "--struct=Wire",
            "-",
        ]
    )
    assert status == 0
    assert stdout == _EXPECTED_FRAME_WIRE
    assert stderr == b""


def test_struct_options_work_before_and_after_the_file() -> None:
    full_output = _run(["layout", "-"])[1]
    expected_wire = full_output.split(b"\n\n")[1] + b"\n"
    for args in (
        ["layout", "--struct", "Wire", "-"],
        ["layout", "--struct=Wire", "-"],
        ["layout", "-", "--struct", "Wire"],
        ["layout", "-", "--struct=Wire"],
    ):
        status, stdout, stderr = _run(args)
        assert (status, stdout, stderr) == (0, expected_wire, b"")


def test_struct_name_grammar_accepts_both_length_boundaries() -> None:
    longest_name = "A" + "x" * 62 + "9"
    source = (
        b"struct _ {\nu8 value;\n}\n"
        + f"struct {longest_name} {{\nu8 value;\n}}\n".encode()
    )
    status, stdout, stderr = _run(
        ["layout", "--struct=_", "--struct", longest_name, "-"], source
    )
    assert status == 0
    assert stdout.startswith(b"struct _: size 1, align 1, padding 0\n")
    assert f"struct {longest_name}: size 1, align 1, padding 0\n".encode() in stdout
    assert stderr == b""


def test_suggest_and_check_reject_struct_before_checking_its_value() -> None:
    _assert_error(["suggest", "--struct"], "suggest does not take --struct")
    _assert_error(["suggest", "--struct="], "suggest does not take --struct")
    _assert_error(["check", "--struct"], "check does not take --struct")
    _assert_error(["check", "--struct=Wire", "-"], "check does not take --struct")


def test_missing_and_invalid_struct_values_are_distinguished() -> None:
    _assert_error(["layout", "--struct"], "--struct needs a value")
    _assert_error(
        ["layout", "--struct", "--unknown", "-"], 'invalid --struct "--unknown"'
    )
    _assert_error(["layout", "--struct=", "-"], 'invalid --struct ""')


def test_invalid_struct_names_are_rejected_and_controls_escaped() -> None:
    invalid_values = ("1x", "A" + "x" * 64, "é", "A\r\nB")
    for value in invalid_values:
        escaped = value.replace("\r", r"\r").replace("\n", r"\n")
        _assert_error(
            ["layout", "--struct", value, "-"], f'invalid --struct "{escaped}"'
        )


def test_unknown_structs_are_checked_in_argument_order() -> None:
    _assert_error(
        ["layout", "--struct", "Frame", "--struct", "Nope", "--struct=Nope2", "-"],
        'unknown struct "Nope" in --struct',
    )
    _assert_error(
        ["layout", "--struct=Nope2", "--struct", "Nope", "-"],
        'unknown struct "Nope2" in --struct',
    )
    _assert_error(["layout", "--struct", "frame", "-"], 'unknown struct "frame" in --struct')


def test_parse_errors_precede_unknown_struct_names() -> None:
    _assert_error(
        ["layout", "--struct", "Nope", "-"],
        "<stdin>: no structs found",
        b"// empty\n",
    )


def test_missing_file_precedes_unknown_struct_names(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sp"
    shown = str(missing).replace("\\", "/")
    _assert_error(
        ["layout", "--struct", "Wire", str(missing)],
        f"{shown}: cannot read the file",
    )


def test_readme_documents_the_exact_struct_selection_example() -> None:
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    readme = readme_path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    plain_readme = readme.replace(chr(96), "")
    assert (
        "--struct NAME is available only with layout and may be repeated; "
        "--struct=NAME is also supported. Only the named structs are printed, once each "
        "and in file order, with the same numbers as in the full listing, because nested "
        "structs are still resolved from the whole file."
    ) in plain_readme
    assert "structpad layout --struct Frame --struct Wire net.sp" in readme
    assert _EXPECTED_FRAME_WIRE.decode().removesuffix("\n") in readme
    assert 'invalid --struct "1x"' in readme
    assert 'unknown struct "Nope" in --struct' in readme
    assert "suggest does not take --struct" in readme
    assert "check does not take --struct" in readme
