"""Inquire trusted orchestration (calculus §13.9 caller loop). Not a shipped public surface.

This package is not re-exported from ``smeme.reasoning``. The deterministic kernel
lives in ``smeme.reasoning.runtime.inquire``; this package executes directives
without leaking VERIFY vs ACQUIRE to the extractor.
"""

from smeme.reasoning.orchestration.inquire.admit import AdmissionStep, admit_extraction
from smeme.reasoning.orchestration.inquire.execute import (
    ExecutionOutcome,
    execute_directive,
    step,
)
from smeme.reasoning.orchestration.inquire.types import (
    AbstainedExtraction,
    AnsweredExtraction,
    ExtractionResult,
    Extractor,
)
from smeme.reasoning.orchestration.inquire.verify import VerificationStep, verify_extraction

__all__ = [
    "AbstainedExtraction",
    "AdmissionStep",
    "AnsweredExtraction",
    "ExecutionOutcome",
    "ExtractionResult",
    "Extractor",
    "VerificationStep",
    "admit_extraction",
    "execute_directive",
    "step",
    "verify_extraction",
]
