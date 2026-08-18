"""Inquire MCP wire codec. No FastMCP imports; no reasoning semantics."""

from __future__ import annotations

import json
from typing import Any

from smeme.reasoning.ir.serialize import ir_from_json, ir_to_json
from smeme.reasoning.ir.types import IR
from smeme.reasoning.orchestration.inquire.verification.transcript import (
    WireVerificationObservation,
)
from smeme.reasoning.orchestration.inquire.verification.types import (
    EvaluationId,
    PresentationVariant,
)
from smeme.reasoning.runtime.inquire.transition import (
    Insufficient,
    Replace,
    Retain,
    Retract,
    VerificationDecision,
)
from smeme.reasoning.runtime.inquire.types import (
    AdmittedAssertion,
    CanonicalProvenanceId,
    EvidenceQuestion,
    ExtractionTask,
    InquiryBudget,
    InquiryDirective,
    VerificationKey,
    WorksheetCatalog,
    WorksheetItem,
)

# Keys that must never appear on an extractor-facing task JSON object.
FORBIDDEN_TASK_KEYS: frozenset[str] = frozenset(
    {
        "VERIFY",
        "ACQUIRE",
        "verification_key",
        "live_option",
        "pv_version",
        "support",
        "resolved",
        "conclusion",
        "stop_reason",
        "action",
        "evaluation_id",
    }
)

BLIND_TASK_KEYS: frozenset[str] = frozenset({"question_id", "stem", "options"})


