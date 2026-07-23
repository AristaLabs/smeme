"""Deterministic DTGraph → IR compilation (structure + question shape for guard semantics)."""

from __future__ import annotations

from smeme.decision_tree.models import DTGraph
from smeme.reasoning.ir.types import (
    DEFAULT_GUARD_EXPR,
    IR,
    IR_FORMAT_VERSION,
    Guard,
    IREdge,
    IRNode,
    IRNodeKind,
    IRQuestionShape,
)


def _node_kind(graph: DTGraph, node_id: str) -> IRNodeKind:
    node = graph.get_node(node_id)
    if node is None:
        msg = "Unknown node id: " + repr(node_id)
        raise ValueError(msg)
    if node.is_conclusion():
        return IRNodeKind.CONCLUSION
    return IRNodeKind.QUESTION


def _question_shape(graph: DTGraph, node_id: str) -> IRQuestionShape:
    node = graph.get_node(node_id)
    if not node or not node.is_question():
        msg = "Expected question node: " + repr(node_id)
        raise ValueError(msg)
    qd = node.question_data
    if not qd:
        msg = "Question node missing question_data: " + repr(node_id)
        raise ValueError(msg)
    if qd.type != "radio":
        msg = f"Unsupported question type for IR compilation: {qd.type!r} on {node_id!r}"
        raise ValueError(msg)
    opts = tuple(qd.options or ())
    if not opts:
        msg = "Radio question must define at least one option: " + repr(node_id)
        raise ValueError(msg)
    return IRQuestionShape(qtype="radio", options=opts)


def _ir_node(graph: DTGraph, node_id: str) -> IRNode:
    kind = _node_kind(graph, node_id)
    if kind == IRNodeKind.CONCLUSION:
        return IRNode(id=node_id, kind=kind, question=None)
    return IRNode(id=node_id, kind=kind, question=_question_shape(graph, node_id))


def compile_dt_graph_to_ir(graph: DTGraph) -> IR:
    """
    Map a DecisionTree graph to IR: nodes (with question shape), one guard per edge, sorted for stability.

    Edge order: (source, target, expr) lexicographically. Guard ids are ``g_000000``, ``g_000001``, …
    in that order. Node order: sorted by id.
    """
    sorted_ids = sorted(graph.node_ids)
    nodes = tuple(_ir_node(graph, nid) for nid in sorted_ids)

    sorted_edges = sorted(
        graph.edges,
        key=lambda e: (e.source, e.target, (e.condition or "").strip()),
    )
    guards: list[Guard] = []
    ir_edges: list[IREdge] = []
    for i, edge in enumerate(sorted_edges):
        gid = f"g_{i:06d}"
        expr = (edge.condition or "").strip() or DEFAULT_GUARD_EXPR
        guards.append(Guard(id=gid, expr=expr))
        ir_edges.append(IREdge(source=edge.source, target=edge.target, guard_id=gid))

    return IR(
        format_version=IR_FORMAT_VERSION,
        nodes=nodes,
        edges=tuple(ir_edges),
        guards=tuple(guards),
    )
