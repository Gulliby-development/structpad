"""Examples and boundary tests for the structpad input parser."""

import random

import pytest

from structpad.model import Field, InputError, Struct
from structpad.parser import parse


def _assert_error(source: str, expected: str, display: str = "t.sp", abi: str = "lp64") -> None:
    with pytest.raises(InputError) as raised:
        parse(display, source, abi)
    assert raised.value.message == expected
    assert str(raised.value) == expected


def _struct_body(fields: list[str], name: str = "A") -> str:
    return f"struct {name} {{\n" + "\n".join(fields) + "\n}\n"


def test_parse_bom_crlf_comments_and_closing_semicolon() -> None:
    source = (
        "\ufeff// wire structs\r\n"
        "struct A{\r\n"
        "\tu8 tag; // one-byte tag\r\n"
        "  char name[10];\t// fixed name\r\n"
        "};\r\n"
    )

    assert parse("net.sp", source, "lp64") == [
        Struct("A", (Field("tag", "u8"), Field("name", "char", 10)))
    ]


def test_parse_packed_and_earlier_nested_structs() -> None:
    source = (
        "struct Base {\n"
        "u32 value;\n"
        "}\n"
        "packed struct Packet {\n"
        "struct Base item[2];\n"
        "}\n"
    )

    assert parse("nested.sp", source, "ilp32") == [
        Struct("Base", (Field("value", "u32"),)),
        Struct("Packet", (Field("item", "struct Base", 2),), packed=True),
    ]



def test_accepts_whitespace_before_primitive_array_and_nested_field_semicolons() -> None:
    source = (
        "struct Base {\n"
        "u16 item \t;\n"
        "}\n"
        "struct Record {\n"
        "u8 count ;\n"
        "char bytes[2] \t;\n"
        "struct Base nested \t;\n"
        "}\n"
    )

    assert parse("spaces.sp", source, "lp64") == [
        Struct("Base", (Field("item", "u16"),)),
        Struct(
            "Record",
            (
                Field("count", "u8"),
                Field("bytes", "char", 2),
                Field("nested", "struct Base"),
            ),
        ),
    ]


def test_accepts_64_character_ascii_names_and_rejects_longer_names() -> None:
    name = "_" + "a" * 63
    assert parse("names.sp", f"struct {name} {{\nu8 {name};\n}}\n", "lp64") == [
        Struct(name, (Field(name, "u8"),))
    ]

    too_long = name + "b"
    source = f"struct {too_long} {{\nu8 value;\n}}\n"
    _assert_error(
        source,
        f't.sp:1: expected "struct NAME {{", found "struct {too_long} {{"',
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("struct 9 {\nu8 value;\n}", 'expected "struct NAME {", found "struct 9 {"'),
        ("struct A { u8 value; }", 'expected "struct NAME {", found "struct A { u8 value; }"'),
        ("\u00e9", 'expected "struct NAME {", found "\u00e9"'),
    ],
)
def test_rejects_invalid_header_lines(source: str, expected: str) -> None:
    _assert_error(source, f"t.sp:1: {expected}")


def test_reports_duplicate_struct_on_its_header() -> None:
    source = "struct A {\nu8 first;\n}\nstruct A {\nu8 second;\n}\n"
    _assert_error(source, 't.sp:4: struct "A" is defined twice')


def test_reports_the_101st_struct_on_its_header() -> None:
    source = "\n".join(f"struct S{i} {{\nu8 value;\n}}" for i in range(101))
    _assert_error(source, "t.sp:301: more than 100 structs")


def test_accepts_100_structs() -> None:
    source = "\n".join(f"struct S{i} {{\nu8 value;\n}}" for i in range(100))
    assert len(parse("many.sp", source, "lp64")) == 100


@pytest.mark.parametrize(
    "line",
    [
        "u8 value",
        "u8 value; extra",
        "u8 9value;",
        "u8 value[2]tail;",
        "u8 value[2;",
    ],
)
def test_rejects_lines_without_field_shape(line: str) -> None:
    source = f"struct A {{\n{line}\n}}\n"
    _assert_error(
        source,
        f't.sp:2: expected "TYPE NAME;" or "TYPE NAME[N];", found "{line}"',
    )


@pytest.mark.parametrize("length", ["", "0", "01", "0001", "65537", "100000", "-1", "+1", "1.0", "abc"])
def test_rejects_invalid_array_lengths_with_original_spelling(length: str) -> None:
    source = f"struct A {{\nu8 value[{length}];\n}}\n"
    _assert_error(source, f't.sp:2: invalid array length "{length}"')


def test_array_length_is_checked_before_type_resolution() -> None:
    source = "struct A {\nfloat value[0];\n}\n"
    _assert_error(source, 't.sp:2: invalid array length "0"')


