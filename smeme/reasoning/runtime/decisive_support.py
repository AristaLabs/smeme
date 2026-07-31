"""Inclusion-minimal answer supports for an entailed conclusion (minimal sufficient evidence).

Finds ``S ⊆ answered evidence`` such that ``T ∧ S ∧ φ ⊨ reach(c)``, minimal under
inclusion. ``T`` and ``E`` are not rewritten — only ``S`` is searched. Product wire
exposes question ids + option strings only (D021) — not guards, paths, or ``reach``
symbols.

This is **not** abductive inference from incomplete or conflicting evidence (see
``smeme/reasoning/evaluate_semantics.md`` §9 decisive support). Z3 is used only as
an entailment oracle; this module does not treat ``unsat_core()`` as a guaranteed MUS.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from smeme.decision_tree.models import DTGraph
from smeme.reasoning.ir.types import IR, IRNodeKind
from smeme.reasoning.runtime.assumptions import (
    EMPTY_ASSUMPTIONS,
    AssumptionsError,
    ReasoningAssumptions,
    apply_assumptions_to_solver,
    validate_assumptions,
)
from smeme.reasoning.runtime.counterfactual import (
    DEFAULT_CHECK_TIMEOUT_MS,
    DEFAULT_TOP_K,
    HARD_MAX_CHECK_TIMEOUT_MS,
    HARD_MAX_TOP_K,
    MAX_REPAIR_SAT_CALLS,
    NormalizedAnswers,
    conclusion_title_from_graph,
    entails_target,
)
from smeme.reasoning.theory.compile_to_z3 import compile_ir_to_z3

MAX_SUPPORT_SAT_CALLS = MAX_REPAIR_SAT_CALLS


class DecisiveSupportError(Exception):
    """Domain failure with stable MCP ``error.code``."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


@dataclass(frozen=True)
class DecisiveSupport:
    """One inclusion-minimal answered-question support."""

    support_answers: NormalizedAnswers
    support_question_ids: tuple[str, ...]

    @classmethod
    def from_answers(cls, answers: NormalizedAnswers) -> DecisiveSupport:
        ids = tuple(sorted(answers))
        return cls(
            support_answers={qid: answers[qid] for qid in ids},
            support_question_ids=ids,
        )


@dataclass
class DecisiveSupportResult:
    target_conclusion_id: str
    target_conclusion_title: str
    supports: list[DecisiveSupport]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    assumptions: ReasoningAssumptions = field(default_factory=lambda: EMPTY_ASSUMPTIONS)

    def to_wire(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "target_conclusion_id": self.target_conclusion_id,
            "target_conclusion_title": self.target_conclusion_title,
            "supports": [
                {
                    "support_question_ids": list(s.support_question_ids),
                    "support_answers": dict(s.support_answers),
                    "support_size": len(s.support_question_ids),
                }
                for s in self.supports
            ],
            "count": len(self.supports),
            "warnings": self.warnings,
        }
        wire_assumptions = self.assumptions.to_wire()
        if wire_assumptions is not None:
            out["assumptions"] = wire_assumptions
        return out


def _conclusion_ids(ir: IR) -> frozenset[str]:
    return frozenset(n.id for n in ir.nodes if n.kind == IRNodeKind.CONCLUSION)


def _set_solver_timeout(solver: Any, timeout_ms: int) -> None:
    solver.set(timeout=timeout_ms)


def _entails(
    entail_solver: Any,
    reach: dict[str, Any],
    ir: IR,
    answers: NormalizedAnswers,
    target_id: str,
    *,
    sat_calls: list[int],
    max_sat_calls: int,
    timeout_ms: int,
) -> str:
    return entails_target(
        entail_solver,
        reach,
        ir,
        answers,
        target_id,
        sat_calls=sat_calls,
        max_sat_calls=max_sat_calls,
        timeout_ms=timeout_ms,
    )


def _raise_gate(gate: str) -> None:
    if gate == "timeout":
        raise DecisiveSupportError(
            "solver_timeout",
            "The reasoning engine timed out while computing answer support. "
            "Retry once; if it persists, note the approximate time and contact the operator.",
        )
    if gate == "budget":
        raise DecisiveSupportError(
            "search_cap_exceeded",
            "Answer-support search hit the server search limit before finishing. "
            "Retry with fewer answered questions or a narrower target; if it persists, "
            "contact the operator.",
        )


def _deletion_shrink(
    entail_solver: Any,
    reach: dict[str, Any],
    ir: IR,
    answers: NormalizedAnswers,
    target_id: str,
    *,
    sat_calls: list[int],
    max_sat_calls: int,
    timeout_ms: int,
) -> NormalizedAnswers:
    """Greedy deletion until no single answered question can be dropped."""
    current = dict(answers)
    progress = True
    while progress:
        progress = False
        for qid in sorted(current):
            candidate = {k: v for k, v in current.items() if k != qid}
            gate = _entails(
                entail_solver,
                reach,
                ir,
                candidate,
                target_id,
                sat_calls=sat_calls,
                max_sat_calls=max_sat_calls,
                timeout_ms=timeout_ms,
            )
            if gate in ("timeout", "budget"):
                _raise_gate(gate)
            if gate == "yes":
                current = candidate
                progress = True
                break
    return current


