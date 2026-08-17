"""Singleton extractor issue (calculus §13.9 / G9). Outside the trusted base."""

from __future__ import annotations

from smeme.reasoning.runtime.inquire.types import (
    EvidenceQuestion,
    ExtractionTask,
    WorksheetCatalog,
)


def build_extractor_issue(
    worksheet_catalog: WorksheetCatalog,
    question_id: str,
) -> ExtractionTask:
    """Exactly one stem + options. No conclusions, ``S_R``, or VERIFY vs ACQUIRE flag."""
    item = worksheet_catalog[question_id]
    return ExtractionTask(
        question=EvidenceQuestion(
            question_id=question_id,
            stem=item.stem,
            options=item.options,
        )
    )
