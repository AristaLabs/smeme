"""Inquire kernel value types. Not re-exported from ``smeme.reasoning``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from smeme.reasoning.runtime.consistency_gate import InconsistencyCause
from smeme.reasoning.runtime.counterfactual import (
    DEFAULT_CHECK_TIMEOUT_MS,
    MAX_REPAIR_SAT_CALLS,
)

InquiryAction = Literal["VERIFY", "ACQUIRE", "STOP"]
StopReason = Literal[
    "inconsistent",
    "verified_resolved_consequence",
    "not_resolvable_by_remaining_evidence_vocabulary",
    "no_joint_discriminator_within_budget",
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
class VerificationKey:
    """§13.9.6 verification identity. Phase 1 compares equality only."""

    artifact_identity: str
    question_id: str
    option: str
    provenance_identity: str
    pv_version: str


@dataclass(frozen=True, slots=True)
class InquiryBudget:
    """Shared operational budget for one ``ANALYZE`` call."""

    max_sat_calls: int = MAX_REPAIR_SAT_CALLS
    timeout_ms: int = DEFAULT_CHECK_TIMEOUT_MS
    max_residual_sat_calls: int | None = None


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
    stop_reason: StopReason | None = None
    inconsistency_cause: InconsistencyCause | None = None
    operational_status: OperationalStatus | None = None


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
