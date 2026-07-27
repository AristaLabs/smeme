"""D025 deploy-time artifact identity (v1 preimage) and evaluation theory stamps."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from smeme.core.models import ReasoningCompiledArtifact
from smeme.reasoning.evidence_contract import hash_contract

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_IDENTITY_FORMAT_VERSION = 1


class ArtifactIntegrityError(ValueError):
    """Stored artifact bytes cannot satisfy the v1 identity preimage."""


def canonical_json_bytes(value: Any) -> bytes:
    """Canonical UTF-8 JSON bytes for identity digests (sort_keys, compact)."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _require_hex64(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not _HEX64.fullmatch(value):
        message = f"{name} must be 64 lower-case hex digits"
        raise ArtifactIntegrityError(message)
    return value


def compute_ir_hash_v1(ir_json: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(ir_json)).hexdigest()


def build_artifact_identity_v1(
    *,
    decision_tree_id: UUID,
    graph_hash: str,
    ir_format_version: int,
    ir_hash: str,
    compiler_version: str,
    cevi_contract_hash: str | None,
    research_corpus_hash: str | None,
) -> dict[str, Any]:
    return {
        "artifact_identity_format_version": _ARTIFACT_IDENTITY_FORMAT_VERSION,
        "compiler_version": compiler_version,
        "decision_tree_id": str(decision_tree_id).lower(),
        "graph_hash": _require_hex64("graph_hash", graph_hash),
        "ir_format_version": ir_format_version,
        "ir_hash": _require_hex64("ir_hash", ir_hash),
        "cevi_contract_hash": _require_hex64("cevi_contract_hash", cevi_contract_hash),
        "research_corpus_hash": _require_hex64("research_corpus_hash", research_corpus_hash),
    }


def canonical_artifact_identity_bytes_v1(identity: dict[str, Any]) -> bytes:
    return canonical_json_bytes(identity)


def compute_artifact_hash_v1(identity: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_artifact_identity_bytes_v1(identity)).hexdigest()


def _validate_stored_contract_hash(
    cevi_contract_json: dict[str, Any] | None,
    cevi_contract_hash: str | None,
) -> str | None:
    if cevi_contract_json is None:
        if cevi_contract_hash is not None:
            raise ArtifactIntegrityError("cevi_contract_hash without contract JSON")
        return None
    expected = hash_contract(cevi_contract_json)
    if cevi_contract_hash is None or expected != cevi_contract_hash:
        raise ArtifactIntegrityError("cevi_contract_hash mismatch")
    return cevi_contract_hash


def compute_identity_fields_from_stored_artifact(
    artifact: ReasoningCompiledArtifact,
) -> tuple[str, str]:
    """Derive ``ir_hash`` and ``artifact_hash`` from persisted artifact bytes only."""
    ir_hash = compute_ir_hash_v1(artifact.ir_json)
    contract_hash = _validate_stored_contract_hash(
        artifact.cevi_contract_json,
        artifact.cevi_contract_hash,
    )
    research_hash = _require_hex64("research_corpus_hash", artifact.research_corpus_hash)
    identity = build_artifact_identity_v1(
        decision_tree_id=artifact.decision_tree_id,
        graph_hash=artifact.graph_hash,
        ir_format_version=artifact.ir_format_version,
        ir_hash=ir_hash,
        compiler_version=artifact.compiler_version,
        cevi_contract_hash=contract_hash,
        research_corpus_hash=research_hash,
    )
    return ir_hash, compute_artifact_hash_v1(identity)


def theory_stamp_from_artifact(artifact: ReasoningCompiledArtifact) -> dict[str, Any]:
    """Blinded report provenance (D025); no IR or graph topology."""
    compiled_at = artifact.compiled_at
    if isinstance(compiled_at, datetime):
        compiled_at_wire = compiled_at.isoformat()
        if compiled_at_wire.endswith("+00:00"):
            compiled_at_wire = compiled_at_wire.replace("+00:00", "Z")
    else:
        compiled_at_wire = str(compiled_at)
    return {
        "decision_tree_id": str(artifact.decision_tree_id).lower(),
        "artifact_id": str(artifact.id).lower(),
        "artifact_version": artifact.artifact_version,
        "artifact_hash": artifact.artifact_hash,
        "graph_hash": artifact.graph_hash,
        "compiled_at": compiled_at_wire,
    }
