"""Pure ABI-aware structure layout calculations."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from structpad.model import Field, Struct
from structpad.types import get_primitive

StructDefinitions = Mapping[str, Struct] | Iterable[Struct] | None


@dataclass(frozen=True)
class FieldLayout:
    """The byte placement and effective alignment of one field."""

    field: Field
    offset: int
    size: int
    alignment: int


@dataclass(frozen=True)
class StructLayout:
    """The computed placement and aggregate metrics of a structure."""

    struct: Struct
    field_layouts: tuple[FieldLayout, ...]
    size: int
    alignment: int
    padding: int


def _definitions_map(structs: StructDefinitions) -> dict[str, Struct]:
    if structs is None:
        return {}
    if isinstance(structs, Mapping):
        return dict(structs)
    return {struct.name: struct for struct in structs}


def _round_up(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def _field_metrics(
    field: Field,
    abi: str,
    definitions: Mapping[str, Struct],
    calculate_nested,
) -> tuple[int, int]:
    struct_name = field.struct_name
    if struct_name is not None:
        try:
            nested = definitions[struct_name]
        except KeyError as error:
            raise ValueError(f'unknown struct "{struct_name}"') from error
        nested_layout = calculate_nested(nested)
        element_size = nested_layout.size
        element_alignment = nested_layout.alignment
    else:
        primitive = get_primitive(field.type_name)
        if primitive is None:
            raise ValueError(f'unknown primitive type: {field.type_name}')
        element_size = primitive.size(abi)
        element_alignment = primitive.alignment(abi)

    count = field.array_length if field.array_length is not None else 1
    return element_size * count, element_alignment


def calculate_layout(
    struct: Struct,
    abi: str,
    structs: StructDefinitions = None,
) -> StructLayout:
    """Calculate a structure's field offsets, aggregate alignment, size and padding."""
    if abi not in {"lp64", "ilp32"}:
        raise ValueError(f"unsupported ABI: {abi}")

    definitions = _definitions_map(structs)
    definitions[struct.name] = struct
    cache: dict[str, StructLayout] = {}
    active: set[str] = set()

    def calculate_nested(item: Struct) -> StructLayout:
        cached = cache.get(item.name)
        if cached is not None:
            return cached
        if item.name in active:
            raise ValueError(f'cyclic nested struct "{item.name}"')

        active.add(item.name)
        offset = 0
        maximum_alignment = 1
        field_layouts: list[FieldLayout] = []
        for field in item.fields:
            size, natural_alignment = _field_metrics(field, abi, definitions, calculate_nested)
            alignment = 1 if item.packed else natural_alignment
            offset = _round_up(offset, alignment)
            field_layouts.append(FieldLayout(field, offset, size, alignment))
            offset += size
            maximum_alignment = max(maximum_alignment, alignment)

        alignment = 1 if item.packed else maximum_alignment
        size = _round_up(offset, alignment)
        field_size_sum = sum(field_layout.size for field_layout in field_layouts)
        result = StructLayout(item, tuple(field_layouts), size, alignment, size - field_size_sum)
        active.remove(item.name)
        cache[item.name] = result
        return result

    return calculate_nested(struct)
