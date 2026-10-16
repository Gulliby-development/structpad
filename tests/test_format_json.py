"""Regression tests for deterministic JSON layout output."""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

_SOURCE_DIRECTORY = str(Path(__file__).resolve().parents[1] / "src")
if _SOURCE_DIRECTORY not in sys.path:
    sys.path.insert(0, _SOURCE_DIRECTORY)

_test_cli = importlib.import_module("test_cli")
_test_ignore = importlib.import_module("test_ignore")
_test_struct_select = importlib.import_module("test_struct_select")
parse = importlib.import_module("structpad.parser").parse
render_layout_json = importlib.import_module("structpad.render").render_layout_json
_run = _test_struct_select._run
_assert_error = _test_struct_select._assert_error
_assert_lf_only = _test_cli._assert_lf_only
_NET_SOURCE = _test_ignore._NET_SOURCE

_PAIR_SOURCE = b"struct Pair {\nu8 a;\nu32 b;\n}\n"
_PAIR_TEXT = (
    b"struct Pair: size 8, align 4, padding 3\n"
    b"offset   size  field\n"
    b"     0      1  a: u8\n"
    b"     1      3  (padding)\n"
    b"     4      4  b: u32\n"
)
_EXPECTED_PAIR_JSON = (
    b"[\n"
    b"  {\n"
    b'    "name": "Pair",\n'
    b'    "size": 8,\n'
    b'    "align": 4,\n'
    b'    "padding": 3,\n'
    b'    "packed": false,\n'
    b'    "fields": [\n'
    b"      {\n"
    b'        "name": "a",\n'
    b'        "type": "u8",\n'
    b'        "offset": 0,\n'
    b'        "size": 1\n'
    b"      },\n"
    b"      {\n"
    b'        "name": "b",\n'
    b'        "type": "u32",\n'
    b'        "offset": 4,\n'
    b'        "size": 4\n'
    b"      }\n"
    b"    ],\n"
    b'    "gaps": [\n'
    b"      {\n"
    b'        "offset": 1,\n'
    b'        "size": 3\n'
    b"      }\n"
    b"    ]\n"
    b"  }\n"
    b"]\n"
)
_EXPECTED_WIRE_JSON = (
    b"[\n"
    b"  {\n"
    b'    "name": "Wire",\n'
    b'    "size": 5,\n'
    b'    "align": 1,\n'
    b'    "padding": 0,\n'
    b'    "packed": true,\n'
    b'    "fields": [\n'
    b"      {\n"
    b'        "name": "kind",\n'
    b'        "type": "u8",\n'
    b'        "offset": 0,\n'
    b'        "size": 1\n'
    b"      },\n"
    b"      {\n"
    b'        "name": "value",\n'
    b'        "type": "u32",\n'
    b'        "offset": 1,\n'
    b'        "size": 4\n'
    b"      }\n"
    b"    ],\n"
    b'    "gaps": []\n'
    b"  }\n"
    b"]\n"
)


def _assert_json_bytes(output: bytes) -> None:
    assert b"\r" not in output
    assert output.endswith(b"\n")
    assert not output.endswith(b"\n\n")


def _assert_ordered_layout_types(layout: dict[str, object]) -> None:
    assert list(layout) == ["name", "size", "align", "padding", "packed", "fields", "gaps"]
    assert type(layout["name"]) is str
    assert type(layout["size"]) is int
    assert type(layout["align"]) is int
    assert type(layout["padding"]) is int
    assert type(layout["packed"]) is bool
    assert type(layout["fields"]) is list
    assert type(layout["gaps"]) is list
    for field in layout["fields"]:
        assert list(field) == ["name", "type", "offset", "size"]
        assert type(field["name"]) is str
        assert type(field["type"]) is str
        assert type(field["offset"]) is int
        assert type(field["size"]) is int
    for gap in layout["gaps"]:
        assert list(gap) == ["offset", "size"]
        assert type(gap["offset"]) is int
        assert type(gap["size"]) is int
    assert sum(gap["size"] for gap in layout["gaps"]) == layout["padding"]


def test_pair_json_bytes_match_requested_schema_through_run_and_renderer() -> None:
    status, stdout, stderr = _run(["layout", "--format", "json", "-"], _PAIR_SOURCE)
    assert (status, stdout, stderr) == (0, _EXPECTED_PAIR_JSON, b"")
    _assert_json_bytes(stdout)

    pair_structs = parse("<stdin>", _PAIR_SOURCE.decode("utf-8"), "lp64")
    rendered = render_layout_json(pair_structs, "lp64")
    assert isinstance(rendered, bytes)
    assert rendered == _EXPECTED_PAIR_JSON
    pair = json.loads(rendered)[0]
    _assert_ordered_layout_types(pair)
    assert pair["fields"] == [
        {"name": "a", "type": "u8", "offset": 0, "size": 1},
        {"name": "b", "type": "u32", "offset": 4, "size": 4},
    ]
    assert pair["gaps"] == [{"offset": 1, "size": 3}]


