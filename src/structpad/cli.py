"""Hand-written command-line interface for structpad."""

import re
import sys
from typing import BinaryIO

from structpad.layout import calculate_layout
from structpad.model import InputError
from structpad.parser import parse
from structpad.render import render_check, render_layout, render_layout_json, render_suggest

_USAGE = (
    "usage: structpad layout [--abi lp64|ilp32] [--struct NAME]... [--format text|json] FILE\n"
    "       structpad suggest [--abi lp64|ilp32] FILE\n"
    "       structpad check [--abi lp64|ilp32] [--max-padding N] [--ignore NAME]... FILE\n"
)
_MAX_PADDING_RE = re.compile(r"[0-9]{1,6}\Z")
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


def _escape_controls(value: str) -> str:
    """Keep diagnostic interpolations on one LF-terminated line."""
    return value.replace("\r", r"\r").replace("\n", r"\n")


def _write_error(stderr: BinaryIO, message: str) -> None:
    stderr.write(f"structpad: {_escape_controls(message)}\n".encode("utf-8", errors="replace"))


def _parse_options(
    command: str, arguments: list[str]
) -> tuple[str, int, str, tuple[str, ...], tuple[str, ...], str] | str:
    abi = "lp64"
    output_format = "text"
    max_padding = 0
    ignored: list[str] = []
    selected: list[str] = []
    file_name: str | None = None
    index = 0

    while index < len(arguments):
        argument = arguments[index]
        if argument == "--abi":
            if index + 1 >= len(arguments):
                return "--abi needs a value"
            value = arguments[index + 1]
            if value not in {"lp64", "ilp32"}:
                return f'invalid --abi "{_escape_controls(value)}" (use lp64 or ilp32)'
            abi = value
            index += 2
            continue

        if argument.startswith("--abi="):
            value = argument[len("--abi=") :]
            if value not in {"lp64", "ilp32"}:
                return f'invalid --abi "{_escape_controls(value)}" (use lp64 or ilp32)'
            abi = value
            index += 1
            continue

        if argument == "--format" or argument.startswith("--format="):
            if command != "layout":
                return f"{command} does not take --format"
            if argument == "--format":
                if index + 1 >= len(arguments):
                    return "--format needs a value"
                value = arguments[index + 1]
                index += 2
            else:
                value = argument[len("--format=") :]
                index += 1
            if value not in {"text", "json"}:
                return f'invalid --format "{_escape_controls(value)}" (use text or json)'
            output_format = value
            continue

        if argument == "--max-padding" or argument.startswith("--max-padding="):
            if command != "check":
                return f"{command} does not take --max-padding"
            if argument == "--max-padding":
                if index + 1 >= len(arguments):
                    return "--max-padding needs a value"
                value = arguments[index + 1]
                index += 2
            else:
                value = argument[len("--max-padding=") :]
                index += 1
            if _MAX_PADDING_RE.fullmatch(value) is None:
                return f'invalid --max-padding "{_escape_controls(value)}"'
            max_padding = int(value)
            continue

        if argument == "--ignore" or argument.startswith("--ignore="):
            if command != "check":
                return f"{command} does not take --ignore"
            if argument == "--ignore":
                if index + 1 >= len(arguments):
                    return "--ignore needs a value"
                value = arguments[index + 1]
                index += 2
            else:
                value = argument[len("--ignore=") :]
                index += 1
            if _NAME_RE.fullmatch(value) is None:
                return f'invalid --ignore "{_escape_controls(value)}"'
            ignored.append(value)
            continue

        if argument == "--struct" or argument.startswith("--struct="):
            if command != "layout":
                return f"{command} does not take --struct"
            if argument == "--struct":
                if index + 1 >= len(arguments):
                    return "--struct needs a value"
                value = arguments[index + 1]
                index += 2
            else:
                value = argument[len("--struct=") :]
                index += 1
            if _NAME_RE.fullmatch(value) is None:
                return f'invalid --struct "{_escape_controls(value)}"'
            selected.append(value)
            continue

        if argument.startswith("-") and argument != "-":
            return f'unknown option "{_escape_controls(argument)}"'
        if file_name is not None:
            return "more than one FILE"
        file_name = argument
        index += 1

    if file_name is None:
        return "missing FILE"
    return abi, max_padding, file_name, tuple(ignored), tuple(selected), output_format


def run(args: list[str], stdin: BinaryIO, stdout: BinaryIO, stderr: BinaryIO) -> int:
    """Run a command using binary streams and return its process exit status."""
    if args == ["--help"]:
        stdout.write(_USAGE.encode("utf-8"))
        return 0
    if not args:
        _write_error(stderr, "missing command (layout, suggest or check)")
        return 2

    command = args[0]
    if command not in {"layout", "suggest", "check"}:
        _write_error(stderr, f'unknown command "{_escape_controls(command)}"')
        return 2

    parsed_options = _parse_options(command, args[1:])
    if isinstance(parsed_options, str):
        _write_error(stderr, parsed_options)
        return 2
    abi, max_padding, file_name, ignored_names, selected_names, output_format = parsed_options
    display = "<stdin>" if file_name == "-" else file_name.replace("\\", "/")

    try:
        if file_name == "-":
            source_bytes = stdin.read()
        else:
            with open(file_name, "rb") as input_file:
                source_bytes = input_file.read()
    except (OSError, ValueError):
        _write_error(stderr, f"{_escape_controls(display)}: cannot read the file")
        return 2

    try:
        source = source_bytes.decode("utf-8")
    except UnicodeDecodeError:
        _write_error(stderr, f"{_escape_controls(display)}: input is not valid UTF-8")
        return 2

    try:
        structs = parse(display, source, abi)
    except InputError as error:
        _write_error(stderr, error.message)
        return 2

    definitions = {struct.name: struct for struct in structs}
    for name in ignored_names:
        if name not in definitions:
            _write_error(stderr, f'unknown struct "{name}" in --ignore')
            return 2

    for name in selected_names:
        if name not in definitions:
            _write_error(stderr, f'unknown struct "{name}" in --struct')
            return 2

    ignored = frozenset(ignored_names)

    if command == "layout":
        renderer = render_layout_json if output_format == "json" else render_layout
        stdout.write(renderer(structs, abi, selected_names or None))
        return 0
    if command == "suggest":
        stdout.write(render_suggest(structs, abi))
        return 0

    output = render_check(structs, abi, max_padding, ignored)
    stdout.write(output)
    if any(
        struct.name not in ignored
        and calculate_layout(struct, abi, definitions).padding > max_padding
        for struct in structs
    ):
        return 1
    return 0


def main() -> int:
    """Run structpad against the process's binary standard streams."""
    return run(sys.argv[1:], sys.stdin.buffer, sys.stdout.buffer, sys.stderr.buffer)
