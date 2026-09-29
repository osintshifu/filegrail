"""Self-checking identifiers: a value that carries its own checksum.

These are the only detectors that can be sure of a match without a region
hint or a surrounding label - the number proves itself. Each test names a
published vector, so a wrong table or a mistyped weight fails here first.
"""

from __future__ import annotations

from filegrail.checksums import bech32_version, is_base58check, is_iban, is_nip, is_regon

# --- bitcoin ------------------------------------------------------------------


def test_the_genesis_address_passes_base58check():
    assert is_base58check("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")


def test_a_pay_to_script_address_passes_base58check():
    assert is_base58check("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")


def test_one_changed_character_fails_base58check():
    assert not is_base58check("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb")


def test_a_character_outside_the_alphabet_fails_base58check():
    """`0`, `O`, `I` and `l` are left out of base58 on purpose."""
    assert not is_base58check("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf0a")


def test_a_segwit_v0_address_is_bech32():
    assert bech32_version("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4") == 0


def test_a_taproot_address_is_bech32m():
    assert bech32_version("bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0") == 1


def test_bech32_is_case_insensitive():
    assert bech32_version("BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4") == 0


def test_a_broken_bech32_checksum_is_nothing():
    assert bech32_version("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5") is None


def test_a_testnet_prefix_is_nothing():
    assert bech32_version("tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx") is None


# --- iban ---------------------------------------------------------------------


def test_the_published_examples_pass_mod_97():
    assert is_iban("GB82WEST12345698765432")
    assert is_iban("PL61109010140000071219812874")
    assert is_iban("DE89370400440532013000")


def test_one_changed_digit_fails_mod_97():
    assert not is_iban("GB82WEST12345698765433")


def test_an_unknown_country_is_not_an_iban():
    assert not is_iban("XX82WEST12345698765432")


def test_the_wrong_length_for_its_country_is_not_an_iban():
    """A German account is 22 characters; one digit short cannot be one."""
    assert not is_iban("DE8937040044053201300")


# --- polish tax and statistical numbers ----------------------------------------


def test_a_nip_with_a_valid_check_digit():
    assert is_nip("5260250274")


def test_a_nip_with_a_wrong_check_digit():
    assert not is_nip("5260250275")


def test_a_nip_whose_weighted_sum_leaves_ten_is_never_valid():
    """The remainder 10 has no digit to land on, so no check digit rescues it."""
    for check in "0123456789":
        assert not is_nip("000000200" + check)


def test_a_nine_digit_regon():
    assert is_regon("123456785")


def test_a_fourteen_digit_regon():
    assert is_regon("12345678500010")


def test_a_regon_with_a_wrong_check_digit():
    assert not is_regon("123456786")


def test_a_regon_of_the_wrong_length_is_nothing():
    assert not is_regon("1234567")


# --- ethereum -----------------------------------------------------------------


def test_keccak_matches_the_published_digest_and_eip55_reads_it():
    from filegrail.checksums import is_eth, keccak256

    assert (
        keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )
    assert is_eth("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed")
    assert not is_eth("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD")