def _is_inclusion_minimal(
    entail_solver: Any,
    reach: dict[str, Any],
    ir: IR,
    answers: NormalizedAnswers,
    target_id: str,
    *,
    sat_calls: list[int],
    max_sat_calls: int,
    timeout_ms: int,
) -> bool:
    if not answers:
        return True
    for qid in sorted(answers):
        candidate = {k: v for k, v in answers.items() if k != qid}
        gate = _entails(
            entail_solver,
            reach,
            ir,
            candidate,
            target_id,
            sat_calls=sat_calls,
            max_sat_calls=max_sat_calls,
            timeout_ms=timeout_ms,
        )
        if gate in ("timeout", "budget"):
            _raise_gate(gate)
        if gate == "yes":
            return False
    return True


def find_minimal_decisive_supports(
    ir: IR,
    graph: DTGraph,
    *,
    base_norm: NormalizedAnswers,
    target_conclusion_id: str,
    top_k: int = DEFAULT_TOP_K,
    max_sat_calls: int = MAX_SUPPORT_SAT_CALLS,
    check_timeout_ms: int = DEFAULT_CHECK_TIMEOUT_MS,
    assumptions: ReasoningAssumptions | None = None,
) -> DecisiveSupportResult:
    """Return up to ``top_k`` inclusion-minimal answer supports that force ``target``.

    Requires ``T ∧ base_norm ∧ φ ⊨ reach(target)``. Empty ``base_norm`` is allowed
    only when the empty assignment already entails the target.
    """
    phi = assumptions if assumptions is not None else EMPTY_ASSUMPTIONS
    try:
        validate_assumptions(ir, phi)
    except AssumptionsError as exc:
        raise DecisiveSupportError(exc.code, exc.message, **exc.details) from exc

    top_k = min(max(1, top_k), HARD_MAX_TOP_K)
    check_timeout_ms = min(max(1, check_timeout_ms), HARD_MAX_CHECK_TIMEOUT_MS)

    if target_conclusion_id not in _conclusion_ids(ir):
        raise DecisiveSupportError(
            "invalid_target_conclusion_id",
            f'target_conclusion_id "{target_conclusion_id}" is not a conclusion on this '
            "workflow. Call smeme_reasoning_list_conclusions for valid ids.",
            target_conclusion_id=target_conclusion_id,
        )

    target_title = conclusion_title_from_graph(graph, target_conclusion_id)
    sat_calls: list[int] = [0]

    entail_solver, entail_sym = compile_ir_to_z3(ir)
    entail_reach = entail_sym["nodes"]
    _set_solver_timeout(entail_solver, check_timeout_ms)
    apply_assumptions_to_solver(entail_solver, entail_reach, phi)

    base_gate = _entails(
        entail_solver,
        entail_reach,
        ir,
        base_norm,
        target_conclusion_id,
        sat_calls=sat_calls,
        max_sat_calls=max_sat_calls,
        timeout_ms=check_timeout_ms,
    )
    if base_gate in ("timeout", "budget"):
        _raise_gate(base_gate)
    if base_gate != "yes":
        raise DecisiveSupportError(
            "target_not_entailed",
            f'Conclusion "{target_title}" is not forced by the current answers'
            + (" under the given path assumptions" if not phi.is_empty() else "")
            + ". Use smeme_reasoning_how_to_reach to explore answer edits, or "
            "smeme_reasoning_evaluate when you need the full report for this case.",
            target_conclusion_id=target_conclusion_id,
            target_conclusion_title=target_title,
        )

    answered_ids = sorted(base_norm)
    supports: list[DecisiveSupport] = []
    seen: set[frozenset[str]] = set()

    # Prefer a deletion-shrunk support first (usually the most useful single support).
    shrunk = _deletion_shrink(
        entail_solver,
        entail_reach,
        ir,
        base_norm,
        target_conclusion_id,
        sat_calls=sat_calls,
        max_sat_calls=max_sat_calls,
        timeout_ms=check_timeout_ms,
    )
    first = DecisiveSupport.from_answers(shrunk)
    supports.append(first)
    seen.add(frozenset(first.support_question_ids))

    if top_k == 1 or not answered_ids:
        return DecisiveSupportResult(
            target_conclusion_id=target_conclusion_id,
            target_conclusion_title=target_title,
            supports=supports,
            assumptions=phi,
        )

    # Enumerate other inclusion-minimal supports by increasing size (lex subsets).
    for size in range(len(answered_ids) + 1):
        if len(supports) >= top_k:
            break
        for combo in itertools.combinations(answered_ids, size):
            if len(supports) >= top_k:
                break
            key = frozenset(combo)
            if key in seen:
                continue
            # Skip supersets of an already-found minimal support.
            if any(found <= key for found in seen):
                continue
            candidate = {qid: base_norm[qid] for qid in combo}
            gate = _entails(
                entail_solver,
                entail_reach,
                ir,
                candidate,
                target_conclusion_id,
                sat_calls=sat_calls,
                max_sat_calls=max_sat_calls,
                timeout_ms=check_timeout_ms,
            )
            if gate in ("timeout", "budget"):
                _raise_gate(gate)
            if gate != "yes":
                continue
            if not _is_inclusion_minimal(
                entail_solver,
                entail_reach,
                ir,
                candidate,
                target_conclusion_id,
                sat_calls=sat_calls,
                max_sat_calls=max_sat_calls,
                timeout_ms=check_timeout_ms,
            ):
                continue
            support = DecisiveSupport.from_answers(candidate)
            supports.append(support)
            seen.add(frozenset(support.support_question_ids))

    return DecisiveSupportResult(
        target_conclusion_id=target_conclusion_id,
        target_conclusion_title=target_title,
        supports=supports,
        assumptions=phi,
    )


__all__ = [
    "DecisiveSupport",
    "DecisiveSupportError",
    "DecisiveSupportResult",
    "MAX_SUPPORT_SAT_CALLS",
    "find_minimal_decisive_supports",
]
