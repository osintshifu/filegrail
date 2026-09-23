"""Compile a PRONOM signature file and a container signature file for the package.

    python tools/build_pronom.py DROID_SignatureFile_V125.xml \\
        container-signature-20260119.xml src/filegrail/data/pronom.json

Both files are published by The National Archives on the DROID signature page.
The output keeps what identification needs and nothing else: each format's
PUID, name, version, MIME type, extensions, signatures and priorities, and each
byte sequence reduced to fixed-length pieces with the gaps between them.

A byte sequence is a list of steps. A gap step is `[min, max]`, with `max` null
where the registry sets no bound. A piece step is a list of alternatives, each
`[length, pattern]`, where the pattern is a regular expression that matches
exactly `length` bytes. Keeping every piece fixed-length lets the matcher walk
the gaps itself instead of handing a regular expression the whole sequence,
which backtracks without bound on the signatures that chain MPEG frames.

Anything in the registry this compiler does not understand stops the build.
A signature dropped in silence is a format never identified, with nothing to say
it was ever meant to be.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://www.nationalarchives.gov.uk/pronom/SignatureFile}"

ATTRIBUTION = (
    "Contains public sector information from The National Archives' PRONOM registry, "
    "licensed under the Open Government Licence v3.0."
)

_TOKEN = re.compile(r"\s+|'[^']*'|\[[^\]]*\]|\(|\)|\||\?\?|[0-9A-Fa-f]{2}")


def _byte(value: int) -> str:
    if 0x30 <= value <= 0x39 or 0x41 <= value <= 0x5A or 0x61 <= value <= 0x7A:
        return chr(value)
    return f"\\x{value:02x}"


def _literal(data: bytes) -> str:
    return "".join(_byte(value) for value in data)


def _class(values: set[int]) -> str:
    if len(values) == 256:
        return "."
    runs: list[list[int]] = []
    for value in sorted(values):
        if runs and runs[-1][1] == value - 1:
            runs[-1][1] = value
        else:
            runs.append([value, value])
    inside = "".join(
        _byte(low) if low == high else f"{_byte(low)}-{_byte(high)}" for low, high in runs
    )
    return f"[{inside}]"


def _range(low: bytes, high: bytes) -> str:
    """Every string of this length from `low` to `high`, compared big-endian."""
    if low > high:
        low, high = high, low
    if len(low) == 1:
        return _class(set(range(low[0], high[0] + 1)))
    if low[0] == high[0]:
        return _byte(low[0]) + _range(low[1:], high[1:])
    rest = len(low) - 1
    parts = [
        _byte(low[0]) + _range(low[1:], b"\xff" * rest),
        _byte(high[0]) + _range(b"\x00" * rest, high[1:]),
    ]
    if high[0] - low[0] > 1:
        parts.append(_class(set(range(low[0] + 1, high[0]))) + "." * rest)
    return "(?:" + "|".join(parts) + ")"


def _value(token: str) -> bytes:
    if token.startswith("'"):
        return token[1:-1].encode("latin-1")
    return bytes.fromhex(token)


def _bracket(token: str) -> tuple[int, str]:
    """One `[...]` token: a range, a bit mask, or a value, any of them negated."""
    inner = token[1:-1]
    negated = inner.startswith("!")
    if negated:
        inner = inner[1:]
    if inner.startswith("&"):
        mask = int(inner[1:], 16)
        return 1, _class({v for v in range(256) if (v & mask == mask) != negated})
    bounds = re.split(r"(?<=')-(?=')|:", inner)
    if len(bounds) == 2:
        low, high = (_value(bound.strip()) for bound in bounds)
        if len(low) != len(high):
            raise ValueError(f"range with unequal ends: {token}")
        pattern = _range(low, high)
    else:
        low = _value(inner)
        pattern = _literal(low)
    size = len(low)
    if not negated:
        return size, pattern
    if size == 1:
        matcher = re.compile(pattern.encode("ascii"), re.S)
        return 1, _class({v for v in range(256) if not matcher.fullmatch(bytes([v]))})
    return size, f"(?!{pattern})" + "." * size


def piece(text: str) -> list[list[object]]:
    """A fragment in PRONOM's syntax, as fixed-length alternatives."""
    choices: list[list[tuple[int, str]]] = []
    group: list[list[tuple[int, str]]] | None = None
    position = 0
    while position < len(text):
        found = _TOKEN.match(text, position)
        if found is None:
            raise ValueError(f"cannot read {text[position:]!r} in {text!r}")
        token = found.group()
        position = found.end()
        if token.isspace():
            continue
        if token == "(":
            group = [[]]
            continue
        if token == "|":
            if group is None:
                raise ValueError(f"alternative outside a group in {text!r}")
            group.append([])
            continue
        if token == ")":
            if group is None:
                raise ValueError(f"unbalanced group in {text!r}")
            options = []
            for option in group:
                size = sum(part[0] for part in option)
                options.append((size, "".join(part[1] for part in option)))
            choices.append(options)
            group = None
            continue
        if token == "??":
            part = (1, ".")
        elif token.startswith("["):
            part = _bracket(token)
        else:
            value = _value(token)
            part = (len(value), _literal(value))
        if group is not None:
            group[-1].append(part)
        else:
            choices.append([part])
    if group is not None:
        raise ValueError(f"unclosed group in {text!r}")
    alternatives = []
    for combination in itertools.product(*choices):
        size = sum(part[0] for part in combination)
        alternatives.append([size, "".join(part[1] for part in combination)])
    return alternatives