def test_wire_json_bytes_match_worked_example_through_run_and_renderer() -> None:
    status, stdout, stderr = _run(
        ["layout", "--format=json", "--struct", "Wire", "-"], _NET_SOURCE
    )
    assert (status, stdout, stderr) == (0, _EXPECTED_WIRE_JSON, b"")
    _assert_json_bytes(stdout)

    net_structs = parse("net.sp", _NET_SOURCE.decode("utf-8"), "lp64")
    rendered = render_layout_json(net_structs, "lp64", ("Wire",))
    assert rendered == _EXPECTED_WIRE_JSON
    wire = json.loads(rendered)[0]
    _assert_ordered_layout_types(wire)
    assert wire["packed"] is True
    assert wire["gaps"] == []


def test_text_remains_default_and_explicit_text_remains_unchanged() -> None:
    default = _run(["layout", "-"], _PAIR_SOURCE)
    explicit = _run(["layout", "--format", "text", "-"], _PAIR_SOURCE)
    equals = _run(["layout", "-", "--format=text"], _PAIR_SOURCE)
    assert default == explicit == equals == (0, _PAIR_TEXT, b"")
    _assert_lf_only(default[1], default[2])


def test_format_forms_work_before_and_after_file() -> None:
    expected = (0, _EXPECTED_PAIR_JSON, b"")
    for args in (
        ["layout", "--format", "json", "-"],
        ["layout", "--format=json", "-"],
        ["layout", "-", "--format", "json"],
        ["layout", "-", "--format=json"],
    ):
        assert _run(args, _PAIR_SOURCE) == expected


def test_last_format_value_wins_in_both_directions() -> None:
    assert _run(
        ["layout", "--format", "text", "--format=json", "-"], _PAIR_SOURCE
    ) == (0, _EXPECTED_PAIR_JSON, b"")
    assert _run(
        ["layout", "--format=json", "--format", "text", "-"], _PAIR_SOURCE
    ) == (0, _PAIR_TEXT, b"")


def test_json_selection_is_deduplicated_in_file_order_and_resolves_nested_types() -> None:
    status, stdout, stderr = _run(
        [
            "layout",
            "--format=json",
            "--struct",
            "Frame",
            "--struct=Wire",
            "--struct",
            "Frame",
            "--struct=Wire",
            "-",
        ],
        _NET_SOURCE,
    )
    assert status == 0
    assert stderr == b""
    _assert_json_bytes(stdout)
    layouts = json.loads(stdout)
    assert [layout["name"] for layout in layouts] == ["Wire", "Frame"]
    wire, frame = layouts
    _assert_ordered_layout_types(wire)
    _assert_ordered_layout_types(frame)
    assert wire["size"] == 5
    assert wire["align"] == 1
    assert wire["padding"] == 0
    assert wire["packed"] is True
    assert frame == {
        "name": "Frame",
        "size": 56,
        "align": 8,
        "padding": 12,
        "packed": False,
        "fields": [
            {"name": "version", "type": "u8", "offset": 0, "size": 1},
            {"name": "head", "type": "struct Packet", "offset": 8, "size": 32},
            {"name": "tail", "type": "struct Wire[2]", "offset": 40, "size": 10},
            {"name": "ok", "type": "bool", "offset": 50, "size": 1},
        ],
        "gaps": [{"offset": 1, "size": 7}, {"offset": 51, "size": 5}],
    }


def test_all_layouts_keep_source_and_declaration_order_and_padding_gaps() -> None:
    status, stdout, stderr = _run(["layout", "--format=json", "-"], _NET_SOURCE)
    assert status == 0
    assert stderr == b""
    _assert_json_bytes(stdout)
    layouts = json.loads(stdout)
    assert [layout["name"] for layout in layouts] == ["Packet", "Wire", "Frame"]
    for layout in layouts:
        _assert_ordered_layout_types(layout)
    packet, wire, frame = layouts
    assert [field["name"] for field in packet["fields"]] == [
        "tag",
        "length",
        "flags",
        "name",
        "next",
    ]
    assert [field["type"] for field in packet["fields"]] == [
        "u8",
        "u32",
        "u16",
        "char[10]",
        "ptr",
    ]
    assert [field["name"] for field in frame["fields"]] == ["version", "head", "tail", "ok"]
    assert [field["type"] for field in frame["fields"]] == [
        "u8",
        "struct Packet",
        "struct Wire[2]",
        "bool",
    ]
    assert wire["fields"] == [
        {"name": "kind", "type": "u8", "offset": 0, "size": 1},
        {"name": "value", "type": "u32", "offset": 1, "size": 4},
    ]
    assert packet["gaps"] == [
        {"offset": 1, "size": 3},
        {"offset": 20, "size": 4},
    ]
    assert frame["gaps"] == [{"offset": 1, "size": 7}, {"offset": 51, "size": 5}]
    assert sum(gap["size"] for gap in packet["gaps"]) == packet["padding"]
    assert sum(gap["size"] for gap in wire["gaps"]) == wire["padding"]
    assert sum(gap["size"] for gap in frame["gaps"]) == frame["padding"]


