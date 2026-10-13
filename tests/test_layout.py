"""Tests for ABI-aware field placement and structure size calculations."""

import random
import sys
from importlib import import_module
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

calculate_layout = import_module("structpad.layout").calculate_layout
model = import_module("structpad.model")
Field = model.Field
InputError = model.InputError
Struct = model.Struct
parse = import_module("structpad.parser").parse
get_primitive = import_module("structpad.types").get_primitive

WORKED_EXAMPLE = """struct Packet {
    u8 tag;
    u32 length;
    u16 flags;
    char name[10];
    ptr next;
}

packed struct Wire {
    u8 kind;
    u32 value;
}

struct Frame {
    u8 version;
    struct Packet head;
    struct Wire tail[2];
    bool ok;
}
"""


@pytest.mark.parametrize(
    ("abi", "expected"),
    [
        (
            "lp64",
            {
                "Packet": (32, 8, 7, [(0, 1), (4, 4), (8, 2), (10, 10), (24, 8)]),
                "Wire": (5, 1, 0, [(0, 1), (1, 4)]),
                "Frame": (56, 8, 12, [(0, 1), (8, 32), (40, 10), (50, 1)]),
            },
        ),
        (
            "ilp32",
            {
                "Packet": (24, 4, 3, [(0, 1), (4, 4), (8, 2), (10, 10), (20, 4)]),
                "Wire": (5, 1, 0, [(0, 1), (1, 4)]),
                "Frame": (40, 4, 4, [(0, 1), (4, 24), (28, 10), (38, 1)]),
            },
        ),
    ],
)
def test_worked_example_layouts_match_both_abis(abi, expected):
    structs = parse("net.sp", WORKED_EXAMPLE, abi)
    definitions = {struct.name: struct for struct in structs}

    for struct in structs:
        layout = calculate_layout(struct, abi, definitions)
        size, alignment, padding, fields = expected[struct.name]
        assert (layout.size, layout.alignment, layout.padding) == (size, alignment, padding)
        assert [(field.offset, field.size) for field in layout.field_layouts] == fields


def test_packed_outer_struct_keeps_nested_struct_inner_layout():
    source = """struct Inner {
    u8 first;
    u32 second;
}
packed struct Outer {
    u8 prefix;
    struct Inner nested;
    u16 suffix;
}
"""
    structs = parse("nested.sp", source, "lp64")
    definitions = {struct.name: struct for struct in structs}

    inner_layout = calculate_layout(definitions["Inner"], "lp64", definitions)
    outer_layout = calculate_layout(definitions["Outer"], "lp64", definitions)

    assert (inner_layout.size, inner_layout.alignment, inner_layout.padding) == (8, 4, 3)
    assert (outer_layout.size, outer_layout.alignment, outer_layout.padding) == (11, 1, 0)
    assert [(field.offset, field.size, field.alignment) for field in outer_layout.field_layouts] == [
        (0, 1, 1),
        (1, 8, 1),
        (9, 2, 1),
    ]


def test_struct_array_and_char_array_sizes():
    structs = parse(
        "arrays.sp",
        """struct Item {
    u16 value;
}
struct Arrays {
    char label[10];
    struct Item items[3];
}
""",
        "lp64",
    )
    definitions = {struct.name: struct for struct in structs}
    layout = calculate_layout(definitions["Arrays"], "lp64", definitions)

    assert (layout.size, layout.alignment, layout.padding) == (16, 2, 0)
    assert [(field.offset, field.size) for field in layout.field_layouts] == [(0, 10), (10, 6)]


def test_char_array_only_struct_has_no_extra_padding():
    struct = parse("chars.sp", "struct Name {\nchar text[10];\n}\n", "lp64")[0]

    layout = calculate_layout(struct, "lp64")

    assert (layout.size, layout.alignment, layout.padding) == (10, 1, 0)
    assert [(field.offset, field.size) for field in layout.field_layouts] == [(0, 10)]


def test_layout_size_limit_accepts_exact_limit_and_parser_rejects_one_over():
    source = """struct Chunk {
    u8 bytes[65536];
}
struct Max {
    struct Chunk data[16384];
}
"""
    structs = parse("limit.sp", source, "lp64")
    definitions = {struct.name: struct for struct in structs}
    layout = calculate_layout(definitions["Max"], "lp64", definitions)

    assert layout.size == 1_073_741_824
    assert layout.padding == 0

    too_large = source.replace("data[16384]", "data[16385]")
    with pytest.raises(InputError) as error:
        parse("limit.sp", too_large, "lp64")

    assert str(error.value) == 'limit.sp:6: struct "Max" is larger than 1073741824 bytes'


def _generated_structs():
    rng = random.Random(1234)
    nested = Struct("Nested", (Field("byte", "u8"), Field("word", "u32")))
    definitions = {"Nested": nested}
    primitive_names = ("u8", "i8", "char", "bool", "u16", "i16", "u32", "i32", "f32", "u64", "i64", "f64", "ptr")

    for case_index in range(128):
        field_count = 1 if case_index == 0 else 256 if case_index == 1 else rng.randint(1, 256)
        fields = []
        for field_index in range(field_count):
            if field_index % 11 == 0 and case_index > 0:
                type_name = "struct Nested"
            else:
                type_name = rng.choice(primitive_names)

            if case_index == 0 and field_index == 0:
                array_length = 1
            elif case_index == 1 and field_index == 0:
                array_length = 65536
            else:
                array_length = rng.randint(1, 65536)

            fields.append(Field(f"field_{field_index}", type_name, array_length))

        generated = Struct(f"Generated{case_index}", tuple(fields), packed=rng.choice((False, True)))
        yield generated, definitions
        definitions[generated.name] = generated


@pytest.mark.parametrize("abi", ["lp64", "ilp32"])
def test_seeded_layout_invariants_for_generated_structs(abi):
    for struct, definitions in _generated_structs():
        layout = calculate_layout(struct, abi, definitions)
        element_size_sum = 0

        assert len(layout.field_layouts) == len(struct.fields)
        for index, field_layout in enumerate(layout.field_layouts):
            field = field_layout.field
            if field.struct_name is not None:
                element_layout = calculate_layout(definitions[field.struct_name], abi, definitions)
                element_size = element_layout.size
                natural_alignment = element_layout.alignment
            else:
                primitive = get_primitive(field.type_name)
                assert primitive is not None
                element_size = primitive.size(abi)
                natural_alignment = primitive.alignment(abi)

            expected_alignment = 1 if struct.packed else natural_alignment
            expected_size = element_size * field.array_length if field.array_length is not None else element_size

            assert field_layout.alignment == expected_alignment
            assert field_layout.size == expected_size
            assert field_layout.offset >= 0
            assert field_layout.offset % expected_alignment == 0
            assert field_layout.offset + field_layout.size <= layout.size
            if index:
                previous = layout.field_layouts[index - 1]
                assert field_layout.offset >= previous.offset + previous.size
            element_size_sum += field_layout.size

        assert layout.padding == layout.size - element_size_sum
        expected_struct_alignment = (
            1 if struct.packed else max(field.alignment for field in layout.field_layouts)
        )
        assert layout.alignment == expected_struct_alignment
        assert layout.size % layout.alignment == 0
