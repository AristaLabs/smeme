from __future__ import annotations

from unittest.mock import patch

from smeme.decision_tree.models import (
    ConclusionData,
    DecisionTreeRegressionFixture,
    DTGraph,
    DTGraphMetadata,
    GraphEdge,
    GraphNode,
    QuestionData,
)
from smeme.reasoning.publish_readiness import assess_publish_readiness_sync
from smeme.reasoning.runtime.analyze import ConclusionSatQueryEnumeration


def _graph(fixture: DecisionTreeRegressionFixture | None = None) -> DTGraph:
    fixtures = [fixture] if fixture is not None else []
    return DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(text="Pick", options=["Yes", "No"], required=True),
            ),
            GraphNode(
                id="c_yes",
                type="conclusion",
                data=ConclusionData(title="Yes", summary="yes outcome"),
            ),
            GraphNode(
                id="c_no",
                type="conclusion",
                data=ConclusionData(title="No", summary="no outcome"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="c_yes", condition="Yes"),
            GraphEdge(source="q1", target="c_no", condition="No"),
        ],
        metadata=DTGraphMetadata(title="Fixture gate", regression_fixtures=fixtures),
    )


def test_matching_regression_fixture_allows_deploy() -> None:
    readiness = assess_publish_readiness_sync(
        _graph(
            DecisionTreeRegressionFixture(
                name="yes path",
                raw_answers={"q1": "Yes"},
                expected_conclusion_id="c_yes",
            )
        )
    )
    assert readiness.ready is True
    assert readiness.preflight_issues == []


def test_regression_fixture_outcome_change_blocks_deploy() -> None:
    readiness = assess_publish_readiness_sync(
        _graph(
            DecisionTreeRegressionFixture(
                name="yes path",
                raw_answers={"q1": "Yes"},
                expected_conclusion_id="c_no",
            )
        )
    )
    assert readiness.ready is False
    assert [issue.code for issue in readiness.preflight_issues] == ["REGRESSION_FIXTURE_FAILED"]


def test_invalid_regression_fixture_answer_blocks_deploy() -> None:
    readiness = assess_publish_readiness_sync(
        _graph(
            DecisionTreeRegressionFixture(
                name="bad option",
                raw_answers={"q1": "Maybe"},
                expected_conclusion_id="c_yes",
            )
        )
    )
    assert readiness.ready is False
    assert [issue.code for issue in readiness.preflight_issues] == ["REGRESSION_FIXTURE_INVALID"]


def test_theory_unsat_blocks_deploy_with_theory_unsat_code() -> None:
    """§11: Deploy refuses when SAT(T) fails — entry point emits THEORY_UNSAT."""
    fake = ConclusionSatQueryEnumeration(
        is_theory_satisfiable=False,
        conclusion_reachable={"c_yes": False, "c_no": False},
        conclusion_pairs_co_reachable={},
        validation_report=None,
    )
    with patch(
        "smeme.reasoning.publish_readiness.enumerate_conclusion_sat_queries",
        return_value=fake,
    ):
        readiness = assess_publish_readiness_sync(_graph())
    assert readiness.ready is False
    codes = [issue.code for issue in readiness.preflight_issues]
    assert "THEORY_UNSAT" in codes
    assert codes.count("DEAD_CONCLUSION") == 2


def test_dead_conclusion_blocks_deploy_with_dead_conclusion_code() -> None:
    """§11: Deploy refuses when SAT(T ∧ reach(c)) fails for some conclusion."""
    fake = ConclusionSatQueryEnumeration(
        is_theory_satisfiable=True,
        conclusion_reachable={"c_yes": True, "c_no": False},
        conclusion_pairs_co_reachable={("c_no", "c_yes"): False},
        validation_report=None,
    )
    with patch(
        "smeme.reasoning.publish_readiness.enumerate_conclusion_sat_queries",
        return_value=fake,
    ):
        readiness = assess_publish_readiness_sync(_graph())
    assert readiness.ready is False
    dead_issues = [i for i in readiness.preflight_issues if i.code == "DEAD_CONCLUSION"]
    assert len(dead_issues) == 1
    assert "c_no" in dead_issues[0].message
    assert "THEORY_UNSAT" not in [i.code for i in readiness.preflight_issues]
