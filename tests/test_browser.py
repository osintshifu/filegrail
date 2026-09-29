import sqlite3
from pathlib import Path

from filegrail.sources.browser import collect_browser_downloads

CHROMIUM_SCHEMA = """
CREATE TABLE downloads (
  id INTEGER PRIMARY KEY, target_path LONGVARCHAR NOT NULL,
  start_time INTEGER NOT NULL, total_bytes INTEGER NOT NULL,
  state INTEGER NOT NULL, referrer VARCHAR NOT NULL,
  tab_url VARCHAR NOT NULL, mime_type VARCHAR(255) NOT NULL);
CREATE TABLE downloads_url_chains (
  id INTEGER NOT NULL, chain_index INTEGER NOT NULL, url LONGVARCHAR NOT NULL);
"""

# 2026-08-31T10:49:33Z expressed as microseconds since 1601-01-01.
START_TIME = (1788173373 + 11644473600) * 1_000_000


def _chromium_profile(home: Path, target: str) -> None:
    profile = home / ".config" / "chromium" / "Default"
    profile.mkdir(parents=True)
    connection = sqlite3.connect(profile / "History")
    connection.executescript(CHROMIUM_SCHEMA)
    connection.execute(
        "INSERT INTO downloads VALUES (1,?,?,?,?,?,?,?)",
        (
            target,
            START_TIME,
            30209,
            1,
            "https://example.org/page",
            "https://example.org/page",
            "application/zip",
        ),
    )
    connection.execute(
        "INSERT INTO downloads_url_chains VALUES (1,0,'https://cdn.example.org/real.zip')"
    )
    connection.commit()
    connection.close()


def test_reads_chromium_download(tmp_path: Path):
    _chromium_profile(tmp_path, "/data/evidence.zip")
    found = collect_browser_downloads(home=tmp_path)

    assert "/data/evidence.zip" in found
    origin = found["/data/evidence.zip"][0]
    assert origin.url == "https://cdn.example.org/real.zip"  # chain beats tab_url
    assert origin.referrer == "https://example.org/page"
    assert origin.tool == "chromium"
    assert origin.bytes == 30209
    assert origin.at == "2026-08-31T10:49:33Z"
    assert origin.priority == 90


def test_interrupted_download_is_flagged(tmp_path: Path):
    profile = tmp_path / ".config" / "chromium" / "Default"
    profile.mkdir(parents=True)
    connection = sqlite3.connect(profile / "History")
    connection.executescript(CHROMIUM_SCHEMA)
    connection.execute(
        "INSERT INTO downloads VALUES (1,'/data/partial.bin',?,0,4,'','https://x.test','')",
        (START_TIME,),
    )
    connection.commit()
    connection.close()

    origin = collect_browser_downloads(home=tmp_path)["/data/partial.bin"][0]
    assert origin.note == "download state 4"


def test_no_profiles_is_not_an_error(tmp_path: Path):
    assert collect_browser_downloads(home=tmp_path) == {}


def test_reading_does_not_modify_the_profile(tmp_path: Path):
    _chromium_profile(tmp_path, "/data/evidence.zip")
    database = tmp_path / ".config" / "chromium" / "Default" / "History"
    before = database.read_bytes()

    collect_browser_downloads(home=tmp_path)

    assert database.read_bytes() == before


FIREFOX_SCHEMA = """
CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url LONGVARCHAR);
CREATE TABLE moz_anno_attributes (id INTEGER PRIMARY KEY, name VARCHAR(32));
CREATE TABLE moz_annos (
  id INTEGER PRIMARY KEY, place_id INTEGER NOT NULL, anno_attribute_id INTEGER,
  content LONGVARCHAR, dateAdded INTEGER DEFAULT 0);
"""


def test_a_firefox_download_with_its_metadata_is_one_record(tmp_path: Path):
    """The destination and the metadata are two annotations on one place. The
    record is the download, once, with the size the metadata carries."""
    from filegrail.sources.browser import _firefox_downloads

    database = tmp_path / "places.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript(FIREFOX_SCHEMA)
    connection.execute("INSERT INTO moz_places VALUES (1, 'https://cdn.example.org/real.zip')")
    connection.execute("INSERT INTO moz_anno_attributes VALUES (1, 'downloads/destinationFileURI')")
    connection.execute("INSERT INTO moz_anno_attributes VALUES (2, 'downloads/metaData')")
    connection.execute(
        "INSERT INTO moz_annos VALUES (1, 1, 1, 'file:///data/evidence.zip', 1788173373000000)"
    )
    connection.execute(
        'INSERT INTO moz_annos VALUES (2, 1, 2, \'{"fileSize":30209,"state":1}\', 0)'
    )
    connection.commit()
    connection.close()

    found = list(_firefox_downloads(database))

    assert len(found) == 1
    target, origin = found[0]
    assert target == "/data/evidence.zip"
    assert origin.url == "https://cdn.example.org/real.zip"
    assert origin.bytes == 30209
