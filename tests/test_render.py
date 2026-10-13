"""Byte-for-byte tests for the three text renderers."""

import random
import sys
from importlib import import_module
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

model = import_module("structpad.model")
Field = model.Field
Struct = model.Struct
renderers = import_module("structpad.render")
render_check = renderers.render_check
render_layout = renderers.render_layout
render_suggest = renderers.render_suggest


WORKED_STRUCTS = (
    Struct(
        "Packet",
        (
            Field("tag", "u8"),
            Field("length", "u32"),
            Field("flags", "u16"),
            Field("name", "char", 10),
            Field("next", "ptr"),
        ),
    ),
    Struct("Wire", (Field("kind", "u8"), Field("value", "u32")), packed=True),
    Struct(
        "Frame",
        (
            Field("version", "u8"),
            Field("head", "struct Packet"),
            Field("tail", "struct Wire", 2),
            Field("ok", "bool"),
        ),
    ),
)


def test_render_layout_matches_worked_example_bytes_for_lp64():
    expected = b"""struct Packet: size 32, align 8, padding 7
offset   size  field
     0      1  tag: u8
     1      3  (padding)
     4      4  length: u32
     8      2  flags: u16
    10     10  name: char[10]
    20      4  (padding)
    24      8  next: ptr

struct Wire: size 5, align 1, padding 0, packed
offset   size  field
     0      1  kind: u8
     1      4  value: u32

struct Frame: size 56, align 8, padding 12
offset   size  field
     0      1  version: u8
     1      7  (padding)
     8     32  head: struct Packet
    40     10  tail: struct Wire[2]
    50      1  ok: bool
    51      5  (padding)
"""
    actual = render_layout(WORKED_STRUCTS, "lp64")

    assert actual == expected
    assert b"\r" not in actual
    assert actual.endswith(b"\n")
    assert not actual.endswith(b"\n\n")


def test_render_layout_matches_worked_example_bytes_for_ilp32():
    expected = b"""struct Packet: size 24, align 4, padding 3
offset   size  field
     0      1  tag: u8
     1      3  (padding)
     4      4  length: u32
     8      2  flags: u16
    10     10  name: char[10]
    20      4  next: ptr

struct Wire: size 5, align 1, padding 0, packed
offset   size  field
     0      1  kind: u8
     1      4  value: u32

struct Frame: size 40, align 4, padding 4
offset   size  field
     0      1  version: u8
     1      3  (padding)
     4     24  head: struct Packet
    28     10  tail: struct Wire[2]
    38      1  ok: bool
    39      1  (padding)
"""
    actual = render_layout(WORKED_STRUCTS, "ilp32")

    assert actual == expected
    assert b"\r" not in actual
    assert actual.endswith(b"\n")
    assert not actual.endswith(b"\n\n")


def test_render_suggest_matches_worked_example_bytes():
    expected = b"""struct Packet: size 32, already compact

struct Wire: packed, size 5, nothing to reorder

struct Frame: size 56 -> 48 (saves 8)
  struct Packet head;
  u8 version;
  struct Wire tail[2];
  bool ok;
"""
    actual = render_suggest(WORKED_STRUCTS, "lp64")

    assert actual == expected
    assert b"\r" not in actual
    assert actual.endswith(b"\n")
    assert not actual.endswith(b"\n\n")


@pytest.mark.parametrize(
    ("limit", "expected"),
    [
        (
            0,
            b"""Packet: 7 bytes of padding (limit 0)
Frame: 12 bytes of padding (limit 0)
2 of 3 structs over the padding limit
""",
        ),
        (
            8,
            b"""Frame: 12 bytes of padding (limit 8)
1 of 3 structs over the padding limit
""",
        ),
        (12, b"ok, 3 structs\n"),
    ],
)
def test_render_check_matches_worked_example_bytes(limit, expected):
    actual = render_check(WORKED_STRUCTS, "lp64", limit)

    assert actual == expected
    assert b"\r" not in actual
    assert actual.endswith(b"\n")
    assert not actual.endswith(b"\n\n")


def test_render_check_uses_singular_byte_and_strictly_exceeds_limit():
    one_padding_byte = Struct("One", (Field("tag", "u8"), Field("value", "u16")))
    expected = b"One: 1 byte of padding (limit 0)\n1 of 1 structs over the padding limit\n"

    assert render_check((one_padding_byte,), "lp64", 0) == expected
    assert render_check((one_padding_byte,), "lp64", 1) == b"ok, 1 structs\n"


def _generated_char_array_structs():
    rng = random.Random(1234)
    alphabet = "abcdefghijklmnopqrstuvwxyz"

    for case_index in range(128):
        if case_index == 0:
            struct_name = "A"
            field_count = 1
        elif case_index == 1:
            struct_name = "S" + "x" * 63
            field_count = 256
        else:
            struct_name = f"Generated{case_index}"
            field_count = rng.randint(1, 256)

        fields = []
        for field_index in range(field_count):
            if case_index == 0:
                field_name = "a"
                array_length = 1
            elif case_index == 1 and field_index == 0:
                field_name = "f" + "x" * 63
                array_length = 65536
            else:
                prefix = f"f{field_index}_"
                suffix_length = rng.randint(0, 64 - len(prefix))
                suffix = "".join(rng.choice(alphabet) for _ in range(suffix_length))
                field_name = prefix + suffix
                array_length = rng.randint(1, 65536)

            fields.append(Field(field_name, "char", array_length))

        yield Struct(struct_name, tuple(fields), packed=bool(rng.randrange(2)))


def _expected_char_array_layout(struct):
    fields = list(struct.fields)
    size = sum(field.array_length for field in fields)
    packed = ", packed" if struct.packed else ""
    lines = [
        f"struct {struct.name}: size {size}, align 1, padding 0{packed}",
        "offset   size  field",
    ]
    offset = 0
    for field in fields:
        lines.append(f"{offset:>6}  {field.array_length:>5}  {field.name}: char[{field.array_length}]")
        offset += field.array_length
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_seeded_char_array_layout_rendering_is_exact_for_generated_inputs():
    for struct in _generated_char_array_structs():
        actual = render_layout((struct,), "lp64")
        expected = _expected_char_array_layout(struct)

        assert actual == expected, f"rendering mismatch for {struct!r}"
        assert b"\r" not in actual, f"CR in output for {struct!r}"
        assert actual.endswith(b"\n"), f"missing final LF for {struct!r}"
