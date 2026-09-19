"""Inquire kernel value types. Not re-exported from ``smeme.reasoning``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, NewType

from smeme.reasoning.runtime.consistency_gate import (
    InconsistencyCause,
    PremiseInvariantError,
)

CanonicalProvenanceId = NewType("CanonicalProvenanceId", str)

DEFAULT_INQUIRE_MAX_SAT_CALLS = 2000
HARD_MAX_INQUIRE_SAT_CALLS = 10_000
DEFAULT_INQUIRE_TIMEOUT_MS = 5000
HARD_MAX_INQUIRE_TIMEOUT_MS = 30_000
DEFAULT_RESOLVING_SUPPORT_MAX_SAT_CALLS = 2000
HARD_MAX_RESOLVING_SUPPORT_SAT_CALLS = 10_000
DEFAULT_RESOLVING_SUPPORT_TIMEOUT_MS = 5000

InquiryAction = Literal["VERIFY", "ACQUIRE", "STOP"]
StopReason = Literal[
    "inconsistent",
    "verified_resolved_consequence",
    "not_resolvable_by_remaining_evidence_vocabulary",
    "no_joint_discriminator_within_budget",
    # Resolved(B) held, but exact S_R search hit SAT budget/timeout/unknown.
    # Distinct from operational_budget (Cons / Resolved / D1 / residual search).
    "resolving_support_incomplete",
    "operational_budget",
    "operational_timeout",
    "operational_unknown",
]
OperationalStatus = Literal["budget", "timeout", "unknown"]


@dataclass(frozen=True, slots=True)
class WorksheetPair:
    """Admitted worksheet assignment ``(q, a)`` after IR-canonical option labels."""

    question_id: str
    option: str


@dataclass(frozen=True, slots=True)
class AdmittedAssertion:
    """Live admitted pair plus opaque provenance. SAT ``E`` is only ``(q, a)``."""

    question_id: str
    option: str
    provenance_id: CanonicalProvenanceId

    def __post_init__(self) -> None:
        if not str(self.provenance_id).strip():
            raise PremiseInvariantError("empty provenance_id")


@dataclass(frozen=True, slots=True)
class VerificationKey:
    """§13.9.6 verification identity: ``(artifact, q, a, p, pv_version)``."""

    artifact_identity: str
    question_id: str
    option: str
    provenance_identity: str
    pv_version: str


def logical_evidence(admitted: tuple[AdmittedAssertion, ...]) -> dict[str, str]:
    """Project SAT ``E`` as ``{q: a}``. Duplicate ``question_id`` is an invariant failure."""
    evidence: dict[str, str] = {}
    for item in admitted:
        if item.question_id in evidence:
            msg = f"duplicate admitted question_id {item.question_id!r}"
            raise PremiseInvariantError(msg)
        evidence[item.question_id] = item.option
    return evidence


def verification_key_for(
    assertion: AdmittedAssertion,
    *,
    artifact_identity: str,
    pv_version: str,
) -> VerificationKey:
    return VerificationKey(
        artifact_identity=artifact_identity,
        question_id=assertion.question_id,
        option=assertion.option,
        provenance_identity=str(assertion.provenance_id),
        pv_version=pv_version,
    )


@dataclass(frozen=True, slots=True)
class InquiryBudget:
    """Shared operational budget for one ``ANALYZE`` call."""

    max_sat_calls: int = DEFAULT_INQUIRE_MAX_SAT_CALLS
    timeout_ms: int = DEFAULT_INQUIRE_TIMEOUT_MS
    max_residual_sat_calls: int | None = None
    max_resolving_support_sat_calls: int = DEFAULT_RESOLVING_SUPPORT_MAX_SAT_CALLS
    resolving_support_timeout_ms: int = DEFAULT_RESOLVING_SUPPORT_TIMEOUT_MS

    def __post_init__(self) -> None:
        _require_budget_range(
            "max_sat_calls",
            self.max_sat_calls,
            minimum=1,
            maximum=HARD_MAX_INQUIRE_SAT_CALLS,
        )
        _require_budget_range(
            "timeout_ms",
            self.timeout_ms,
            minimum=1,
            maximum=HARD_MAX_INQUIRE_TIMEOUT_MS,
        )
        if self.max_residual_sat_calls is not None:
            _require_budget_range(
                "max_residual_sat_calls",
                self.max_residual_sat_calls,
                minimum=0,
                maximum=HARD_MAX_INQUIRE_SAT_CALLS,
            )
        _require_budget_range(
            "max_resolving_support_sat_calls",
            self.max_resolving_support_sat_calls,
            minimum=1,
            maximum=HARD_MAX_RESOLVING_SUPPORT_SAT_CALLS,
        )
        _require_budget_range(
            "resolving_support_timeout_ms",
            self.resolving_support_timeout_ms,
            minimum=1,
            maximum=HARD_MAX_INQUIRE_TIMEOUT_MS,
        )


def _require_budget_range(name: str, value: int, *, minimum: int, maximum: int) -> None:
    if not minimum <= value <= maximum:
        message = f"{name} must be between {minimum} and {maximum}"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class InquiryDiagnostics:
    """Bounded operational diagnostics; attached to non-semantic ANALYZE stops."""

    phase: str
    operational_status: OperationalStatus
    sat_calls: int
    general_sat_calls: int
    resolving_support_sat_calls: int
    elapsed_ms: float
    max_sat_calls: int
    timeout_ms: int
    max_resolving_support_sat_calls: int
    resolving_support_timeout_ms: int


@dataclass(frozen=True, slots=True)
class WorksheetItem:
    """Extractor-facing stem and IR option labels for one question."""

    stem: str
    options: tuple[str, ...]


WorksheetCatalog = Mapping[str, WorksheetItem]


@dataclass(frozen=True, slots=True)
class InquiryDirective:
    """Orchestrator / test result of ``ANALYZE``. Not an extractor payload."""

    action: InquiryAction
    question_id: str | None = None
    option: str | None = None
    verification_key: VerificationKey | None = None
    stop_reason: StopReason | None = None
    inconsistency_cause: InconsistencyCause | None = None
    operational_status: OperationalStatus | None = None
    diagnostics: InquiryDiagnostics | None = None


@dataclass(frozen=True, slots=True)
class EvidenceQuestion:
    """Singleton worksheet question issued to the extractor (G9)."""

    question_id: str
    stem: str
    options: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExtractionTask:
    """Exactly one :class:`EvidenceQuestion`. No VERIFY/ACQUIRE flag, no conclusions."""

    question: EvidenceQuestion
