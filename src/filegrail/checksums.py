"""Checksums that let a value vouch for itself.

Every detector in `identify` has to decide whether a run of characters is an
identifier or a coincidence, and most of them decide it from shape and context:
a known TLD, a hemisphere letter, the name of the field. The values here carry
the decision inside them. A wallet address, a bank account and a tax number
each end in digits computed from the rest, so one changed character fails, and
a match can be believed without a region hint or a surrounding label.

That certainty has a floor. A check digit in base ten passes one random number
in ten; the Polish numbers, taken modulo eleven, pass about one in eleven. The
Bitcoin checksums are thirty bits and never pass by accident. The callers know
which is which: the tax numbers are only taken beside the label that names
them, and the addresses are taken wherever they stand.

Everything here is the standard library. The Base58Check digest is two rounds
of SHA-256; the Bech32 polynomial is thirty lines of arithmetic; mod-97 is a
long division.
"""

from __future__ import annotations

import base64
import hashlib

_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

_BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONSTANT = 1
_BECH32M_CONSTANT = 0x2BC830A3
_BECH32_GENERATOR = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)

#: The one human-readable part a mainnet address can have.
_MAINNET = "bc"

#: The length an IBAN has in each country that has adopted the standard, from
#: the ISO 13616 registry. A country that is not here has no IBAN, and a
#: number of the wrong length for its country cannot be one however its
#: check digits come out.
_IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16,
    "BG": 22, "BH": 22, "BI": 27, "BR": 29, "BY": 28, "CH": 21, "CR": 22,
    "CY": 28, "CZ": 24, "DE": 22, "DJ": 27, "DK": 18, "DO": 28, "EE": 20,
    "EG": 29, "ES": 24, "FI": 18, "FK": 18, "FO": 18, "FR": 27, "GB": 22,
    "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HR": 21, "HU": 28,
    "IE": 22, "IL": 23, "IQ": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30,
    "KZ": 20, "LB": 28, "LC": 32, "LI": 21, "LT": 20, "LU": 20, "LV": 21,
    "LY": 25, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MN": 20, "MR": 27,
    "MT": 31, "MU": 30, "NI": 28, "NL": 18, "NO": 15, "OM": 23, "PK": 24,
    "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "RU": 33,
    "SA": 24, "SC": 31, "SD": 18, "SE": 24, "SI": 19, "SK": 24, "SM": 27,
    "SO": 23, "ST": 25, "SV": 28, "TL": 23, "TN": 24, "TR": 26, "UA": 29,
    "VA": 22, "VG": 24, "XK": 20, "YE": 30,
}  # fmt: skip

_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)

_REGON_WEIGHTS = {
    9: (8, 9, 2, 3, 4, 5, 6, 7),
    14: (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8),
}


def is_base58check(text: str) -> bool:
    """Whether `text` is a 25-byte Base58Check payload whose tail is its digest."""
    return base58check_version(text) is not None