@pytest.mark.parametrize("length", [1, 65_536])
def test_accepts_array_length_endpoints(length: int) -> None:
    parsed = parse("arrays.sp", _struct_body([f"u8 value[{length}];"]), "lp64")
    assert parsed[0].fields == (Field("value", "u8", length),)


def test_rejects_unknown_primitive_type() -> None:
    _assert_error("struct A {\nfloat value;\n}\n", 't.sp:2: unknown type "float"')


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("struct Missing item;", 'unknown struct "Missing"'),
        ("struct A value;", 'unknown struct "A"'),
    ],
)
def test_rejects_undefined_or_self_nested_struct(field: str, message: str) -> None:
    _assert_error(f"struct A {{\n{field}\n}}\n", f"t.sp:2: {message}")


def test_rejects_duplicate_field_name() -> None:
    source = "struct A {\nu8 a;\nu16 a;\n}\n"
    _assert_error(source, 't.sp:3: duplicate field "a"')


def test_accepts_256_fields_and_rejects_the_257th() -> None:
    fields = [f"u8 field_{index};" for index in range(256)]
    parsed = parse("fields.sp", _struct_body(fields), "lp64")
    assert len(parsed[0].fields) == 256

    too_many = fields + ["u8 final_field;"]
    source = _struct_body(too_many)
    _assert_error(source, "t.sp:258: more than 256 fields")


def test_reports_empty_struct_on_its_closing_line() -> None:
    _assert_error("struct A {\n}\n", 't.sp:2: struct "A" has no fields')


def test_reports_unclosed_struct_at_its_header_line() -> None:
    _assert_error("struct A {\nu8 a;\n", 't.sp:1: struct "A" is not closed')


def test_reports_file_without_structs_without_a_line_number() -> None:
    _assert_error("// only a comment\n \t\n", "t.sp: no structs found")


def test_escapes_residual_cr_in_source_diagnostics() -> None:
    source = "struct A {\nu8 value;\r"
    _assert_error(
        source,
        't.sp:2: expected "TYPE NAME;" or "TYPE NAME[N];", found "u8 value;\\r"',
    )


def test_escapes_cr_and_lf_in_interpolated_diagnostic_values() -> None:
    _assert_error(
        "not a struct",
        'bad\\r\\nname.sp:1: expected "struct NAME {", found "not a struct"',
        display="bad\r\nname.sp",
    )
    _assert_error(
        "struct A {\nu8 value[1\r];\n}\n",
        't.sp:2: invalid array length "1\\r"',
    )


def test_reports_nested_size_overflow_on_the_closing_line() -> None:
    source = (
        "struct A {\n"
        "u8 a;\n"
        "}\n"
        "struct B {\n"
        "struct A a[65536];\n"
        "}\n"
        "struct C {\n"
        "struct B x[65536];\n"
        "}\n"
    )
    _assert_error(source, 't.sp:9: struct "C" is larger than 1073741824 bytes')


def test_accepts_exact_maximum_struct_size_and_rejects_one_above() -> None:
    exact = (
        "struct Unit {\n"
        "u8 bytes[65536];\n"
        "}\n"
        "struct Exact {\n"
        "struct Unit units[16384];\n"
        "}\n"
    )
    parsed = parse("size.sp", exact, "lp64")
    assert len(parsed) == 2
    assert parsed[1].fields == (Field("units", "struct Unit", 16_384),)

    too_large = exact + "struct TooLarge {\nstruct Unit units[16385];\n}\n"
    _assert_error(
        too_large,
        't.sp:9: struct "TooLarge" is larger than 1073741824 bytes',
    )


def test_seeded_array_length_domain_examples() -> None:
    rng = random.Random(1234)
    valid_lengths = [1, 65_536] + [rng.randint(1, 65_536) for _ in range(98)]
    for length in valid_lengths:
        source = _struct_body([f"u8 value[{length}];"])
        try:
            parsed = parse("generated.sp", source, "lp64")
        except InputError as error:
            pytest.fail(f"counterexample={source!r}; unexpected error={error}")
        assert parsed[0].fields == (Field("value", "u8", length),), f"counterexample={source!r}"

    invalid_lengths = ["0", "65537", "01", "0001", "-1"]
    invalid_lengths.extend(
        str(rng.randint(65_537, 999_999)) if index % 2 == 0 else f"0{rng.randint(1, 65_536)}"
        for index in range(95)
    )
    for length in invalid_lengths:
        source = _struct_body([f"u8 value[{length}];"])
        try:
            parse("generated.sp", source, "lp64")
        except InputError as error:
            expected = f'generated.sp:2: invalid array length "{length}"'
            assert str(error) == expected, f"counterexample={source!r}"
        else:
            pytest.fail(f"counterexample={source!r}; invalid length was accepted")
