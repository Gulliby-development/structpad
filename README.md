<p align="center"><img src="docs/logo.svg" width="96" alt="" /></p>

# structpad

structpad is an offline command-line tool for people who design binary records, network packets, and FFI structures. It parses a small struct description language, reports field offsets and padding for the selected ABI, suggests a lower-padding field order, and can fail a CI job when padding exceeds a limit. It reads input without changing it and uses only the Python standard library at runtime.

[![CI](https://github.com/Gulliby-development/structpad/actions/workflows/ci.yml/badge.svg)](https://github.com/Gulliby-development/structpad/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Install

Install the package with Python 3.11 or newer:

```sh
pip install .
```

You can run the command as `structpad` or use the module form:

```sh
python -m structpad --help
```

## Usage

Save this example as `net.sp`:

```text
// wire structs
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
}
```

Show each struct's field offsets, sizes, alignment, and padding:

```sh
structpad layout net.sp
```

For the example above, the layout is:

```text
struct Packet: size 32, align 8, padding 7
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
    51      5  (padding)
```

Suggest an order with less padding:

```sh
structpad suggest net.sp
```

```text
struct Packet: size 32, already compact

struct Wire: packed, size 5, nothing to reorder

struct Frame: size 56 -> 48 (saves 8)
  struct Packet head;
  u8 version;
  struct Wire tail[2];
  bool ok;
```

Check structs against a padding limit; the default limit is zero bytes:

```sh
structpad check --max-padding 8 net.sp
```

```text
Frame: 12 bytes of padding (limit 8)
1 of 3 structs over the padding limit
```

The check exits with status 1 when any struct exceeds the limit.

`--ignore NAME` is available only with `check` and may be repeated; `--ignore=NAME` is also supported. Ignored structs are omitted from the padding check but remain included in the summary's total. The summary ends with the number of distinct ignored names, so duplicates do not increase that count.

```sh
structpad check --ignore Packet net.sp
```

```text
Frame: 12 bytes of padding (limit 0)
1 of 3 structs over the padding limit (1 ignored)
```

Ignoring both `Packet` and `Frame` prints `ok, 3 structs (2 ignored)` and exits with status 0. Invalid names such as `1x` produce `invalid --ignore "1x"`; a name not defined in the file produces `unknown struct "Nope" in --ignore`. Both errors exit with status 2.

Select the ABI with `--abi lp64` (the default) or `--abi ilp32`; for example:

```sh
structpad layout --abi ilp32 net.sp
```

Use `-` as the file argument to read from standard input. The display name in diagnostics is `<stdin>`.

## Input language

A file contains one or more struct definitions. Each field is a primitive type, an array, or a previously defined struct:

```text
struct Header {
    u8 kind;
    u32 length;
    char name[10];
}
```

Names begin with an ASCII letter or underscore. Array lengths are decimal values from 1 through 65536. Use `packed struct Name {` to give all fields byte alignment. Blank lines, comments beginning with `//`, and a UTF-8 byte-order mark are accepted. A struct must contain at least one field, and nested structs must be defined earlier in the file.

The `lp64` ABI uses 8-byte pointers; `ilp32` uses 4-byte pointers. Both ABIs align 64-bit integers and floats to 8 bytes under `lp64`; under `ilp32` they keep their 8-byte size but use 4-byte alignment. Each field starts at an offset aligned to its type, and the final struct size is rounded up to the struct alignment. Padding is the space between fields and at the end.

## Exit codes

- `0`: command succeeded, or `check` found no struct over the padding limit.
- `1`: `check` found at least one struct over the padding limit.
- `2`: usage or input error.

## Development

Run the test suite and linter from the project root:

```sh
python -m pytest -q
python -m ruff check .
```

## License

MIT, see [LICENSE](LICENSE).

---

Built with BAKED, an open-source coding agent.