def _gap(low: str | None, high: str | None) -> list[list[int | None]]:
    """A gap step, or none where the pieces touch."""
    lowest = int(low or 0)
    highest = None if high is None else int(high)
    if lowest == 0 and highest == 0:
        return []
    return [[lowest, highest]]


def _fragments(sub: ET.Element, side: str, ns: str) -> list[tuple[list, str, str]]:
    by_position: dict[int, list[ET.Element]] = {}
    for fragment in sub.findall(ns + side):
        by_position.setdefault(int(fragment.get("Position", "1")), []).append(fragment)
    found = []
    for position in sorted(by_position):
        fragments = by_position[position]
        alternatives = [option for fragment in fragments for option in piece(fragment.text or "")]
        first = fragments[0]
        found.append((alternatives, first.get("MinOffset"), first.get("MaxOffset")))
    return found


def _subsequence(sub: ET.Element, ns: str) -> list:
    """The pieces of one subsequence in the order they sit in the file."""
    steps: list = []
    for alternatives, low, high in reversed(_fragments(sub, "LeftFragment", ns)):
        steps.append(alternatives)
        steps.extend(_gap(low, high))
    sequence = sub.find(ns + "Sequence")
    if sequence is None or not (sequence.text or "").strip():
        raise ValueError("subsequence without a sequence")
    steps.append(piece(sequence.text or ""))
    for alternatives, low, high in _fragments(sub, "RightFragment", ns):
        steps.extend(_gap(low, high))
        steps.append(alternatives)
    return steps


def byte_sequence(element: ET.Element, ns: str = NS) -> list:
    """`[anchor, steps]`: B from the start, E from the end, V anywhere."""
    reference = element.get("Reference") or "Variable"
    subs = sorted(element.findall(ns + "SubSequence"), key=lambda s: int(s.get("Position", "1")))
    if not subs:
        raise ValueError("byte sequence without a subsequence")
    steps: list = []
    if reference == "EOFoffset":
        # Position 1 sits against the end, each later one to the left of it.
        for sub in subs:
            offset = _gap(sub.get("SubSeqMinOffset"), sub.get("SubSeqMaxOffset"))
            steps = _subsequence(sub, ns) + offset + steps
        return ["E", steps]
    if reference == "BOFoffset":
        for sub in subs:
            steps += _gap(sub.get("SubSeqMinOffset"), sub.get("SubSeqMaxOffset"))
            steps += _subsequence(sub, ns)
        return ["B", steps]
    if reference != "Variable":
        raise ValueError(f"unknown reference {reference}")
    for index, sub in enumerate(subs):
        if index:
            steps += _gap(sub.get("SubSeqMinOffset"), sub.get("SubSeqMaxOffset"))
        steps += _subsequence(sub, ns)
    return ["V", steps]


