"""Stage B: canonical ``fact:*`` records → existing ``ir_*`` solver symbol names (deterministic)."""

from __future__ import annotations

from typing import Any

from z3 import Bool, Not

from smeme.reasoning.ir.types import IR, IRNodeKind
from smeme.reasoning.runtime.canonical_facts import CanonicalFactRecord
from smeme.reasoning.runtime.schemas import BlobEvidenceItem, EvidenceConfidence, Fact
from smeme.reasoning.theory.z3_symbols import radio_option_symbol_name


class UnmappableFactAtomError(ValueError):
    """Stage B cannot map a canonical fact to a Z3 bool name for the loaded IR."""

    def __init__(self, fact_atom_id: str, detail: str = "") -> None:
        self.fact_atom_id = fact_atom_id
        msg = f"unmappable canonical fact atom: {fact_atom_id!r}"
        if detail:
            msg += f" ({detail})"
        super().__init__(msg)


def solver_symbol_for_canonical_fact(ir: IR, rec: CanonicalFactRecord) -> str:
    """
    Map one :class:`CanonicalFactRecord` to the ``ir_*`` symbol string used in Z3.

    Raises :class:`UnmappableFactAtomError` when the fact does not align with the IR catalog
    (expected for malformed blob inputs; the ``raw_answers`` path should only emit aligned facts).
    """
    nodes = {n.id: n for n in ir.nodes}
    node = nodes.get(rec.question_id)
    if node is None or node.kind != IRNodeKind.QUESTION or node.question is None:
        raise UnmappableFactAtomError(rec.fact_atom_id(), "unknown question id for IR")

    qshape = node.question
    opts = tuple(qshape.options)

    if rec.kind != "radio":
        raise UnmappableFactAtomError(rec.fact_atom_id(), f"unknown kind {rec.kind!r}")
    if qshape.qtype != "radio":
        raise UnmappableFactAtomError(rec.fact_atom_id(), "question is not radio")
    if rec.option_label is None or rec.option_label not in opts:
        raise UnmappableFactAtomError(
            rec.fact_atom_id(),
            "option_label not in IR question options",
        )
    return radio_option_symbol_name(rec.question_id, rec.option_label)


def apply_canonical_facts_to_solver(
    solver: Any,
    ir: IR,
    facts: list[CanonicalFactRecord],
    *,
    z3_ctx: Any,
) -> tuple[list[BlobEvidenceItem], list[Fact]]:
    """
    Project canonical facts to ``ir_*`` names, assert unit literals on ``solver``, and build
    audit :class:`BlobEvidenceItem` / :class:`Fact` rows using **projected** solver symbols.
    """
    items: list[BlobEvidenceItem] = []
    out_facts: list[Fact] = []

    for rec in facts:
        sym = solver_symbol_for_canonical_fact(ir, rec)
        items.append(
            BlobEvidenceItem(
                atom=sym,
                value=rec.value,
                source_span=rec.source_span,
                confidence=rec.confidence,
            )
        )
        if rec.confidence == EvidenceConfidence.ABSENT:
            continue
        ref = Bool(sym, ctx=z3_ctx)
        solver.add(ref if rec.value else Not(ref))
        out_facts.append(Fact(atom=sym, value=rec.value))

    return items, out_facts


__all__ = [
    "UnmappableFactAtomError",
    "apply_canonical_facts_to_solver",
    "solver_symbol_for_canonical_fact",
]
