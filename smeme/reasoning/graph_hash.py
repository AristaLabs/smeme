"""Canonical fingerprint of a ``DTGraph`` for compile cache invalidation (hash of graph JSON)."""

from __future__ import annotations

import hashlib
import json

from smeme.qnr.models import DTGraph


def canonical_graph_hash(graph: DTGraph) -> str:
    """SHA-256 of JSON-serialized graph with sorted keys (stable across dumps)."""
    payload = graph.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