def base58check_version(text: str) -> int | None:
    """The version byte of a 25-byte Base58Check payload, or None if it is not one.

    That is the shape of a legacy or pay-to-script address: a version byte, a
    twenty-byte hash and four bytes of double SHA-256 over the rest. Bitcoin
    and the chains that copied it tell their addresses apart by that byte.
    """
    number = 0
    for char in text:
        index = _BASE58.find(char)
        if index < 0:
            return None
        number = number * 58 + index
    body = number.to_bytes((number.bit_length() + 7) // 8, "big")
    # Each leading `1` is a leading zero byte, which the integer cannot carry.
    leading = len(text) - len(text.lstrip("1"))
    raw = b"\x00" * leading + body
    if len(raw) != 25:
        return None
    digest = hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()
    return raw[0] if digest[:4] == raw[-4:] else None


def _polymod(values: list[int]) -> int:
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for bit, coefficient in enumerate(_BECH32_GENERATOR):
            if (top >> bit) & 1:
                checksum ^= coefficient
    return checksum


def bech32_version(text: str, hrp: str = _MAINNET) -> int | None:
    """The witness version of a Bech32 address under `hrp`, or None if it is not one.

    Version 0 addresses (``bc1q``) use the original Bech32 checksum; every
    later version, Taproot's ``bc1p`` among them, uses Bech32m. Mixed case is
    not an address: the specification allows all-lower or all-upper and nothing
    between, and a candidate that breaks that rule was never written by a wallet.
    """
    if text != text.lower() and text != text.upper():
        return None
    lowered = text.lower()
    prefix, separator, data = lowered.rpartition("1")
    if prefix != hrp or not separator or len(data) < 6:
        return None
    try:
        values = [_BECH32.index(char) for char in data]
    except ValueError:
        return None
    version = values[0]
    if version > 16:
        return None
    expanded = [ord(char) >> 5 for char in prefix] + [0] + [ord(char) & 31 for char in prefix]
    expected = _BECH32_CONSTANT if version == 0 else _BECH32M_CONSTANT
    if _polymod(expanded + values) != expected:
        return None
    return version


# --- bitcoin cash ---------------------------------------------------------------
#
# CashAddr is Bech32's alphabet with a forty-bit checksum of its own, computed
# over the `bitcoincash` prefix whether or not the address is written with it.

_CASHADDR_PREFIX = "bitcoincash"
_CASHADDR_GENERATOR = (0x98F2BC8E61, 0x79B76D99E2, 0xF33E5FB3C4, 0xAE2EABE2A8, 0x1E4F43E470)


def is_cashaddr(text: str) -> bool:
    """Whether `text` is a Bitcoin Cash address, prefixed or bare, whose checksum holds."""
    if text != text.lower() and text != text.upper():
        return False
    prefix, _, data = text.lower().rpartition(":")
    if prefix not in ("", _CASHADDR_PREFIX) or len(data) != 42:
        return False
    try:
        values = [_BECH32.index(char) for char in data]
    except ValueError:
        return False
    checksum = 1
    for value in [ord(char) & 31 for char in _CASHADDR_PREFIX] + [0] + values:
        top = checksum >> 35
        checksum = ((checksum & 0x07FFFFFFFF) << 5) ^ value
        for bit, coefficient in enumerate(_CASHADDR_GENERATOR):
            if (top >> bit) & 1:
                checksum ^= coefficient
    return checksum == 1


def is_iban(text: str) -> bool:
    """Whether `text`, spaces or not, is an IBAN: known country, right length, mod-97."""
    compact = "".join(text.split()).upper()
    if not compact.isascii() or not compact.isalnum():
        return False
    if _IBAN_LENGTHS.get(compact[:2]) != len(compact) or not compact[2:4].isdigit():
        return False
    rearranged = compact[4:] + compact[:4]
    return int("".join(str(int(char, 36)) for char in rearranged)) % 97 == 1


def is_nip(digits: str) -> bool:
    """Whether ten digits are a Polish tax number: weighted sum mod 11 is the last.

    A remainder of ten has no digit to land on, so no check digit rescues it.
    """
    if len(digits) != 10 or not digits.isdigit():
        return False
    remainder = sum(int(d) * w for d, w in zip(digits[:9], _NIP_WEIGHTS, strict=True)) % 11
    return remainder != 10 and remainder == int(digits[9])


def is_regon(digits: str) -> bool:
    """Whether nine or fourteen digits are a Polish statistical number.

    Same weighted sum, with a remainder of ten written as zero.
    """
    weights = _REGON_WEIGHTS.get(len(digits))
    if weights is None or not digits.isdigit():
        return False
    remainder = sum(int(d) * w for d, w in zip(digits[:-1], weights, strict=True)) % 11
    return (0 if remainder == 10 else remainder) == int(digits[-1])


def is_onion(label: str) -> bool:
    """Whether 56 base32 characters are a version 3 onion service address.

    The label decodes to a public key, two bytes of checksum and a version
    byte; the checksum is SHA3-256 over a fixed prefix, the key and the
    version. Version 2 addresses are not accepted: the network stopped
    serving them in 2021, and a sixteen-character hash has no checksum.
    """
    try:
        raw = base64.b32decode(label.upper())
    except ValueError:
        return False
    if len(raw) != 35 or raw[34] != 3:
        return False
    digest = hashlib.sha3_256(b".onion checksum" + raw[:32] + raw[34:]).digest()
    return digest[:2] == raw[32:34]


#: The first two digits a routing number can start with: Federal Reserve
#: districts, thrifts, electronic-only and traveller's cheques. Anything else
#: was never assigned.
_ABA_PREFIXES = frozenset({f"{n:02d}" for n in (*range(0, 13), *range(21, 33), *range(61, 73), 80)})


def is_aba(digits: str) -> bool:
    """Whether nine digits are a US bank routing number: prefix and 3-7-1 mod 10."""
    if len(digits) != 9 or not digits.isdigit() or digits[:2] not in _ABA_PREFIXES:
        return False
    weights = (3, 7, 1, 3, 7, 1, 3, 7, 1)
    return sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 10 == 0


# --- ethereum -------------------------------------------------------------------
#
# EIP-55 spells an address in the case its own Keccak-256 digest dictates, so
# the case is a checksum. `hashlib` has SHA-3, which is Keccak with a different
# padding byte and a different answer; the sponge itself is forty lines.

_KECCAK_ROUNDS = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)  # fmt: skip
_KECCAK_ROTATIONS = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)
_LANE = (1 << 64) - 1


