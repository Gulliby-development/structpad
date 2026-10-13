"""Primitive type sizes and alignments for supported ABIs."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PrimitiveType:
    """The size and natural alignment of a primitive under both supported ABIs."""

    name: str
    lp64_size: int
    lp64_alignment: int
    ilp32_size: int
    ilp32_alignment: int

    def size(self, abi: str) -> int:
        """Return the primitive's size for an ABI."""
        if abi == "lp64":
            return self.lp64_size
        if abi == "ilp32":
            return self.ilp32_size
        raise ValueError(f"unsupported ABI: {abi}")

    def alignment(self, abi: str) -> int:
        """Return the primitive's alignment for an ABI."""
        if abi == "lp64":
            return self.lp64_alignment
        if abi == "ilp32":
            return self.ilp32_alignment
        raise ValueError(f"unsupported ABI: {abi}")


PRIMITIVE_TYPES = {
    row[0]: PrimitiveType(*row)
    for row in (
        ("u8", 1, 1, 1, 1),
        ("i8", 1, 1, 1, 1),
        ("char", 1, 1, 1, 1),
        ("bool", 1, 1, 1, 1),
        ("u16", 2, 2, 2, 2),
        ("i16", 2, 2, 2, 2),
        ("u32", 4, 4, 4, 4),
        ("i32", 4, 4, 4, 4),
        ("f32", 4, 4, 4, 4),
        ("u64", 8, 8, 8, 4),
        ("i64", 8, 8, 8, 4),
        ("f64", 8, 8, 8, 4),
        ("ptr", 8, 8, 4, 4),
    )
}


def get_primitive(name: str) -> PrimitiveType | None:
    """Return the primitive definition, or None for a non-primitive type name."""
    return PRIMITIVE_TYPES.get(name)