def test_ilp32_nested_layout_uses_full_definitions_and_expected_packet_values() -> None:
    status, stdout, stderr = _run(
        ["layout", "--abi=ilp32", "--format=json", "--struct=Packet", "-"], _NET_SOURCE
    )
    assert status == 0
    assert stderr == b""
    _assert_json_bytes(stdout)
    packet = json.loads(stdout)[0]
    _assert_ordered_layout_types(packet)
    assert packet == {
        "name": "Packet",
        "size": 24,
        "align": 4,
        "padding": 3,
        "packed": False,
        "fields": [
            {"name": "tag", "type": "u8", "offset": 0, "size": 1},
            {"name": "length", "type": "u32", "offset": 4, "size": 4},
            {"name": "flags", "type": "u16", "offset": 8, "size": 2},
            {"name": "name", "type": "char[10]", "offset": 10, "size": 10},
            {"name": "next", "type": "ptr", "offset": 20, "size": 4},
        ],
        "gaps": [{"offset": 1, "size": 3}],
    }


def test_renderer_emits_empty_arrays_for_empty_input_and_selection() -> None:
    assert render_layout_json((), "lp64") == b"[]\n"
    net_structs = parse("net.sp", _NET_SOURCE.decode("utf-8"), "lp64")
    assert render_layout_json(net_structs, "lp64", ()) == b"[]\n"


def test_suggest_and_check_reject_format_before_inspecting_value() -> None:
    for command in ("suggest", "check"):
        for option in (
            ["--format", "json"],
            ["--format=json"],
            ["--format", "xml"],
            ["--format="],
            ["--format"],
        ):
            _assert_error([command, *option], f"{command} does not take --format")


def test_layout_invalid_empty_missing_and_control_values_have_exact_errors() -> None:
    _assert_error(
        ["layout", "--format", "xml", "-"],
        'invalid --format "xml" (use text or json)',
    )
    _assert_error(
        ["layout", "--format=", "-"],
        'invalid --format "" (use text or json)',
    )
    _assert_error(
        ["layout", "--format"],
        "--format needs a value",
    )
    _assert_error(
        ["layout", "--format", "bad\r\nvalue", "-"],
        'invalid --format "bad\\r\\nvalue" (use text or json)',
    )
    _assert_error(
        ["layout", "--format=bad\r\nvalue", "-"],
        'invalid --format "bad\\r\\nvalue" (use text or json)',
    )


def test_option_errors_are_reported_in_left_to_right_order_before_input_errors(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.sp"
    missing_name = str(missing.resolve())
    shown = missing_name.replace("\\", "/")
    _assert_error(
        ["layout", "--format=xml", "--abi=unknown", str(missing)],
        'invalid --format "xml" (use text or json)',
    )
    _assert_error(
        ["layout", "--abi=unknown", "--format=xml", str(missing)],
        'invalid --abi "unknown" (use lp64 or ilp32)',
    )
    _assert_error(
        ["layout", "--unknown", "--format=xml", str(missing)],
        'unknown option "--unknown"',
    )
    _assert_error(
        ["layout", "--format=xml", "--unknown", str(missing)],
        'invalid --format "xml" (use text or json)',
    )
    _assert_error(
        ["layout", "--format=xml", str(missing)],
        'invalid --format "xml" (use text or json)',
    )
    _assert_error(
        ["layout", "--format=json", missing_name],
        f"{shown}: cannot read the file",
    )


def test_json_option_preserves_file_utf8_syntax_and_selection_errors(tmp_path: Path) -> None:
    invalid_utf8 = tmp_path / "invalid-utf8.sp"
    invalid_utf8.write_bytes(b"struct Bad {\n\xff\n}\n")
    invalid_utf8_name = str(invalid_utf8.resolve())
    shown_invalid_utf8 = invalid_utf8_name.replace("\\", "/")
    _assert_error(
        ["layout", "--format=json", invalid_utf8_name],
        f"{shown_invalid_utf8}: input is not valid UTF-8",
    )

    _assert_error(
        ["layout", "--format=json", "-"],
        '<stdin>:2: expected "TYPE NAME;" or "TYPE NAME[N];", found "u8 broken"',
        b"struct Broken {\nu8 broken\n}\n",
    )
    _assert_error(
        ["layout", "--format=json", "--struct=Nope", "-"],
        'unknown struct "Nope" in --struct',
    )


def test_invalid_utf8_stdin_bytes_keep_the_process_input_diagnostic() -> None:
    project_root = Path(__file__).resolve().parents[1]
    src_path = (project_root / "src").resolve()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(src_path)

    result = subprocess.run(
        [sys.executable, "-m", "structpad", "layout", "--format=json", "-"],
        cwd=project_root,
        env=environment,
        input=b"struct Broken {\n\xff\n}\n",
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b"structpad: <stdin>: input is not valid UTF-8\n"
