"""Symbolic IR value types (immutable). Guard ``expr`` strings are interpreted in theory as **radio** option labels (or :data:`DEFAULT_GUARD_EXPR` for default edges)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

# Semantics: ``expr == DEFAULT_GUARD_EXPR`` is the **default / unconditional** edge (logically TRUE),
# not a missing or absent condition. Validators and theory must treat it as a first-class case.
DEFAULT_GUARD_EXPR: str = ""

# Bumped when the serialized IR shape changes (compiler output contract).
# v2: IRNode.question / IRQuestionShape (lossless question type + options for guard semantics).
# v3: Question vertices are radio-only (finite exclusive choice); checkbox/text removed from IR.
IR_FORMAT_VERSION: int = 3

QuestionTypeIR = Literal["radio"]


@dataclass(frozen=True, slots=True)
class IRQuestionShape:
    """Radio question shape: ``Guard.expr`` for non-default edges is an option label (exact string)."""

    qtype: QuestionTypeIR
    options: tuple[str, ...]


class IRNodeKind(str, Enum):
    """IR node role. Maps QNR `question` / `conclusion`; no separate STATE until QNR models it."""

    QUESTION = "question"
    CONCLUSION = "conclusion"


@dataclass(frozen=True, slots=True)
class IRNode:
    """One navigable or terminal vertex in the IR.

    ``question`` is set for :attr:`IRNodeKind.QUESTION` (lossless carry-over from QNR
    ``QuestionData``); conclusions use ``None``.
    """

    id: str
    kind: IRNodeKind
    question: IRQuestionShape | None


@dataclass(frozen=True, slots=True)
class Guard:
    """Named guard.

    ``expr`` is opaque at the IR layer. Use :data:`DEFAULT_GUARD_EXPR` for the default-edge
    sentinel (always-true guard when the source question applies)—not “no condition” or missing data.
    The theory layer interprets non-default ``expr`` as a **radio** option label (exact match to
    one of that question's options).

    **Identity:** each edge keeps its own ``id`` even when two guards are semantically equivalent
    after canonicalization—do not merge rows in IR; Z3 ties semantics, not IR structure.
    """

    id: str
    expr: str


@dataclass(frozen=True, slots=True)
class IREdge:
    """Directed edge; guard_id references a Guard in the same IR."""

    source: str
    target: str
    guard_id: str


@dataclass(frozen=True, slots=True)
class IR:
    """Compiled intermediate representation of a QNR graph."""

    format_version: int
    nodes: tuple[IRNode, ...]
    edges: tuple[IREdge, ...]
    guards: tuple[Guard, ...]


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Result of :func:`validate_ir` (B0.5-lite structural checks)."""

    valid: bool
    errors: tuple[str, ...]
