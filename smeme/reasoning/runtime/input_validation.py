"""Bounds and allowlists for reasoning evaluate payloads."""

from __future__ import annotations

import re
from typing import Any

from smeme.reasoning.ir.types import IR, IRNodeKind
from smeme.reasoning.runtime.ingest_codes import IngestErrorCode
from smeme.reasoning.runtime.schemas import BlobEvidenceItem

MAX_ANSWER_KEYS = 512
MAX_QUESTION_ID_LEN = 256
MAX_RADIO_OR_OPTION_STR_LEN = 2048
MAX_TEXT_ANSWER_LEN = 65536
MAX_CHECKBOX_SELECTIONS = 256
MAX_EVIDENCE_ITEMS = 10_000
MAX_ATOM_NAME_LEN = 256

_ATOM_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class ReasoningInputValidationError(ValueError):
    """Payload failed structural validation.

    When raised during provenance ingest, ``ingest_error_code`` selects the MCP/REST
    ``error.code`` (see :class:`~smeme.reasoning.runtime.ingest_codes.IngestErrorCode`).
    """

    def __init__(
        self,
        message: str,
        *,
        ingest_error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.ingest_error_code = ingest_error_code
        self.details = dict(details or {})


def _reject_ctrl(s: str, *, field: str) -> None:
    if _CTRL_RE.search(s):
        msg = f"{field} contains disallowed control characters"
        raise ReasoningInputValidationError(msg)


def validate_raw_answers_for_ir(ir: IR, raw_answers: dict[str, Any]) -> None:
    """Strict allowlist keyed by question node ids present on ``ir``."""
    allowed = frozenset(
        n.id for n in ir.nodes if n.kind == IRNodeKind.QUESTION and n.question is not None
    )

    if len(raw_answers) > MAX_ANSWER_KEYS:
        msg = f"Too many answer keys (max {MAX_ANSWER_KEYS})"
        raise ReasoningInputValidationError(msg)

    for qid, val in raw_answers.items():
        if not isinstance(qid, str):
            raise ReasoningInputValidationError("Question ids must be strings")
        if len(qid) > MAX_QUESTION_ID_LEN or not qid.strip():
            raise ReasoningInputValidationError("Invalid question id")
        _reject_ctrl(qid, field="question_id")
        if qid not in allowed:
            msg = f"Unknown question id: {qid!r}"
            raise ReasoningInputValidationError(msg)

        node = next(x for x in ir.nodes if x.id == qid)
        q = node.question
        assert q is not None
        if q.qtype != "radio":
            msg = f"Unsupported question type for {qid!r}"
            raise ReasoningInputValidationError(msg)

        if val is not None and not isinstance(val, str):
            msg = f"Answer for {qid!r} must be a string or null"
            raise ReasoningInputValidationError(msg)
        if isinstance(val, str):
            _reject_ctrl(val, field="answer")
            if len(val) > MAX_RADIO_OR_OPTION_STR_LEN:
                msg = f"Answer for {qid!r} exceeds maximum length"
                raise ReasoningInputValidationError(msg)
            stripped = val.strip()
            if stripped:
                options_lower = {opt.strip().lower() for opt in q.options}
                if stripped.lower() not in options_lower:
                    msg = f"Answer for {qid!r} does not match any option label (got {stripped!r})"
                    raise ReasoningInputValidationError(
                        msg,
                        ingest_error_code=IngestErrorCode.ingest_invalid_answer_option.value,
                    )


def validate_evidence_items_for_ir(ir: IR, items: list[BlobEvidenceItem]) -> None:
    """Every atom must correspond to an IR-derived symbol prefix."""
    if len(items) > MAX_EVIDENCE_ITEMS:
        msg = f"Too many evidence items (max {MAX_EVIDENCE_ITEMS})"
        raise ReasoningInputValidationError(msg)
    for it in items:
        name = it.atom
        if len(name) > MAX_ATOM_NAME_LEN or not _ATOM_NAME_RE.match(name):
            msg = f"Invalid atom name: {name!r}"
            raise ReasoningInputValidationError(msg)
