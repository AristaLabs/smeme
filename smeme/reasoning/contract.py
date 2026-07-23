"""Reasoning authoring contract — stricter gate layered on tier-3 publication validation."""

from __future__ import annotations

from smeme.qnr.helpers.validation import has_cycle, validate_graph
from smeme.qnr.models import DTGraph


def enforce_reasoning_authoring_contract(graph: DTGraph) -> list[str]:
    """
    Return human-readable blocking errors, or [] if the graph can compile to validated IR.

    Uses the legacy strict ``validate_graph`` (single-message) plus explicit cycle check
    so symbolic reasoning and interactive navigation stay aligned.
    """
    if len(graph.get_conclusion_nodes()) < 2:
        return ["[Reasoning] At least two conclusion nodes are required."]

    ok, msg = validate_graph(graph)
    if not ok and msg:
        return [f"[Reasoning] {msg}"]

    cyc, cdesc = has_cycle(graph)
    if cyc and cdesc:
        return [f"[Reasoning] {cdesc}"]

    return []
