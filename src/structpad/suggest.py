"""Stable, pure field-order suggestions for reducing structure padding."""

from structpad.layout import StructDefinitions, calculate_layout
from structpad.model import Struct


def suggest(
    struct: Struct,
    abi: str,
    structs: StructDefinitions = None,
) -> Struct:
    """Return a stable alignment-sorted struct only when that order is smaller."""
    if struct.packed:
        return struct

    current_layout = calculate_layout(struct, abi, structs)
    ordered_fields = tuple(
        field
        for field, _layout in sorted(
            zip(struct.fields, current_layout.field_layouts),
            key=lambda item: -item[1].alignment,
        )
    )
    if ordered_fields == struct.fields:
        return struct

    candidate = Struct(struct.name, ordered_fields, struct.packed)
    candidate_layout = calculate_layout(candidate, abi, structs)
    if candidate_layout.size < current_layout.size:
        return candidate
    return struct
