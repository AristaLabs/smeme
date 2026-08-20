"""Path sensitivity under a hypothetical answer edit (on-route entailment).

Primary query: after merging override answers into baseline ``E ↦ E'``, does
``T ∧ E' ∧ φ ⊨ ⋀_{n ∈ R} reach(n)`` for the baseline reasoning path ``R``?

Secondary: conclusion-entailment side-car under the same ``E'`` (still / newly /
no longer entailed). Product MCP name: ``smeme_reasoning_edit_affects_path``.
See ``docs/planning/sprint-mcp-path-under-edit.md`` and ``smeme/reasoning/evaluate_semantics.md`` (§9 logical analysis tools).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from smeme.decision_tree.models import DTGraph
from smeme.reasoning.ir.types import IR, IRNodeKind
from smeme.reasoning.runtime.assumptions import (
    EMPTY_ASSUMPTIONS,
    AssumptionsError,
    ReasoningAssumptions,
    validate_assumptions,
)
from smeme.reasoning.runtime.consistency_gate import ConsequenceQueryResult
from smeme.reasoning.runtime.counterfactual import (
    DEFAULT_CHECK_TIMEOUT_MS,
    HARD_MAX_CHECK_TIMEOUT_MS,
    MAX_REPAIR_SAT_CALLS,
    NormalizedAnswers,
    conclusion_title_from_graph,
    entails_target,
    merge_ingest_payloads,
    merge_normalized_answers,
    normalized_from_answers,
)
from smeme.reasoning.runtime.evaluate import evaluate_reasoning
from smeme.reasoning.runtime.ingest_codes import sort_warnings
from smeme.reasoning.runtime.ingest_envelope import prepare_evaluate_ingest
from smeme.reasoning.runtime.report_builder import reasoning_path_node_ids
from smeme.reasoning.theory.compile_to_z3 import compile_ir_to_z3

MAX_PATH_SAT_CALLS = MAX_REPAIR_SAT_CALLS


class PathUnderEditError(Exception):
    """Domain failure with stable MCP ``error.code``."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


@dataclass(frozen=True)
class PathNodeWire:
    """Blind report-vocabulary description of a path node."""

    kind: str  # "answered" | "outcome"
    label: str
    node_id: str | None = None  # conclusion_id only (worksheet / list_conclusions)

    def to_wire(self) -> dict[str, Any]:
        if self.kind == "outcome":
            out: dict[str, Any] = {
                "kind": "outcome",
                "conclusion_title": self.label,
            }
            if self.node_id is not None:
                out["conclusion_id"] = self.node_id
            return out
        return {"kind": "answered", "question": self.label}


@dataclass
class EditAffectsPathResult:
    path_still_entailed: bool
    path_nodes_lost: list[PathNodeWire]
    conclusions_still_entailed: list[dict[str, str]]
    conclusions_newly_entailed: list[dict[str, str]]
    conclusions_no_longer_entailed: list[dict[str, str]]
    changed_answers: list[dict[str, Any]]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    assumptions: ReasoningAssumptions = field(default_factory=lambda: EMPTY_ASSUMPTIONS)

    def to_wire(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path_still_entailed": self.path_still_entailed,
            "edit_affects_path": not self.path_still_entailed,
            "path_nodes_lost": [n.to_wire() for n in self.path_nodes_lost],
            "conclusions_still_entailed": list(self.conclusions_still_entailed),
            "conclusions_newly_entailed": list(self.conclusions_newly_entailed),
            "conclusions_no_longer_entailed": list(self.conclusions_no_longer_entailed),
            "changed_answers": list(self.changed_answers),
            "warnings": self.warnings,
        }
        wire_assumptions = self.assumptions.to_wire()
        if wire_assumptions is not None:
            out["assumptions"] = wire_assumptions
        return out


def _conclusion_ids(ir: IR) -> list[str]:
    return sorted(n.id for n in ir.nodes if n.kind == IRNodeKind.CONCLUSION)


