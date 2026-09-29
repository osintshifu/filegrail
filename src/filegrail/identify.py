"""Identifiers found in the metadata a scan already read.

The detectors here are ported from DirSifu (MIT, same author), which arrived at
them by finding out what a regex sweep actually costs. Each type is
recognisable with high precision and normalisable without guessing - by a known
TLD, a checksum, a shape nothing else has, or the label beside it - and the
readme's table of identifier types is the list of them.

Deliberately **not** detected, with reasons, because a noisy identifier list is
worse than a short one:

* **phone numbers** - without a phone-number library and a region hint the false
  positive rate is ruinous: invoice numbers, order ids, timestamps, version
  strings and partial hashes all match.
* **dates** - a sweep yields thousands of meaningless hits, and the dates that
  matter here already arrive as a claim's timestamp.
* **IPv6** - high false-positive rate against code (``::``).

What differs from DirSifu is the corpus. DirSifu reads document text; this reads
what files record **about themselves** - an author line, a company, a template
path, a producing URL, a camera's GPS fix - which is exactly where identifiers a
document body never mentions turn out to live. That corpus is short strings
rather than prose, so precision costs less here than it does there.

Document text is available too, under `content=True`, and it is kept as its own
corpus rather than merged: the precision argument above is the reason, and
telling the two apart is what makes the answer worth having. A name in a
document is a lead. A name in a document that the record of the file's *arrival*
also carries was put there twice, by separate acts - and nothing that reads only
one corpus can say so.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from email.utils import getaddresses
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

from .checksums import (
    base58check_version,
    bech32_version,
    is_aba,
    is_cashaddr,
    is_eth,
    is_iban,
    is_monero,
    is_nip,
    is_onion,
    is_regon,
    is_vin,
)
from .models import ORIGIN, FileRecord, category
from .models import label as source_label
from .redact import PATTERNS as REDACT_PATTERNS
from .redact import fingerprint

#: What files record about themselves: the corpus this has always read, and the
#: one the detectors were tuned for. Short structured strings, where a match is
#: nearly always a real identifier.
IN_METADATA = "metadata"

#: What files say. Read only when asked, and kept as its own corpus rather than
#: merged into the one above: prose is an order of magnitude noisier - a
#: citation, a file name, an abbreviation with a dot in it all match something -
#: and letting that into the metadata list would drown the half that is reliable.
IN_CONTENT = "content"


class _Text(NamedTuple):
    """One string to search, with everything needed to say where it came from."""

    file: str

    #: The whole path, which is what makes two files two files. `file` is the
    #: name a place is shown with, and one name turns up in many folders.
    path: str
    source: str
    where: str
    text: str
    corpus: str

    #: Whether the origin this came from is a record of how the file arrived.
    #: Meaningless for content, which records nothing.
    acquired: bool

    #: Machine-readable evidence coordinates. `source` above is the label used
    #: in the report; these are kept separately so graph relationships do not
    #: have to recover structured evidence from presentation text.
    source_id: str
    category: str | None
    match: str | None
    at: str | None


#: Occurrences are counted exactly; the sampled list of places is capped so one
#: value repeated across a huge tree cannot dominate the output.
MAX_SAMPLES = 20

#: Exact places kept for one identifier in one file. The relationship retains
#: its full occurrence count when a long list is shortened.
MAX_RELATION_PLACES = 100

#: How a file and the field it was found in are joined into one place
#: string. It goes into `--json` in exactly this form, so it is a constant
#: rather than a literal in two places - and the report re-renders the
#: separator with whatever the terminal can actually print.
PLACE = " · "

#: What the `source` of a value found in a document body is called. The text of
#: a file is not one of the evidence sources - nothing wrote it down about the
#: file - so it is named for what it is.
CONTENT_SOURCE = "content"


@dataclass(frozen=True, slots=True)
class IdentifierEvidence:
    """One checkable place that ties an identifier to a file."""

    source: str
    category: str | None
    match: str | None
    place: str
    corpus: str
    at: str | None


EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@([A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)+)\b"
)
URL_RE = re.compile(r"\bhttps?://[^\s<>\"'`\](){}]+", re.IGNORECASE)
IPV4_RE = re.compile(r"(?<![\w.\-])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.\-])")
HASH_RE = re.compile(
    r"(?<![A-Za-z0-9\-])([A-Fa-f0-9]{32}|[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64}|[A-Fa-f0-9]{128})"
    r"(?![A-Za-z0-9\-])"
)
DOMAIN_RE = re.compile(
    r"(?<![\w.@\-/\\])"
    r"((?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,})"
    r"(?![\w\-])"
)

#: A bare ``name.ext`` token that is far more likely to be a file than a host.
#: Every one of these suffixes is also a real TLD, so a suffix blocklist alone
#: cannot decide it - the shape of the whole token has to be considered.
FILE_LIKE_RE = re.compile(
    r"^[a-z_][a-z0-9_\-]*\.(?:md|py|js|mjs|cjs|ts|tsx|jsx|json|txt|yml|yaml|sh|bash|zsh"
    r"|go|rs|css|html|htm|xml|csv|log|toml|ini|cfg|conf|lock|sql|rb|php|java|kt|swift"
    r"|c|h|cpp|hpp|cs|pl|lua|r|vue|svelte|proto|graphql|map|so|db|bak|tmp|zip|gz|tar"
    r"|doc|docx|xls|xlsx|ppt|pptx|pdf|jpg|jpeg|png|gif|tif|tiff|heic|mp4|mp3|dotm)$",
    re.IGNORECASE,
)

#: Candidates only: the checksum decides. A legacy or pay-to-script address is
#: base58 with a version character in front - `1` and `3` on Bitcoin, `L` and
#: `M` on Litecoin, `D`, `9` and `A` on Dogecoin - and the version byte under
#: it names the chain. A Bech32 address is `bc1` or `ltc1` and its own
#: alphabet, which leaves out `1`, `b`, `i` and `o` so nothing is misread.
LEGACY_ADDRESS_RE = re.compile(
    r"(?<![A-Za-z0-9])([13LMD9A][1-9A-HJ-NP-Za-km-z]{25,34})(?![A-Za-z0-9])"
)
BTC_BECH32_RE = re.compile(
    r"(?<![A-Za-z0-9])(bc1[02-9ac-hj-np-z]{6,87})(?![A-Za-z0-9])", re.IGNORECASE
)
LTC_BECH32_RE = re.compile(
    r"(?<![A-Za-z0-9])(ltc1[02-9ac-hj-np-z]{6,87})(?![A-Za-z0-9])", re.IGNORECASE
)
#: A Bitcoin Cash address: CashAddr's forty-two characters, with the
#: `bitcoincash:` prefix or without it - the checksum covers it either way.
CASHADDR_RE = re.compile(
    r"(?<![A-Za-z0-9:])((?:bitcoincash:)?[qp][02-9ac-hj-np-z]{41})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
#: A Monero address: `4` or `8` and ninety-four base58 characters, eleven more
#: for an integrated one.
MONERO_RE = re.compile(
    r"(?<![A-Za-z0-9])([48][1-9A-HJ-NP-Za-km-z]{94}(?:[1-9A-HJ-NP-Za-km-z]{11})?)(?![A-Za-z0-9])"
)

#: Printed in groups of four as often as not, so a space is allowed between
#: any two characters and stripped before the number is checked.
IBAN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30})(?![A-Za-z0-9])")

#: The Polish numbers are taken only beside their label, or behind the `PL`
#: of an EU VAT id: their check digit passes about one random number in
#: eleven, and ten bare digits in a document are an order number far more
#: often than a taxpayer. The label is what makes the checksum worth trusting.
NIP_LABELLED_RE = re.compile(r"\bNIP\b[\s:.#-]*((?:\d[\s-]?){9}\d)", re.IGNORECASE)
NIP_PREFIXED_RE = re.compile(r"(?<![A-Za-z0-9])PL(\d{10})(?![A-Za-z0-9])")
REGON_RE = re.compile(r"\bREGON\b[\s:.#-]*(\d{14}|\d{9})(?!\d)", re.IGNORECASE)

#: A version 3 onion address is 56 base32 characters and its own checksum.
ONION_RE = re.compile(r"(?<![a-z2-7])([a-z2-7]{56})\.onion(?![\w\-])", re.IGNORECASE)

#: Six pairs of hex with one separator throughout, and not a window cut out
#: of something longer - a key fingerprint is the same pairs, sixteen or
#: thirty-two of them.
MAC_RE = re.compile(
    r"(?<![\w:\-])([0-9A-Fa-f]{2}([:\-])(?:[0-9A-Fa-f]{2}\2){4}[0-9A-Fa-f]{2})(?![\w:\-])"
)

#: Neither is a device: one is unset, the other is everybody.
_NOT_A_DEVICE = frozenset({"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"})

#: An account or group on a Windows machine or domain: the machine's three
#: sub-authorities and a relative id. The short well-known SIDs - `S-1-5-18`
#: is SYSTEM on every Windows there is - identify nothing in particular.
SID_RE = re.compile(r"(?<![\w\-])(S-1-5-21-\d{1,10}-\d{1,10}-\d{1,10}-\d{1,10})(?![\w\-])")

#: A bank identifier code has no checksum, so it is taken only beside its
#: label, and its country has to be one. Eight characters, or eleven with a
#: branch.
BIC_RE = re.compile(
    r"\b(?:BIC|SWIFT)\b(?:\s*(?:code|number))?[\s:.#-]*"
    r"([A-Za-z]{6}[A-Za-z0-9]{2}(?:[A-Za-z0-9]{3})?)(?![\w\-])",
    re.IGNORECASE,
)

#: The credential shapes `--redact` knows by their prefix, taken here as
#: identifiers: a key or a token in a document is a finding. Only the shapes
#: that prove themselves - a vendor prefix, a JWT's three segments - and not
#: the rules that go by the name beside a value, which stay redaction's
#: business. What is reported is the kind and a fingerprint, the same one
#: redaction writes, and never the value: a report that leaves the machine
#: must not become the place the secret was copied to.
_SECRET_KINDS = frozenset({"aws_access_key", "vendor_token", "jwt"})
_SECRET_PATTERNS = tuple(
    (kind, pattern, group) for kind, pattern, group in REDACT_PATTERNS if kind in _SECRET_KINDS
)

#: Every private key opens with the same line, and a scan that goes by the
#: line never sees the rest. So a key block's identity is where it is, not
#: what it holds, and all of them are the one fact.
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")
PRIVATE_KEY = "private key block"

#: Fields whose *name* says a person wrote this. Matched on the whole name,
#: namespace and all: XMP's `dc:creator` is the author, while a bare `Creator`
#: in a PDF or a PNG is the program that wrote it, which is why that one sits
#: in the software fields above. A name is never read out of prose - a
#: capitalised pair of words is a name, a town and a sign-off in equal
#: measure - and since a document body is addressed by line, it cannot
#: reach these tables by construction.
_PERSON_FIELDS = frozenset(
    {
        "author",
        "dc:creator",
        "artist",
        "by-line",
        "lastmodifiedby",
        "lastauthor",
        "cp:lastmodifiedby",
    }
)

#: Mail headers carrying mailboxes, whose display names are people.
_MAILBOX_FIELDS = frozenset({"from", "to", "cc", "reply-to", "sender"})

#: Fields whose name says an organisation. `Source` is not here: it is an
#: agency in IPTC, a scanner in a PNG and something else again in RIFF.
_ORG_FIELDS = frozenset({"company", "credit"})

#: Hex and dashes only - a GUID, a digest - is a device id, not a name, however
#: many of its letters are letters.
_HEX_BLOB_RE = re.compile(r"[0-9a-f\-]+")

#: What an application writes where a name should go.
_NOBODY = frozenset(
    {
        "microsoft office user",
        "windows user",
        "office user",
        "user",
        "admin",
        "administrator",
        "unknown",
        "author",
        "owner",
        "default",
        "n/a",
        "none",
        "anonymous",
        "guest",
        "root",
        "system",
        "unnamed",
        "untitled",
    }
)

#: Where a URL is somebody's profile: the host, what to call the platform,
#: and what the path has to look like. `www.` and `m.` come off the host.
#: On GitHub the owner is the first segment of any path, a repository included.
_PROFILE_PATH = {
    "x": re.compile(r"^/([A-Za-z0-9_]{1,15})/?$"),
    "instagram": re.compile(r"^/([A-Za-z0-9_.]{1,30})/?$"),
    "github": re.compile(r"^/([A-Za-z0-9][A-Za-z0-9\-]{0,38})(?:/|$)"),
    "linkedin": re.compile(r"^/in/([A-Za-z0-9\-%]+)/?$"),
    "telegram": re.compile(r"^/([A-Za-z0-9_]{5,32})/?$"),
    "tiktok": re.compile(r"^/@([A-Za-z0-9_.]+)/?$"),
    "youtube": re.compile(r"^/@([A-Za-z0-9_.\-]+)/?$"),
    "reddit": re.compile(r"^/(?:u|user)/([A-Za-z0-9_\-]+)/?$"),
    "facebook": re.compile(r"^/([A-Za-z0-9.]{5,})/?$"),
}
_PROFILE_HOSTS = {
    "x.com": "x",
    "twitter.com": "x",
    "instagram.com": "instagram",
    "github.com": "github",
    "raw.githubusercontent.com": "github",
    "linkedin.com": "linkedin",
    "t.me": "telegram",
    "telegram.me": "telegram",
    "tiktok.com": "tiktok",
    "youtube.com": "youtube",
    "reddit.com": "reddit",
    "facebook.com": "facebook",
}

#: First path segments that are a site's own pages rather than somebody's.
_NOT_A_HANDLE = frozenset(
    {
        "home", "search", "login", "signup", "signin", "settings", "explore", "p",
        "reel", "reels", "stories", "orgs", "about", "help", "share", "sharer",
        "sharer.php", "groups", "pages", "events", "hashtag", "i", "intent",
        "profile.php", "topics", "marketplace", "watch", "tv", "status",
        "notifications", "messages", "privacy", "terms", "features", "pricing",
        "sponsors", "apps", "site", "new", "join", "trending", "live", "shorts",
        "feed", "dialog", "photo", "video", "videos", "posts", "tag", "tags",
        "channel", "user", "pub", "company", "jobs", "legal", "policies",
        "advisories", "collections", "enterprise", "security", "readme", "codespaces",
        "pulls", "issues", "organizations", "users", "contact", "resources", "solutions",
        "team", "copilot", "account", "dashboard", "logout", "user-attachments", "assets",
        "downloads", "stars", "customer-stories", "sessions",
    }
)  # fmt: skip

#: A user's directory on the machine that made the file - `C:\Users\name`,
#: `/Users/name`, `/home/name` - as it turns up in a template path, a
#: recorded location or a command. The ones every machine has are nobody's.
USER_DIR_RE = re.compile(r"(?:^|[\\/])(?i:Users|home)[\\/]([^\\/\s:*?\"<>|]{1,64})(?=[\\/]|$)")
_SHARED_HOMES = frozenset(
    {"public", "default", "default user", "all users", "shared", "administrator"}
)

#: The United States numbers. None can be trusted on its own - two have no
#: checksum and the third's passes one random number in ten - so each is
#: taken only beside the label that names it. A social security number is
#: the key to somebody's identity and is reported as a credential is: as a
#: fingerprint, never as the number.
SSN_RE = re.compile(
    r"\b(?:SSN|SS#|Social Security(?:\s+(?:Number|No\.?|#))?)[\s:.#-]*"
    r"(\d{3})-(\d{2})-(\d{4})(?!\d)",
    re.IGNORECASE,
)
EIN_RE = re.compile(
    r"\b(?:EIN|FEIN|TIN|Employer Identification(?:\s+(?:Number|No\.?))?"
    r"|Tax ID(?:\s+(?:Number|No\.?))?)[\s:.#-]*(\d{2})-(\d{7})(?!\d)",
    re.IGNORECASE,
)
ABA_RE = re.compile(
    r"\b(?:ABA|RTN|routing(?:\s+(?:number|no\.?|#|transit(?:\s+number)?))?)[\s:.#-]*"
    r"(\d{9})(?!\d)",
    re.IGNORECASE,
)

#: The prefixes the IRS assigns an employer identification number; the gaps
#: - 07, 17, 49, 69, 79, 89, 96 and their neighbours - were never used.
_EIN_PREFIXES = frozenset(
    f"{n:02d}"
    for n in (*range(1, 7), *range(10, 17), *range(20, 28), *range(30, 49), *range(50, 69),
              *range(71, 78), *range(80, 89), *range(90, 96), 98, 99)
)  # fmt: skip

#: Analytics, tag-manager, advertising and payment ids with a prefix of their
#: own, taken wherever they stand: an account is an account, and the same
#: one on two sites is one owner. `ca-pub-` and `pub-` name the same AdSense
#: publisher and fold into one. A Stripe publishable key is an account, not
#: a secret - the secret one starts `sk_` and is a `secret`.
TRACKER_RE = re.compile(
    r"(?<![\w\-])("
    r"UA-\d{4,10}-\d{1,4}"
    r"|GTM-[A-Z0-9]{5,8}"
    r"|AW-\d{9,11}"
    r"|DC-\d{6,10}"
    r"|(?:ca-)?pub-\d{16}"
    r"|pk_live_[A-Za-z0-9]{20,}"
    r")(?![\w\-])"
)

#: A GA4 measurement id, which has to carry a digit: `G-SHOCK` does not.
GA4_RE = re.compile(r"(?<![\w\-])(G-(?=[A-Z0-9]*\d)[A-Z0-9]{8,12})(?![\w\-])")

#: Ids that are a bare number and are believed only beside the service that
#: issued them - in the loader or tracking-pixel URL a page carries, which
#: the content reader keeps even though it leaves `<script>` out, or in the
#: call itself where a text file quotes one. Two groups where a service has
#: two spellings; whichever matched is the id.
ANCHORED_TRACKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "facebook",
        re.compile(
            r"facebook\.com/tr/?\?(?:[^\s\"'&]*&)?id=(\d{15,16})(?!\d)"
            r"|fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d{15,16})['\"]"
        ),
    ),
    ("yandex", re.compile(r"mc\.yandex\.ru/watch/(\d{6,9})(?!\d)|\bym\(\s*(\d{6,9})\s*,")),
    ("amazon", re.compile(r"[?&]tag=([a-z0-9][a-z0-9\-]{1,30}-2[01])(?![\w\-])", re.IGNORECASE)),
    ("hotjar", re.compile(r"\bhjid\s*[:=]\s*['\"]?(\d{5,8})(?!\d)")),
    ("clarity", re.compile(r"clarity\.ms/tag/([a-z0-9]{8,12})(?![\w\-])")),
)

CVE_RE = re.compile(r"\b(CVE-\d{4}-\d{4,7})\b", re.IGNORECASE)
CWE_RE = re.compile(r"\b(CWE-\d{1,4})\b", re.IGNORECASE)
#: A GitHub advisory: three groups of four from the alphabet GitHub mints them in.
GHSA_RE = re.compile(r"\b(GHSA(?:-[23456789cfghjmpqrvwx]{4}){3})\b", re.IGNORECASE)

#: A registry key under any hive, long name or short. Windows does not care
#: about case, so neither does the normalised form, which also uses the
#: short hive name so the two spellings are one key.
REGISTRY_RE = re.compile(
    r"\b(HKEY_LOCAL_MACHINE|HKEY_CURRENT_USER|HKEY_CLASSES_ROOT|HKEY_USERS|HKEY_CURRENT_CONFIG"
    r"|HKLM|HKCU|HKCR|HKU|HKCC)(\\[^\s\"'<>|*?]+)",
    re.IGNORECASE,
)
_HIVES = {
    "hkey_local_machine": "hklm",
    "hkey_current_user": "hkcu",
    "hkey_classes_root": "hkcr",
    "hkey_users": "hku",
    "hkey_current_config": "hkcc",
}

#: A digest written as colon-separated pairs, the way a certificate or an SSH
#: key fingerprint is shown: sixteen, twenty or thirty-two of them. The same
#: value as the bare spelling, and folded into it.
COLON_DIGEST_RE = re.compile(
    r"(?<![0-9A-Fa-f:])("
    r"(?:[0-9A-Fa-f]{2}:){15}[0-9A-Fa-f]{2}"
    r"|(?:[0-9A-Fa-f]{2}:){19}[0-9A-Fa-f]{2}"
    r"|(?:[0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}"
    r")(?![0-9A-Fa-f:])"
)

#: IPv6, in the two spellings that cannot be mistaken for code: all eight
#: groups written out, or any form inside the brackets a URL puts round one.
#: A compressed address standing bare - `a::b` - is still not taken: `::` is
#: what a scope operator looks like, and the false-positive rate is ruinous.
IPV6_FULL_RE = re.compile(r"(?<![\w:.])((?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4})(?![\w:.])")
IPV6_BRACKET_RE = re.compile(r"\[([0-9A-Fa-f:.]{2,45})\]")

#: Where a file sat on a Windows machine: a drive letter, an environment
#: variable, or a UNC share, which names a host. POSIX paths are not taken -
#: a slash is in every URL and every fraction. Windows does not care about
#: case, so neither does the normalised form.
_PATH_PART = r"[^\\/:*?\"<>|\s]+"
PATH_RE = re.compile(
    rf"(?<![\w\\])("
    rf"[A-Za-z]:\\(?:{_PATH_PART}\\)*(?:{_PATH_PART})?"
    rf"|%[A-Za-z_][A-Za-z0-9_]*%\\(?:{_PATH_PART}\\)*(?:{_PATH_PART})?"
    rf"|\\\\{_PATH_PART}(?:\\{_PATH_PART})+"
    r")"
)

#: A machine's name, as a shortcut's tracker block or a mail hop writes it. The
#: underscore is there because NetBIOS allows one and DNS does not.
HOSTNAME_RE = re.compile(
    r"[A-Za-z0-9_](?:[A-Za-z0-9_\-]{0,61}[A-Za-z0-9_])?"
    r"(?:\.[A-Za-z0-9_](?:[A-Za-z0-9_\-]{0,61}[A-Za-z0-9_])?)*"
)
#: Fields whose whole value is a machine: the shortcut's `MachineID`, and the
#: two ends of a `Received:` hop. A mailbox in a `From:` header is not the shape.
_HOSTNAME_FIELDS = frozenset({"machineid", "from", "by"})
#: Names that stand in for a machine without being one.
_NOT_A_HOST = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "unknown",
        "tsclient",
        "wsl.localhost",
        "server",
        "servername",
        "hostname",
        "computer",
        "computername",
    }
)

#: The bare name of something Windows will run, on its own or inside a path
#: or a URL. No spaces, or `run the file evil.exe` is one name; no `.com`,
#: or every domain is one; no source files, which are the stuff of every
#: readme.
EXECUTABLE_RE = re.compile(
    r"(?<![\w\-.])([\w\-.]+\.(?:exe|dll|scr|sys|bat|cmd|ps1|vbs|vbe|jse|wsf|hta|msi|lnk|pif|cpl|jar))"
    r"(?![\w\-])",
    re.IGNORECASE,
)

#: An Ethereum address: `0x` and exactly forty hex digits. The checksum is
#: the case, and `is_eth` reads it; a transaction hash is sixty-four and is
#: not one.
ETH_RE = re.compile(r"(?<![A-Za-z0-9])(0x[0-9a-fA-F]{40})(?![A-Za-z0-9])")

#: Seventeen characters from the alphabet a VIN allows - no I, O or Q. Bare,
#: it has to carry the North American check digit; beside its label it is
#: taken as written, because Europe never required the digit.
VIN_RE = re.compile(r"(?<![A-Z0-9])([A-HJ-NPR-Z0-9]{17})(?![A-Z0-9])")
VIN_LABELLED_RE = re.compile(r"\bVIN\b[\s:.#-]*([A-HJ-NPR-Z0-9]{17})(?![A-Z0-9])")

#: Company registry numbers carry no checksum, so the label is the whole
#: warrant: a Companies House number, a SEC filer's CIK, an EU VAT id whose
#: country is one. A Polish VAT id is a NIP and is taken as that.
CRN_RE = re.compile(
    r"\b(?:Company\s+(?:No\.?|Number|Reg(?:istration)?(?:\s+(?:No\.?|Number))?)"
    r"|Companies\s+House(?:\s+(?:No\.?|Number))?|Registered\s+(?:No\.?|Number))"
    r"[\s:.#-]*(\d{8}|[A-Za-z]{2}\d{6})(?!\w)",
    re.IGNORECASE,
)
CIK_RE = re.compile(r"\bCIK\b[\s:.#-]*(\d{1,10})(?!\d)")
VAT_RE = re.compile(
    r"\bVAT(?:\s+(?:No\.?|Number|ID|Reg(?:istration)?(?:\s+(?:No\.?|Number))?))?\b"
    r"[\s:.#-]*([A-Za-z]{2}[A-Za-z0-9]{8,12})(?!\w)",
    re.IGNORECASE,
)

#: An autonomous system number, as `ASN 3356` or `AS3356`. The second
#: spelling is also a product line and a quality standard, which are not.
ASN_RE = re.compile(r"\bASN\s*[:#]?\s*(\d{1,6})(?!\d)|\bAS(\d{1,6})(?!\w)")
_NOT_AN_ASN = frozenset({"400", "9100", "9110", "9120"})

_UPPER = "A-ZÀ-ÖØ-ÞĄĆĘŁŃÓŚŹŻ"
_LOWER = "a-zß-öø-ÿąćęłńóśźż"

#: The one way a name is read out of prose: when the text itself labels it.
#: A legal form says a company, an honorific says a person, a town after a
#: postcode says an address. Recall is low by design. A capitalised pair of
#: words on its own is a name, a town and a sign-off in equal measure, and
#: is never believed.
_LEGAL_FORM = (
    r"Sp\. z o\.o\.|Sp\. j\.|Sp\. k\.|S\.K\.A\.|S\.A\.|SA|GmbH & Co\. KG|GmbH|AG"
    r"|Ltd\.?|Limited|Inc\.?|Incorporated|L\.L\.C\.|LLC|LLP|PLC|Corp\.?|Corporation"
    r"|Co\., Ltd\.?|& Co\.|B\.V\.|N\.V\.|S\.r\.l\.|S\.p\.A\.|S\.à r\.l\.|SARL|SAS"
    r"|Pty\.? Ltd\.?|Oyj|Oy|ApS|A/S|s\.r\.o\.|a\.s\.|d\.o\.o\.|OÜ|SIA|UAB|Kft\.|Zrt\."
)
ORG_RE = re.compile(rf"((?:\b[{_UPPER}][\w&'’.\-]*\s+){{1,5}}(?:{_LEGAL_FORM}))(?![\w.])")
HONORIFIC_RE = re.compile(
    rf"\b(?:Pan|Pani|Mr|Mrs|Ms|Mx|Dr|Prof|Mgr|Herr|Frau|Sir|Dame)\.?\s+"
    rf"([{_UPPER}][{_LOWER}{_UPPER}'\-]+(?:\s+[{_UPPER}][{_LOWER}'\-]+){{1,2}})(?![\w'])"
)
POSTCODE_RE = re.compile(
    rf"\b(\d{{2}}-\d{{3}})\s+([{_UPPER}][{_LOWER}]+(?:[\s\-][{_UPPER}][{_LOWER}]+)*)\b"
    r"|\b([A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})\b"
)

_DEC = r"[-+]?\d{1,3}(?:\.\d+)?"

#: Ordered, and the order is the precision ranking: an earlier pattern claims
#: its span so a later, looser one cannot re-read the same text.
COORDINATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("geo_uri", re.compile(rf"\bgeo:({_DEC}),\s*({_DEC})")),
    (
        "map_url",
        re.compile(
            rf"(?:/maps/@|[?&]q=|[?&]ll=|[?&]mlat=|#map=\d+/)({_DEC})[,/]\s*({_DEC})",
            re.IGNORECASE,
        ),
    ),
    (
        "dms",
        re.compile(
            r"(\d{1,3})\s*[°º]\s*(\d{1,2})\s*['′]\s*(\d{1,2}(?:\.\d+)?)?\s*[\"″]?\s*"
            r"([NnSs])[,;\s]+"
            r"(\d{1,3})\s*[°º]\s*(\d{1,2})\s*['′]\s*(\d{1,2}(?:\.\d+)?)?\s*[\"″]?\s*"
            r"([EeWw])"
        ),
    ),
    (
        "hemisphere",
        re.compile(rf"({_DEC})\s*[°º]?\s*([NnSs])[,;\s]+({_DEC})\s*[°º]?\s*([EeWw])"),
    ),
    (
        "labelled",
        re.compile(
            # [^\w+-] rather than \W for the separators: \W is greedy over the
            # sign, so "Longitude: -74.0060" silently yielded +74.0060 - a
            # coordinate in the wrong hemisphere, which is worse than none.
            rf"(?i)\blat(?:itude)?\b[^\w+-]{{0,4}}({_DEC})"
            rf"[^\w+-]{{1,12}}?\blon(?:g|gitude)?\b[^\w+-]{{0,4}}({_DEC})"
        ),
    ),
)

_TRAILING_PUNCT = ".,;:!?'\"`)]}>"

#: A coordinate this tool decoded itself, from EXIF or an ISO 6709 atom, is not
#: a string that has to earn belief - it arrived as a pair of numbers in a field
#: that means latitude and longitude.
_TRUSTED_COORDINATE_FIELDS = frozenset({"geo"})

#: Fields that name a piece of software. This corpus is *made* of version
#: strings - `LibreOffice/24.2.7.2$Linux_X86_64` is the commonest value in it -
#: and a dotted quad or a forty-character build hash inside one is never an
#: address or a document digest. DirSifu could not make this call because it
#: reads prose; here the field name is known, so it can.
#: Fields holding a message identifier. RFC 5322 builds one to the same shape
#: as a mailbox - `<id@domain>` - so it matches every test for an address, and
#: nobody can write to it. A lead nobody can follow is worse than no lead.
_MESSAGE_ID_FIELDS = frozenset({"message-id", "in-reply-to", "references", "content-id"})
#: The headers that name a message by its id. `Content-ID` names a part of one.
_MESSAGE_FIELDS = frozenset({"message-id", "in-reply-to", "references"})
MESSAGE_ID_RE = re.compile(r"<([^<>\s@]+@[^<>\s@]+)>")

#: Fields whose value is a term from a published vocabulary. Its URI names the
#: vocabulary - what kind of picture this is - and no host anybody in a case
#: runs, so nothing in it is an identifier.
_VOCABULARY_FIELDS = frozenset({"digitalsourcetype"})

_SOFTWARE_FIELDS = frozenset(
    {
        "tool",
        "software",
        "producer",
        "creator",
        "application",
        "appversion",
        "generator",
        "encoder",
        "template",
        "lastmodifiedby",
        # XMP's own names for the same thing, plus the version properties it
        # adds. `exif:GPSVersionID` is 2.2.0.0 in almost every photograph ever
        # geotagged, and it has never been an address.
        "creatortool",
        "softwareagent",
        "gpsversionid",
        "exifversion",
        "flashpixversion",
    }
)


@dataclass(slots=True)
class Identifier:
    """One value, everywhere it was seen."""

    type: str
    value: str
    normalized: str
    count: int = 0
    files: int = 0
    private: bool | None = None
    where: list[str] = field(default_factory=list)

    #: Which corpora it was seen in. Both is the interesting answer: the value
    #: was written into the document and recorded about it, by two separate
    #: acts, and neither one alone says that.
    corpora: set[str] = field(default_factory=set)

    #: Whether one of the places was a record of how the file arrived - a
    #: download address, a referrer, a quarantine event. A value a document
    #: names that its own arrival record also names is a link rather than a
    #: coincidence, and it is the whole reason for reading content at all.
    acquired: bool = False

    #: For a digest: the address in the same scan it is the digest of. A list
    #: of hashed addresses is how advertising platforms and Gravatar carry an
    #: address without writing it, and one address in the clear beside the
    #: list names an entry of it with certainty.
    of: str | None = None

    #: How many times each file held it, by path. What `files` counts, and
    #: what says one list inside one file is most of a type - kept whole
    #: where `where` is only a sample.
    holders: dict[str, int] = field(default_factory=dict)

    #: Checkable evidence for each file relationship. Kept out of `to_dict`
    #: because the existing identifier list is a stable summary; the graph is
    #: the machine-readable shape for per-file relationships.
    evidence: dict[str, dict[IdentifierEvidence, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "type": self.type,
            "value": self.value,
            "normalized": self.normalized,
            "count": self.count,
            "files": self.files,
            "corpora": sorted(self.corpora),
            "acquired": self.acquired,
            "where": self.where,
        }
        if self.private is not None:
            data["private"] = self.private
        if self.of is not None:
            data["of"] = self.of
        return data


# --- normalisation -----------------------------------------------------------


@lru_cache(maxsize=1)
def known_tlds() -> frozenset[str]:
    """The bundled IANA top-level domain list, lowercased."""
    path = Path(__file__).parent / "data" / "tlds.txt"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset()
    return frozenset(
        line.strip().lower() for line in lines if line.strip() and not line.startswith("#")
    )


def normalize_domain(host: str) -> str | None:
    cleaned = host.strip().strip(".").lower()
    if not cleaned or "." not in cleaned:
        return None
    # `.onion` is a special-use name (RFC 7686) that no resolver answers, and
    # an address there is its own identifier type, checksum and all. It is
    # not a domain here whatever the TLD list says - and it does say so.
    if cleaned.endswith(".onion"):
        return None
    with suppress(UnicodeError, UnicodeDecodeError):
        cleaned = cleaned.encode("idna").decode("ascii")
    if cleaned.rsplit(".", 1)[-1] not in known_tlds():
        return None
    return cleaned


def normalize_url(raw: str) -> tuple[str, str | None] | None:
    """Return ``(normalised_url, host)`` or None when unusable.

    ``SplitResult`` is lazy: :func:`urlsplit` itself rarely raises, but reading
    ``.port`` parses the netloc and raises on anything that is not a number in
    range. Real data contains things like ``http://localhost:1420$``, so every
    attribute read sits inside the guard, not just the parse.
    """
    cleaned = raw.rstrip(_TRAILING_PUNCT)
    try:
        parts = urlsplit(cleaned)
        if not parts.scheme or not parts.hostname:
            return None
        host = parts.hostname.lower()
        port = parts.port
        path = parts.path.rstrip("/") if parts.path != "/" else ""
        query = parts.query
    except ValueError:
        return None
    netloc = host if port is None else f"{host}:{port}"
    normalized = f"{parts.scheme.lower()}://{netloc}{path}"
    if query:
        normalized += f"?{query}"
    return normalized, normalize_domain(host)


def _dms(degrees: str, minutes: str, seconds: str | None, hemisphere: str) -> float:
    value = float(degrees) + float(minutes) / 60 + (float(seconds) if seconds else 0.0) / 3600
    return -value if hemisphere.upper() in {"S", "W"} else value


def find_coordinates(text: str) -> list[tuple[str, float, float, str]]:
    """Every coordinate literally written in `text`, as (raw, lat, lon, pattern).

    A bare pair of decimals is never accepted, however many places it carries:
    an SVG path, a CSV of measurements and a version tuple all look exactly like
    one. A coordinate has to arrive with a hemisphere letter, a degree symbol, a
    ``geo:`` scheme, a map URL or an explicit latitude label to be believed.
    """
    found: list[tuple[str, float, float, str]] = []
    claimed: list[tuple[int, int]] = []

    for name, pattern in COORDINATE_PATTERNS:
        for match in pattern.finditer(text):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in claimed):
                continue
            groups = match.groups()
            try:
                if name == "dms":
                    latitude = _dms(groups[0], groups[1], groups[2], groups[3])
                    longitude = _dms(groups[4], groups[5], groups[6], groups[7])
                elif name == "hemisphere":
                    latitude = float(groups[0]) * (-1 if groups[1].upper() == "S" else 1)
                    longitude = float(groups[2]) * (-1 if groups[3].upper() == "W" else 1)
                else:
                    latitude, longitude = float(groups[0]), float(groups[1])
            except (TypeError, ValueError):
                continue
            if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
                continue
            # Null Island is a default, a placeholder or a parse failure.
            if abs(latitude) < 1e-9 and abs(longitude) < 1e-9:
                continue
            claimed.append(span)
            found.append((match.group(0).strip(), latitude, longitude, name))
    return found


def _hostname(name: str) -> str | None:
    """A machine name no public DNS answers for, lowercased, or None."""
    cleaned = name.strip().rstrip(".")
    if not HOSTNAME_RE.fullmatch(cleaned):
        return None
    lowered = cleaned.lower()
    if lowered in _NOT_A_HOST or re.fullmatch(r"[\d.]+", lowered):
        return None
    if normalize_domain(lowered) is not None:
        return None  # a public name is a `domain`
    return lowered


def _looks_like_version(text: str, start: int) -> bool:
    """``v1.2.3.4`` is a version string, not an address."""
    return start > 0 and text[start - 1] in "vV"


def _ssn_shaped(area: str, group: str, serial: str) -> bool:
    """Whether the three parts are ones the administration has ever issued."""
    return area not in {"000", "666"} and area[0] != "9" and group != "00" and serial != "0000"


def _plain(name: str) -> str:
    """One spelling for one name: case and spacing folded, accents kept.

    `Kowalski, Jan` and `Jan Kowalski` stay two entries. Deciding they are one
    would be guessing, and a wrong merge is worse than a duplicate.
    """
    return " ".join(name.strip().strip("\"'").split()).casefold()


def normalize_name(name: str) -> str:
    """The public normalization shared by person nodes in the graph."""
    return _plain(name)


def _names(value: str) -> Iterator[str]:
    """The names in a field, which XMP and Office write `;`-separated."""
    for part in value.split(";"):
        name = part.strip().strip("\"'")
        plain = _plain(name)
        if len(plain) < 2 or plain in _NOBODY or not any(char.isalpha() for char in plain):
            continue
        if _HEX_BLOB_RE.fullmatch(plain):
            continue  # a device id or a digest where a name should go
        if EMAIL_RE.fullmatch(name):
            continue  # already an email, and naming it twice says nothing new
        yield name


def _profile(url: str) -> tuple[str, str] | None:
    """(platform, user) if `url` is somebody's page on a platform this knows."""
    try:
        parts = urlsplit(url.rstrip(_TRAILING_PUNCT))
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    for prefix in ("www.", "m.", "mobile."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    platform = _PROFILE_HOSTS.get(host)
    if platform is None:
        return None
    match = _PROFILE_PATH[platform].match(parts.path)
    if match is None or match.group(1).lower() in _NOT_A_HANDLE:
        return None
    return platform, match.group(1)


# --- the corpus --------------------------------------------------------------


def _texts(
    records: list[FileRecord], *, content: bool = False, metadata: bool = True
) -> Iterator[_Text]:
    """Yield every string a scan can search, and where each one came from.

    The field name travels with the value because an identifier without its
    source is a lead nobody can check.

    `metadata` is what the files record about themselves and what the machine
    recorded about them; it was already in hand. `content` is what the
    documents say, and costs an open, a decode and a parse per file.
    """
    if content:
        # Imported here rather than at the top: reading bodies pulls in the
        # container readers, and a scan that was not asked for them should not
        # pay to import them.
        from .sources.content import read_passages
    for record in records:
        name = Path(record.path).name
        for found in record.evidence if metadata else ():
            arrival = category(found) == ORIGIN
            source = source_label(found)
            for label, value in (
                ("url", found.url),
                ("referrer", found.referrer),
                ("command", found.command),
                ("tool", found.tool),
                ("note", found.note),
                ("geo", found.geo),
                ("location", found.location),
            ):
                if value:
                    yield _Text(
                        name,
                        record.path,
                        source,
                        label,
                        value,
                        IN_METADATA,
                        arrival,
                        found.source,
                        category(found),
                        found.matched_by,
                        found.at,
                    )
            for label, value in found.fields.items():
                if value:
                    yield _Text(
                        name,
                        record.path,
                        source,
                        label,
                        str(value),
                        IN_METADATA,
                        arrival,
                        found.source,
                        category(found),
                        found.matched_by,
                        found.at,
                    )
        if content:
            # One yield per passage rather than one per file. Scanning them
            # apart is what lets a value carry the line, slide or chapter it
            # was on, and it costs about a fifth more than scanning the
            # document as one string.
            for passage in read_passages(Path(record.path)) or ():
                yield _Text(
                    name,
                    record.path,
                    CONTENT_SOURCE,
                    passage.place,
                    passage.text,
                    IN_CONTENT,
                    False,
                    CONTENT_SOURCE,
                    None,
                    None,
                    None,
                )


def extract(
    records: list[FileRecord], *, content: bool = False, metadata: bool = True
) -> list[Identifier]:
    """Every identifier in what the scan read, deduplicated across files.

    `metadata` is the corpus of what the files record about themselves,
    `content` the corpus of what they say. The two are kept apart on each
    entry rather than merged, so a reader can tell a name in a document from a
    name in a download record - and see where one value is both.
    """
    found: dict[tuple[str, str], Identifier] = {}

    for source in _texts(records, content=content, metadata=metadata):
        place = f"{source.file}{PLACE}{source.source}{PLACE}{source.where}"
        for family, raw, normalized, private in _scan(source.text, source.where):
            key = (family, normalized)
            entry = found.get(key)
            if entry is None:
                entry = Identifier(type=family, value=raw, normalized=normalized, private=private)
                found[key] = entry
            entry.count += 1
            entry.holders[source.path] = entry.holders.get(source.path, 0) + 1
            entry.corpora.add(source.corpus)
            entry.acquired = entry.acquired or source.acquired
            evidence = IdentifierEvidence(
                source=source.source_id,
                category=source.category,
                match=source.match,
                place=f"{source.source}{PLACE}{source.where}",
                corpus=source.corpus,
                at=source.at,
            )
            places = entry.evidence.setdefault(source.path, {})
            if evidence in places or len(places) < MAX_RELATION_PLACES:
                places[evidence] = places.get(evidence, 0) + 1
            if place not in entry.where:
                if len(entry.where) < MAX_SAMPLES:
                    entry.where.append(place)

    for entry in found.values():
        entry.files = len(entry.holders)

    # A digest that is the digest of an address seen in the same scan is that
    # address, named twice: once hashed, once in the clear. Equality of the
    # digest is certain, so this is the one link here that involves no guess.
    for address in [entry.normalized for entry in found.values() if entry.type == "email"]:
        encoded = address.encode("utf-8")
        for kind, digest in (
            ("md5", hashlib.md5(encoded, usedforsecurity=False).hexdigest()),
            ("sha1", hashlib.sha1(encoded, usedforsecurity=False).hexdigest()),
            ("sha256", hashlib.sha256(encoded).hexdigest()),
            ("sha512", hashlib.sha512(encoded).hexdigest()),
        ):
            hashed = found.get((kind, digest))
            if hashed is not None:
                hashed.of = address

    return sorted(found.values(), key=lambda i: (i.type, -i.count, i.normalized))


def _scan(text: str, where: str) -> Iterator[tuple[str, str, str, bool | None]]:
    """Yield (type, raw, normalized, private) for one value."""
    if where.lower().rpartition(":")[2] in _VOCABULARY_FIELDS:
        return
    hosts: set[str] = set()

    identifier = where.lower().rpartition(":")[2] in _MESSAGE_ID_FIELDS

    # A reply names the message it answers, so one id seen in two saved
    # messages is the thread between them. The host is not case-sensitive.
    if where.lower().rpartition(":")[2] in _MESSAGE_FIELDS:
        for match in MESSAGE_ID_RE.finditer(text):
            mail_local, mail_host = match.group(1).rsplit("@", 1)
            yield "message_id", match.group(0), f"<{mail_local}@{mail_host.lower()}>", None

    # Who the file says made it: read from the name of the field, never from
    # what the text looks like.
    named = where.lower()
    if named in _PERSON_FIELDS:
        for person in _names(text):
            yield "person", person, _plain(person), None
    elif named in _MAILBOX_FIELDS:
        for display, _address in getaddresses([text]):
            for person in _names(display):
                yield "person", person, _plain(person), None
    elif named in _ORG_FIELDS:
        for organisation in _names(text):
            yield "org", organisation, _plain(organisation), None

    if named in _HOSTNAME_FIELDS and (machine := _hostname(text)):
        yield "hostname", text.strip(), machine, None

    for match in USER_DIR_RE.finditer(text):
        login = match.group(1)
        if login.lower() not in _SHARED_HOMES:
            yield "handle", f"home:{login}", f"home:{login.lower()}", None

    for match in EMAIL_RE.finditer(text):
        host = normalize_domain(match.group(1))
        if host is None:
            continue  # unknown TLD: almost always a false positive
        # The domain is still worth having: a message id names the host that
        # minted it, which is a real fact about where the message was written.
        if not identifier:
            yield "email", match.group(0), match.group(0).lower(), None
        hosts.add(host)

    for match in URL_RE.finditer(text):
        parsed = normalize_url(match.group(0))
        if parsed is None:
            continue
        normalized, host = parsed
        yield "url", match.group(0).rstrip(_TRAILING_PUNCT), normalized, None
        if host:
            hosts.add(host)
        profile = _profile(match.group(0))
        if profile is not None:
            platform, user = profile
            yield "handle", f"{platform}:{user}", f"{platform}:{user.lower()}", None

    # XMP writes `pdf:Producer` where a PDF writes `Producer`, so the namespace
    # comes off before the name is looked up.
    software = where.lower().rpartition(":")[2] in _SOFTWARE_FIELDS

    for match in IPV4_RE.finditer(text):
        if software or _looks_like_version(text, match.start(1)):
            continue
        try:
            address = ipaddress.IPv4Address(match.group(1))
        except ipaddress.AddressValueError:
            continue
        reserved = address.is_private or address.is_reserved or address.is_loopback
        yield "ipv4", match.group(1), str(address), bool(reserved)

    for raw, latitude, longitude, _pattern in _coordinates(text, where):
        # Five decimal places is about a metre, so two renderings of one fix
        # collapse together while two genuinely different fixes stay apart.
        yield "geo", raw, f"{latitude:.5f},{longitude:.5f}", None

    for match in HASH_RE.finditer(text):
        if software:
            continue  # a build id, not a digest of anything a case cares about
        raw = match.group(1)
        kind = {32: "md5", 40: "sha1", 64: "sha256", 128: "sha512"}[len(raw)]
        yield kind, raw, raw.lower(), None

    for match in COLON_DIGEST_RE.finditer(text):
        if software:
            continue
        digest = match.group(1).replace(":", "").lower()
        kind = {32: "md5", 40: "sha1", 64: "sha256"}[len(digest)]
        yield kind, match.group(1), digest, None

    for pattern in (IPV6_FULL_RE, IPV6_BRACKET_RE):
        for match in pattern.finditer(text):
            try:
                address6 = ipaddress.IPv6Address(match.group(1))
            except ipaddress.AddressValueError:
                continue
            reserved6 = (
                address6.is_private
                or address6.is_reserved
                or address6.is_loopback
                or address6.is_link_local
            )
            yield "ipv6", match.group(1), str(address6), bool(reserved6)

    for match in CVE_RE.finditer(text):
        yield "cve", match.group(1), match.group(1).upper(), None

    for match in CWE_RE.finditer(text):
        yield "cwe", match.group(1), match.group(1).upper(), None

    for match in GHSA_RE.finditer(text):
        yield "ghsa", match.group(1), "GHSA" + match.group(1)[4:].lower(), None

    for match in REGISTRY_RE.finditer(text):
        hive = match.group(1).lower()
        key = _HIVES.get(hive, hive) + match.group(2).rstrip(_TRAILING_PUNCT).casefold()
        yield "registry", match.group(0).rstrip(_TRAILING_PUNCT), key, None

    for match in PATH_RE.finditer(text):
        location = match.group(1).rstrip(_TRAILING_PUNCT)
        # A bare drive or variable - `C:\`, `%TEMP%\` - is a place, not a file.
        if location.rstrip("\\").count("\\") == 0:
            continue
        yield "path", location, location.casefold(), None
        if location.startswith("\\\\"):
            share_host = location[2:].split("\\", 1)[0]
            if machine := _hostname(share_host):
                yield "hostname", share_host, machine, None
            elif public_host := normalize_domain(share_host):
                hosts.add(public_host)

    for match in EXECUTABLE_RE.finditer(text):
        yield "executable", match.group(1), match.group(1).casefold(), None

    # The self-checking values. A wallet address is believed wherever it
    # stands; the tax numbers only beside their label, see the patterns.
    for match in LEGACY_ADDRESS_RE.finditer(text):
        address_version = base58check_version(match.group(1))
        if address_version in (0x00, 0x05):
            yield "btc", match.group(1), match.group(1), None
        elif address_version in (0x30, 0x32):
            yield "ltc", match.group(1), match.group(1), None
        elif address_version in (0x1E, 0x16):
            yield "doge", match.group(1), match.group(1), None

    for match in BTC_BECH32_RE.finditer(text):
        if bech32_version(match.group(1)) is not None:
            yield "btc", match.group(1), match.group(1).lower(), None

    for match in LTC_BECH32_RE.finditer(text):
        if bech32_version(match.group(1), "ltc") is not None:
            yield "ltc", match.group(1), match.group(1).lower(), None

    for match in CASHADDR_RE.finditer(text):
        if is_cashaddr(match.group(1)):
            cash_body = match.group(1).lower().rpartition(":")[2]
            yield "bch", match.group(1), f"bitcoincash:{cash_body}", None

    for match in MONERO_RE.finditer(text):
        if is_monero(match.group(1)):
            yield "xmr", match.group(1), match.group(1), None

    for match in IBAN_RE.finditer(text):
        if is_iban(match.group(1)):
            yield "iban", match.group(1), "".join(match.group(1).split()), None

    for match in ETH_RE.finditer(text):
        if is_eth(match.group(1)):
            yield "eth", match.group(1), match.group(1).lower(), None

    for match in VIN_LABELLED_RE.finditer(text):
        yield "vin", match.group(1), match.group(1), None

    for match in VIN_RE.finditer(text):
        if is_vin(match.group(1)):
            yield "vin", match.group(1), match.group(1), None

    for pattern in (NIP_LABELLED_RE, NIP_PREFIXED_RE):
        for match in pattern.finditer(text):
            digits = re.sub(r"\D", "", match.group(1))
            if is_nip(digits):
                yield "nip", match.group(1), digits, None

    for match in REGON_RE.finditer(text):
        if is_regon(match.group(1)):
            yield "regon", match.group(1), match.group(1), None

    for match in ONION_RE.finditer(text):
        label = match.group(1).lower()
        if is_onion(label):
            yield "onion", match.group(0), f"{label}.onion", None

    for match in MAC_RE.finditer(text):
        hardware = match.group(1).lower().replace("-", ":")
        if hardware not in _NOT_A_DEVICE:
            yield "mac", match.group(1), hardware, None

    for match in SID_RE.finditer(text):
        yield "sid", match.group(1), match.group(1), None

    for match in BIC_RE.finditer(text):
        code = match.group(1).upper()
        if code[4:6].lower() in known_tlds():
            yield "bic", match.group(1), code, None

    for kind, pattern, group in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            handle = f"{kind} {fingerprint(match.group(group))}"
            yield "secret", handle, handle, None

    for _ in PRIVATE_KEY_RE.finditer(text):
        yield "secret", PRIVATE_KEY, PRIVATE_KEY, None

    for match in ORG_RE.finditer(text):
        organisation = match.group(1).strip()
        yield "org", organisation, _plain(organisation).rstrip("."), None

    for match in HONORIFIC_RE.finditer(text):
        yield "person", match.group(1), _plain(match.group(1)), None

    for match in POSTCODE_RE.finditer(text):
        place = f"{match.group(1)} {match.group(2)}" if match.group(1) else match.group(3)
        yield "postcode", place, _plain(place), None

    for match in SSN_RE.finditer(text):
        if _ssn_shaped(*match.groups()):
            handle = fingerprint("".join(match.groups()))
            yield "ssn", handle, handle, None

    for match in EIN_RE.finditer(text):
        if match.group(1) in _EIN_PREFIXES:
            number = f"{match.group(1)}-{match.group(2)}"
            yield "ein", number, number, None

    for match in ABA_RE.finditer(text):
        if is_aba(match.group(1)):
            yield "aba", match.group(1), match.group(1), None

    for match in CRN_RE.finditer(text):
        yield "crn", match.group(1), match.group(1).upper(), None

    for match in CIK_RE.finditer(text):
        yield "cik", match.group(1), str(int(match.group(1))), None

    for match in VAT_RE.finditer(text):
        code = match.group(1).upper()
        country = code[:2].lower()
        if country != "pl" and country in known_tlds():
            yield "vat", match.group(1), code, None

    for match in ASN_RE.finditer(text):
        number = next(group for group in match.groups() if group)
        if number not in _NOT_AN_ASN:
            yield "asn", match.group(0), f"AS{int(number)}", None

    for match in TRACKER_RE.finditer(text):
        tag = match.group(1)
        lowered = tag.lower()
        folded = lowered.removeprefix("ca-") if lowered.startswith(("ca-pub-", "pub-")) else tag
        yield "tracker", tag, folded, None

    for match in GA4_RE.finditer(text):
        yield "tracker", match.group(1), match.group(1), None

    for service, pattern in ANCHORED_TRACKERS:
        for match in pattern.finditer(text):
            tag = next(group for group in match.groups() if group)
            yield "tracker", f"{service}:{tag}", f"{service}:{tag.lower()}", None

    # Domains harvested from URLs and emails are certain. Bare tokens have to
    # clear the TLD list and not look like a file name.
    for host in sorted(hosts):
        yield "domain", host, host, None

    for match in DOMAIN_RE.finditer(text):
        candidate = match.group(1)
        if FILE_LIKE_RE.match(candidate):
            continue
        host = normalize_domain(candidate)
        if host is None or host in hosts:
            continue
        yield "domain", candidate, host, None


def _coordinates(text: str, where: str) -> list[tuple[str, float, float, str]]:
    if where in _TRUSTED_COORDINATE_FIELDS:
        parts = text.split(",")
        if len(parts) == 2:
            try:
                latitude, longitude = float(parts[0]), float(parts[1])
            except ValueError:
                return []
            if abs(latitude) > 1e-9 or abs(longitude) > 1e-9:
                return [(text, latitude, longitude, "decoded")]
        return []
    return find_coordinates(text)
