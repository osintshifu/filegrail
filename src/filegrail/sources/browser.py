"""Read download records from browser history databases.

These databases are the most reliable origin source available on a normal
workstation: they record the originating page, the referrer, the timestamps and
the byte count, and they survive the file being moved or renamed later.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..models import EvidenceRecord
from ..util import chrome_time, firefox_time

CHROMIUM_PROFILE_GLOBS = [
    ".config/google-chrome/*/History",
    ".config/chromium/*/History",
    ".config/BraveSoftware/*/*/History",
    ".config/microsoft-edge/*/History",
    ".config/vivaldi/*/History",
    "Library/Application Support/Google/Chrome/*/History",
    "Library/Application Support/BraveSoftware/*/*/History",
    "Library/Application Support/Microsoft Edge/*/History",
    "AppData/Local/Google/Chrome/User Data/*/History",
    "AppData/Local/BraveSoftware/*/User Data/*/History",
    "AppData/Local/Microsoft/Edge/User Data/*/History",
]

FIREFOX_PROFILE_GLOBS = [
    ".mozilla/firefox/*/places.sqlite",
    "snap/firefox/common/.mozilla/firefox/*/places.sqlite",
    ".var/app/org.mozilla.firefox/.mozilla/firefox/*/places.sqlite",
    "Library/Application Support/Firefox/Profiles/*/places.sqlite",
    "AppData/Roaming/Mozilla/Firefox/Profiles/*/places.sqlite",
]

# Chromium download state 1 == complete. Anything else was interrupted.
_CHROMIUM_COMPLETE = 1


def _profiles(home: Path, globs: list[str]) -> Iterator[Path]:
    for pattern in globs:
        yield from sorted(home.glob(pattern))


def _open_readonly(database: Path) -> tuple[sqlite3.Connection, Path]:
    """Copy the database before reading it.

    A live browser holds a write lock and may leave a hot WAL, so reading the
    original risks both failure and modification of the user's profile.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="filegrail-"))
    copy = temp_dir / database.name
    shutil.copy2(database, copy)
    for suffix in ("-wal", "-shm"):
        sidecar = database.with_name(database.name + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, copy.with_name(copy.name + suffix))
    return sqlite3.connect(f"file:{copy}?mode=ro", uri=True), temp_dir


def _chromium_downloads(database: Path) -> Iterator[tuple[str, EvidenceRecord]]:
    connection, temp_dir = _open_readonly(database)
    try:
        rows = connection.execute(
            "SELECT id, target_path, tab_url, referrer, start_time, "
            "total_bytes, mime_type, state FROM downloads"
        ).fetchall()

        chains: dict[int, str] = {}
        try:
            for download_id, url in connection.execute(
                "SELECT id, url FROM downloads_url_chains ORDER BY chain_index"
            ):
                chains[download_id] = url
        except sqlite3.OperationalError:
            pass  # older or trimmed schema

        for download_id, target, tab_url, referrer, start, size, mime, state in rows:
            if not target:
                continue
            note = None if state == _CHROMIUM_COMPLETE else f"download state {state}"
            yield (
                target,
                EvidenceRecord(
                    source="browser-download",
                    url=chains.get(download_id) or tab_url or None,
                    referrer=referrer or None,
                    tool=_browser_name(database),
                    at=chrome_time(start),
                    bytes=size or None,
                    mime=mime or None,
                    note=note,
                ),
            )
    finally:
        connection.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def _firefox_downloads(database: Path) -> Iterator[tuple[str, EvidenceRecord]]:
    connection, temp_dir = _open_readonly(database)
    try:
        rows = connection.execute(
            """
            SELECT dest.content, place.url, meta.content, dest.dateAdded
            FROM moz_annos AS dest
            JOIN moz_anno_attributes AS dest_attr
              ON dest_attr.id = dest.anno_attribute_id
             AND dest_attr.name = 'downloads/destinationFileURI'
            JOIN moz_places AS place ON place.id = dest.place_id
            LEFT JOIN (
              SELECT note.place_id, note.content
              FROM moz_annos AS note
              JOIN moz_anno_attributes AS note_attr
                ON note_attr.id = note.anno_attribute_id
               AND note_attr.name = 'downloads/metaData'
            ) AS meta ON meta.place_id = dest.place_id
            """
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []

    try:
        for destination, url, metadata, added in rows:
            target = _file_uri_to_path(destination)
            if not target:
                continue
            size = None
            if metadata:
                try:
                    size = json.loads(metadata).get("fileSize")
                except (ValueError, AttributeError):
                    size = None
            yield (
                target,
                EvidenceRecord(
                    source="browser-download",
                    url=url or None,
                    tool="firefox",
                    at=firefox_time(added),
                    bytes=size,
                ),
            )
    finally:
        connection.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def _file_uri_to_path(value: str | None) -> str | None:
    if not value or not value.startswith("file://"):
        return None
    return unquote(urlparse(value).path) or None


def _browser_name(database: Path) -> str:
    lowered = str(database).lower()
    for marker, name in (
        ("brave", "brave"),
        ("chromium", "chromium"),
        ("google-chrome", "chrome"),
        ("chrome", "chrome"),
        ("edge", "edge"),
        ("vivaldi", "vivaldi"),
    ):
        if marker in lowered:
            return name
    return "chromium-based"


def collect_browser_downloads(
    home: Path | None = None, stats: dict[str, int] | None = None
) -> dict[str, list[EvidenceRecord]]:
    """Map absolute target path -> origins recorded by any local browser.

    When `stats` is given it is filled with how many profiles were readable and
    how many download records they held, so the caller can explain an empty
    result instead of just reporting nothing.
    """
    home = home or Path.home()
    found: dict[str, list[EvidenceRecord]] = {}
    profiles_found = 0
    profiles_read = 0
    records = 0

    readers = [
        (CHROMIUM_PROFILE_GLOBS, _chromium_downloads),
        (FIREFOX_PROFILE_GLOBS, _firefox_downloads),
    ]
    for globs, reader in readers:
        for profile in _profiles(home, globs):
            profiles_found += 1
            try:
                seen = list(reader(profile))
            except (sqlite3.Error, OSError):
                continue  # unreadable or locked profile is not fatal
            profiles_read += 1
            records += len(seen)
            for target, origin in seen:
                found.setdefault(target, []).append(origin)

    if stats is not None:
        stats["browser_profiles_found"] = profiles_found
        stats["browser_profiles"] = profiles_read
        stats["browser_records"] = records
        stats["browser_artifacts_found"] = profiles_found
        stats["browser_artifacts_read"] = profiles_read

    return found