def _question_label(graph: DTGraph, node_id: str) -> str:
    for node in graph.nodes:
        if node.id != node_id:
            continue
        data = node.data
        text = getattr(data, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        return node_id
    return node_id


def _path_node_wire(graph: DTGraph, ir: IR, node_id: str) -> PathNodeWire:
    kinds = {n.id: n.kind for n in ir.nodes}
    kind = kinds.get(node_id)
    if kind == IRNodeKind.CONCLUSION:
        return PathNodeWire(
            kind="outcome",
            label=conclusion_title_from_graph(graph, node_id),
            node_id=node_id,
        )
    return PathNodeWire(kind="answered", label=_question_label(graph, node_id))


def _conclusion_wire(graph: DTGraph, conclusion_id: str) -> dict[str, str]:
    return {
        "conclusion_id": conclusion_id,
        "conclusion_title": conclusion_title_from_graph(graph, conclusion_id),
    }


def _set_solver_timeout(solver: Any, timeout_ms: int) -> None:
    solver.set(timeout=timeout_ms)


def _entails_node(
    entail_solver: Any,
    reach: dict[str, Any],
    ir: IR,
    answers: NormalizedAnswers,
    node_id: str,
    *,
    sat_calls: list[int],
    max_sat_calls: int,
    timeout_ms: int,
    assumptions: ReasoningAssumptions = EMPTY_ASSUMPTIONS,
) -> ConsequenceQueryResult:
    return entails_target(
        entail_solver,
        reach,
        ir,
        answers,
        node_id,
        sat_calls=sat_calls,
        max_sat_calls=max_sat_calls,
        timeout_ms=timeout_ms,
        assumptions=assumptions,
    )


def _raise_gate(gate: ConsequenceQueryResult) -> None:
    if gate.status == "timeout":
        raise PathUnderEditError(
            "solver_timeout",
            "The path check timed out. Narrow the override answers and retry.",
        )
    if gate.status == "unknown":
        raise PathUnderEditError(
            "solver_unknown",
            "The path check returned an inconclusive result. Narrow the override and retry.",
        )
    if gate.status == "inconsistent":
        cause = gate.require_cause()
        raise PathUnderEditError(
            cause,
            (
                "These answers cannot all hold together."
                if cause == "answers_inconsistent"
                else "The path assumptions conflict with the answers or branching rules."
            ),
        )
    raise PathUnderEditError(
        "search_cap_exceeded",
        "The path check hit an internal search budget. Narrow the override and retry.",
    )


def _entailed_set(
    entail_solver: Any,
    reach: dict[str, Any],
    ir: IR,
    answers: NormalizedAnswers,
    node_ids: list[str],
    *,
    sat_calls: list[int],
    max_sat_calls: int,
    timeout_ms: int,
    assumptions: ReasoningAssumptions = EMPTY_ASSUMPTIONS,
) -> set[str]:
    out: set[str] = set()
    for nid in node_ids:
        gate = _entails_node(
            entail_solver,
            reach,
            ir,
            answers,
            nid,
            sat_calls=sat_calls,
            max_sat_calls=max_sat_calls,
            timeout_ms=timeout_ms,
            assumptions=assumptions,
        )
        if gate.status in ("timeout", "budget", "unknown", "inconsistent"):
            _raise_gate(gate)
        if gate.status == "entailed":
            out.add(nid)
    return out


def _changed_answers_wire(
    base_norm: NormalizedAnswers,
    merged_norm: NormalizedAnswers,
) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    for qid in sorted(set(base_norm) | set(merged_norm)):
        before_val = base_norm.get(qid)
        after_val = merged_norm.get(qid)
        if before_val != after_val:
            changed.append(
                {
                    "question_id": qid,
                    "before": before_val,
                    "after": after_val,
                }
            )
    return changed


def run_edit_affects_path(
    ir: IR,
    graph: DTGraph,
    *,
    base_payload: dict[str, Any],
    override_payload: dict[str, Any],
    assumptions: ReasoningAssumptions | None = None,
    check_timeout_ms: int = DEFAULT_CHECK_TIMEOUT_MS,
    max_sat_calls: int = MAX_PATH_SAT_CALLS,
) -> EditAffectsPathResult:
    """Return whether an answer edit breaks entailment of the baseline path ``R``."""
    phi = assumptions if assumptions is not None else EMPTY_ASSUMPTIONS
    try:
        validate_assumptions(ir, phi)
    except AssumptionsError as exc:
        raise PathUnderEditError(exc.code, exc.message, **exc.details) from exc

    check_timeout_ms = min(max(1, check_timeout_ms), HARD_MAX_CHECK_TIMEOUT_MS)
    sat_calls: list[int] = [0]

    base_answers, base_env, base_warnings, _ = prepare_evaluate_ingest(ir, base_payload)
    override_answers, override_env, override_warnings, _ = prepare_evaluate_ingest(
        ir, override_payload
    )

    base_norm = normalized_from_answers(base_answers)
    override_norm = normalized_from_answers(override_answers)
    merged_norm = merge_normalized_answers(base_norm, override_norm)

    eval_before, _ = evaluate_reasoning(
        ir,
        raw_answers=base_answers,
        skip_ir_validation=True,
        assumptions=phi,
    )
    path_ids = reasoning_path_node_ids(graph, base_env, eval_before)
    if not path_ids:
        raise PathUnderEditError(
            "path_not_entailed_at_baseline",
            "There is no forced decision path under the baseline answers yet. "
            "Call smeme_reasoning_evaluate / evaluate_continue to gather answers, "
            "smeme_reasoning_evaluate_answers for bulk Apply, or use "
            "smeme_reasoning_what_if when you want to see an alternate world.",
        )

    entail_solver, entail_sym = compile_ir_to_z3(ir)
    entail_reach = entail_sym["nodes"]
    _set_solver_timeout(entail_solver, check_timeout_ms)
    # φ admitted inside entails_target (E-then-φ), not on the outer solver.

    baseline_entailed = _entailed_set(
        entail_solver,
        entail_reach,
        ir,
        base_norm,
        path_ids,
        sat_calls=sat_calls,
        max_sat_calls=max_sat_calls,
        timeout_ms=check_timeout_ms,
        assumptions=phi,
    )
    missing = [nid for nid in path_ids if nid not in baseline_entailed]
    if missing:
        raise PathUnderEditError(
            "path_not_entailed_at_baseline",
            "The current decision path is not fully forced by the baseline answers"
            + (" under the given path assumptions" if not phi.is_empty() else "")
            + ". Call smeme_reasoning_evaluate / evaluate_continue to gather answers, "
            "smeme_reasoning_evaluate_answers for bulk Apply, or use "
            "smeme_reasoning_what_if when you want to see an alternate world.",
            path_nodes_not_entailed=[_path_node_wire(graph, ir, nid).to_wire() for nid in missing],
        )

    conclusion_ids = _conclusion_ids(ir)
    base_conclusions = _entailed_set(
        entail_solver,
        entail_reach,
        ir,
        base_norm,
        conclusion_ids,
        sat_calls=sat_calls,
        max_sat_calls=max_sat_calls,
        timeout_ms=check_timeout_ms,
        assumptions=phi,
    )

    merged_payload = merge_ingest_payloads(base_env, override_env, merged_norm)
    after_answers, _after_env, after_warnings, _ = prepare_evaluate_ingest(ir, merged_payload)
    after_norm = normalized_from_answers(after_answers)

    after_path_entailed = _entailed_set(
        entail_solver,
        entail_reach,
        ir,
        after_norm,
        path_ids,
        sat_calls=sat_calls,
        max_sat_calls=max_sat_calls,
        timeout_ms=check_timeout_ms,
        assumptions=phi,
    )
    lost_ids = [nid for nid in path_ids if nid not in after_path_entailed]
    path_still = not lost_ids

    after_conclusions = _entailed_set(
        entail_solver,
        entail_reach,
        ir,
        after_norm,
        conclusion_ids,
        sat_calls=sat_calls,
        max_sat_calls=max_sat_calls,
        timeout_ms=check_timeout_ms,
        assumptions=phi,
    )

    still = sorted(base_conclusions & after_conclusions)
    newly = sorted(after_conclusions - base_conclusions)
    lost_conc = sorted(base_conclusions - after_conclusions)

    warnings = sort_warnings([*base_warnings, *override_warnings, *after_warnings])
    return EditAffectsPathResult(
        path_still_entailed=path_still,
        path_nodes_lost=[_path_node_wire(graph, ir, nid) for nid in lost_ids],
        conclusions_still_entailed=[_conclusion_wire(graph, cid) for cid in still],
        conclusions_newly_entailed=[_conclusion_wire(graph, cid) for cid in newly],
        conclusions_no_longer_entailed=[_conclusion_wire(graph, cid) for cid in lost_conc],
        changed_answers=_changed_answers_wire(base_norm, after_norm),
        warnings=warnings,
        assumptions=phi,
    )


__all__ = [
    "EditAffectsPathResult",
    "MAX_PATH_SAT_CALLS",
    "PathNodeWire",
    "PathUnderEditError",
    "run_edit_affects_path",
]
