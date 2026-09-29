"""Folders a sync client keeps in step with an account.

What is readable locally is which directories a client syncs and to what
account or server. What is not readable is who put a file there: Dropbox
encrypts its file cache, and for every one of these the answer lives on the
server rather than on this machine.

So the claim is containment and nothing more, and it answers a different
question from the origin sources. Sync runs both ways. A file
in a synced folder may have arrived from the account or may have been made here
and pushed to it, and the folder cannot tell those apart.
"""

from __future__ import annotations

import json
from pathlib import Path

from filegrail.models import ACTIVITY, category
from filegrail.scan import scan
from filegrail.sources.sync import collect_sync_roots, read_sync


def _nextcloud(home: Path, folder: Path) -> None:
    config = home / ".config/Nextcloud"
    config.mkdir(parents=True)
    (config / "nextcloud.cfg").write_text(
        "[Accounts]\n"
        "0\\url=https://cloud.example.org\n"
        "0\\dav_user=a.person\n"
        f"0\\Folders\\1\\localPath={folder}/\n"
        "0\\Folders\\1\\targetPath=/Documents\n",
        encoding="utf-8",
    )


def _dropbox(home: Path, folder: Path) -> None:
    config = home / ".dropbox"
    config.mkdir(parents=True)
    (config / "info.json").write_text(
        json.dumps({"personal": {"path": str(folder), "subscription_type": "Basic"}}),
        encoding="utf-8",
    )


def test_a_nextcloud_folder_is_found_with_its_server_and_account(tmp_path: Path):
    folder = tmp_path / "Nextcloud"
    folder.mkdir()
    _nextcloud(tmp_path, folder)

    roots = collect_sync_roots(home=tmp_path)

    assert [(r.client, r.path) for r in roots] == [("Nextcloud", folder)]
    assert roots[0].account == "a.person at https://cloud.example.org"


def test_a_dropbox_folder_is_found(tmp_path: Path):
    folder = tmp_path / "Dropbox"
    folder.mkdir()
    _dropbox(tmp_path, folder)

    roots = collect_sync_roots(home=tmp_path)

    assert [(r.client, r.path) for r in roots] == [("Dropbox", folder)]
    assert "personal" in roots[0].account


def test_a_file_inside_a_synced_folder_is_claimed(tmp_path: Path):
    folder = tmp_path / "Nextcloud"
    (folder / "sub").mkdir(parents=True)
    _nextcloud(tmp_path, folder)
    target = folder / "sub" / "report.pdf"
    target.write_bytes(b"\x00")

    origin = read_sync(target, collect_sync_roots(home=tmp_path))

    assert origin is not None
    assert origin.tool == "Nextcloud"
    assert "a.person" in origin.fields["account"]


def test_a_file_outside_every_synced_folder_is_not_claimed(tmp_path: Path):
    folder = tmp_path / "Nextcloud"
    folder.mkdir()
    _nextcloud(tmp_path, folder)
    elsewhere = tmp_path / "report.pdf"
    elsewhere.write_bytes(b"\x00")

    assert read_sync(elsewhere, collect_sync_roots(home=tmp_path)) is None


def test_a_sibling_directory_with_the_same_prefix_is_not_inside_it(tmp_path: Path):
    """`Nextcloud-old` is not inside `Nextcloud`, and comparing the two as text
    would say it was."""
    folder = tmp_path / "Nextcloud"
    folder.mkdir()
    (tmp_path / "Nextcloud-old").mkdir()
    _nextcloud(tmp_path, folder)
    outside = tmp_path / "Nextcloud-old" / "report.pdf"
    outside.write_bytes(b"\x00")

    assert read_sync(outside, collect_sync_roots(home=tmp_path)) is None


def test_it_says_the_file_was_handled_here_not_where_it_came_from(tmp_path: Path):
    """Sync runs both ways: the file may have arrived from the account or been
    made here and pushed to it, and containment cannot tell those apart."""
    folder = tmp_path / "Nextcloud"
    folder.mkdir()
    _nextcloud(tmp_path, folder)
    target = folder / "report.pdf"
    target.write_bytes(b"\x00")

    origin = read_sync(target, collect_sync_roots(home=tmp_path))

    assert category(origin) == ACTIVITY
    # `category` answers ACTIVITY for anything it does not know, so the rank is
    # asserted too: together they say the source was actually registered.
    assert origin.priority > 0


def test_no_client_configured_at_all(tmp_path: Path):
    assert collect_sync_roots(home=tmp_path) == []


def test_a_scan_attaches_it(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    folder = home / "Nextcloud"
    folder.mkdir()
    _nextcloud(home, folder)
    (folder / "report.pdf").write_bytes(b"\x00")

    record = next(iter(scan(folder, use_shell_history=False, home=home)))

    assert [o.tool for o in record.evidence if o.source == "sync-folder"] == ["Nextcloud"]
