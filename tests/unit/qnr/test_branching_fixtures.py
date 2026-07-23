"""Fixture-based branching quality evals (Track A baseline)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smeme.qnr.generation.agentic.branching_quality import assess_branching_quality
from smeme.qnr.helpers.validation import validate_graph_for_editing, validate_graph_for_generation
from smeme.qnr.models import DTGraph

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "qnr_generation"


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text())


def _graph_from_fixture(payload: dict) -> DTGraph:
    return DTGraph(**payload["graph"])


@pytest.mark.parametrize(
    "fixture_name,expect_valid,expect_error_codes,expect_warning_codes",
    [
        (
            "georgia_product_liability",
            True,
            set(),
            {"HIGH_PATH_RATIO"},
        ),
    ],
)
def test_branching_fixture_eval(
    fixture_name, expect_valid, expect_error_codes, expect_warning_codes
):
    payload = _load_fixture(fixture_name)
    graph = _graph_from_fixture(payload)
    allowed = frozenset(payload.get("allowed_conclusion_ids", []))

    editing = validate_graph_for_editing(graph)
    assert editing["is_valid"] is True, "Fixture should be structurally valid (tier-2)"

    generation = validate_graph_for_generation(
        graph,
        allowed_conclusion_ids=allowed,
        allowed_conclusions_parse_ok=bool(allowed),
    )
    assert generation["is_valid"] is expect_valid

    assessment = assess_branching_quality(
        graph,
        allowed_conclusion_ids=allowed,
        allowed_conclusions_parse_ok=bool(allowed),
    )
    error_codes = {d.code for d in assessment.diagnostics if d.severity == "error"}
    warning_codes = {d.code for d in assessment.diagnostics if d.severity == "warning"}
    assert expect_error_codes.issubset(error_codes)
    assert expect_warning_codes.issubset(warning_codes)

    metrics = assessment.metrics.to_dict()
    assert metrics["question_count"] == 7
    assert metrics["conclusion_count"] == 3
    assert metrics["reachable_conclusion_count"] == 3


def test_georgia_fixture_metrics_snapshot():
    """Baseline metrics — Georgia passes Track A with warnings only (Track B candidate)."""
    payload = _load_fixture("georgia_product_liability")
    graph = _graph_from_fixture(payload)
    assessment = assess_branching_quality(graph)

    metrics = assessment.metrics.to_dict()
    assert metrics["max_path_length"] == 6
    assert metrics["path_length_ratio"] == pytest.approx(0.857, abs=0.01)
    assert metrics["early_distinct_target_count"] == 2
    assert metrics["same_target_node_count"] == 0
    assert metrics["reachable_conclusion_count"] == 3

    codes = {d.code for d in assessment.diagnostics}
    assert "HIGH_PATH_RATIO" in codes
    assert "FAKE_BRANCHING" not in codes
