"""ANALYZE control: allocate the next isolated extraction (calculus §13.9.5).

Stop reasons include semantic ends (``verified_resolved_consequence``,
``inconsistent``, …) and operational ends. When ``Resolved(B)`` holds but exact
``S_R`` search hits budget/timeout/unknown, the directive is STOP with
``resolving_support_incomplete`` (distinct from generic ``operational_budget`` on
Cons / Resolved / D1 / residual witness search).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from time import perf_counter

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
    InquiryDiagnostics,
    InquiryDirective,
    VerificationKey,
    WorksheetCatalog,
    logical_evidence,
    verification_key_for,
)

logger = logging.getLogger(__name__)


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
    started = perf_counter()
    _ = worksheet_catalog
    phi = assumptions if assumptions is not None else EMPTY_ASSUMPTIONS
    evidence = logical_evidence(admitted)
    base = compile_working_base(ir, evidence, phi, budget)

    def finish(
        directive: InquiryDirective,
        *,
        phase: str,
        resolving_support_sat_calls: int = 0,
    ) -> InquiryDirective:
        elapsed_ms = round((perf_counter() - started) * 1000, 3)
        general_sat_calls = base.sat_calls[0]
        total_sat_calls = general_sat_calls + resolving_support_sat_calls
        logger.info(
            "Inquire ANALYZE completed",
            extra={
                "inquire_action": directive.action,
                "inquire_stop_reason": directive.stop_reason,
                "inquire_operational_status": directive.operational_status,
                "inquire_phase": phase,
                "inquire_sat_calls": total_sat_calls,
                "inquire_general_sat_calls": general_sat_calls,
                "inquire_resolving_support_sat_calls": resolving_support_sat_calls,
                "inquire_elapsed_ms": elapsed_ms,
                "inquire_max_sat_calls": budget.max_sat_calls,
                "inquire_timeout_ms": budget.timeout_ms,
                "inquire_max_resolving_support_sat_calls": (budget.max_resolving_support_sat_calls),
                "inquire_resolving_support_timeout_ms": (budget.resolving_support_timeout_ms),
            },
        )
        if directive.operational_status is None:
            return directive
        diagnostics = InquiryDiagnostics(
            phase=phase,
            operational_status=directive.operational_status,
            sat_calls=total_sat_calls,
            general_sat_calls=general_sat_calls,
            resolving_support_sat_calls=resolving_support_sat_calls,
            elapsed_ms=elapsed_ms,
            max_sat_calls=budget.max_sat_calls,
            timeout_ms=budget.timeout_ms,
            max_resolving_support_sat_calls=budget.max_resolving_support_sat_calls,
            resolving_support_timeout_ms=budget.resolving_support_timeout_ms,
        )
        return replace(directive, diagnostics=diagnostics)

    cons = check_cons(base)
    if cons.status in ("budget", "timeout", "unknown"):
        return finish(_operational_stop(cons.status), phase="consistency")
    if cons.status == "inconsistent":
        return finish(
            InquiryDirective(
                action="STOP",
                stop_reason="inconsistent",
                inconsistency_cause=cons.cause,
            ),
            phase="consistency",
        )

    resolved = resolved_conclusion(base)
    if resolved.status in ("budget", "timeout", "unknown"):
        return finish(_operational_stop(resolved.status), phase="resolved")
    if resolved.status == "inconsistent":
        return finish(
            InquiryDirective(
                action="STOP",
                stop_reason="inconsistent",
                inconsistency_cause=resolved.cause,
            ),
            phase="resolved",
        )
    if resolved.status == "resolved":
        if resolved.conclusion_id is None:
            raise PremiseInvariantError("Resolved status without conclusion_id")
        support = resolving_support(
            base,
            resolved.conclusion_id,
            max_sat_calls=budget.max_resolving_support_sat_calls,
            timeout_ms=budget.resolving_support_timeout_ms,
        )
        if support.status in ("budget", "timeout", "unknown"):
            # Case may already be Resolved; S_R enumeration (esp. larger sheets) exhausted
            # its dedicated SAT budget. Do not collapse this into generic operational_budget —
            # chat Apply can still emit a concluded report from admitted answers.
            op = support.status if support.status in ("budget", "timeout", "unknown") else "unknown"
            return finish(
                InquiryDirective(
                    action="STOP",
                    stop_reason="resolving_support_incomplete",
                    operational_status=op,  # type: ignore[arg-type]
                ),
                phase="resolving_support",
                resolving_support_sat_calls=support.sat_calls,
            )
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
                return finish(
                    InquiryDirective(
                        action="VERIFY",
                        question_id=assertion.question_id,
                        option=assertion.option,
                        verification_key=verification_key_for(
                            assertion,
                            artifact_identity=artifact_identity,
                            pv_version=pv_version,
                        ),
                    ),
                    phase="resolving_support",
                    resolving_support_sat_calls=support.sat_calls,
                )
        return finish(
            InquiryDirective(
                action="STOP",
                stop_reason="verified_resolved_consequence",
            ),
            phase="resolving_support",
            resolving_support_sat_calls=support.sat_calls,
        )

    d1 = myopic_discriminators(base)
    if d1.status in ("budget", "timeout", "unknown"):
        return finish(_operational_stop(d1.status), phase="myopic_discriminators")
    if d1.status == "ok" and d1.question_ids:
        return finish(
            InquiryDirective(action="ACQUIRE", question_id=d1.question_ids[0]),
            phase="myopic_discriminators",
        )

    witness = search_resolving_witness(base, budget)
    if witness.status == "acquire":
        return finish(
            InquiryDirective(action="ACQUIRE", question_id=witness.question_id),
            phase="residual_witness",
        )
    if witness.status == "not_resolvable":
        return finish(
            InquiryDirective(
                action="STOP",
                stop_reason="not_resolvable_by_remaining_evidence_vocabulary",
            ),
            phase="residual_witness",
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
        return finish(
            InquiryDirective(
                action="STOP",
                stop_reason="no_joint_discriminator_within_budget",
                operational_status=op,  # type: ignore[arg-type]
            ),
            phase="residual_witness",
        )
    return finish(_operational_stop("unknown"), phase="residual_witness")
