"""Check what has to be inside the built wheel, and what it has to say.

    python tools/check_wheel.py

CI runs it on every commit, and the release runs it on the very files it
publishes.
"""

from __future__ import annotations

import glob
import sys
import zipfile

#: None of these is imported, so nothing else notices their absence: the TLD
#: list and the PRONOM registry are data the readers need, and the marker is
#: what makes the annotations visible to anyone installing this.
REQUIRED = ("filegrail/data/tlds.txt", "filegrail/data/pronom.json", "filegrail/py.typed")


def problems(path: str) -> list[str]:
    """Everything wrong with the wheel at `path`, or nothing."""
    wheel = zipfile.ZipFile(path)
    names = wheel.namelist()
    found = [f"missing {name}" for name in REQUIRED if name not in names]
    metadata = wheel.read(next(n for n in names if n.endswith(".dist-info/METADATA"))).decode()
    for line in ("License-Expression: Apache-2.0", "License-File: LICENSE"):
        if line not in metadata:
            found.append(f"METADATA lacks {line!r}")
    if "Classifier: License ::" in metadata:
        found.append("METADATA carries a license classifier beside the expression")
    return found


def main() -> int:
    wheels = glob.glob("dist/*.whl")
    if len(wheels) != 1:
        print(f"expected one wheel in dist/, found {wheels}", file=sys.stderr)
        return 1
    found = problems(wheels[0])
    for problem in found:
        print(problem, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
