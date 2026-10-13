"""Parser for the structpad structure-description language."""

import re

from structpad.layout import calculate_layout
from structpad.model import Field, InputError, Struct
from structpad.types import get_primitive

_NAME = r"[A-Za-z_][A-Za-z0-9_]{0,63}"
_HEADER_RE = re.compile(rf"struct[ \t]+(?P<name>{_NAME})[ \t]*\{{\Z")
_PACKED_HEADER_RE = re.compile(rf"packed[ \t]+struct[ \t]+(?P<name>{_NAME})[ \t]*\{{\Z")
_FIELD_RE = re.compile(rf"(?P<name>{_NAME})(?:\[(?P<length>[^\[\]]*)\])?\Z")
_LENGTH_RE = re.compile(r"[1-9][0-9]*\Z")
_MAX_STRUCT_SIZE = 1_073_741_824


def _escape_controls(value: str) -> str:
    """Keep interpolated input visible without allowing multiline diagnostics."""
    return value.replace("\r", r"\r").replace("\n", r"\n")


def _source_lines(text: str) -> list[str]:
    """Split LF-delimited input, removing one CR only when it precedes an LF."""
    text = text.removeprefix("\ufeff")
    pieces = text.split("\n")
    lines: list[str] = []
    for index, piece in enumerate(pieces):
        if index == len(pieces) - 1 and piece == "" and text.endswith("\n"):
            continue
        if index < len(pieces) - 1 and piece.endswith("\r"):
            piece = piece[:-1]
        lines.append(piece)
    return lines


def _invalid_line(display: str, line_number: int, content: str) -> InputError:
    return InputError(
        f'{display}:{line_number}: expected "TYPE NAME;" or "TYPE NAME[N];", found "{content}"'
    )


def _valid_array_length(value: str) -> int | None:
    """Return a permitted array length, or None when its spelling/value is invalid."""
    if not _LENGTH_RE.fullmatch(value) or len(value) > 5:
        return None
    number = int(value)
    if number > 65_536:
        return None
    return number


def parse(display: str, text: str, abi: str) -> list[Struct]:
    """Parse structure declarations and report the first source error."""
    if abi not in {"lp64", "ilp32"}:
        raise ValueError(f"unsupported ABI: {abi}")

    shown_display = _escape_controls(display)
    structures: list[Struct] = []
    defined: dict[str, Struct] = {}
    current_name: str | None = None
    current_packed = False
    current_fields: list[Field] = []
    current_field_names: set[str] = set()
    header_line = 0

    for line_number, raw_line in enumerate(_source_lines(text), start=1):
        content = raw_line.split("//", 1)[0].strip(" \t")
        if not content:
            continue
        shown_content = _escape_controls(content)

        if current_name is None:
            header_match = _PACKED_HEADER_RE.fullmatch(content)
            packed = header_match is not None
            if header_match is None:
                header_match = _HEADER_RE.fullmatch(content)
            if header_match is None:
                raise InputError(
                    f'{shown_display}:{line_number}: expected "struct NAME {{", found "{shown_content}"'
                )

            name = header_match.group("name")
            if name in defined:
                raise InputError(f'{shown_display}:{line_number}: struct "{name}" is defined twice')
            if len(structures) >= 100:
                raise InputError(f"{shown_display}:{line_number}: more than 100 structs")

            current_name = name
            current_packed = packed
            current_fields = []
            current_field_names = set()
            header_line = line_number
            continue

        if content in {"}", "};"}:
            if not current_fields:
                raise InputError(
                    f'{shown_display}:{line_number}: struct "{current_name}" has no fields'
                )
            completed = Struct(current_name, tuple(current_fields), current_packed)
            measured = calculate_layout(completed, abi, defined)
            if measured.size > _MAX_STRUCT_SIZE:
                raise InputError(
                    f'{shown_display}:{line_number}: struct "{current_name}" is larger than '
                    f"{_MAX_STRUCT_SIZE} bytes"
                )
            structures.append(completed)
            defined[current_name] = completed
            current_name = None
            current_packed = False
            current_fields = []
            current_field_names = set()
            header_line = 0
            continue

        if not content.endswith(";"):
            raise _invalid_line(shown_display, line_number, shown_content)

        tokens = re.split(r"[ \t]+", content[:-1].strip(" \t"))
        if len(tokens) == 2 and tokens[0] != "struct":
            type_name, raw_field = tokens
        elif (
            len(tokens) == 3
            and tokens[0] == "struct"
            and re.fullmatch(_NAME, tokens[1]) is not None
        ):
            type_name = f"struct {tokens[1]}"
            raw_field = tokens[2]
        else:
            raise _invalid_line(shown_display, line_number, shown_content)

        field_match = _FIELD_RE.fullmatch(raw_field)
        if field_match is None:
            raise _invalid_line(shown_display, line_number, shown_content)
        field_name = field_match.group("name")
        raw_length = field_match.group("length")
        array_length: int | None = None
        if raw_length is not None:
            array_length = _valid_array_length(raw_length)
            if array_length is None:
                raise InputError(
                    f'{shown_display}:{line_number}: invalid array length "{_escape_controls(raw_length)}"'
                )

        struct_name: str | None = None
        if type_name.startswith("struct "):
            struct_name = type_name[len("struct ") :]
            if struct_name not in defined:
                raise InputError(
                    f'{shown_display}:{line_number}: unknown struct "{_escape_controls(struct_name)}"'
                )
        elif get_primitive(type_name) is None:
            raise InputError(
                f'{shown_display}:{line_number}: unknown type "{_escape_controls(type_name)}"'
            )

        if field_name in current_field_names:
            raise InputError(f'{shown_display}:{line_number}: duplicate field "{field_name}"')
        if len(current_fields) >= 256:
            raise InputError(f"{shown_display}:{line_number}: more than 256 fields")

        current_fields.append(Field(field_name, type_name, array_length))
        current_field_names.add(field_name)

    if current_name is not None:
        raise InputError(
            f'{shown_display}:{header_line}: struct "{current_name}" is not closed'
        )
    if not structures:
        raise InputError(f"{shown_display}: no structs found")
    return structures
