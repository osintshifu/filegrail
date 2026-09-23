"""Write the validation corpus out, so the claims can be checked from outside.

`tests/specimens.py` holds one file per route through the metadata reader and
what has to be read out of it, and `tests/test_specimens.py` checks that in the
suite. This writes the same files to a directory with a manifest beside them,
which serves two purposes the suite cannot.

The first is that a claim nobody outside the project can check is not much of a
claim. Anyone can build this corpus and point another tool at it.

The second is differential testing. Comparing what this project reads against
what an established tool reads needs files both of them can open, and needs to
know beforehand what is in them. That is what the manifest is: for every file,
the route it came from, the block that must be reported, the values that must
come back, and the digest of the bytes, so a corpus built on another machine is
demonstrably the same corpus.

    python tools/build_corpus.py out/corpus
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "src"))

from tests.specimens import SPECIMENS  # noqa: E402

#: Where it goes when nothing says otherwise.
DEFAULT = HERE / "build" / "corpus"


def build(into: Path) -> dict[str, object]:
    """Write every specimen under every extension its route claims."""
    if into.exists():
        shutil.rmtree(into)
    into.mkdir(parents=True)

    files = []
    for specimen in SPECIMENS:
        folder = into / specimen.route.lower().replace(" ", "-")
        folder.mkdir(exist_ok=True)
        for suffix in sorted(specimen.suffixes):
            written = folder / f"specimen{suffix}"
            specimen.write(written)
            raw = written.read_bytes()
            files.append(
                {
                    "path": str(written.relative_to(into)),
                    "route": specimen.route,
                    "block": specimen.block,
                    "expect": specimen.expect,
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )

    from filegrail import __version__

    return {
        "corpus": "filegrail validation corpus",
        "version": __version__,
        "note": (
            "Every file is synthetic and minimal. `block` is the metadata block the "
            "reader must name, and `expect` maps a field - or `tool`, `note`, `at` "
            "for what a record says about itself - to the value that must come back."
        ),
        "files": sorted(files, key=lambda item: item["path"]),
    }


def main() -> int:
    into = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT
    manifest = build(into)
    (into / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    files = manifest["files"]
    assert isinstance(files, list)
    print(f"{len(files)} files from {len(SPECIMENS)} routes in {into}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
