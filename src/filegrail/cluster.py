"""Which files in one scan came from the same place.

A directory is a list of files. A case is the smaller number of sources that
produced them, and the difference between those two readings is what this is
for: twelve files naming three authors is a picture, twelve rows is not.

Nothing here says two files came from one person or one camera. It says they
name the same thing, and on which axis - because the axes are not equally
strong and presenting them alike would be the lie in the middle of an
otherwise useful summary. A body serial names one physical camera. A make and
model names a product that thousands of people own. A name in an author field
is text somebody typed, and two people can type the same one.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from .models import BLOCK_LABELS, EvidenceRecord, FileRecord, label
from .overview import AUTHOR_FIELDS

#: A name in a field meant for one: text a person or a program wrote down.
AUTHOR = "author"

#: One physical camera. A body serial is assigned per unit, so two files
#: carrying the same one were taken by the same machine.
DEVICE = "device"

#: One physical lens. A lens carries a serial of its own and does not stay with
#: the body it was bought with: it is lent, it is kept across an upgrade and it
#: is sold on. So two files through one lens are two files naming one object,
#: which is worth saying and is **not** the same as saying one camera took both.
#: Separate from `DEVICE` for exactly that reason.
LENS = "lens"

#: A make and model. It says what kind of camera, and deliberately not which:
#: the two are a different claim and are never merged, because a reader told
#: that two photographs "came from the same camera" on the strength of a model
#: name has been told something the metadata does not support.
MODEL = "model"

#: The axes in the order the report reads them: what took the picture, then what
#: was mounted on it, then what kind of thing it was, and all three before a name
#: somebody typed. Strongest identification first, so a section cut short keeps
#: the part that identifies most.
AXES = (DEVICE, LENS, MODEL, AUTHOR)

#: Where a camera writes the serial of the body itself.
_SERIAL_FIELDS = ("BodySerialNumber", "SerialNumber", "InternalSerialNumber")

#: And of the lens. Standard EXIF reserves this name and so does every vendor
#: block that carries one, so one spelling reaches both.
_LENS_SERIAL = "LensSerialNumber"

#: How these formats write more than one author into a field meant for one.
#: OOXML, the PDF `Info` dictionary and Dublin Core all use it, and the value
#: read whole is a person nobody is - which hides every real author in it.
#: A comma is deliberately not a separator: `Smith, John` is one person written
#: surname first, and splitting there would invent two people per document.
_AUTHOR_SEPARATOR = ";"

#: The make and the model, which are one answer written in two fields.
_MAKE, _MODEL = "Make", "Model"

#: How a basis joins the block to the field inside it.
_BASIS = " \u00b7 "


@dataclass(slots=True)
class Group:
    """The files in a scan that named one value on one axis."""

    axis: str
    name: str
    paths: list[str]

    #: The block and field the value was read from - `EXIF · BodySerialNumber`.
    #: A cluster without it says four files share a serial and leaves a reader
    #: to guess which tag that was, which is the first thing anybody checks.
    basis: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"axis": self.axis, "name": self.name, "basis": self.basis, "paths": self.paths}


@dataclass(frozen=True, slots=True)
class Attribute:
    """One author or camera value and the evidence record carrying it."""

    axis: str
    name: str
    basis: str
    evidence: EvidenceRecord


def cluster(records: list[FileRecord]) -> list[Group]:
    """Group the scanned files by every identifying value they share."""
    found: dict[tuple[str, str], list[str]] = {}
    bases: dict[tuple[str, str], str] = {}
    # One name in two cases is one name - `iSamples Team` and `iSamples team`
    # are the same team typed twice - and it is shown as it was first seen.
    spelled: dict[tuple[str, str], str] = {}
    for record in records:
        for attribute in attributes(record):
            key = (attribute.axis, attribute.name.casefold())
            paths = found.setdefault(key, [])
            bases.setdefault(key, attribute.basis)
            spelled.setdefault(key, attribute.name)
            if record.path not in paths:
                paths.append(record.path)
    groups = [Group(key[0], spelled[key], paths, bases[key]) for key, paths in found.items()]
    groups.sort(key=lambda group: (AXES.index(group.axis), -len(group.paths), group.name))
    return groups


def _model(fields: dict[str, str]) -> str | None:
    """`NIKON COOLPIX P6000` out of the two fields that spell it.

    A make with no model is dropped rather than grouped on: `NIKON` alone puts
    every Nikon in the scan in one bucket, which is a fact about the shop
    rather than about the case.
    """
    model = (fields.get(_MODEL) or "").strip()
    if not model:
        return None
    make = (fields.get(_MAKE) or "").strip()
    if make and not model.upper().startswith(make.upper()):
        return f"{make} {model}"
    return model


def attributes(record: FileRecord) -> Iterator[Attribute]:
    """Every identifying value this file carries, the axis it sits on, and the
    field it was read from."""
    for found in record.evidence:
        block = BLOCK_LABELS.get(found.block or "", label(found))
        for field in AUTHOR_FIELDS.get(found.block or "", ()):
            for name in (found.fields.get(field) or "").split(_AUTHOR_SEPARATOR):
                if name.strip():
                    yield Attribute(AUTHOR, name.strip(), f"{block}{_BASIS}{field}", found)

        for field in _SERIAL_FIELDS:
            serial = (found.fields.get(field) or "").strip()
            if serial:
                yield Attribute(DEVICE, serial, f"{block}{_BASIS}{field}", found)
                break

        lens = (found.fields.get(_LENS_SERIAL) or "").strip()
        if lens:
            yield Attribute(LENS, lens, f"{block}{_BASIS}{_LENS_SERIAL}", found)

        model = _model(found.fields)
        if model:
            named = _MODEL if _MAKE not in found.fields else f"{_MAKE} + {_MODEL}"
            yield Attribute(MODEL, model, f"{block}{_BASIS}{named}", found)
