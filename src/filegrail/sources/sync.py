"""Folders a sync client keeps in step with an account.

Two things are readable locally: which directories a client syncs, and to what
account or server. A third is not, and it is the one usually wanted - who put
the file there. Dropbox encrypts its file cache, and for every client here that
answer lives on the server rather than on this machine, so nothing below claims
it.

What is left is containment, and it answers a different question from the other
origin sources rather than a weaker version of the same one. **Sync runs
both ways.** A file in a synced folder may have arrived from the account, or
may have been made here and pushed to it, and the folder cannot tell those
apart. So it is recorded as something that handled the file, which is what is
actually known, rather than as an account it came from.
"""

from __future__ import annotations

import configparser
import json
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

from ..models import EvidenceRecord

#: A configuration naming more roots than this is not one of these clients.
_MAX_ROOTS = 64


@dataclass(slots=True)
class SyncRoot:
    """One directory a client keeps in step with one account."""

    client: str
    path: Path

    #: Who or what it syncs with, in the words the configuration used. Never
    #: invented: a client that names no account gets a description of what it
    #: does name, and nothing more.
    account: str


def collect_sync_roots(
    home: Path | None = None, stats: dict[str, int] | None = None
) -> list[SyncRoot]:
    """Every directory a local sync client says it keeps in step."""
    home = home or Path.home()
    found: list[SyncRoot] = []
    for reader in (_nextcloud, _dropbox, _syncthing, _onedrive):
        try:
            found.extend(reader(home))
        except (OSError, ValueError, ElementTree.ParseError, configparser.Error):
            continue
    found = found[:_MAX_ROOTS]
    if stats is not None:
        stats["sync_records"] = len(found)
    return found


def read_sync(path: Path, roots: list[SyncRoot]) -> EvidenceRecord | None:
    """Say that this file sits inside a folder some client syncs."""
    for root in roots:
        if not _inside(path, root.path):
            continue
        return EvidenceRecord(
            source="sync-folder",
            tool=root.client,
            note=f"inside a folder {root.client} keeps in step with {root.account}",
            fields={"account": root.account, "root": str(root.path)},
        )
    return None


def _inside(path: Path, root: Path) -> bool:
    """Whether `path` is under `root`, by path components rather than by text.

    `Nextcloud-old` is not inside `Nextcloud`, and comparing the two as strings
    says that it is.
    """
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


# --- the clients -------------------------------------------------------------


def _nextcloud(home: Path) -> list[SyncRoot]:
    """`nextcloud.cfg`: an INI naming the server, the user and every folder."""
    found: list[SyncRoot] = []
    for relative in (
        ".config/Nextcloud/nextcloud.cfg",
        ".var/app/com.nextcloud.desktopclient.nextcloud/config/Nextcloud/nextcloud.cfg",
        "Library/Preferences/Nextcloud/nextcloud.cfg",
        "AppData/Roaming/Nextcloud/nextcloud.cfg",
    ):
        config = home / relative
        if not config.is_file():
            continue
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read_string(config.read_text(encoding="utf-8", errors="replace"))
        if not parser.has_section("Accounts"):
            continue

        section = parser["Accounts"]
        for key, value in section.items():
            # `0\folders\1\localpath`, and the account it belongs to is its
            # first component - one configuration can hold several.
            if not key.endswith("\\localpath"):
                continue
            index = key.split("\\", 1)[0]
            user = section.get(f"{index}\\dav_user") or section.get(f"{index}\\user")
            url = section.get(f"{index}\\url")
            found.append(
                SyncRoot("Nextcloud", Path(value.rstrip("/")), _account(user, url, "Nextcloud"))
            )
    return found


def _dropbox(home: Path) -> list[SyncRoot]:
    """`info.json`: the roots and which kind of account each one is.

    The address itself is in `config.dbx`, which is encrypted, so the account
    is described by the kind of account it is and not named.
    """
    config = home / ".dropbox/info.json"
    if not config.is_file():
        return []
    document = json.loads(config.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(document, dict):
        return []

    found = []
    for kind_of, entry in document.items():
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            plan = entry.get("subscription_type")
            said = f"a {kind_of} account" + (f" ({plan})" if isinstance(plan, str) else "")
            found.append(SyncRoot("Dropbox", Path(entry["path"]), said))
    return found


def _syncthing(home: Path) -> list[SyncRoot]:
    """`config.xml`: the folders, and how many devices each is shared with."""
    for relative in (
        ".config/syncthing/config.xml",
        ".local/state/syncthing/config.xml",
        "Library/Application Support/Syncthing/config.xml",
        "AppData/Local/Syncthing/config.xml",
    ):
        config = home / relative
        if not config.is_file():
            continue
        root = ElementTree.fromstring(config.read_text(encoding="utf-8", errors="replace"))
        found = []
        for folder in root.iter("folder"):
            where = folder.get("path")
            if not where:
                continue
            shared = sum(1 for _ in folder.iter("device"))
            label = folder.get("label") or folder.get("id") or "a folder"
            found.append(
                SyncRoot("Syncthing", Path(where), f"{label}, shared with {shared} device(s)")
            )
        return found
    return []


def _onedrive(home: Path) -> list[SyncRoot]:
    """The Linux client's `config`: `sync_dir = "~/OneDrive"` and little else.

    Microsoft's own client keeps its state in an undocumented binary format,
    so this is the one configuration that can be read without guessing.
    """
    config = home / ".config/onedrive/config"
    if not config.is_file():
        return []
    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
        name, _, value = line.partition("=")
        if name.strip() != "sync_dir":
            continue
        where = value.strip().strip('"').strip()
        if not where:
            continue
        expanded = Path(where.replace("~", str(home), 1) if where.startswith("~") else where)
        return [SyncRoot("OneDrive", expanded, "the account this client is signed in as")]
    return []


def _account(user: str | None, url: str | None, client: str) -> str:
    if user and url:
        return f"{user} at {url}"
    return user or url or f"the account {client} is signed in as"
