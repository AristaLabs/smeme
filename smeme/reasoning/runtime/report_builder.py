"""Server-generated evaluation report (product-facing memo, no Z3 vocabulary on MCP wire)."""

from __future__ import annotations

import unicodedata
from typing import Any

from smeme.decision_tree.models import ConclusionData, DTGraph
from smeme.reasoning.runtime.evaluate import EvaluationResult
from smeme.reasoning.runtime.ingest_envelope import ParsedIngestEnvelope

REPORT_SCHEMA_VERSION = 1


def _normalize_text(s: str) -> str:
    return unicodedata.normalize("NFC", s.strip())


def _result_kind(eval_result: EvaluationResult) -> str:
    status = eval_result.status
    if status == "SAT_UNIQUE":
        return "concluded"
    if status == "SAT_AMBIGUOUS":
        return "multiple_outcomes_possible"
    if status == "UNDER_DETERMINED":
        return "needs_more_information"
    if status == "UNSAT":
        reason = eval_result.explanation.get("reason")
        if reason == "blob_conflict":
            return "sources_conflict"
        if reason == "assumptions_unsat":
            return "assumptions_inconsistent"
        return "answers_inconsistent"
    return "needs_more_information"


def _graph_question_labels(graph: DTGraph) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in graph.nodes:
        if not node.is_question():
            continue
        qd = node.question_data
        if qd is None:
            continue
        out[node.id] = _normalize_text(qd.text)
    return out


def _graph_conclusion_by_id(graph: DTGraph) -> dict[str, ConclusionData]:
    out: dict[str, ConclusionData] = {}
    for node in graph.nodes:
        if not node.is_conclusion():
            continue
        cd = node.conclusion_data
        if cd is not None:
            out[node.id] = cd
    return out


def _evidence_by_id(envelope: ParsedIngestEnvelope) -> dict[str, dict[str, Any]]:
    return {it["id"]: it for it in envelope.evidence_items if isinstance(it.get("id"), str)}


