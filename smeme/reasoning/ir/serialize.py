"""JSON serialization for persisted IR artifacts (``IR_FORMAT_VERSION`` is the schema version)."""

from __future__ import annotations

from typing import Any

from smeme.reasoning.ir.types import (
    IR,
    IR_FORMAT_VERSION,
    Guard,
    IREdge,
    IRNode,
    IRNodeKind,
    IRQuestionShape,
)


def ir_to_json(ir: IR) -> dict[str, Any]:
    """Deterministic dict suitable for JSONB storage (sorted keys in nested lists via tuple source order)."""
    nodes_out: list[dict[str, Any]] = []
    for n in ir.nodes:
        q: dict[str, Any] | None = None
        if n.question is not None:
            q = {
                "qtype": n.question.qtype,
                "options": list(n.question.options),
            }
        nodes_out.append(
            {
                "id": n.id,
                "kind": n.kind.value,
                "question": q,
            }
        )
    return {
        "format_version": ir.format_version,
        "nodes": nodes_out,
        "edges": [
            {"source": e.source, "target": e.target, "guard_id": e.guard_id} for e in ir.edges
        ],
        "guards": [{"id": g.id, "expr": g.expr} for g in ir.guards],
    }


def ir_from_json(data: dict[str, Any]) -> IR:
    """Parse artifact JSON into :class:`IR`. Raises ``KeyError`` / ``ValueError`` on bad shapes."""
    fv = int(data["format_version"])
    if fv != IR_FORMAT_VERSION:
        msg = f"Unsupported IR format_version {fv!r}; expected {IR_FORMAT_VERSION}"
        raise ValueError(msg)

    nodes: list[IRNode] = []
    for row in data["nodes"]:
        kind = IRNodeKind(row["kind"])
        qraw = row.get("question")
        qshape: IRQuestionShape | None = None
        if qraw is not None:
            qt = qraw.get("qtype")
            if qt != "radio":
                msg = f"Unsupported IR question qtype {qt!r}; expected 'radio'"
                raise ValueError(msg)
            opts = tuple(qraw.get("options") or ())
            if not opts:
                msg = "IR radio question requires non-empty options for node " + repr(row.get("id"))
                raise ValueError(msg)
            qshape = IRQuestionShape(qtype="radio", options=opts)
        nodes.append(IRNode(id=row["id"], kind=kind, question=qshape))

    edges = tuple(
        IREdge(source=r["source"], target=r["target"], guard_id=r["guard_id"])
        for r in data["edges"]
    )
    guards = tuple(Guard(id=r["id"], expr=r["expr"]) for r in data["guards"])

    return IR(format_version=fv, nodes=tuple(nodes), edges=edges, guards=guards)
