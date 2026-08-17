"""Deterministic fake ``P_v`` implementations. Not a public Inquire export."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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
)


@dataclass(frozen=True, slots=True)
class VerificationRequest:
    assertion: AdmittedAssertion


@dataclass(frozen=True, slots=True)
class VerificationResult:
    payload: object = None


class VerificationPolicy(Protocol):
    def decide(
        self, request: VerificationRequest, result: VerificationResult
    ) -> VerificationDecision: ...


@dataclass(frozen=True, slots=True)
class AlwaysRetainPolicy:
    def decide(
        self, request: VerificationRequest, result: VerificationResult
    ) -> VerificationDecision:
        _ = request, result
        return Retain()


@dataclass(frozen=True, slots=True)
class AlwaysRetractPolicy:
    def decide(
        self, request: VerificationRequest, result: VerificationResult
    ) -> VerificationDecision:
        _ = request, result
        return Retract()


@dataclass(frozen=True, slots=True)
class AlwaysInsufficientPolicy:
    def decide(
        self, request: VerificationRequest, result: VerificationResult
    ) -> VerificationDecision:
        _ = request, result
        return Insufficient()


@dataclass(frozen=True, slots=True)
class ReplaceWith:
    option: str
    provenance_id: CanonicalProvenanceId

    def decide(
        self, request: VerificationRequest, result: VerificationResult
    ) -> VerificationDecision:
        _ = request, result
        return Replace(option=self.option, provenance_id=self.provenance_id)
