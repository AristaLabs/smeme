"""ANALYZE control: allocate the next isolated extraction (calculus §13.9.5)."""

from __future__ import annotations

from smeme.reasoning.ir.types import IR
from smeme.reasoning.runtime.assumptions import EMPTY_ASSUMPTIONS, ReasoningAssumptions
from smeme.reasoning.runtime.consistency_gate import PremiseInvariantError
from smeme.reasoning.runtime.inquire.discriminators import myopic_discriminators
from smeme.reasoning.runtime.inquire.resolvable import search_resolving_witness
from smeme.reasoning.runtime.inquire.space import (
    check_cons,
    compile_working_base,
    resolved_conclusion,
)
from smeme.reasoning.runtime.inquire.support import resolving_support
from smeme.reasoning.runtime.inquire.types import (
    AdmittedAssertion,
    InquiryBudget,
    InquiryDirective,
    VerificationKey,
    WorksheetCatalog,
    logical_evidence,
    verification_key_for,
)


def _operational_stop(status: str) -> InquiryDirective:
    reason = {
        "budget": "operational_budget",
        "timeout": "operational_timeout",
        "unknown": "operational_unknown",
    }.get(status, "operational_unknown")
    op = status if status in ("budget", "timeout", "unknown") else "unknown"
    return InquiryDirective(
        action="STOP",
        stop_reason=reason,  # type: ignore[arg-type]
        operational_status=op,  # type: ignore[arg-type]
    )


def _assertion_for_pair(
    admitted: tuple[AdmittedAssertion, ...], question_id: str, option: str
) -> AdmittedAssertion:
    matches = [
        item for item in admitted if item.question_id == question_id and item.option == option
    ]
    if len(matches) != 1:
        msg = f"S_R pair {(question_id, option)!r} is not a unique live assertion"
        raise PremiseInvariantError(msg)
    return matches[0]


def _pair_verified(
    admitted: tuple[AdmittedAssertion, ...],
    verified: frozenset[VerificationKey],
    question_id: str,
    option: str,
    *,
    artifact_identity: str,
    pv_version: str,
) -> bool:
    assertion = _assertion_for_pair(admitted, question_id, option)
    key = verification_key_for(
        assertion, artifact_identity=artifact_identity, pv_version=pv_version
    )
    return key in verified


def analyze_inquiry(
    ir: IR,
    admitted: tuple[AdmittedAssertion, ...],
    assumptions: ReasoningAssumptions | None,
    verified: frozenset[VerificationKey],
    budget: InquiryBudget,
    worksheet_catalog: WorksheetCatalog,
    *,
    artifact_identity: str,
    pv_version: str,
) -> InquiryDirective:
    """Stateless ANALYZE. Derived ``C_poss`` / ``S_R`` / ``D_1`` are not returned or stored."""
    _ = worksheet_catalog
    phi = assumptions if assumptions is not None else EMPTY_ASSUMPTIONS
    evidence = logical_evidence(admitted)
    base = compile_working_base(ir, evidence, phi, budget)

    cons = check_cons(base)
    if cons.status in ("budget", "timeout", "unknown"):
        return _operational_stop(cons.status)
    if cons.status == "inconsistent":
        return InquiryDirective(
            action="STOP",
            stop_reason="inconsistent",
            inconsistency_cause=cons.cause,
        )

    resolved = resolved_conclusion(base)
    if resolved.status in ("budget", "timeout", "unknown"):
        return _operational_stop(resolved.status)
    if resolved.status == "inconsistent":
        return InquiryDirective(
            action="STOP",
            stop_reason="inconsistent",
            inconsistency_cause=resolved.cause,
        )
    if resolved.status == "resolved":
        if resolved.conclusion_id is None:
            raise PremiseInvariantError("Resolved status without conclusion_id")
        support = resolving_support(base, resolved.conclusion_id)
        if support.status in ("budget", "timeout", "unknown"):
            return _operational_stop(support.status)
        for pair in support.pairs:
            if not _pair_verified(
                admitted,
                verified,
                pair.question_id,
                pair.option,
                artifact_identity=artifact_identity,
                pv_version=pv_version,
            ):
                assertion = _assertion_for_pair(admitted, pair.question_id, pair.option)
                return InquiryDirective(
                    action="VERIFY",
                    question_id=assertion.question_id,
                    option=assertion.option,
                    verification_key=verification_key_for(
                        assertion,
                        artifact_identity=artifact_identity,
                        pv_version=pv_version,
                    ),
                )
        return InquiryDirective(
            action="STOP",
            stop_reason="verified_resolved_consequence",
        )

    d1 = myopic_discriminators(base)
    if d1.status in ("budget", "timeout", "unknown"):
        return _operational_stop(d1.status)
    if d1.status == "ok" and d1.question_ids:
        return InquiryDirective(action="ACQUIRE", question_id=d1.question_ids[0])

    witness = search_resolving_witness(base, budget)
    if witness.status == "acquire":
        return InquiryDirective(action="ACQUIRE", question_id=witness.question_id)
    if witness.status == "not_resolvable":
        return InquiryDirective(
            action="STOP",
            stop_reason="not_resolvable_by_remaining_evidence_vocabulary",
        )
    if witness.status == "budget_miss":
        op = (
            witness.operational_status
            if witness.operational_status
            in (
                "budget",
                "timeout",
                "unknown",
            )
            else "budget"
        )
        return InquiryDirective(
            action="STOP",
            stop_reason="no_joint_discriminator_within_budget",
            operational_status=op,  # type: ignore[arg-type]
        )
    return _operational_stop("unknown")