def _signatures(parent: ET.Element, ns: str) -> list[list]:
    return [
        [byte_sequence(sequence, ns) for sequence in signature.iterfind(ns + "ByteSequence")]
        for signature in parent.iter(ns + "InternalSignature")
    ]


def compile_registry(signature_file: Path, container_file: Path) -> dict:
    root = ET.parse(signature_file).getroot()
    signatures = {
        signature.get("ID"): [
            byte_sequence(sequence) for sequence in signature.iterfind(NS + "ByteSequence")
        ]
        for signature in root.iter(NS + "InternalSignature")
    }
    formats = {}
    for entry in root.iter(NS + "FileFormat"):
        formats[entry.get("ID")] = {
            "puid": entry.get("PUID"),
            "name": entry.get("Name"),
            "version": entry.get("Version") or "",
            "mime": entry.get("MIMEType") or "",
            "extensions": [e.text for e in entry.iterfind(NS + "Extension")],
            "signatures": [e.text for e in entry.iterfind(NS + "InternalSignatureID")],
            "over": [e.text for e in entry.iterfind(NS + "HasPriorityOverFileFormatID")],
        }

    containers = ET.parse(container_file).getroot()
    puids = {
        mapping.get("signatureId"): mapping.get("Puid")
        for mapping in containers.iter("FileFormatMapping")
    }
    container_signatures = []
    for signature in containers.iter("ContainerSignature"):
        files = []
        for member in signature.iter("File"):
            binary = member.find("BinarySignatures")
            files.append(
                [
                    member.findtext("Path"),
                    None if binary is None else _signatures(binary, ""),
                ]
            )
        container_signatures.append(
            {
                "id": signature.get("Id"),
                "type": signature.get("ContainerType"),
                "puid": puids[signature.get("Id")],
                "files": files,
            }
        )
    triggers: dict[str, list[str]] = {}
    for trigger in containers.iter("TriggerPuid"):
        triggers.setdefault(trigger.get("ContainerType") or "", []).append(
            trigger.get("Puid") or ""
        )

    return {
        "attribution": ATTRIBUTION,
        "signature_file": {
            "version": root.get("Version"),
            "created": root.get("DateCreated"),
            "sha256": hashlib.sha256(signature_file.read_bytes()).hexdigest(),
        },
        "container_file": {
            "version": containers.get("signatureVersion"),
            "name": container_file.name,
            "sha256": hashlib.sha256(container_file.read_bytes()).hexdigest(),
        },
        "formats": formats,
        "signatures": signatures,
        "containers": {"triggers": triggers, "signatures": container_signatures},
    }


def dump(compiled: dict) -> str:
    """One format, signature or container signature a line.

    A new release of the registry then shows as the entries it changed rather
    than as one line of most of a megabyte.
    """

    def one(value: object) -> str:
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    def block(opening: str, rows: list[str], closing: str) -> str:
        return opening + "\n" + ",\n".join(rows) + "\n" + closing

    def keyed(value: dict) -> str:
        return block("{", [f"{one(key)}:{one(value[key])}" for key in sorted(value)], "}")

    sections = []
    for key in sorted(compiled):
        value = compiled[key]
        if key in ("formats", "signatures"):
            said = keyed(value)
        elif key == "containers":
            said = block(
                "{",
                [
                    f'"signatures":{block("[", [one(item) for item in value["signatures"]], "]")}',
                    f'"triggers":{one(value["triggers"])}',
                ],
                "}",
            )
        else:
            said = one(value)
        sections.append(f"{one(key)}:{said}")
    return block("{", sections, "}") + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    compiled = compile_registry(Path(argv[0]), Path(argv[1]))
    Path(argv[2]).write_text(dump(compiled), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