class InquireCodecError(ValueError):
    """Malformed Inquire MCP payload with a stable ``error.code``."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _require_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InquireCodecError("inquire_invalid_payload", f"{label} must be a JSON object")
    return value


def _require_list(value: Any, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise InquireCodecError("inquire_invalid_payload", f"{label} must be a JSON array")
    return value


def parse_json_object(raw: str, *, label: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InquireCodecError(
            "inquire_invalid_payload", f"{label} is not valid JSON: {exc}"
        ) from exc
    return _require_mapping(data, label=label)


def parse_json_array(raw: str, *, label: str) -> list[Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InquireCodecError(
            "inquire_invalid_payload", f"{label} is not valid JSON: {exc}"
        ) from exc
    return _require_list(data, label=label)


def decode_ir(ir_json: str) -> IR:
    data = parse_json_object(ir_json, label="ir_json")
    try:
        return ir_from_json(data)
    except (KeyError, ValueError, TypeError) as exc:
        raise InquireCodecError(
            "inquire_invalid_payload", f"ir_json could not be parsed: {exc}"
        ) from exc


def encode_ir(ir: IR) -> dict[str, Any]:
    return ir_to_json(ir)


def decode_worksheet_catalog(catalog_json: str) -> dict[str, WorksheetItem]:
    data = parse_json_object(catalog_json, label="worksheet_catalog_json")
    out: dict[str, WorksheetItem] = {}
    for qid, item in data.items():
        if not isinstance(qid, str) or not qid.strip():
            raise InquireCodecError(
                "inquire_invalid_payload", "worksheet catalog keys must be non-empty strings"
            )
        row = _require_mapping(item, label=f"worksheet_catalog[{qid!r}]")
        stem = row.get("stem")
        options = row.get("options")
        if not isinstance(stem, str) or not stem.strip():
            raise InquireCodecError(
                "inquire_invalid_payload",
                f"worksheet_catalog[{qid!r}].stem must be a non-empty string",
            )
        if (
            not isinstance(options, list)
            or not options
            or not all(isinstance(o, str) and o.strip() for o in options)
        ):
            raise InquireCodecError(
                "inquire_invalid_payload",
                f"worksheet_catalog[{qid!r}].options must be a non-empty string array",
            )
        out[qid] = WorksheetItem(stem=stem, options=tuple(options))
    return out


def encode_worksheet_catalog(catalog: WorksheetCatalog) -> dict[str, Any]:
    return {
        qid: {"stem": item.stem, "options": list(item.options)} for qid, item in catalog.items()
    }


def decode_admitted(admitted_json: str) -> tuple[AdmittedAssertion, ...]:
    rows = parse_json_array(admitted_json, label="admitted_json")
    out: list[AdmittedAssertion] = []
    for i, row in enumerate(rows):
        item = _require_mapping(row, label=f"admitted_json[{i}]")
        try:
            qid = item["question_id"]
            option = item["option"]
            provenance_id = item["provenance_id"]
        except KeyError as exc:
            raise InquireCodecError(
                "inquire_invalid_payload",
                f"admitted_json[{i}] missing {exc.args[0]}",
            ) from exc
        if not isinstance(qid, str) or not isinstance(option, str):
            raise InquireCodecError(
                "inquire_invalid_payload",
                f"admitted_json[{i}] question_id and option must be strings",
            )
        if not isinstance(provenance_id, str) or not provenance_id.strip():
            raise InquireCodecError(
                "inquire_invalid_payload",
                f"admitted_json[{i}] provenance_id must be a non-empty string",
            )
        out.append(
            AdmittedAssertion(
                question_id=qid,
                option=option,
                provenance_id=CanonicalProvenanceId(provenance_id),
            )
        )
    return tuple(out)


def encode_admitted(admitted: tuple[AdmittedAssertion, ...]) -> list[dict[str, str]]:
    return [
        {
            "question_id": a.question_id,
            "option": a.option,
            "provenance_id": str(a.provenance_id),
        }
        for a in admitted
    ]


def decode_verification_key(
    data: dict[str, Any], *, label: str = "verification_key"
) -> VerificationKey:
    row = _require_mapping(data, label=label)
    try:
        return VerificationKey(
            artifact_identity=str(row["artifact_identity"]),
            question_id=str(row["question_id"]),
            option=str(row["option"]),
            provenance_identity=str(row["provenance_identity"]),
            pv_version=str(row["pv_version"]),
        )
    except KeyError as exc:
        raise InquireCodecError(
            "inquire_invalid_payload", f"{label} missing {exc.args[0]}"
        ) from exc


def encode_verification_key(key: VerificationKey) -> dict[str, str]:
    return {
        "artifact_identity": key.artifact_identity,
        "question_id": key.question_id,
        "option": key.option,
        "provenance_identity": key.provenance_identity,
        "pv_version": key.pv_version,
    }


def decode_verified(verified_json: str) -> frozenset[VerificationKey]:
    rows = parse_json_array(verified_json, label="verified_json")
    keys: list[VerificationKey] = []
    for i, row in enumerate(rows):
        keys.append(decode_verification_key(_require_mapping(row, label=f"verified_json[{i}]")))
    return frozenset(keys)


def encode_verified(verified: frozenset[VerificationKey]) -> list[dict[str, str]]:
    return sorted(
        (encode_verification_key(k) for k in verified),
        key=lambda d: (
            d["artifact_identity"],
            d["question_id"],
            d["option"],
            d["provenance_identity"],
            d["pv_version"],
        ),
    )


def decode_budget(budget_json: str | None) -> InquiryBudget:
    if budget_json is None or not str(budget_json).strip():
        return InquiryBudget()
    data = parse_json_object(budget_json, label="budget_json")
    kwargs: dict[str, Any] = {}
    for field in ("max_sat_calls", "timeout_ms", "max_residual_sat_calls"):
        if field in data and data[field] is not None:
            if not isinstance(data[field], int):
                raise InquireCodecError(
                    "inquire_invalid_payload", f"budget_json.{field} must be an integer"
                )
            kwargs[field] = data[field]
    return InquiryBudget(**kwargs)


def encode_blind_task(task: ExtractionTask) -> dict[str, Any]:
    """Flatten ExtractionTask to the extractor-facing wire shape."""
    payload = {
        "question_id": task.question.question_id,
        "stem": task.question.stem,
        "options": list(task.question.options),
    }
    assert set(payload) <= BLIND_TASK_KEYS
    return payload


def decode_blind_task(data: dict[str, Any]) -> ExtractionTask:
    row = _require_mapping(data, label="blind_task")
    extra = set(row) - BLIND_TASK_KEYS
    if extra:
        raise InquireCodecError(
            "inquire_invalid_payload",
            f"blind task contains unexpected keys: {sorted(extra)}",
        )
    try:
        qid = row["question_id"]
        stem = row["stem"]
        options = row["options"]
    except KeyError as exc:
        raise InquireCodecError(
            "inquire_invalid_payload", f"blind task missing {exc.args[0]}"
        ) from exc
    if not isinstance(qid, str) or not isinstance(stem, str):
        raise InquireCodecError(
            "inquire_invalid_payload", "blind task question_id and stem must be strings"
        )
    if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
        raise InquireCodecError(
            "inquire_invalid_payload", "blind task options must be a string array"
        )
    return ExtractionTask(
        question=EvidenceQuestion(question_id=qid, stem=stem, options=tuple(options))
    )


def assert_blind_task_payload(payload: dict[str, Any]) -> None:
    """Fail closed if extractor-facing JSON contains control-channel keys."""
    keys = set(payload)
    if keys != BLIND_TASK_KEYS:
        raise InquireCodecError(
            "inquire_invalid_payload",
            f"blind task keys must be exactly {sorted(BLIND_TASK_KEYS)}, got {sorted(keys)}",
        )
    leaked = keys & FORBIDDEN_TASK_KEYS
    if leaked:
        raise InquireCodecError(
            "inquire_invalid_payload",
            f"blind task leaks control keys: {sorted(leaked)}",
        )
    blob = json.dumps(payload, sort_keys=True)
    for forbidden in FORBIDDEN_TASK_KEYS:
        # Substring scan on serialized form (plan: serialized JSON invariant).
        if forbidden in ("VERIFY", "ACQUIRE"):
            # These are uppercase mode tokens; check as JSON substrings.
            if f'"{forbidden}"' in blob or f": {forbidden}" in blob:
                raise InquireCodecError(
                    "inquire_invalid_payload",
                    f"blind task serialized payload contains {forbidden!r}",
                )
        elif f'"{forbidden}"' in blob:
            raise InquireCodecError(
                "inquire_invalid_payload",
                f"blind task serialized payload contains key {forbidden!r}",
            )


def encode_directive(directive: InquiryDirective) -> dict[str, Any]:
    out: dict[str, Any] = {"action": directive.action}
    if directive.question_id is not None:
        out["question_id"] = directive.question_id
    if directive.option is not None:
        out["option"] = directive.option
    if directive.verification_key is not None:
        out["verification_key"] = encode_verification_key(directive.verification_key)
    if directive.stop_reason is not None:
        out["stop_reason"] = directive.stop_reason
    if directive.inconsistency_cause is not None:
        out["inconsistency_cause"] = directive.inconsistency_cause
    if directive.operational_status is not None:
        out["operational_status"] = directive.operational_status
    return out


def encode_evaluations(
    evaluations: list[dict[str, Any]] | tuple[Any, ...],
) -> list[dict[str, Any]]:
    """Encode prepared evaluations for the trusted analyze response."""
    from smeme.reasoning.orchestration.inquire.verification.transcript import (
        PreparedEvaluation,
    )

    out: list[dict[str, Any]] = []
    for item in evaluations:
        if isinstance(item, PreparedEvaluation):
            task_payload = encode_blind_task(item.task)
            assert_blind_task_payload(task_payload)
            out.append(
                {
                    "evaluation_id": str(item.evaluation_id),
                    "task": task_payload,
                }
            )
        else:
            out.append(item)
    return out


def encode_decision(decision: VerificationDecision) -> dict[str, Any]:
    if isinstance(decision, Retain):
        return {"kind": "retain"}
    if isinstance(decision, Insufficient):
        return {"kind": "insufficient"}
    if isinstance(decision, Retract):
        return {"kind": "retract"}
    if isinstance(decision, Replace):
        return {
            "kind": "replace",
            "option": decision.option,
            "provenance_id": str(decision.provenance_id),
        }
    raise InquireCodecError("inquire_invalid_payload", f"unknown decision type {type(decision)!r}")


def decode_wire_observations(observations_json: str) -> tuple[WireVerificationObservation, ...]:
    rows = parse_json_array(observations_json, label="observations_json")
    out: list[WireVerificationObservation] = []
    for i, row in enumerate(rows):
        item = _require_mapping(row, label=f"observations_json[{i}]")
        try:
            evaluation_id = item["evaluation_id"]
            question_id = item["question_id"]
        except KeyError as exc:
            raise InquireCodecError(
                "inquire_invalid_payload",
                f"observations_json[{i}] missing {exc.args[0]}",
            ) from exc
        if not isinstance(evaluation_id, str) or not isinstance(question_id, str):
            raise InquireCodecError(
                "inquire_invalid_payload",
                f"observations_json[{i}] evaluation_id and question_id must be strings",
            )
        selected = item.get("selected_option")
        if selected is not None and not isinstance(selected, str):
            raise InquireCodecError(
                "inquire_invalid_payload",
                f"observations_json[{i}].selected_option must be a string or null",
            )
        provenance = item.get("provenance_id")
        if provenance is not None and (not isinstance(provenance, str) or not provenance.strip()):
            raise InquireCodecError(
                "inquire_invalid_payload",
                f"observations_json[{i}].provenance_id must be a non-empty string or null",
            )
        presentation: PresentationVariant | None = None
        if "presentation" in item and item["presentation"] is not None:
            pres = _require_mapping(
                item["presentation"], label=f"observations_json[{i}].presentation"
            )
            order = pres.get("option_order")
            if not isinstance(order, list) or not all(isinstance(o, str) for o in order):
                raise InquireCodecError(
                    "inquire_invalid_payload",
                    f"observations_json[{i}].presentation.option_order must be a string array",
                )
            presentation = PresentationVariant(option_order=tuple(order))
        out.append(
            WireVerificationObservation(
                evaluation_id=EvaluationId(evaluation_id),
                question_id=question_id,
                selected_option=selected,
                provenance_id=(
                    CanonicalProvenanceId(provenance) if provenance is not None else None
                ),
                presentation=presentation,
            )
        )
    return tuple(out)


__all__ = [
    "BLIND_TASK_KEYS",
    "FORBIDDEN_TASK_KEYS",
    "InquireCodecError",
    "assert_blind_task_payload",
    "decode_admitted",
    "decode_blind_task",
    "decode_budget",
    "decode_ir",
    "decode_verification_key",
    "decode_verified",
    "decode_wire_observations",
    "decode_worksheet_catalog",
    "encode_admitted",
    "encode_blind_task",
    "encode_decision",
    "encode_directive",
    "encode_evaluations",
    "encode_ir",
    "encode_verification_key",
    "encode_verified",
    "encode_worksheet_catalog",
    "parse_json_object",
]
