#!/usr/bin/env python3
"""Load a saved DTGraph JSON, compile to IR, print IR + validation + enumeration + witness.

Usage:
  uv run python scripts/dt_reasoning_inspect.py
  uv run python scripts/dt_reasoning_inspect.py /path/to/dt_graph.json

Default JSON: tests/fixtures/reasoning/test_dt_graphs/sample_dt_graph.json (two-branch radio).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from smeme.decision_tree.models import DTGraph
from smeme.reasoning.ir.types import IR
from smeme.reasoning.ir.validate import validate_ir
from smeme.reasoning.dt_graph_bridge import compile_dt_graph_to_ir
from smeme.reasoning.runtime.analyze import enumerate_conclusion_sat_queries
from smeme.reasoning.runtime.run import solve_reachability_witness


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_fixture() -> Path:
    return (
        _repo_root()
        / "tests"
        / "fixtures"
        / "reasoning"
        / "test_dt_graphs"
        / "sample_dt_graph.json"
    )


def _ir_to_jsonable(ir: IR) -> dict[str, object]:
    nodes: list[dict[str, object]] = []
    for n in ir.nodes:
        q: dict[str, object] | None = None
        if n.question is not None:
            q = {
                "qtype": n.question.qtype,
                "options": list(n.question.options),
            }
        nodes.append({"id": n.id, "kind": n.kind.value, "question": q})
    return {
        "format_version": ir.format_version,
        "nodes": nodes,
        "edges": [
            {"source": e.source, "target": e.target, "guard_id": e.guard_id} for e in ir.edges
        ],
        "guards": [{"id": g.id, "expr": g.expr} for g in ir.guards],
    }


def _enumeration_to_jsonable(r) -> dict[str, object]:
    pairs = [
        {"conclusion_a": a, "conclusion_b": b, "co_reachable_sat": v}
        for (a, b), v in sorted(r.conclusion_pairs_co_reachable.items())
    ]
    return {
        "is_theory_satisfiable": r.is_theory_satisfiable,
        "conclusion_reachable": dict(sorted(r.conclusion_reachable.items())),
        "conclusion_pairs_co_reachable": pairs,
        "validation_valid": r.validation_report.valid if r.validation_report else None,
        "validation_errors": list(r.validation_report.errors) if r.validation_report else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Print DecisionTree → IR and Phase 1 reasoning outputs.")
    parser.add_argument(
        "json_path",
        nargs="?",
        type=Path,
        default=None,
        help="Path to DTGraph JSON (default: bundled sample fixture)",
    )
    args = parser.parse_args()
    path = args.json_path or _default_fixture()
    if not path.is_file():
        print(f"Not a file: {path}", file=sys.stderr)
        return 1

    raw = path.read_text(encoding="utf-8")
    graph = DTGraph.model_validate_json(raw)

    print("=== DTGraph (normalized dump) ===")
    print(json.dumps(graph.model_dump(mode="json"), indent=2))
    print()

    ir = compile_dt_graph_to_ir(graph)

    print("=== IR (compiled from DecisionTree) ===")
    print(json.dumps(_ir_to_jsonable(ir), indent=2))
    print()

    report = validate_ir(ir)
    print("=== validate_ir ===")
    print(json.dumps({"valid": report.valid, "errors": list(report.errors)}, indent=2))
    print()

    if not report.valid:
        print(
            "Skipping enumerate_conclusion_sat_queries / solve_reachability_witness — IR invalid.",
            file=sys.stderr,
        )
        return 2

    enum = enumerate_conclusion_sat_queries(ir, validate=True)
    print("=== enumerate_conclusion_sat_queries ===")
    print(json.dumps(_enumeration_to_jsonable(enum), indent=2))
    print()

    witness = solve_reachability_witness(ir, validate=True)
    print("=== solve_reachability_witness (ReachabilityWitness.to_dict) ===")
    print(json.dumps(witness.to_dict(), indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
