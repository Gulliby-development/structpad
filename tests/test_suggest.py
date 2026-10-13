"""Tests for stable, padding-reducing field-order suggestions."""

import random
import sys
from importlib import import_module
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

Field = import_module("structpad.model").Field
Struct = import_module("structpad.model").Struct
parse = import_module("structpad.parser").parse
calculate_layout = import_module("structpad.layout").calculate_layout
suggest = import_module("structpad.suggest").suggest


NET_EXAMPLE = """struct Packet {
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
    ("abi", "expected_frame_size", "suggested_size"),
    [("lp64", 56, 48), ("ilp32", 40, 36)],
)
def test_worked_example_suggestions(abi, expected_frame_size, suggested_size):
    structs = parse("net.sp", NET_EXAMPLE, abi)
    definitions = {struct.name: struct for struct in structs}
    packet, wire, frame = structs

    assert suggest(packet, abi, definitions) == packet
    assert suggest(wire, abi, definitions) == wire

    suggestion = suggest(frame, abi, definitions)
    assert [field.name for field in suggestion.fields] == ["head", "version", "tail", "ok"]
    assert calculate_layout(frame, abi, definitions).size == expected_frame_size
    assert calculate_layout(suggestion, abi, definitions).size == suggested_size


@pytest.mark.parametrize(
    ("abi", "original_size", "suggested_size"),
    [("lp64", 24, 16), ("ilp32", 16, 12)],
)
def test_mixed_struct_sorts_by_alignment_and_preserves_ties(abi, original_size, suggested_size):
    struct = parse(
        "mixed.sp",
        """struct Mixed {
    u8 a;
    u64 b;
    u8 c;
    u16 d;
}
""",
        abi,
    )[0]

    suggestion = suggest(struct, abi)
    assert [field.name for field in suggestion.fields] == ["b", "d", "a", "c"]
    assert calculate_layout(struct, abi).size == original_size
    assert calculate_layout(suggestion, abi).size == suggested_size


def test_compact_struct_is_left_in_source_order():
    struct = parse(
        "compact.sp",
        """struct Compact {
    u64 wide;
    u32 word;
    u16 half;
    u8 byte;
}
""",
        "lp64",
    )[0]

    assert suggest(struct, "lp64") == struct


def test_seeded_suggestion_invariants_for_generated_structs():
    rng = random.Random(1234)
    nested = Struct("Nested", (Field("byte", "u8"), Field("word", "u32")))
    definitions = {"Nested": nested}
    primitive_names = (
        "u8",
        "i8",
        "char",
        "bool",
        "u16",
        "i16",
        "u32",
        "i32",
        "f32",
        "u64",
        "i64",
        "f64",
        "ptr",
    )

    generated = []
    for case_index in range(128):
        field_count = 1 if case_index == 0 else 256 if case_index == 1 else rng.randint(1, 256)
        fields = []
        for field_index in range(field_count):
            if field_index % 13 == 0 and case_index > 0:
                type_name = "struct Nested"
            else:
                type_name = primitive_names[field_index % len(primitive_names)]
                if field_index >= len(primitive_names):
                    type_name = rng.choice(primitive_names)

            if case_index == 0:
                array_length = 1
            elif case_index == 1 and field_index == 0:
                array_length = 65536
            else:
                array_length = rng.randint(1, 65536)

            fields.append(Field(f"field_{field_index}", type_name, array_length))

        struct = Struct(f"Generated{case_index}", tuple(fields), packed=rng.choice((False, True)))
        generated.append(struct)
        definitions[struct.name] = struct

    assert len(generated) >= 100
    for abi in ("lp64", "ilp32"):
        for struct in generated:
            original_layout = calculate_layout(struct, abi, definitions)
            result = suggest(struct, abi, definitions)
            counterexample = f"abi={abi}, struct={struct!r}, result={result!r}"

            assert len(result.fields) == len(struct.fields), counterexample
            assert sorted(result.fields, key=lambda field: field.name) == sorted(
                struct.fields, key=lambda field: field.name
            ), counterexample

            if struct.packed:
                assert result == struct, counterexample
                continue

            stable_alignment_order = tuple(
                field
                for field, _layout in sorted(
                    zip(struct.fields, original_layout.field_layouts),
                    key=lambda pair: -pair[1].alignment,
                )
            )
            sorted_candidate = Struct(struct.name, stable_alignment_order, struct.packed)
            candidate_size = calculate_layout(sorted_candidate, abi, definitions).size
            expected_fields = (
                stable_alignment_order
                if candidate_size < original_layout.size
                else struct.fields
            )
            assert result.fields == expected_fields, counterexample
            assert calculate_layout(result, abi, definitions).size <= original_layout.size, counterexample
