"""Cycle detection on authored graphs, including chains deeper than the Python stack."""

from __future__ import annotations

import sys

from smeme.decision_tree.helpers.validation import has_cycle
from smeme.decision_tree.models import DTGraph

DEEP = sys.getrecursionlimit() * 3


def _graph(node_ids: list[str], edges: list[tuple[str, str]]) -> DTGraph:
    return DTGraph.model_validate(
        {
            "nodes": [
                {
                    "id": nid,
                    "type": "question",
                    "data": {"text": "Q?", "type": "radio", "options": ["a", "b"], "required": True},
                }
                for nid in node_ids
            ],
            "edges": [{"source": s, "target": t, "condition": None} for s, t in edges],
            "metadata": {"title": "t"},
        }
    )


def _chain(n: int) -> tuple[list[str], list[tuple[str, str]]]:
    ids = [f"q{i}" for i in range(n)]
    return ids, [(ids[i], ids[i + 1]) for i in range(n - 1)]


def test_has_cycle_reports_nodes_on_small_cycle() -> None:
    graph = _graph(["q1", "q2", "q3"], [("q1", "q2"), ("q2", "q3"), ("q3", "q1")])

    found, description = has_cycle(graph)

    assert found is True
    assert description is not None
    assert description.startswith("Cycle detected: ")
    assert {"q1", "q2", "q3"} <= set(description.removeprefix("Cycle detected: ").split(" → "))


def test_has_cycle_false_for_dag_with_shared_descendant() -> None:
    graph = _graph(["q1", "q2", "q3", "q4"], [("q1", "q2"), ("q1", "q3"), ("q2", "q4"), ("q3", "q4")])

    assert has_cycle(graph) == (False, None)


def test_has_cycle_handles_chain_deeper_than_recursion_limit() -> None:
    ids, edges = _chain(DEEP)

    assert has_cycle(_graph(ids, edges)) == (False, None)


def test_has_cycle_finds_back_edge_at_end_of_deep_chain() -> None:
    ids, edges = _chain(DEEP)
    edges.append((ids[-1], ids[0]))

    found, description = has_cycle(_graph(ids, edges))

    assert found is True
    assert description is not None
    assert {ids[0], ids[-1]} <= set(description.removeprefix("Cycle detected: ").split(" → "))
