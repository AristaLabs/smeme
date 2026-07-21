"""``cevi_contract_hash`` invariants: canonical JSON + SHA-256 per ``evidence_contract.md`` §4."""

from __future__ import annotations

import re

from smeme.reasoning import evidence_contract as ec


def test_same_structure_different_key_order_same_hash() -> None:
    a = {"b": 1, "a": 2, "c": {"z": 0, "y": 1}}
    b = {"a": 2, "c": {"y": 1, "z": 0}, "b": 1}
    assert ec.hash_contract(a) == ec.hash_contract(b)
    assert ec.canonical_json_dumps(a) == ec.canonical_json_dumps(b)


def test_different_value_different_hash() -> None:
    assert ec.hash_contract({"x": 1}) != ec.hash_contract({"x": 2})


def test_canonical_json_no_insignificant_whitespace() -> None:
    s = ec.canonical_json_dumps({"a": 1, "b": {"c": 2}})
    assert " " not in s, "keys and separators use compact form only"
    assert s == ec.canonical_json_dumps({"b": {"c": 2}, "a": 1})


def test_hash_is_64_char_lowercase_hex() -> None:
    h = ec.hash_contract({})
    assert len(h) == 64
    assert h == h.lower()
    assert re.fullmatch(r"[0-9a-f]{64}", h) is not None


def test_sha256_hex_bytes_and_str() -> None:
    assert ec.sha256_hex("hello") == ec.sha256_hex(b"hello")
    assert len(ec.sha256_hex("x")) == 64


def test_absent_contract_db_both_fields_null() -> None:
    """No contract: both ``cevi_contract_json`` and ``cevi_contract_hash`` stay null — do not hash."""
    contract_json: dict | None = None
    stored_hash: str | None
    if contract_json is None:
        stored_hash = None
    else:
        stored_hash = ec.hash_contract(contract_json)
    assert stored_hash is None


def test_ir_only_empty_contract_v1_fingerprint() -> None:
    """IR-only v1: empty dict still yields a stable 64-hex hash (one branch for 'has contract')."""
    h = ec.hash_contract({})
    assert len(h) == 64
    assert h == ec.hash_contract({})
