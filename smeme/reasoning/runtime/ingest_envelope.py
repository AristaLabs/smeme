"""Provenance ingest envelope: parse, caps, validate against IR (no Z3).

**Legacy ``raw_answers_json``:** If the JSON object has no ``answers`` key and no
``evidence_items`` / ``evidence_refs`` keys, the entire object is treated as the
``answers`` map (legacy flat shape). If ``evidence_items`` or ``evidence_refs`` is
present, ``answers`` is **required** (explicit provenance envelope).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from smeme.reasoning.ir.types import IR, IRNodeKind
from smeme.reasoning.runtime.canonical_facts import raw_answers_to_canonical_facts
from smeme.reasoning.runtime.ingest_codes import (
    HarnessNext,
    IngestErrorCode,
    IngestWarningCode,
    harness_next_for_ingest,
    sort_warnings,
)
from smeme.reasoning.runtime.input_validation import (
    MAX_ANSWER_KEYS,
    MAX_QUESTION_ID_LEN,
    ReasoningInputValidationError,
    _reject_ctrl,
    validate_raw_answers_for_ir,
)

# Caps for harness provenance envelope; separate from blob evaluate limits.
MAX_EVIDENCE_ITEMS = 1024
MAX_EVIDENCE_REFS_PER_QUESTION = 64
MAX_EVIDENCE_ITEM_ID_LEN = 256
MAX_EVIDENCE_SOURCE_ID_LEN = 256
MAX_EVIDENCE_EXCERPT_LEN = 8192
MAX_EVIDENCE_TITLE_LEN = 512
MAX_EVIDENCE_LOCATOR_LEN = 2048

_LOCATOR_KINDS = frozenset({"file", "url", "mcp_resource", "workspace_path", "other"})

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ID_SAFE_RE = re.compile(r"^[A-Za-z0-9_.:/#\-]+$")


@dataclass
class ParsedIngestEnvelope:
    answers: dict[str, Any]
    evidence_items: list[dict[str, Any]]
    evidence_refs: dict[str, list[str]]


class ReasoningIngestError(Exception):
    """Blocking ingest validation failure."""

    def __init__(self, code: IngestErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _iso8601_utc_z_ok(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return False
    return dt.tzinfo is not None


def parse_ingest_envelope_dict(raw: dict[str, Any]) -> ParsedIngestEnvelope:
    """Normalize top-level JSON object into answers + evidence parts.

    Raises :class:`ReasoningIngestError` on structural / cap violations.
    """
    if not isinstance(raw, dict):
        raise ReasoningIngestError(
            IngestErrorCode.ingest_malformed, "payload must be a JSON object"
        )

    has_answers = "answers" in raw
    has_evidence = "evidence_items" in raw or "evidence_refs" in raw

    if has_answers:
        answers = raw["answers"]
        if not isinstance(answers, dict):
            raise ReasoningIngestError(
                IngestErrorCode.ingest_malformed, "answers must be a JSON object"
            )
        ev_items_raw = raw.get("evidence_items", [])
        ev_refs_raw = raw.get("evidence_refs", {})
    elif has_evidence:
        raise ReasoningIngestError(
            IngestErrorCode.ingest_malformed,
            "evidence_items or evidence_refs requires an explicit answers object",
        )
    else:
        answers = dict(raw)
        ev_items_raw = []
        ev_refs_raw = {}

    if not isinstance(ev_items_raw, list):
        raise ReasoningIngestError(
            IngestErrorCode.ingest_malformed, "evidence_items must be an array"
        )
    if len(ev_items_raw) > MAX_EVIDENCE_ITEMS:
        raise ReasoningIngestError(
            IngestErrorCode.ingest_cap_exceeded,
            f"Too many evidence_items (max {MAX_EVIDENCE_ITEMS})",
        )

    evidence_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for i, it in enumerate(ev_items_raw):
        if not isinstance(it, dict):
            raise ReasoningIngestError(
                IngestErrorCode.ingest_malformed,
                f"evidence_items[{i}] must be an object",
            )
        eid = it.get("id")
        if not isinstance(eid, str) or not eid.strip():
            raise ReasoningIngestError(
                IngestErrorCode.ingest_invalid_evidence_id,
                f"evidence_items[{i}].id must be a non-empty string",
            )
        eid = eid.strip()
        if len(eid) > MAX_EVIDENCE_ITEM_ID_LEN:
            raise ReasoningIngestError(
                IngestErrorCode.ingest_invalid_evidence_id,
                "evidence item id exceeds maximum length",
            )
        _reject_ctrl(eid, field="evidence_items[].id")
        if not _ID_SAFE_RE.match(eid):
            raise ReasoningIngestError(
                IngestErrorCode.ingest_invalid_evidence_id,
                "evidence item id has invalid characters",
            )
        if eid in seen_ids:
            raise ReasoningIngestError(
                IngestErrorCode.ingest_duplicate_evidence_item_id,
                f"duplicate evidence item id: {eid!r}",
            )
        seen_ids.add(eid)

        sid = it.get("source_id")
        if sid is not None:
            if not isinstance(sid, str) or not sid.strip():
                raise ReasoningIngestError(
                    IngestErrorCode.ingest_invalid_evidence_id,
                    f"evidence_items[{i}].source_id must be a non-empty string when set",
                )
            sid = sid.strip()
            if len(sid) > MAX_EVIDENCE_SOURCE_ID_LEN:
                raise ReasoningIngestError(
                    IngestErrorCode.ingest_invalid_evidence_id,
                    "source_id exceeds maximum length",
                )
            _reject_ctrl(sid, field="source_id")

        rat = it.get("retrieved_at")
        if rat is not None:
            if not isinstance(rat, str) or not _iso8601_utc_z_ok(rat):
                raise ReasoningIngestError(
                    IngestErrorCode.ingest_invalid_timestamp,
                    f"evidence_items[{i}].retrieved_at must be ISO 8601 with timezone",
                )

        ex = it.get("excerpt")
        if ex is not None:
            if not isinstance(ex, str):
                raise ReasoningIngestError(
                    IngestErrorCode.ingest_malformed,
                    f"evidence_items[{i}].excerpt must be a string when set",
                )
            if len(ex) > MAX_EVIDENCE_EXCERPT_LEN:
                raise ReasoningIngestError(
                    IngestErrorCode.ingest_cap_exceeded,
                    "excerpt exceeds maximum length",
                )
            _reject_ctrl(ex, field="excerpt")

        title = it.get("title")
        if title is not None:
            if not isinstance(title, str) or not title.strip():
                raise ReasoningIngestError(
                    IngestErrorCode.ingest_malformed,
                    f"evidence_items[{i}].title must be a non-empty string when set",
                )
            title = title.strip()
            if len(title) > MAX_EVIDENCE_TITLE_LEN:
                raise ReasoningIngestError(
                    IngestErrorCode.ingest_cap_exceeded,
                    "title exceeds maximum length",
                )
            _reject_ctrl(title, field="title")

        locator = it.get("locator")
        if locator is not None:
            if not isinstance(locator, str) or not locator.strip():
                raise ReasoningIngestError(
                    IngestErrorCode.ingest_malformed,
                    f"evidence_items[{i}].locator must be a non-empty string when set",
                )
            locator = locator.strip()
            if len(locator) > MAX_EVIDENCE_LOCATOR_LEN:
                raise ReasoningIngestError(
                    IngestErrorCode.ingest_cap_exceeded,
                    "locator exceeds maximum length",
                )
            _reject_ctrl(locator, field="locator")

        locator_kind = it.get("locator_kind")
        if locator_kind is not None:
            if not isinstance(locator_kind, str) or locator_kind.strip() not in _LOCATOR_KINDS:
                raise ReasoningIngestError(
                    IngestErrorCode.ingest_malformed,
                    f"evidence_items[{i}].locator_kind must be one of: {', '.join(sorted(_LOCATOR_KINDS))}",
                )
            locator_kind = locator_kind.strip()

        item_out: dict[str, Any] = {"id": eid}
        if sid is not None:
            item_out["source_id"] = sid
        if rat is not None:
            item_out["retrieved_at"] = rat
        if ex is not None:
            item_out["excerpt"] = ex
        if title is not None:
            item_out["title"] = title
        if locator is not None:
            item_out["locator"] = locator
        if locator_kind is not None:
            item_out["locator_kind"] = locator_kind
        evidence_items.append(item_out)

    if not isinstance(ev_refs_raw, dict):
        raise ReasoningIngestError(
            IngestErrorCode.ingest_malformed, "evidence_refs must be an object"
        )

    evidence_refs: dict[str, list[str]] = {}
    for qid, ref_list in ev_refs_raw.items():
        if not isinstance(qid, str):
            raise ReasoningIngestError(
                IngestErrorCode.ingest_malformed, "evidence_refs keys must be strings"
            )
        if len(qid) > MAX_QUESTION_ID_LEN or not qid.strip():
            raise ReasoningIngestError(
                IngestErrorCode.ingest_malformed, "invalid question id in evidence_refs"
            )
        _reject_ctrl(qid, field="evidence_refs key")
        if not isinstance(ref_list, list):
            raise ReasoningIngestError(
                IngestErrorCode.ingest_malformed,
                f"evidence_refs[{qid!r}] must be an array",
            )
        if len(ref_list) > MAX_EVIDENCE_REFS_PER_QUESTION:
            raise ReasoningIngestError(
                IngestErrorCode.ingest_cap_exceeded,
                f"Too many evidence refs for question {qid!r} (max {MAX_EVIDENCE_REFS_PER_QUESTION})",
            )
        out_refs: list[str] = []
        for j, rid in enumerate(ref_list):
            if not isinstance(rid, str) or not rid.strip():
                raise ReasoningIngestError(
                    IngestErrorCode.ingest_malformed,
                    f"evidence_refs[{qid!r}][{j}] must be a non-empty string",
                )
            rid = rid.strip()
            if rid not in seen_ids:
                raise ReasoningIngestError(
                    IngestErrorCode.ingest_dangling_evidence_ref,
                    f"evidence ref {rid!r} for {qid!r} is not listed in evidence_items",
                )
            out_refs.append(rid)
        evidence_refs[qid] = out_refs

    if len(answers) > MAX_ANSWER_KEYS:
        raise ReasoningIngestError(
            IngestErrorCode.ingest_cap_exceeded,
            f"Too many answer keys (max {MAX_ANSWER_KEYS})",
        )

    return ParsedIngestEnvelope(
        answers=answers,
        evidence_items=evidence_items,
        evidence_refs=evidence_refs,
    )


def _allowed_question_ids(ir: IR) -> frozenset[str]:
    return frozenset(
        n.id for n in ir.nodes if n.kind == IRNodeKind.QUESTION and n.question is not None
    )


def validate_reasoning_ingest_envelope(
    ir: IR,
    envelope: ParsedIngestEnvelope,
) -> tuple[list[dict[str, Any]], HarnessNext]:
    """Validate envelope against published IR; return sorted warnings + ``harness_next``.

    Raises :class:`ReasoningIngestError` on hard rejects.
    """
    allowed = _allowed_question_ids(ir)

    for qid in envelope.evidence_refs:
        if qid not in allowed:
            raise ReasoningIngestError(
                IngestErrorCode.ingest_unknown_question_id,
                f"Unknown question id in evidence_refs: {qid!r}",
            )

    try:
        validate_raw_answers_for_ir(ir, envelope.answers)
    except ReasoningInputValidationError as exc:
        msg = str(exc)
        if exc.ingest_error_code:
            raise ReasoningIngestError(IngestErrorCode(exc.ingest_error_code), msg) from exc
        if "Unknown question id" in msg:
            raise ReasoningIngestError(IngestErrorCode.ingest_unknown_question_id, msg) from exc
        raise ReasoningIngestError(IngestErrorCode.ingest_malformed, msg) from exc

    warnings: list[dict[str, Any]] = []
    missing_ref_qs: list[str] = []
    for qid, val in envelope.answers.items():
        if qid not in allowed:
            continue
        answered = val is not None and not (isinstance(val, str) and not val.strip())
        if isinstance(val, list) and len(val) > 0:
            answered = True
        if not answered:
            continue
        refs = envelope.evidence_refs.get(qid, [])
        if not refs:
            missing_ref_qs.append(qid)

    if missing_ref_qs:
        warnings.append(
            {
                "code": str(IngestWarningCode.missing_evidence_ref),
                "question_ids": sorted(missing_ref_qs),
            }
        )

    sorted_w = sort_warnings(warnings)
    return sorted_w, harness_next_for_ingest(warnings=sorted_w)


def envelope_to_wire_dict(envelope: ParsedIngestEnvelope) -> dict[str, Any]:
    """Serialize parsed envelope for persistence (provenance wire form)."""
    return {
        "answers": envelope.answers,
        "evidence_items": envelope.evidence_items,
        "evidence_refs": envelope.evidence_refs,
    }


def prepare_evaluate_ingest(
    ir: IR,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], ParsedIngestEnvelope, list[dict[str, Any]], HarnessNext]:
    """Parse + validate ingest; return ``(answers, envelope, warnings, harness_next)``.

    ``harness_next=phase_2_ok`` means the envelope is structurally valid **and**
    answers can be grounded into canonical facts (same Stage A path evaluate uses).
    It does not run the solver or promise a conclusion.
    """
    env = parse_ingest_envelope_dict(payload)
    warnings, hn = validate_reasoning_ingest_envelope(ir, env)
    # Ensure grounding succeeds before advertising phase_2_ok.
    try:
        raw_answers_to_canonical_facts(ir, env.answers)
    except ReasoningInputValidationError as exc:
        raise ReasoningIngestError(IngestErrorCode.ingest_malformed, str(exc)) from exc
    return env.answers, env, warnings, hn


__all__ = [
    "MAX_EVIDENCE_EXCERPT_LEN",
    "MAX_EVIDENCE_ITEM_ID_LEN",
    "MAX_EVIDENCE_ITEMS",
    "MAX_EVIDENCE_LOCATOR_LEN",
    "MAX_EVIDENCE_REFS_PER_QUESTION",
    "MAX_EVIDENCE_SOURCE_ID_LEN",
    "MAX_EVIDENCE_TITLE_LEN",
    "ParsedIngestEnvelope",
    "ReasoningIngestError",
    "envelope_to_wire_dict",
    "parse_ingest_envelope_dict",
    "prepare_evaluate_ingest",
    "validate_reasoning_ingest_envelope",
]
