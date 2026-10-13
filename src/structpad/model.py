"""Immutable data models shared by the parser and analysis layers."""

from dataclasses import dataclass


class InputError(Exception):
    """A user-facing input error without the structpad prefix."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Field:
    """One field declaration in a struct."""

    name: str
    type_name: str
    array_length: int | None = None

    @property
    def is_array(self) -> bool:
        """Whether this declaration has an explicit array length."""
        return self.array_length is not None

    @property
    def struct_name(self) -> str | None:
        """The nested struct name, if this field has a struct type."""
        prefix = "struct "
        if self.type_name.startswith(prefix):
            return self.type_name[len(prefix) :]
        return None


@dataclass(frozen=True)
class Struct:
    """A struct declaration and its fields in source order."""

    name: str
    fields: tuple[Field, ...]
    packed: bool = False
