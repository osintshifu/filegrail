"""What two files have in common, and where they parted company.

Two files can be related in two independent ways, and conflating them loses the
interesting case. They can share an *earlier life* - the same camera body, the
same authoring software, capture times seconds apart - and they can have reached
this machine by the *same route* or by different ones.

The combination that matters is a shared earlier life with different origins:
one photograph out of a camera arriving by two paths says something about how it
travelled that neither file says alone.

Nothing here concludes that two files are "the same". It reports what agrees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .models import METADATA, SOURCE_LABELS, FileRecord, category

#: Fields that identify a device or an author rather than describing a picture.
#: An identical `ExposureTime` means two photographs used the same shutter speed,
#: which is not evidence of anything; an identical `BodySerialNumber` is.
IDENTIFYING = (
    "Make",
    "Model",
    "BodySerialNumber",
    "LensSerialNumber",
    "LensModel",
    "CameraOwnerName",
    "Software",
    "Artist",
    "Copyright",
    "Producer",
    "Creator",
    "Application",
    "Company",
    "creator",
    "lastModifiedBy",
    "Template",
    "generator",
)

#: Close enough that two files were plausibly produced in one action.
_NEARBY_SECONDS = 300


@dataclass(slots=True)
class Comparison:
    shared: list[tuple[str, str]] = field(default_factory=list)
    differing: list[tuple[str, str, str]] = field(default_factory=list)
    origin: list[tuple[str, str]] = field(default_factory=list)
    interval: str | None = None
    assessment: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "shared": [{"field": name, "value": value} for name, value in self.shared],
            "differing": [
                {"field": name, "left": left, "right": right}
                for name, left, right in self.differing
            ],
            "origin": [{"file": name, "route": route} for name, route in self.origin],
            "interval": self.interval,
            "assessment": self.assessment,
        }


def compare(left: FileRecord, right: FileRecord) -> Comparison:
    """Compare what two files say about themselves and how each arrived."""
    found = Comparison()
    first, second = _fields(left), _fields(right)

    for name in IDENTIFYING:
        one, other = first.get(name), second.get(name)
        if one and other:
            if one == other:
                found.shared.append((name, one))
            else:
                found.differing.append((name, one, other))

    found.origin = [(Path(r.path).name, _route(r)) for r in (left, right)]
    found.interval = _interval(left, right)
    found.assessment = _assess(found)
    return found


def _fields(record: FileRecord) -> dict[str, str]:
    """Every decoded field from the file's own metadata, flattened.

    Intrinsic claims only. An application that opened the file is not software
    that made it, and letting an activity record supply `Software` produced
    the nonsense of comparing a camera against a chat client.
    """
    merged: dict[str, str] = {}
    for found in record.evidence:
        if category(found) != METADATA:
            continue
        for name, value in found.fields.items():
            merged.setdefault(name, str(value))
        if found.tool:
            merged.setdefault("Software", found.tool)
    return merged


def _route(record: FileRecord) -> str:
    arrived = record.origin
    if arrived is None:
        return "no origin record"
    label = SOURCE_LABELS.get(arrived.source, arrived.source)
    where = arrived.url or arrived.command or arrived.tool
    return f"{label}: {where}" if where else label


def _interval(left: FileRecord, right: FileRecord) -> str | None:
    """How far apart the two files claim to have been created."""
    one, other = _created(left), _created(right)
    if one is None or other is None:
        return None

    seconds = abs(int((one - other).total_seconds()))
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute"), (1, "second")):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}" + ("" if count == 1 else "s")
    return "0 seconds"


def _created(record: FileRecord) -> datetime | None:
    said = record.metadata
    if said is None or not said.at:
        return None
    try:
        return datetime.fromisoformat(said.at.replace("Z", "+00:00"))
    except ValueError:
        return None


def _assess(found: Comparison) -> str:
    """The reading, in one sentence, and never stronger than the evidence."""
    routes = {route for _name, route in found.origin}
    same_route = len(routes) == 1 and "no origin record" not in routes

    if not found.shared:
        if found.differing:
            return "The two files name different devices or authors. Nothing here connects them."
        return "Neither file records enough about itself to be compared."

    named = ", ".join(name for name, _value in found.shared)
    nearby = found.interval and found.interval.endswith("seconds")

    if same_route and nearby:
        return (
            f"Both files agree on {named}, were created within {found.interval} of each other, "
            "and arrived by the same route. They were most likely produced and acquired together."
        )
    if not same_route and len(routes) > 1:
        return (
            f"Both files agree on {named}, but they arrived by different routes. Files that "
            "share an earlier life and not an arrival path travelled separately, which is "
            "usually the more interesting of the two findings."
        )
    return f"Both files agree on {named}. How each one arrived is not established here."
