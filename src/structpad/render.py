"""Byte-oriented text renderers for structpad commands."""

from collections.abc import Mapping, Sequence

from structpad.layout import StructLayout, calculate_layout
from structpad.model import Field, Struct
from structpad.suggest import suggest


def _definitions(structs: Sequence[Struct]) -> Mapping[str, Struct]:
    return {struct.name: struct for struct in structs}


def _field_type(field: Field) -> str:
    type_name = field.type_name
    if field.array_length is not None:
        type_name += f"[{field.array_length}]"
    return type_name


def _field_declaration(field: Field) -> str:
    array_suffix = f"[{field.array_length}]" if field.array_length is not None else ""
    return f"{field.type_name} {field.name}{array_suffix};"


def _layout_block(layout: StructLayout) -> str:
    struct = layout.struct
    packed = ", packed" if struct.packed else ""
    lines = [
        (f"struct {struct.name}: size {layout.size}, align {layout.alignment}, "
         f"padding {layout.padding}{packed}"),
        "offset   size  field",
    ]
    offset = 0
    for field_layout in layout.field_layouts:
        if field_layout.offset > offset:
            lines.append(f"{offset:>6}  {field_layout.offset - offset:>5}  (padding)")
        lines.append(
            f"{field_layout.offset:>6}  {field_layout.size:>5}  "
            f"{field_layout.field.name}: {_field_type(field_layout.field)}"
        )
        offset = field_layout.offset + field_layout.size
    if offset < layout.size:
        lines.append(f"{offset:>6}  {layout.size - offset:>5}  (padding)")
    return "\n".join(lines)


def render_layout(
    structs: Sequence[Struct], abi: str, selected_names: Sequence[str] | None = None
) -> bytes:
    """Render layouts as UTF-8 bytes with LF line endings."""
    definitions = _definitions(structs)
    selected = None if selected_names is None else frozenset(selected_names)
    blocks = [
        _layout_block(calculate_layout(struct, abi, definitions))
        for struct in structs
        if selected is None or struct.name in selected
    ]
    return (("\n\n".join(blocks) + "\n") if blocks else "").encode("utf-8")


def render_suggest(structs: Sequence[Struct], abi: str) -> bytes:
    """Render stable field-order suggestions as UTF-8 bytes with LF endings."""
    definitions = _definitions(structs)
    blocks: list[str] = []
    for struct in structs:
        current = calculate_layout(struct, abi, definitions)
        if struct.packed:
            blocks.append(
                f"struct {struct.name}: packed, size {current.size}, nothing to reorder"
            )
            continue

        proposed = suggest(struct, abi, definitions)
        if proposed.fields == struct.fields:
            blocks.append(f"struct {struct.name}: size {current.size}, already compact")
            continue

        improved = calculate_layout(proposed, abi, definitions)
        saving = current.size - improved.size
        lines = [
            f"struct {struct.name}: size {current.size} -> {improved.size} (saves {saving})"
        ]
        lines.extend(f"  {_field_declaration(field)}" for field in proposed.fields)
        blocks.append("\n".join(lines))
    return ("\n\n".join(blocks) + "\n").encode("utf-8")


def render_check(
    structs: Sequence[Struct],
    abi: str,
    max_padding: int,
    ignored: frozenset[str] = frozenset(),
) -> bytes:
    """Render padding-limit results as UTF-8 bytes with LF line endings."""
    definitions = _definitions(structs)
    over_limit: list[tuple[Struct, int]] = []
    for struct in structs:
        if struct.name in ignored:
            continue
        padding = calculate_layout(struct, abi, definitions).padding
        if padding > max_padding:
            over_limit.append((struct, padding))

    ignored_suffix = f" ({len(ignored)} ignored)" if ignored else ""

    if not over_limit:
        return f"ok, {len(structs)} structs{ignored_suffix}\n".encode()

    lines = []
    for struct, padding in over_limit:
        byte_word = "byte" if padding == 1 else "bytes"
        lines.append(f"{struct.name}: {padding} {byte_word} of padding (limit {max_padding})")
    lines.append(
        f"{len(over_limit)} of {len(structs)} structs over the padding limit"
        f"{ignored_suffix}"
    )
    return ("\n".join(lines) + "\n").encode("utf-8")
