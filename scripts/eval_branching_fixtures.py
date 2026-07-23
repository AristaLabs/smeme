#!/usr/bin/env python3
"""Print branching quality metrics and diagnostics for generation fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smeme.qnr.generation.agentic.branching_quality import assess_branching_quality  # noqa: E402
from smeme.qnr.helpers.validation import validate_graph_for_generation  # noqa: E402
from smeme.qnr.models import DTGraph  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "qnr_generation"


def eval_fixture(path: Path) -> None:
    payload = json.loads(path.read_text())
    graph = DTGraph(**payload["graph"])
    allowed = frozenset(payload.get("allowed_conclusion_ids", []))

    result = validate_graph_for_generation(
        graph,
        allowed_conclusion_ids=allowed or None,
        allowed_conclusions_parse_ok=bool(allowed),
    )
    assessment = assess_branching_quality(
        graph,
        allowed_conclusion_ids=allowed or None,
        allowed_conclusions_parse_ok=bool(allowed),
    )

    print(f"\n=== {payload.get('name', path.stem)} ===")
    print(f"Description: {payload.get('description', '')}")
    print(f"Generation valid: {result['is_valid']}")
    print(f"Errors: {len(result['errors'])} | Warnings: {len(result['warnings'])}")
    print("\nMetrics:")
    print(json.dumps(assessment.metrics.to_dict(), indent=2))
    print("\nDiagnostics:")
    for diag in assessment.diagnostics:
        print(f"  [{diag.severity}] {diag.code}: {diag.message}")
        print(f"    → {diag.suggestion}")


def main() -> None:
    paths = sorted(FIXTURES.glob("*.json"))
    if not paths:
        print(f"No fixtures in {FIXTURES}")
        return
    for path in paths:
        eval_fixture(path)


if __name__ == "__main__":
    main()
