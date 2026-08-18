"""One-step Inquire execution: directive → blind task → extract → admit or ``P_v``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from smeme.reasoning.ir.types import IR
from smeme.reasoning.orchestration.inquire.admit import admit_extraction
from smeme.reasoning.orchestration.inquire.types import (
    AbstainedExtraction,
    AnsweredExtraction,
    ExtractionResult,
    Extractor,
)
from smeme.reasoning.orchestration.inquire.verification.policy import (
    DEFAULT_VERIFICATION_POLICY,
    BlindVerificationPolicy,
)
from smeme.reasoning.orchestration.inquire.verification.runner import run_verification
from smeme.reasoning.runtime.assumptions import ReasoningAssumptions
from smeme.reasoning.runtime.consistency_gate import PremiseInvariantError
from smeme.reasoning.runtime.inquire import (
    analyze_inquiry,
    build_extractor_issue,
)
from smeme.reasoning.runtime.inquire.types import (
    AdmittedAssertion,
    ExtractionTask,
    InquiryBudget,
    InquiryDirective,
    VerificationKey,
    WorksheetCatalog,
)

ExecutionStatus = Literal[
    "stop",
    "acquired",
    "abstained",
    "verified",
]


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    admitted: tuple[AdmittedAssertion, ...]
    verified: frozenset[VerificationKey]
    directive: InquiryDirective
    task: ExtractionTask | None
    result: ExtractionResult | None
    status: ExecutionStatus


def _bind_result_to_issued_task(
    *,
    directive: InquiryDirective,
    task: ExtractionTask,
    result: ExtractionResult,
) -> None:
    if directive.question_id is None:
        raise PremiseInvariantError("directive missing question_id")
    if task.question.question_id != directive.question_id:
        msg = (
            f"issued task question_id {task.question.question_id!r} does not match "
            f"directive question_id {directive.question_id!r}"
        )
        raise PremiseInvariantError(msg)
    if result.question_id != task.question.question_id:
        msg = (
            f"extraction result question_id {result.question_id!r} does not match "
            f"issued task {task.question.question_id!r}"
        )
        raise PremiseInvariantError(msg)
    if result.question_id != directive.question_id:
        msg = (
            f"extraction result question_id {result.question_id!r} does not match "
            f"directive question_id {directive.question_id!r}"
        )
        raise PremiseInvariantError(msg)


def execute_directive(
    *,
    ir: IR,
    admitted: tuple[AdmittedAssertion, ...],
    verified: frozenset[VerificationKey],
    directive: InquiryDirective,
    worksheet_catalog: WorksheetCatalog,
    extractor: Extractor,
    artifact_identity: str,
    verification_policy: BlindVerificationPolicy = DEFAULT_VERIFICATION_POLICY,
) -> ExecutionOutcome:
    """Execute one already-issued directive. Does not call ``analyze_inquiry``."""
    if directive.action == "STOP":
        return ExecutionOutcome(
            admitted=admitted,
            verified=verified,
            directive=directive,
            task=None,
            result=None,
            status="stop",
        )

    if directive.question_id is None:
        msg = f"{directive.action} directive missing question_id"
        raise PremiseInvariantError(msg)

    if directive.action == "ACQUIRE":
        task = build_extractor_issue(worksheet_catalog, directive.question_id)
        result = extractor.extract(task)
        _bind_result_to_issued_task(directive=directive, task=task, result=result)
        if isinstance(result, AbstainedExtraction):
            return ExecutionOutcome(
                admitted=admitted,
                verified=verified,
                directive=directive,
                task=task,
                result=result,
                status="abstained",
            )
        if not isinstance(result, AnsweredExtraction):
            msg = f"unexpected extraction result type {type(result)!r}"
            raise PremiseInvariantError(msg)
        step_out = admit_extraction(ir, admitted, task=task, result=result)
        return ExecutionOutcome(
            admitted=step_out.admitted,
            verified=verified,
            directive=directive,
            task=task,
            result=result,
            status="acquired",
        )

    if directive.action == "VERIFY":
        battery = run_verification(
            ir=ir,
            admitted=admitted,
            verified=verified,
            directive=directive,
            worksheet_catalog=worksheet_catalog,
            extractor=extractor,
            artifact_identity=artifact_identity,
            verification_policy=verification_policy,
        )
        return ExecutionOutcome(
            admitted=battery.step.admitted,
            verified=battery.step.verified,
            directive=directive,
            task=battery.task,
            result=battery.result,
            status="verified",
        )

    msg = f"unknown directive action {directive.action!r}"
    raise PremiseInvariantError(msg)


def step(
    *,
    ir: IR,
    admitted: tuple[AdmittedAssertion, ...],
    assumptions: ReasoningAssumptions | None,
    verified: frozenset[VerificationKey],
    budget: InquiryBudget,
    worksheet_catalog: WorksheetCatalog,
    extractor: Extractor,
    artifact_identity: str,
    verification_policy: BlindVerificationPolicy = DEFAULT_VERIFICATION_POLICY,
) -> ExecutionOutcome:
    """``ANALYZE`` then ``execute_directive``. Returns updated epistemic state."""
    directive = analyze_inquiry(
        ir,
        admitted,
        assumptions,
        verified,
        budget,
        worksheet_catalog,
        artifact_identity=artifact_identity,
        pv_version=verification_policy.pv_version,
    )
    return execute_directive(
        ir=ir,
        admitted=admitted,
        verified=verified,
        directive=directive,
        worksheet_catalog=worksheet_catalog,
        extractor=extractor,
        artifact_identity=artifact_identity,
        verification_policy=verification_policy,
    )
