import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def _readme() -> str:
    return README.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _fenced_blocks(markdown: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"^```([^\n]*)\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
    return [
        (language, body.removesuffix("\n"))
        for language, body in pattern.findall(markdown)
    ]


def test_readme_has_required_sections_and_commands() -> None:
    readme = _readme()

    for heading in (
        "## Install",
        "## Usage",
        "## Input language",
        "## Exit codes",
        "## Development",
    ):
        assert heading in readme

    for command in (
        "pip install .",
        "python -m structpad --help",
        "structpad layout net.sp",
        "structpad suggest net.sp",
        "structpad check --max-padding 8 net.sp",
        "structpad layout --abi ilp32 net.sp",
        "python -m pytest -q",
        "python -m ruff check .",
    ):
        assert command in readme


def test_readme_documents_ignore_option() -> None:
    readme = _readme()

    for required_text in (
        "--ignore NAME",
        "structpad check --ignore Packet net.sp",
        "1 of 3 structs over the padding limit (1 ignored)",
        "ok, 3 structs (2 ignored)",
        'invalid --ignore "1x"',
        'unknown struct "Nope" in --ignore',
    ):
        assert required_text in readme


def test_readme_has_worked_input_and_exact_layout_output_as_fenced_blocks() -> None:
    blocks = _fenced_blocks(_readme())

    worked_input = """// wire structs
struct Packet {
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
}"""

    layout_output = """struct Packet: size 32, align 8, padding 7
offset   size  field
     0      1  tag: u8
     1      3  (padding)
     4      4  length: u32
     8      2  flags: u16
    10     10  name: char[10]
    20      4  (padding)
    24      8  next: ptr

struct Wire: size 5, align 1, padding 0, packed
offset   size  field
     0      1  kind: u8
     1      4  value: u32

struct Frame: size 56, align 8, padding 12
offset   size  field
     0      1  version: u8
     1      7  (padding)
     8     32  head: struct Packet
    40     10  tail: struct Wire[2]
    50      1  ok: bool
    51      5  (padding)"""

    text_blocks = [body for language, body in blocks if language == "text"]
    assert worked_input in text_blocks
    assert layout_output in text_blocks
