"""Pydantic types for evaluation audit trails (answers → evidence → facts)."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceConfidence(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    ABSENT = "absent"


class BlobEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atom: str = Field(
        max_length=256,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
        description="Symbol name tied to IR/Z3 bool",
    )
    value: bool
    source_span: str = Field(
        max_length=120,
        description="Verbatim excerpt or empty if absent (truncated audit projection)",
    )
    confidence: EvidenceConfidence


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atom: str
    value: bool
    fact_type: str = "USER_EDITABLE"


class ReasoningRawAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["raw"] = "raw"
    answers: dict[str, str | list[str] | None] = Field(default_factory=dict, max_length=512)