def _supporting_evidence_for_question(
    envelope: ParsedIngestEnvelope,
    qid: str,
    *,
    evidence_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    refs = envelope.evidence_refs.get(qid, [])
    out: list[dict[str, Any]] = []
    for rid in refs:
        it = evidence_index.get(rid)
        if it is None:
            continue
        block: dict[str, Any] = {"id": rid}
        for key in ("title", "locator", "locator_kind", "source_id", "retrieved_at", "excerpt"):
            if key in it:
                block[key] = it[key]
        out.append(block)
    return out


def _format_answer(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        return ", ".join(str(x) for x in val)
    return str(val)


def _topological_node_order(triggered_edges: list[Any]) -> list[str]:
    """Order nodes from fired edges.

    Accepts structured ``{source, target, guard_id}`` rows (current) and legacy
    ``\"source->target\"`` strings (persisted runs / older tests).
    """
    edges: list[tuple[str, str]] = []
    for te in triggered_edges:
        if isinstance(te, dict):
            src = te.get("source")
            tgt = te.get("target")
            if isinstance(src, str) and isinstance(tgt, str) and src and tgt:
                edges.append((src, tgt))
            continue
        if not isinstance(te, str) or "->" not in te:
            continue
        src, tgt = te.split("->", 1)
        edges.append((src.strip(), tgt.strip()))
    if not edges:
        return []
    nodes: set[str] = set()
    for s, t in edges:
        nodes.add(s)
        nodes.add(t)
    in_deg = dict.fromkeys(nodes, 0)
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for s, t in edges:
        adj[s].append(t)
        in_deg[t] = in_deg.get(t, 0) + 1
    queue = sorted(n for n in nodes if in_deg[n] == 0)
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for t in sorted(adj.get(n, [])):
            in_deg[t] -= 1
            if in_deg[t] == 0:
                queue.append(t)
        queue.sort()
    return order


def _build_candidates(
    graph: DTGraph,
    eval_result: EvaluationResult,
) -> list[dict[str, Any]]:
    conclusions = _graph_conclusion_by_id(graph)
    true_ids = eval_result.explanation.get("true_conclusions")
    if not isinstance(true_ids, list):
        true_ids = []
    selected_id = eval_result.true_conclusion_id
    candidates: list[dict[str, Any]] = []
    for cid in sorted(true_ids, key=str):
        cd = conclusions.get(cid)
        if cd is None:
            continue
        status = (
            "selected" if cid == selected_id and eval_result.status == "SAT_UNIQUE" else "possible"
        )
        if eval_result.status == "SAT_UNIQUE" and cid != selected_id:
            status = "possible"
        entry: dict[str, Any] = {
            "title": cd.title,
            "summary": cd.summary,
            "status": status,
        }
        if cd.recommendations:
            entry["recommendations"] = list(cd.recommendations)
        candidates.append(entry)
    if eval_result.status == "SAT_UNIQUE" and selected_id and not candidates:
        cd = conclusions.get(selected_id)
        if cd is not None:
            entry = {
                "title": cd.title,
                "summary": cd.summary,
                "status": "selected",
            }
            if cd.recommendations:
                entry["recommendations"] = list(cd.recommendations)
            candidates.append(entry)
    return candidates


def reasoning_path_node_ids(
    graph: DTGraph,
    envelope: ParsedIngestEnvelope,
    eval_result: EvaluationResult,
) -> list[str]:
    """IR node ids that appear as steps on the product reasoning path (ordered).

    Same membership filter as :func:`_build_reasoning_path` — answered questions on
    the triggered-edge topo order, plus conclusion nodes on that order.
    """
    question_labels = _graph_question_labels(graph)
    conclusions = _graph_conclusion_by_id(graph)
    path_order = _topological_node_order(eval_result.triggered_edges)
    out: list[str] = []
    for nid in path_order:
        if nid in question_labels:
            ans = envelope.answers.get(nid)
            if ans is None or (isinstance(ans, str) and not ans.strip()):
                continue
            out.append(nid)
        elif nid in conclusions:
            out.append(nid)
    return out


def _build_reasoning_path(
    graph: DTGraph,
    envelope: ParsedIngestEnvelope,
    eval_result: EvaluationResult,
    *,
    question_labels: dict[str, str],
    evidence_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    conclusions = _graph_conclusion_by_id(graph)
    path_order = _topological_node_order(eval_result.triggered_edges)
    steps: list[dict[str, Any]] = []
    step_no = 0
    for nid in path_order:
        if nid in question_labels:
            ans = envelope.answers.get(nid)
            if ans is None or (isinstance(ans, str) and not ans.strip()):
                continue
            step_no += 1
            steps.append(
                {
                    "step": step_no,
                    "kind": "answered",
                    "question": question_labels[nid],
                    "answer": _format_answer(ans),
                    "supporting_evidence": _supporting_evidence_for_question(
                        envelope, nid, evidence_index=evidence_index
                    ),
                }
            )
        elif nid in conclusions:
            cd = conclusions[nid]
            step_no += 1
            steps.append(
                {
                    "step": step_no,
                    "kind": "outcome",
                    "conclusion_title": cd.title,
                    "conclusion_summary": cd.summary,
                    **({"recommendations": list(cd.recommendations)} if cd.recommendations else {}),
                }
            )
    return steps


def _worksheet_question_ids(graph: DTGraph) -> list[str]:
    return sorted(
        (n.id for n in graph.nodes if n.is_question()),
        key=str,
    )


def _build_answer_sheet(
    graph: DTGraph,
    envelope: ParsedIngestEnvelope,
    *,
    question_labels: dict[str, str],
    evidence_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    sheet: list[dict[str, Any]] = []
    for qid in _worksheet_question_ids(graph):
        if qid not in question_labels:
            continue
        ans = envelope.answers.get(qid)
        if ans is None and qid not in envelope.evidence_refs:
            continue
        sheet.append(
            {
                "question": question_labels.get(qid, qid),
                "answer": _format_answer(ans) if ans is not None else "",
                "supporting_evidence": _supporting_evidence_for_question(
                    envelope, qid, evidence_index=evidence_index
                ),
            }
        )
    return sheet


def _answered_questions_on_path(
    path_order: list[str],
    *,
    question_labels: dict[str, str],
    envelope: ParsedIngestEnvelope,
) -> list[tuple[str, str, str]]:
    """Return (question_id, question_text, answer) for answered questions on the witness path."""
    out: list[tuple[str, str, str]] = []
    for nid in path_order:
        if nid not in question_labels:
            continue
        ans = envelope.answers.get(nid)
        if ans is None or (isinstance(ans, str) and not ans.strip()):
            continue
        out.append((nid, question_labels[nid], _format_answer(ans)))
    return out


def _not_reached_question_labels(
    graph: DTGraph,
    *,
    question_labels: dict[str, str],
    path_order: list[str],
) -> list[str]:
    on_path = set(path_order)
    return [
        question_labels[qid]
        for qid in _worksheet_question_ids(graph)
        if qid in question_labels and qid not in on_path
    ]


def _format_not_reached_sentence(not_reached: list[str]) -> str:
    if not not_reached:
        return ""
    if len(not_reached) == 1:
        return f'"{not_reached[0]}" was not reached on this path.'
    joined = "; ".join(f'"{label}"' for label in not_reached)
    return f"These questions were not reached on this path: {joined}."


def _build_routing_bridge_sentence(
    *,
    result_kind: str,
    answered_on_path: list[tuple[str, str, str]],
    not_reached: list[str],
) -> str:
    if not answered_on_path:
        return ""
    _qid, question, answer = answered_on_path[-1]
    if result_kind == "concluded":
        lead = f'This outcome follows from answering {answer} on "{question}".'
    elif result_kind == "multiple_outcomes_possible":
        lead = f'This path stops after answering {answer} on "{question}".'
    else:
        return ""
    tail = _format_not_reached_sentence(not_reached)
    if tail:
        return f"{lead} {tail}"
    return lead


def _join_memo_paragraphs(parts: list[str]) -> str:
    return "\n\n".join(p.strip() for p in parts if isinstance(p, str) and p.strip())


def _build_headline(
    graph: DTGraph,
    eval_result: EvaluationResult,
    result_kind: str,
) -> str:
    conclusions = _graph_conclusion_by_id(graph)
    if result_kind == "concluded" and eval_result.true_conclusion_id:
        cd = conclusions.get(eval_result.true_conclusion_id)
        if cd is not None:
            return cd.title
    if result_kind == "multiple_outcomes_possible":
        return "More than one outcome may apply"
    if result_kind == "answers_inconsistent":
        return "These answers cannot all hold together"
    if result_kind == "assumptions_inconsistent":
        return "These assumptions cannot hold with the answers provided"
    if result_kind == "sources_conflict":
        return "Sources conflict on the facts provided"
    if result_kind == "needs_more_information":
        return "More information is needed to reach a conclusion"
    return "Evaluation complete"


def _build_brief_memo(
    *,
    headline: str,
    result_kind: str,
    reasoning_path: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    answer_sheet: list[dict[str, Any]],
    routing_bridge: str = "",
) -> str:
    parts: list[str] = [headline.rstrip(".")]
    if result_kind == "concluded":
        for step in reasoning_path:
            if step.get("kind") == "outcome":
                summary = step.get("conclusion_summary")
                if isinstance(summary, str) and summary.strip():
                    parts.append(summary.strip())
                break
        if routing_bridge:
            parts.append(routing_bridge)
    elif result_kind == "multiple_outcomes_possible":
        if candidates:
            titles = [c.get("title", "") for c in candidates if c.get("title")]
            if titles:
                parts.append("Possible outcomes: " + "; ".join(titles) + ".")
        if routing_bridge:
            parts.append(routing_bridge)
    elif result_kind == "needs_more_information":
        unanswered = [row["question"] for row in answer_sheet if not row.get("answer")]
        if unanswered:
            parts.append("Still open: " + "; ".join(unanswered[:5]) + ".")
        else:
            parts.append("Additional answers or sources may be required.")
    elif result_kind == "answers_inconsistent":
        parts.append("Review the answers provided; they cannot all be true under this workflow.")
    elif result_kind == "assumptions_inconsistent":
        parts.append(
            "The forced or blocked path assumptions conflict with the answers or with each "
            "other under this workflow. Relax force_reachable_ids / force_unreachable_ids "
            "or adjust answers, then retry."
        )
    elif result_kind == "sources_conflict":
        parts.append("Review conflicting sources and resolve disagreements before re-evaluating.")
    return _join_memo_paragraphs(parts)


def build_evaluation_report(
    *,
    graph: DTGraph,
    envelope: ParsedIngestEnvelope,
    eval_result: EvaluationResult,
) -> dict[str, Any]:
    """Build product-facing ``report`` object for MCP evaluate (no Z3 field names)."""
    question_labels = _graph_question_labels(graph)
    evidence_index = _evidence_by_id(envelope)
    result_kind = _result_kind(eval_result)
    candidates = _build_candidates(graph, eval_result)
    reasoning_path = _build_reasoning_path(
        graph,
        envelope,
        eval_result,
        question_labels=question_labels,
        evidence_index=evidence_index,
    )
    answer_sheet = _build_answer_sheet(
        graph,
        envelope,
        question_labels=question_labels,
        evidence_index=evidence_index,
    )
    headline = _build_headline(graph, eval_result, result_kind)
    path_order = _topological_node_order(eval_result.triggered_edges)
    answered_on_path = _answered_questions_on_path(
        path_order,
        question_labels=question_labels,
        envelope=envelope,
    )
    not_reached = _not_reached_question_labels(
        graph,
        question_labels=question_labels,
        path_order=path_order,
    )
    routing_bridge = _build_routing_bridge_sentence(
        result_kind=result_kind,
        answered_on_path=answered_on_path,
        not_reached=not_reached,
    )
    brief_memo = _build_brief_memo(
        headline=headline,
        result_kind=result_kind,
        reasoning_path=reasoning_path,
        candidates=candidates,
        answer_sheet=answer_sheet,
        routing_bridge=routing_bridge,
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "result_kind": result_kind,
        "headline": headline,
        "brief_memo": brief_memo,
        "reasoning_path": reasoning_path,
        "candidates": candidates,
        "answer_sheet": answer_sheet,
    }


__all__ = [
    "REPORT_SCHEMA_VERSION",
    "build_evaluation_report",
    "reasoning_path_node_ids",
]
