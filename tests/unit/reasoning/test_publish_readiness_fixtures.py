from __future__ import annotations

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


def _graph(fixture: DecisionTreeRegressionFixture) -> DTGraph:
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
        metadata=DTGraphMetadata(title="Fixture gate", regression_fixtures=[fixture]),
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
