"""Stage A: structured answers → canonical fact records (``fact:*`` identity, pre-Z3)."""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from smeme.reasoning.ir.types import IR, IRNodeKind
from smeme.reasoning.runtime.input_validation import (
    MAX_RADIO_OR_OPTION_STR_LEN,
    ReasoningInputValidationError,
)
from smeme.reasoning.runtime.schemas import EvidenceConfidence

_RADIO_FACT_ATOM_RE = re.compile(r"^fact:radio:([^:]+):(.+)$")

# Audit projection only — must not constrain author-controlled option labels.
SOURCE_SPAN_MAX_LEN = 120


def _grounding_error(question_id: str, exc: ValidationError) -> tuple[str, dict[str, str]]:
    """Stable message and machine-branchable grounding failure details."""
    err = exc.errors()[0] if exc.errors() else {}
    loc = err.get("loc") or ()
    field = ".".join(str(p) for p in loc) if loc else "record"
    constraint = str(err.get("type") or "validation_error")
    detail = str(err.get("msg") or exc)
    remedy = (
        "Shorten the affected question id or option label, redeploy the decision tree, "
        "then retry the same answers."
        if constraint == "string_too_long"
        else "Correct the affected deployed question metadata, redeploy, then retry."
    )
    message = (
        f"Answer grounding failed for question {question_id!r} "
        f"(field={field}, constraint={constraint}): {detail}"
    )
    return message, {
        "question_id": question_id,
        "field": field,
        "constraint": constraint,
        "remedy": remedy,
    }


class CanonicalFactRecord(BaseModel):
    """One grounded fact in the canonical ``fact:*`` namespace (not a Z3 symbol name)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["radio"]
    question_id: str = Field(max_length=256)
    value: bool
    confidence: EvidenceConfidence
    source_span: str = Field(default="", max_length=SOURCE_SPAN_MAX_LEN)
    option_label: str | None = Field(default=None, max_length=MAX_RADIO_OR_OPTION_STR_LEN)
    """Radio: option label exactly as in :class:`~smeme.reasoning.ir.types.IRQuestionShape`."""

    bridge_rule_id: str | None = Field(default=None, max_length=256)
    """Optional id when a typed bridge rule produced/overrode this row (schema reserved; no blob path)."""

    source_item_id: str | None = Field(default=None, max_length=256)
    """Optional evidence chunk / item id for audit (schema reserved)."""

    char_start: int | None = None
    char_end: int | None = None
    """Offsets into the search haystack (raw evidence for ``regex_span``; normalized string for ``normalized_token_regex``)."""

    @model_validator(mode="after")
    def _char_span_consistent(self) -> Self:
        if (self.char_start is None) ^ (self.char_end is None):
            raise ValueError("char_start and char_end must both be set or both omitted")
        if self.char_start is not None and self.char_end is not None:
            if self.char_start < 0 or self.char_end < 0:
                raise ValueError("char offsets must be non-negative")
            if self.char_end < self.char_start:
                raise ValueError("char_end must be >= char_start")
        return self

    def fact_atom_id(self) -> str:
        if self.kind != "radio":
            raise ValueError("only radio facts are supported")
        if self.option_label is None:
            raise ValueError("radio fact requires option_label")
        return f"fact:radio:{self.question_id}:{self.option_label}"


def validate_fact_atom_id(atom_id: str) -> None:
    """Reject malformed ``fact:*`` ids (Stage A emits only valid ids)."""
    bad = "invalid canonical fact atom id: " + repr(atom_id)
    if _RADIO_FACT_ATOM_RE.fullmatch(atom_id):
        return
    raise ValueError(bad)


def raw_answers_to_canonical_facts(
    ir: IR,
    raw_answers: dict[str, str | list[str] | None],
) -> list[CanonicalFactRecord]:
    """
    Emit canonical fact records in **the same order** as the legacy ``ir.nodes`` walk
    in ``evaluate_reasoning`` / ``_apply_user_facts`` (per-question, per-option).
    """
    out: list[CanonicalFactRecord] = []

    for n in ir.nodes:
        if n.kind != IRNodeKind.QUESTION or n.question is None:
            continue
        qid = n.id
        qt = n.question.qtype
        if qt != "radio":
            continue
        val = raw_answers.get(qid)
        answered = val is not None and bool(str(val).strip())
        opt_str = str(val).strip().lower() if answered else ""
        conf = EvidenceConfidence.EXPLICIT if answered else EvidenceConfidence.ABSENT
        for opt in n.question.options:
            value = opt.strip().lower() == opt_str
            # Truncate audit projection; full label stays on option_label.
            span = opt_str[:SOURCE_SPAN_MAX_LEN] if value else ""
            try:
                out.append(
                    CanonicalFactRecord(
                        kind="radio",
                        question_id=qid,
                        value=value,
                        confidence=conf,
                        source_span=span,
                        option_label=opt,
                    )
                )
            except ValidationError as exc:
                message, details = _grounding_error(qid, exc)
                raise ReasoningInputValidationError(
                    message,
                    ingest_error_code="ingest_grounding_failed",
                    details=details,
                ) from exc

    return out


__all__ = [
    "CanonicalFactRecord",
    "SOURCE_SPAN_MAX_LEN",
    "raw_answers_to_canonical_facts",
    "validate_fact_atom_id",
]
