"""Helpers for **PublishedEvidenceContract** (Phase 2+) and ``cevi_contract_hash`` storage.

Invariants: ``evidence_contract.md`` §4 — canonical JSON and ``cevi_contract_hash`` (sorted keys,
compact separators, UTF-8, SHA-256 hexdigest), same stability discipline as
:func:`smeme.reasoning.graph_hash.canonical_graph_hash`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

__all__ = [
    "canonical_json_dumps",
    "hash_contract",
    "sha256_hex",
]


def canonical_json_dumps(obj: Any) -> str:
    """Return stable JSON: sorted keys at every object level, no insignificant whitespace.

    Must match the rule used for :func:`hash_contract` and ``cevi_contract_hash`` in docs
    (``separators=(",", ":")`` with ``utf-8`` for hashing). ``ensure_ascii=False`` matches
    :func:`smeme.reasoning.graph_hash.canonical_graph_hash`.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_hex(data: str | bytes) -> str:
    """64-character lowercase hex SHA-256 of UTF-8 *bytes* (or raw *bytes*)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hash_contract(contract: Mapping[str, Any]) -> str:
    """``sha256_hex(utf-8 bytes of canonical_json_dumps(contract))``.

    Use for any stored ``cevi_contract_json`` (including empty or IR-only v1). When the product
    stores *no* contract, keep both ``cevi_contract_json`` and ``cevi_contract_hash`` null; do
    not call this with a missing contract.
    """
    return sha256_hex(canonical_json_dumps(dict(contract)))
