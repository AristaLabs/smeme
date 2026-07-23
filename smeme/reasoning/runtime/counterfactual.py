"""Counterfactual reasoning: what-if comparison and how-to-reach repair search."""

from __future__ import annotations

import itertools
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

from z3 import And, Bool, BoolRef, Implies, Not, is_true, sat, unknown, unsat

from smeme.qnr.models import DTGraph
from smeme.reasoning.cevi.fact_projection import apply_canonical_facts_to_solver
from smeme.reasoning.ir.types import IR, IRNodeKind
from smeme.reasoning.runtime.assumptions import (
    EMPTY_ASSUMPTIONS,
    AssumptionsError,
    ReasoningAssumptions,
    apply_assumptions_to_solver,
    validate_assumptions,
)
from smeme.reasoning.runtime.canonical_facts import raw_answers_to_canonical_facts
from smeme.reasoning.runtime.evaluate import evaluate_reasoning
from smeme.reasoning.runtime.ingest_codes import sort_warnings
from smeme.reasoning.runtime.ingest_envelope import (
    ParsedIngestEnvelope,
    prepare_evaluate_ingest,
)
from smeme.reasoning.runtime.report_builder import build_evaluation_report
from smeme.reasoning.theory.compile_to_z3 import compile_ir_to_z3
from smeme.reasoning.theory.z3_symbols import radio_option_symbol_name

NormalizedAnswers = dict[str, str]
ReachMode = Literal["entailed", "possible"]
REACH_MODES: frozenset[str] = frozenset({"entailed", "possible"})

MAX_REPAIR_SAT_CALLS = 2000
DEFAULT_MAX_CHANGES = 3
HARD_MAX_CHANGES = 5
DEFAULT_TOP_K = 3
HARD_MAX_TOP_K = 10
DEFAULT_CHECK_TIMEOUT_MS = 5000
HARD_MAX_CHECK_TIMEOUT_MS = 30000


