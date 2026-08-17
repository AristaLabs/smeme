"""Inquire kernel (calculus §13.9 target). Not a shipped public surface.

This package is not re-exported from ``smeme.reasoning``.
"""

from smeme.reasoning.runtime.inquire.analyze import analyze_inquiry
from smeme.reasoning.runtime.inquire.extraction import build_extractor_issue
from smeme.reasoning.runtime.inquire.transition import apply_verification_decision

__all__ = ["analyze_inquiry", "build_extractor_issue", "apply_verification_decision"]