def _rotate(lane: int, by: int) -> int:
    return ((lane << by) | (lane >> (64 - by))) & _LANE if by else lane


def _keccak_f(state: list[list[int]]) -> list[list[int]]:
    for constant in _KECCAK_ROUNDS:
        parity = [
            state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4] for x in range(5)
        ]
        theta = [parity[(x - 1) % 5] ^ _rotate(parity[(x + 1) % 5], 1) for x in range(5)]
        state = [[state[x][y] ^ theta[x] for y in range(5)] for x in range(5)]
        moved = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                moved[y][(2 * x + 3 * y) % 5] = _rotate(state[x][y], _KECCAK_ROTATIONS[x][y])
        state = [
            [moved[x][y] ^ ((~moved[(x + 1) % 5][y]) & moved[(x + 2) % 5][y]) for y in range(5)]
            for x in range(5)
        ]
        state[0][0] ^= constant
    return state


def keccak256(data: bytes) -> bytes:
    """Keccak-256 as Ethereum uses it: the original padding, not SHA-3's."""
    rate = 136
    padded = bytearray(data) + b"\x01"
    padded += b"\x00" * (-len(padded) % rate)
    padded[-1] |= 0x80
    state = [[0] * 5 for _ in range(5)]
    for offset in range(0, len(padded), rate):
        block = padded[offset : offset + rate]
        for i in range(rate // 8):
            state[i % 5][i // 5] ^= int.from_bytes(block[8 * i : 8 * i + 8], "little")
        state = _keccak_f(state)
    return b"".join(state[i % 5][i // 5].to_bytes(8, "little") for i in range(4))


def is_eth(text: str) -> bool:
    """Whether `0x` and forty hex digits are an Ethereum address.

    Written all in one case the address carries no checksum and is taken by
    its shape; written in mixed case it has to be the case EIP-55 dictates.
    """
    body = text[2:]
    if not text.startswith("0x") or len(body) != 40:
        return False
    if any(char not in "0123456789abcdefABCDEF" for char in body):
        return False
    if body == body.lower() or body == body.upper():
        return True
    digest = keccak256(body.lower().encode("ascii")).hex()
    return all(
        (char.upper() if int(nibble, 16) >= 8 else char.lower()) == char
        for char, nibble in zip(body, digest[:40], strict=True)
    )


# --- monero ---------------------------------------------------------------------
#
# Monero's base58 is Bitcoin's alphabet applied eight bytes at a time, so every
# block encodes to the same width, and its checksum is the first four bytes of
# the Keccak-256 above.

#: Bytes a final block holds, by how many characters encode it.
_MONERO_BLOCK = {2: 1, 3: 2, 5: 3, 6: 4, 7: 5, 9: 6, 10: 7, 11: 8}
#: The mainnet network bytes - standard, integrated, subaddress - and the
#: length each decodes to.
_MONERO_NETWORKS = {18: 69, 19: 77, 42: 69}


def is_monero(text: str) -> bool:
    """Whether `text` is a mainnet Monero address whose checksum holds."""
    raw = bytearray()
    for start in range(0, len(text), 11):
        block = text[start : start + 11]
        size = _MONERO_BLOCK.get(len(block))
        if size is None:
            return False
        number = 0
        for char in block:
            index = _BASE58.find(char)
            if index < 0:
                return False
            number = number * 58 + index
        if number >> (8 * size):
            return False
        raw += number.to_bytes(size, "big")
    if not raw or _MONERO_NETWORKS.get(raw[0]) != len(raw):
        return False
    return keccak256(bytes(raw[:-4]))[:4] == raw[-4:]


# --- vehicles -------------------------------------------------------------------

_VIN_VALUES = dict(
    zip(
        "ABCDEFGHJKLMNPRSTUVWXYZ",
        (1, 2, 3, 4, 5, 6, 7, 8, 1, 2, 3, 4, 5, 7, 9, 2, 3, 4, 5, 6, 7, 8, 9),
        strict=True,
    )
)
_VIN_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def is_vin(text: str) -> bool:
    """Whether seventeen characters carry a North American VIN check digit.

    Europe does not require the digit, so a European VIN fails here however
    real it is; the caller takes those beside a label instead.
    """
    if len(text) != 17:
        return False
    try:
        total = sum(
            (int(char) if char.isdigit() else _VIN_VALUES[char]) * weight
            for char, weight in zip(text, _VIN_WEIGHTS, strict=True)
        )
    except KeyError:
        return False
    remainder = total % 11
    return ("X" if remainder == 10 else str(remainder)) == text[8]