class CounterfactualError(Exception):
    """Domain failure with stable MCP ``error.code``."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


@dataclass
class WhatIfResult:
    before_report: dict[str, Any]
    after_report: dict[str, Any]
    delta: dict[str, Any]
    warnings: list[dict[str, Any]]
    assumptions: ReasoningAssumptions = field(default_factory=lambda: EMPTY_ASSUMPTIONS)


@dataclass
class RepairPlan:
    change_count: int
    changed_answers: dict[str, str]
    dropped_answers: list[str]
    preview_target_reached: bool
    preview_report: dict[str, Any]


@dataclass
class HowToReachResult:
    target_conclusion_id: str
    target_conclusion_title: str
    satisfiable: bool
    already_reachable: bool
    minimal_change_count: int | None
    plans: list[RepairPlan]
    blockers: dict[str, Any] | None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    reach_mode: ReachMode = "entailed"
    assumptions: ReasoningAssumptions = field(default_factory=lambda: EMPTY_ASSUMPTIONS)


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s.strip())


def normalized_from_answers(answers: dict[str, Any]) -> NormalizedAnswers:
    """Map ingest ``answers`` to non-empty option strings only."""
    out: NormalizedAnswers = {}
    for qid, val in answers.items():
        if val is None:
            continue
        if isinstance(val, list):
            if not val:
                continue
            text = str(val[0]).strip()
        else:
            text = str(val).strip()
        if text:
            out[str(qid)] = text
    return out


def merge_normalized_answers(
    base: NormalizedAnswers,
    override: NormalizedAnswers,
) -> NormalizedAnswers:
    merged = dict(base)
    merged.update(override)
    return merged


def merge_ingest_payloads(
    base_env: ParsedIngestEnvelope,
    override_env: ParsedIngestEnvelope,
    merged_answers: NormalizedAnswers,
) -> dict[str, Any]:
    """Build Shape C payload for merged assignment (override wins evidence refs per question)."""
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for it in base_env.evidence_items:
        eid = it.get("id")
        if isinstance(eid, str):
            evidence_by_id[eid] = it
    for it in override_env.evidence_items:
        eid = it.get("id")
        if isinstance(eid, str):
            evidence_by_id[eid] = it
    evidence_refs = dict(base_env.evidence_refs)
    evidence_refs.update(override_env.evidence_refs)
    return {
        "answers": dict(merged_answers),
        "evidence_items": list(evidence_by_id.values()),
        "evidence_refs": evidence_refs,
    }


def _candidate_titles(report: dict[str, Any]) -> dict[str, str | None]:
    """Map NFC title → status (or None if absent)."""
    out: dict[str, str | None] = {}
    for c in report.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        title = c.get("title")
        if not isinstance(title, str):
            continue
        out[_nfc(title)] = c.get("status") if isinstance(c.get("status"), str) else None
    return out


def build_what_if_delta(
    *,
    base_norm: NormalizedAnswers,
    merged_norm: NormalizedAnswers,
    before_report: dict[str, Any],
    after_report: dict[str, Any],
) -> dict[str, Any]:
    """Structured diff using report vocabulary only (§3.1)."""
    changed: list[dict[str, Any]] = []
    all_qids = sorted(set(base_norm) | set(merged_norm))
    for qid in all_qids:
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

    before_rk = before_report.get("result_kind")
    after_rk = after_report.get("result_kind")
    result_kind_changed = before_rk != after_rk

    before_headline = before_report.get("headline")
    after_headline = after_report.get("headline")
    headline_changed = before_headline != after_headline

    before_titles = _candidate_titles(before_report)
    after_titles = _candidate_titles(after_report)
    before_set = set(before_titles)
    after_set = set(after_titles)
    added_titles = sorted(after_set - before_set)
    removed_titles = sorted(before_set - after_set)

    status_changes: list[dict[str, Any]] = []
    for title in sorted(before_set & after_set):
        bs = before_titles.get(title)
        ast = after_titles.get(title)
        if bs != ast:
            status_changes.append(
                {
                    "title": title,
                    "before_status": bs,
                    "after_status": ast,
                }
            )

    outcome_changed = (
        result_kind_changed or bool(added_titles) or bool(removed_titles) or bool(status_changes)
    )

    return {
        "changed_answers": changed,
        "result_kind_changed": result_kind_changed,
        "before_result_kind": before_rk,
        "after_result_kind": after_rk,
        "headline_changed": headline_changed,
        "before_headline": before_headline,
        "after_headline": after_headline,
        "candidates": {
            "added_titles": added_titles,
            "removed_titles": removed_titles,
            "status_changes": status_changes,
        },
        "reasoning_path_changed": before_report.get("reasoning_path")
        != after_report.get("reasoning_path"),
        "outcome_changed": outcome_changed,
    }


def run_what_if(
    ir: IR,
    graph: DTGraph,
    *,
    base_payload: dict[str, Any],
    override_payload: dict[str, Any],
    assumptions: ReasoningAssumptions | None = None,
) -> WhatIfResult:
    """Compare baseline vs merged override assignments (two evaluate passes + delta).

    Optional ``assumptions`` apply the same force/forbid ``reach`` constraints
    (ALGEBRA §18) to both evaluate passes.
    """
    phi = assumptions if assumptions is not None else EMPTY_ASSUMPTIONS
    validate_assumptions(ir, phi)

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
    report_before = build_evaluation_report(graph=graph, envelope=base_env, eval_result=eval_before)

    merged_payload = merge_ingest_payloads(base_env, override_env, merged_norm)
    after_answers, after_env, after_warnings, _ = prepare_evaluate_ingest(ir, merged_payload)
    eval_after, _ = evaluate_reasoning(
        ir,
        raw_answers=after_answers,
        skip_ir_validation=True,
        assumptions=phi,
    )
    report_after = build_evaluation_report(graph=graph, envelope=after_env, eval_result=eval_after)

    delta = build_what_if_delta(
        base_norm=base_norm,
        merged_norm=merged_norm,
        before_report=report_before,
        after_report=report_after,
    )
    warnings = sort_warnings([*base_warnings, *override_warnings, *after_warnings])
    return WhatIfResult(
        before_report=report_before,
        after_report=report_after,
        delta=delta,
        warnings=warnings,
        assumptions=phi,
    )


def _question_ids(ir: IR) -> frozenset[str]:
    return frozenset(n.id for n in ir.nodes if n.kind == IRNodeKind.QUESTION)


def _conclusion_ids(ir: IR) -> frozenset[str]:
    return frozenset(n.id for n in ir.nodes if n.kind == IRNodeKind.CONCLUSION)


def conclusion_title_from_graph(graph: DTGraph, conclusion_id: str) -> str:
    for node in graph.nodes:
        if node.id == conclusion_id and node.is_conclusion():
            cd = node.conclusion_data
            if cd is not None and cd.title:
                return cd.title
    return conclusion_id


def _radio_option_atoms(ir: IR, ctx: Any) -> dict[str, dict[str, BoolRef]]:
    out: dict[str, dict[str, BoolRef]] = {}
    for n in ir.nodes:
        if n.kind != IRNodeKind.QUESTION or n.question is None:
            continue
        if n.question.qtype != "radio":
            continue
        atoms: dict[str, BoolRef] = {}
        for opt in n.question.options:
            sym = radio_option_symbol_name(n.id, opt)
            atoms[opt] = Bool(sym, ctx=ctx)
        out[n.id] = atoms
    return out


def _option_conjunction(
    option_atoms: dict[str, BoolRef],
    answer_label: str,
) -> BoolRef:
    clauses: list[BoolRef] = []
    answer_cmp = answer_label.strip().lower()
    for opt, bref in option_atoms.items():
        if opt.strip().lower() == answer_cmp:
            clauses.append(bref)
        else:
            clauses.append(Not(bref))
    if len(clauses) == 1:
        return clauses[0]
    return And(*clauses)


def _plan_signature(changed: dict[str, str], dropped: list[str]) -> tuple[tuple[str, str], ...]:
    items = [(q, changed[q]) for q in sorted(changed)]
    drop_sig = tuple(sorted(dropped))
    return (tuple(items), drop_sig)


def _set_solver_timeout(solver: Any, timeout_ms: int) -> None:
    solver.set("timeout", timeout_ms)


def _check_sat_budget(
    solver: Any,
    *,
    assumptions: list[BoolRef] | None,
    sat_calls: list[int],
    max_sat_calls: int,
) -> Any:
    if sat_calls[0] >= max_sat_calls:
        return "budget"
    if assumptions:
        chk = solver.check(*assumptions)
    else:
        chk = solver.check()
    sat_calls[0] += 1
    return chk


def entails_target(
    entail_solver: Any,
    reach: dict[str, BoolRef],
    ir: IR,
    repaired: NormalizedAnswers,
    target_id: str,
    *,
    sat_calls: list[int],
    max_sat_calls: int,
    timeout_ms: int,
) -> Literal["yes", "no", "timeout", "budget"]:
    """Return whether ``T ∧ E ⊨ reach(target)`` (UNSAT of ``T ∧ E ∧ ¬reach``)."""
    if sat_calls[0] >= max_sat_calls:
        return "budget"
    _set_solver_timeout(entail_solver, timeout_ms)
    entail_solver.push()
    raw: dict[str, str | None] = dict(repaired)
    canonical = raw_answers_to_canonical_facts(ir, raw)
    apply_canonical_facts_to_solver(entail_solver, ir, canonical, z3_ctx=entail_solver.ctx)
    entail_solver.add(Not(reach[target_id]))
    chk = entail_solver.check()
    sat_calls[0] += 1
    entail_solver.pop()
    if chk == unknown:
        return "timeout"
    if sat_calls[0] > max_sat_calls:
        return "budget"
    return "yes" if chk == unsat else "no"


def possible_target(
    possible_solver: Any,
    reach: dict[str, BoolRef],
    ir: IR,
    repaired: NormalizedAnswers,
    target_id: str,
    *,
    sat_calls: list[int],
    max_sat_calls: int,
    timeout_ms: int,
) -> Literal["yes", "no", "timeout", "budget"]:
    """Return whether ``SAT(T ∧ E ∧ reach(target))`` (exists a completing assignment)."""
    if sat_calls[0] >= max_sat_calls:
        return "budget"
    _set_solver_timeout(possible_solver, timeout_ms)
    possible_solver.push()
    raw: dict[str, str | None] = dict(repaired)
    canonical = raw_answers_to_canonical_facts(ir, raw)
    apply_canonical_facts_to_solver(possible_solver, ir, canonical, z3_ctx=possible_solver.ctx)
    possible_solver.add(reach[target_id])
    chk = possible_solver.check()
    sat_calls[0] += 1
    possible_solver.pop()
    if chk == unknown:
        return "timeout"
    if sat_calls[0] > max_sat_calls:
        return "budget"
    return "yes" if chk == sat else "no"


def _target_gate(
    mode: ReachMode,
    *,
    entail_solver: Any,
    possible_solver: Any,
    entail_reach: dict[str, BoolRef],
    possible_reach: dict[str, BoolRef],
    ir: IR,
    repaired: NormalizedAnswers,
    target_id: str,
    sat_calls: list[int],
    max_sat_calls: int,
    timeout_ms: int,
) -> Literal["yes", "no", "timeout", "budget"]:
    if mode == "possible":
        return possible_target(
            possible_solver,
            possible_reach,
            ir,
            repaired,
            target_id,
            sat_calls=sat_calls,
            max_sat_calls=max_sat_calls,
            timeout_ms=timeout_ms,
        )
    return entails_target(
        entail_solver,
        entail_reach,
        ir,
        repaired,
        target_id,
        sat_calls=sat_calls,
        max_sat_calls=max_sat_calls,
        timeout_ms=timeout_ms,
    )


def _realize_witness(
    model: Any,
    *,
    base_norm: NormalizedAnswers,
    freed_set: frozenset[str],
    reach: dict[str, BoolRef],
    option_atoms: dict[str, dict[str, BoolRef]],
) -> tuple[NormalizedAnswers, dict[str, str], list[str]] | None:
    repaired = dict(base_norm)
    changed: dict[str, str] = {}
    dropped: list[str] = []

    for qid in sorted(freed_set):
        rq = reach.get(qid)
        if rq is None:
            return None
        reach_val = is_true(model.eval(rq, model_completion=True))
        if not reach_val:
            if qid in repaired:
                del repaired[qid]
            if qid in base_norm:
                dropped.append(qid)
            continue

        atoms = option_atoms.get(qid)
        if not atoms:
            return None
        true_opts = [
            opt for opt, bref in atoms.items() if is_true(model.eval(bref, model_completion=True))
        ]
        if len(true_opts) != 1:
            return None
        opt = true_opts[0]
        base_ans = base_norm.get(qid)
        if base_ans is not None and opt.strip().lower() == base_ans.strip().lower():
            continue
        repaired[qid] = opt
        changed[qid] = opt

    dropped.sort()
    return repaired, changed, dropped


def _is_cosmetic_plan(
    *,
    base_norm: NormalizedAnswers,
    repaired: NormalizedAnswers,
    changed: dict[str, str],
    dropped: list[str],
    reach_mode: ReachMode,
    entail_solver: Any,
    possible_solver: Any,
    entail_reach: dict[str, BoolRef],
    possible_reach: dict[str, BoolRef],
    ir: IR,
    target_id: str,
    sat_calls: list[int],
    max_sat_calls: int,
    timeout_ms: int,
) -> bool:
    if not changed and not dropped:
        return True
    reverted = dict(repaired)
    for qid in changed:
        if qid in base_norm:
            reverted[qid] = base_norm[qid]
        else:
            reverted.pop(qid, None)
    for qid in dropped:
        if qid in base_norm:
            reverted[qid] = base_norm[qid]
    gate_rep = _target_gate(
        reach_mode,
        entail_solver=entail_solver,
        possible_solver=possible_solver,
        entail_reach=entail_reach,
        possible_reach=possible_reach,
        ir=ir,
        repaired=reverted,
        target_id=target_id,
        sat_calls=sat_calls,
        max_sat_calls=max_sat_calls,
        timeout_ms=timeout_ms,
    )
    gate_base = _target_gate(
        reach_mode,
        entail_solver=entail_solver,
        possible_solver=possible_solver,
        entail_reach=entail_reach,
        possible_reach=possible_reach,
        ir=ir,
        repaired=base_norm,
        target_id=target_id,
        sat_calls=sat_calls,
        max_sat_calls=max_sat_calls,
        timeout_ms=timeout_ms,
    )
    return gate_rep == "yes" and gate_base == "yes"


def _setup_search_solver(
    ir: IR,
    *,
    base_norm: NormalizedAnswers,
    target_id: str,
    locked: frozenset[str],
    timeout_ms: int,
    assumptions: ReasoningAssumptions = EMPTY_ASSUMPTIONS,
) -> tuple[
    Any, dict[str, BoolRef], dict[str, BoolRef], dict[str, dict[str, BoolRef]], dict[str, BoolRef]
]:
    search_solver, sym = compile_ir_to_z3(ir)
    reach = sym["nodes"]
    _set_solver_timeout(search_solver, timeout_ms)
    apply_assumptions_to_solver(search_solver, reach, assumptions)
    search_solver.add(reach[target_id])

    option_atoms = _radio_option_atoms(ir, search_solver.ctx)
    keep_by_qid: dict[str, BoolRef] = {}

    for qid, answer in sorted(base_norm.items()):
        atoms = option_atoms.get(qid)
        if not atoms:
            continue
        phi_q = _option_conjunction(atoms, answer)
        if qid in locked:
            search_solver.add(phi_q)
        else:
            keep_sym = f"ir_keep_{qid}"
            keep_q = Bool(keep_sym, ctx=search_solver.ctx)
            keep_by_qid[qid] = keep_q
            search_solver.add(Implies(keep_q, phi_q))

    return search_solver, reach, keep_by_qid, option_atoms, sym["guards"]


def _preflight_how_to_reach(
    ir: IR,
    *,
    base_norm: NormalizedAnswers,
    target_id: str,
    locked: frozenset[str],
    target_title: str,
    sat_calls: list[int],
    max_sat_calls: int,
    timeout_ms: int,
    assumptions: ReasoningAssumptions = EMPTY_ASSUMPTIONS,
) -> None:
    conclusion_ids = _conclusion_ids(ir)
    if target_id not in conclusion_ids:
        raise CounterfactualError(
            "invalid_target_conclusion_id",
            f'target_conclusion_id "{target_id}" is not a conclusion on this published workflow. '
            "Obtain conclusion ids from the SMEme editor or admin tooling — evaluate reports "
            f"do not include them. If you have a conclusion title, ask the workflow owner which "
            f'id matches "{target_title}".',
            target_conclusion_id=target_id,
        )

    structural_solver, sym = compile_ir_to_z3(ir)
    reach = sym["nodes"]
    _set_solver_timeout(structural_solver, timeout_ms)
    apply_assumptions_to_solver(structural_solver, reach, assumptions)
    structural_solver.add(reach[target_id])
    chk = structural_solver.check()
    sat_calls[0] += 1
    if chk == unknown:
        raise CounterfactualError(
            "solver_timeout",
            "The reasoning engine timed out on this repair search. Retry once with a smaller "
            "max_changes; if it persists, note the approximate time and contact the operator.",
        )
    if chk != sat:
        locked_list = ", ".join(sorted(locked)) if locked else "(none)"
        raise CounterfactualError(
            "target_not_reachable_under_locks",
            f'Conclusion "{target_title}" cannot be reached with the current answers and locked '
            f"questions ({locked_list}). Try removing locks, changing baseline answers, or pick a "
            "different target conclusion.",
            target_conclusion_title=target_title,
            locked_question_ids=sorted(locked),
        )

    if locked:
        locked_solver, locked_sym = compile_ir_to_z3(ir)
        locked_reach = locked_sym["nodes"]
        option_atoms = _radio_option_atoms(ir, locked_solver.ctx)
        _set_solver_timeout(locked_solver, timeout_ms)
        apply_assumptions_to_solver(locked_solver, locked_reach, assumptions)
        for qid in sorted(locked):
            ans = base_norm.get(qid)
            if ans is None:
                continue
            atoms = option_atoms.get(qid)
            if atoms:
                locked_solver.add(_option_conjunction(atoms, ans))
        locked_solver.add(locked_reach[target_id])
        chk2 = locked_solver.check()
        sat_calls[0] += 1
        if chk2 == unknown:
            raise CounterfactualError(
                "solver_timeout",
                "The reasoning engine timed out on this repair search. Retry once with a smaller "
                "max_changes; if it persists, note the approximate time and contact the operator.",
            )
        if chk2 != sat:
            locked_list = ", ".join(sorted(locked))
            raise CounterfactualError(
                "target_not_reachable_under_locks",
                f'Conclusion "{target_title}" cannot be reached with the current answers and locked '
                f"questions ({locked_list}). Try removing locks, changing baseline answers, or pick "
                "a different target conclusion.",
                target_conclusion_title=target_title,
                locked_question_ids=sorted(locked),
            )


def find_repairs_for_target(
    ir: IR,
    graph: DTGraph,
    *,
    base_norm: NormalizedAnswers,
    base_envelope: ParsedIngestEnvelope,
    target_conclusion_id: str,
    locked_question_ids: list[str] | None = None,
    max_changes: int = DEFAULT_MAX_CHANGES,
    top_k: int = DEFAULT_TOP_K,
    max_sat_calls: int = MAX_REPAIR_SAT_CALLS,
    check_timeout_ms: int = DEFAULT_CHECK_TIMEOUT_MS,
    reach_mode: str = "entailed",
    assumptions: ReasoningAssumptions | None = None,
) -> HowToReachResult:
    """Bounded cardinality-minimal answer-edit repair search (§4).

    ``reach_mode``:
    - ``entailed`` (default): accept plans only when ``T ∧ E' ⊨ reach(target)``.
    - ``possible``: accept plans when ``SAT(T ∧ E' ∧ reach(target))``.

    Optional ``assumptions`` force/forbid ``reach`` on IR nodes (ALGEBRA §18).
    """
    mode_raw = (reach_mode or "entailed").strip().lower()
    if mode_raw not in REACH_MODES:
        raise CounterfactualError(
            "invalid_reach_mode",
            f'reach_mode must be "entailed" or "possible" (got "{reach_mode}"). '
            "Use entailed when the outcome must hold for every completion of unanswered "
            "questions; possible when any completing assignment is enough.",
            reach_mode=reach_mode,
        )
    mode: ReachMode = "possible" if mode_raw == "possible" else "entailed"
    phi = assumptions if assumptions is not None else EMPTY_ASSUMPTIONS
    try:
        validate_assumptions(ir, phi)
    except AssumptionsError as exc:
        raise CounterfactualError(exc.code, exc.message, **exc.details) from exc

    max_changes = min(max(1, max_changes), HARD_MAX_CHANGES)
    top_k = min(max(1, top_k), HARD_MAX_TOP_K)
    check_timeout_ms = min(max(1, check_timeout_ms), HARD_MAX_CHECK_TIMEOUT_MS)
    locked = frozenset(locked_question_ids or [])
    question_ids = _question_ids(ir)

    for qid in locked:
        if qid not in question_ids:
            raise CounterfactualError(
                "invalid_locked_question_id",
                f'locked_question_ids contains unknown or non-question id "{qid}". '
                "Use question ids from smeme_reasoning_template_get for this workflow.",
                locked_question_id=qid,
            )

    target_title = conclusion_title_from_graph(graph, target_conclusion_id)
    sat_calls: list[int] = [0]

    _preflight_how_to_reach(
        ir,
        base_norm=base_norm,
        target_id=target_conclusion_id,
        locked=locked,
        target_title=target_title,
        sat_calls=sat_calls,
        max_sat_calls=max_sat_calls,
        timeout_ms=check_timeout_ms,
        assumptions=phi,
    )

    entail_solver, entail_sym = compile_ir_to_z3(ir)
    entail_reach = entail_sym["nodes"]
    _set_solver_timeout(entail_solver, check_timeout_ms)
    apply_assumptions_to_solver(entail_solver, entail_reach, phi)

    possible_solver, possible_sym = compile_ir_to_z3(ir)
    possible_reach = possible_sym["nodes"]
    _set_solver_timeout(possible_solver, check_timeout_ms)
    apply_assumptions_to_solver(possible_solver, possible_reach, phi)

    phase0 = _target_gate(
        mode,
        entail_solver=entail_solver,
        possible_solver=possible_solver,
        entail_reach=entail_reach,
        possible_reach=possible_reach,
        ir=ir,
        repaired=base_norm,
        target_id=target_conclusion_id,
        sat_calls=sat_calls,
        max_sat_calls=max_sat_calls,
        timeout_ms=check_timeout_ms,
    )
    if phase0 == "timeout":
        raise CounterfactualError(
            "solver_timeout",
            "The reasoning engine timed out on this repair search. Retry once with a smaller "
            "max_changes; if it persists, note the approximate time and contact the operator.",
        )
    if phase0 == "budget":
        return _how_to_reach_blocked(
            target_conclusion_id,
            target_title,
            code="search_cap_exceeded",
            message=(
                "Repair search hit the server search limit before finishing. This does not "
                "prove that no plan exists. Retry with a lower max_changes, fewer locked "
                "questions, or a narrower question set; if it persists, contact the operator."
            ),
            max_changes=max_changes,
            sat_calls=sat_calls[0],
            locked=locked,
            search_complete=False,
            reach_mode=mode,
            assumptions=phi,
        )
    if phase0 == "yes":
        return HowToReachResult(
            target_conclusion_id=target_conclusion_id,
            target_conclusion_title=target_title,
            satisfiable=True,
            already_reachable=True,
            minimal_change_count=0,
            plans=[],
            blockers=None,
            reach_mode=mode,
            assumptions=phi,
        )

    search_solver, reach, keep_by_qid, option_atoms, _guards = _setup_search_solver(
        ir,
        base_norm=base_norm,
        target_id=target_conclusion_id,
        locked=locked,
        timeout_ms=check_timeout_ms,
        assumptions=phi,
    )

    candidates = sorted(qid for qid in base_norm if qid not in locked)
    seen_signatures: set[tuple[tuple[str, str], ...]] = set()
    layer_plans: list[RepairPlan] = []
    budget_exhausted = False
    search_complete = False

    for freed_count in range(1, max_changes + 1):
        if budget_exhausted:
            break
        layer_plans = []
        for subset in itertools.combinations(candidates, freed_count):
            if sat_calls[0] >= max_sat_calls:
                budget_exhausted = True
                break
            freed_set = frozenset(subset)
            active = [keep_by_qid[q] for q in candidates if q not in freed_set and q in keep_by_qid]
            chk = _check_sat_budget(
                search_solver,
                assumptions=active,
                sat_calls=sat_calls,
                max_sat_calls=max_sat_calls,
            )
            if chk == "budget":
                budget_exhausted = True
                break
            if chk == unknown:
                raise CounterfactualError(
                    "solver_timeout",
                    "The reasoning engine timed out on this repair search. Retry once with a "
                    "smaller max_changes; if it persists, note the approximate time and contact "
                    "the operator.",
                )
            if chk != sat:
                continue

            model = search_solver.model()
            realized = _realize_witness(
                model,
                base_norm=base_norm,
                freed_set=freed_set,
                reach=reach,
                option_atoms=option_atoms,
            )
            if realized is None:
                continue
            repaired_norm, changed, dropped = realized
            sig = _plan_signature(changed, dropped)
            if sig in seen_signatures:
                continue

            # Search solver already asserts reach[target]; entailed mode still requires
            # the stronger gate. Possible mode accepts the SAT witness after realization.
            if mode == "entailed":
                ent = entails_target(
                    entail_solver,
                    entail_reach,
                    ir,
                    repaired_norm,
                    target_conclusion_id,
                    sat_calls=sat_calls,
                    max_sat_calls=max_sat_calls,
                    timeout_ms=check_timeout_ms,
                )
                if ent == "timeout":
                    raise CounterfactualError(
                        "solver_timeout",
                        "The reasoning engine timed out on this repair search. Retry once with a "
                        "smaller max_changes; if it persists, note the approximate time and contact "
                        "the operator.",
                    )
                if ent == "budget":
                    budget_exhausted = True
                    break
                if ent == "no":
                    continue

            realized_count = len(changed) + len(dropped)
            if realized_count == 0 or realized_count > max_changes:
                continue

            if _is_cosmetic_plan(
                base_norm=base_norm,
                repaired=repaired_norm,
                changed=changed,
                dropped=dropped,
                reach_mode=mode,
                entail_solver=entail_solver,
                possible_solver=possible_solver,
                entail_reach=entail_reach,
                possible_reach=possible_reach,
                ir=ir,
                target_id=target_conclusion_id,
                sat_calls=sat_calls,
                max_sat_calls=max_sat_calls,
                timeout_ms=check_timeout_ms,
            ):
                continue

            seen_signatures.add(sig)
            raw_for_eval: dict[str, str | None] = dict(repaired_norm)
            eval_result, _audit = evaluate_reasoning(
                ir,
                raw_answers=raw_for_eval,
                skip_ir_validation=True,
                assumptions=phi,
            )
            merged_payload = merge_ingest_payloads(base_envelope, base_envelope, repaired_norm)
            _, after_env, _after_warnings, _ = prepare_evaluate_ingest(ir, merged_payload)
            preview_report = build_evaluation_report(
                graph=graph,
                envelope=after_env,
                eval_result=eval_result,
            )
            layer_plans.append(
                RepairPlan(
                    change_count=realized_count,
                    changed_answers=changed,
                    dropped_answers=dropped,
                    preview_target_reached=True,
                    preview_report=preview_report,
                )
            )

        if budget_exhausted:
            break
        if layer_plans:
            layer_plans.sort(
                key=lambda p: (
                    p.change_count,
                    _plan_signature(p.changed_answers, p.dropped_answers),
                )
            )
            layer_plans = layer_plans[:top_k]
            break
    else:
        if not budget_exhausted:
            search_complete = True

    if layer_plans:
        min_cc = min(p.change_count for p in layer_plans)
        return HowToReachResult(
            target_conclusion_id=target_conclusion_id,
            target_conclusion_title=target_title,
            satisfiable=True,
            already_reachable=False,
            minimal_change_count=min_cc,
            plans=layer_plans,
            blockers=None,
            reach_mode=mode,
            assumptions=phi,
        )

    if budget_exhausted:
        return _how_to_reach_blocked(
            target_conclusion_id,
            target_title,
            code="search_cap_exceeded",
            message=(
                "Repair search hit the server search limit before finishing. This does not "
                "prove that no plan exists. Retry with a lower max_changes, fewer locked "
                "questions, or a narrower question set; if it persists, contact the operator."
            ),
            max_changes=max_changes,
            sat_calls=sat_calls[0],
            locked=locked,
            search_complete=False,
            reach_mode=mode,
            assumptions=phi,
        )

    return _how_to_reach_blocked(
        target_conclusion_id,
        target_title,
        code="no_plan_within_max_changes",
        message=(
            f"No answer-edit plan within max_changes={max_changes} would reach the target "
            f'outcome "{target_title}". The search completed within server limits — this is not '
            "a timeout. Try raising max_changes (up to 5), unlocking questions, or adjusting "
            "baseline answers."
        ),
        max_changes=max_changes,
        sat_calls=sat_calls[0],
        locked=locked,
        search_complete=search_complete,
        reach_mode=mode,
        assumptions=phi,
    )


def _how_to_reach_blocked(
    target_id: str,
    target_title: str,
    *,
    code: str,
    message: str,
    max_changes: int,
    sat_calls: int,
    locked: frozenset[str],
    search_complete: bool,
    reach_mode: ReachMode = "entailed",
    assumptions: ReasoningAssumptions = EMPTY_ASSUMPTIONS,
) -> HowToReachResult:
    return HowToReachResult(
        target_conclusion_id=target_id,
        target_conclusion_title=target_title,
        satisfiable=False,
        already_reachable=False,
        minimal_change_count=None,
        plans=[],
        blockers={
            "code": code,
            "message": message,
            "search_complete": search_complete,
            "max_changes_searched": max_changes,
            "sat_calls": sat_calls,
            "locked_question_ids": sorted(locked),
            "target_conclusion_title": target_title,
        },
        reach_mode=reach_mode,
        assumptions=assumptions,
    )


def how_to_reach_to_wire(result: HowToReachResult) -> dict[str, Any]:
    plans_wire = []
    for p in result.plans:
        entry: dict[str, Any] = {
            "change_count": p.change_count,
            "changed_answers": p.changed_answers,
            "dropped_answers": p.dropped_answers,
            "preview_report": p.preview_report,
        }
        if not result.already_reachable:
            entry["preview_target_reached"] = p.preview_target_reached
        plans_wire.append(entry)
    out: dict[str, Any] = {
        "target_conclusion_id": result.target_conclusion_id,
        "target_conclusion_title": result.target_conclusion_title,
        "reach_mode": result.reach_mode,
        "satisfiable": result.satisfiable,
        "already_reachable": result.already_reachable,
        "minimal_change_count": result.minimal_change_count,
        "plans": plans_wire,
        "blockers": result.blockers,
        "warnings": result.warnings,
    }
    wire_assumptions = result.assumptions.to_wire()
    if wire_assumptions is not None:
        out["assumptions"] = wire_assumptions
    return out


__all__ = [
    "CounterfactualError",
    "DEFAULT_CHECK_TIMEOUT_MS",
    "DEFAULT_MAX_CHANGES",
    "DEFAULT_TOP_K",
    "HARD_MAX_CHANGES",
    "HARD_MAX_TOP_K",
    "HowToReachResult",
    "MAX_REPAIR_SAT_CALLS",
    "NormalizedAnswers",
    "REACH_MODES",
    "ReachMode",
    "RepairPlan",
    "WhatIfResult",
    "build_what_if_delta",
    "conclusion_title_from_graph",
    "entails_target",
    "find_repairs_for_target",
    "how_to_reach_to_wire",
    "possible_target",
    "merge_ingest_payloads",
    "merge_normalized_answers",
    "normalized_from_answers",
    "run_what_if",
]
