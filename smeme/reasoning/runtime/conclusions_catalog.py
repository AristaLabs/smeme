"""Wire helpers for listing workflow conclusions (structural reachability catalog)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from smeme.qnr.models import DTGraph
from smeme.reasoning.runtime.analyze import ConclusionSatQueryEnumeration
from smeme.reasoning.runtime.counterfactual import conclusion_title_from_graph


def build_conclusions_catalog_wire(
    *,
    qnr_id: UUID,
    graph: DTGraph,
    enumeration: ConclusionSatQueryEnumeration,
) -> dict[str, Any]:
    """Product-shaped catalog of conclusion nodes and structural reachability.

    Uses :func:`~smeme.reasoning.runtime.analyze.enumerate_conclusion_sat_queries`
    outcomes — existential feasibility under published rules, not a specific user's
    answers. Pair with ``smeme_reasoning_evaluate`` for case-specific outcomes.
    """
    conclusions: list[dict[str, Any]] = []
    reachable_count = 0

    for cid in sorted(enumeration.conclusion_reachable):
        reachable = bool(enumeration.conclusion_reachable[cid])
        if reachable:
            reachable_count += 1

        entry: dict[str, Any] = {
            "conclusion_id": cid,
            "conclusion_title": conclusion_title_from_graph(graph, cid),
            "reachable": reachable,
        }
        for node in graph.nodes:
            if node.id != cid or not node.is_conclusion():
                continue
            cd = node.conclusion_data
            if cd is None:
                break
            entry["summary"] = cd.summary
            if cd.severity is not None:
                entry["severity"] = cd.severity
            break
        conclusions.append(entry)

    out: dict[str, Any] = {
        "qnr_id": str(qnr_id).lower(),
        "workflow_rules_consistent": enumeration.is_theory_satisfiable,
        "conclusions": conclusions,
        "count": len(conclusions),
        "reachable_count": reachable_count,
    }
    if not enumeration.is_theory_satisfiable:
        out["hint"] = (
            "This workflow's branching rules cannot all hold together. "
            "The owner should fix and re-publish it in the SMEme editor."
        )
    elif reachable_count < len(conclusions):
        out["hint"] = (
            "Some conclusions cannot be reached under the published rules. "
            "Unreachable entries are still listed with reachable=false."
        )
    return out
