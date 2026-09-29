"""Redaction for output that is about to leave the machine.

`filegrail` reads browser and shell history, so its own output is sensitive in a
way the scanned files are not: a URL can carry `?api_key=`, a session token or
a password reset link, and a recorded command can carry a credential in an
argument. Printing that into a bug report or a shared JSON file is the one
mistake here that cannot be undone.

The approach is biased hard towards precision, because a false positive removes
real evidence from a provenance report and makes the redaction count untrustworthy.
Redacted values are replaced by a short fingerprint of the value rather than a
flat marker, so two occurrences of the same secret stay visibly linked without
the secret itself being recoverable.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PLACEHOLDER = "[REDACTED:{kind}:{fingerprint}]"

#: Query parameters whose value is a credential rather than a search term.
SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "auth_token",
        "code",
        "credential",
        "id_token",
        "key",
        "password",
        "passwd",
        "pwd",
        "refresh_token",
        "secret",
        "session",
        "sessionid",
        "sig",
        "signature",
        "token",
        "x-api-key",
    }
)

#: Ordered: earlier patterns win, so a token inside an Authorization header is
#: redacted once, by the header rule, rather than twice.
PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    # The armour says what was there and stays; the body is the secret. A key
    # pasted into a note arrives as one multi-line value, and a key on one
    # line arrives without its footer, so the body is whatever base64 - or
    # `Proc-Type:` header lines - follows the opening line, and nothing more.
    (
        "private_key",
        re.compile(
            r"(-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----)"
            r"((?:\s*(?:[A-Za-z0-9+/=]{8,}|[A-Za-z-]+: [^\n]+))+)"
        ),
        2,
    ),
    (
        "auth_header",
        re.compile(
            r"(?i)\b(authorization\s*[:=]\s*[\"']?(?:bearer|basic|token)\s+)"
            r"([A-Za-z0-9._\-+/=]{8,})"
        ),
        2,
    ),
    (
        "url_credentials",
        re.compile(r"\b([a-z][a-z0-9+.\-]*://[^/\s:@]+:)([^/\s@\"']{3,})(?=@)"),
        2,
    ),
    ("aws_access_key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), 1),
    (
        "vendor_token",
        re.compile(
            r"\b(sk-[A-Za-z0-9_\-]{16,}"
            r"|[sr]k_(?:live|test)_[A-Za-z0-9]{16,}"
            r"|ghp_[A-Za-z0-9]{20,}"
            r"|gho_[A-Za-z0-9]{20,}"
            r"|github_pat_[A-Za-z0-9_]{20,}"
            r"|xox[baprs]-[A-Za-z0-9\-]{10,}"
            r"|AIza[0-9A-Za-z_\-]{30,}"
            r"|glpat-[A-Za-z0-9_\-]{15,}"
            r"|npm_[A-Za-z0-9]{36}"
            r"|hf_[A-Za-z0-9]{30,}"
            r"|shp(?:at|ss|ca|pa)_[0-9a-f]{32}"
            r"|SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}"
            r"|\d{8,10}:[A-Za-z0-9_\-]{35}"
            r"|SK[0-9a-f]{32})"
        ),
        1,
    ),
    (
        "jwt",
        re.compile(r"\b(eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,})"),
        1,
    ),
    (
        "argument",
        re.compile(
            r"(?i)(--?(?:pass(?:word)?|secret|token|api[_-]?key|apikey"
            r"|credentials?|private[_-]?key|access[_-]?key|auth)[\w.\-]*[=\s]+[\"']?)"
            r"([^\s\"',;]{4,})"
        ),
        2,
    ),
)

#: Shortest value worth treating as a credential. Real secrets are not 3 chars.
MIN_SECRET_LENGTH = 8

#: Documentation placeholders: ``<token>``, ``${API_KEY}``, ``{{secret}}``.
_PLACEHOLDER_PREFIXES = ("<", "${", "{{", "$(", "%(", "%{")

#: Values that sit in a credential-shaped position but carry no secret.
_ALLOWLIST = frozenset(
    {
        "true",
        "false",
        "null",
        "none",
        "nil",
        "yes",
        "no",
        "changeme",
        "redacted",
        "example",
        "placeholder",
        "todo",
        "tbd",
        "required",
        "optional",
        "unset",
        "empty",
        "default",
        "disabled",
        "enabled",
        "env",
        "environment",
        "vault",
        "keyring",
        "stdin",
        "prompt",
    }
)

#: Filler such as ``***``, ``xxxx``, ``----``.
_FILLER_CHARS = frozenset(".*_-x# ")


def fingerprint(secret: str) -> str:
    """Correlatable, non-reversible handle. Never the value, never a prefix."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


def looks_like_secret(value: str) -> bool:
    """Shape gate for values matched by their surrounding name, not their form."""
    candidate = value.strip().strip("\"'`")
    if len(candidate) < MIN_SECRET_LENGTH:
        return False
    if candidate.lower() in _ALLOWLIST:
        return False
    if candidate.startswith(_PLACEHOLDER_PREFIXES):
        return False
    if set(candidate) <= _FILLER_CHARS:
        return False
    if candidate.isalpha():
        # A single prose word. A real credential is essentially never one.
        capitalised = candidate[0].isupper() and candidate[1:].islower()
        if candidate.islower() or candidate.isupper() or capitalised:
            return False
    return True


def _placeholder(kind: str, secret: str) -> str:
    return PLACEHOLDER.format(kind=kind, fingerprint=fingerprint(secret))


def redact_url(value: str) -> str:
    """Strip credential-bearing query parameters, keeping the URL readable.

    The path and host are the provenance; only the parameters that carry
    credentials are replaced, so the record still says where the file came from.
    """
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.query:
        return value

    changed = False
    pairs = []
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in SENSITIVE_QUERY_KEYS and item:
            pairs.append((key, _placeholder("query", item)))
            changed = True
        else:
            pairs.append((key, item))

    if not changed:
        return value
    # Keep the placeholder's own punctuation unescaped so the output stays legible.
    return urlunsplit(parts._replace(query=urlencode(pairs, safe="[]:")))


def redact_text(value: str) -> str:
    """Replace credentials found anywhere in a line of output."""
    if not value:
        return value

    for kind, pattern, group in PATTERNS:

        def replace(match: re.Match[str], _kind: str = kind, _group: int = group) -> str:
            secret = match.group(_group)
            if _kind == "argument" and not looks_like_secret(secret):
                return match.group(0)
            if secret.startswith("[REDACTED:"):
                return match.group(0)
            prefix = match.group(1) if _group == 2 else ""
            return prefix + _placeholder(_kind, secret)

        value = pattern.sub(replace, value)
    return value
