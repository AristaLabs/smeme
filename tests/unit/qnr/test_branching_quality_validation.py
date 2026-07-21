"""Generation-path branching quality gates (Track A)."""

from smeme.qnr.generation.agentic.branching_quality import (
    BRANCHING_QUALITY_PREFIX,
    assess_branching_quality,
    branching_quality_errors_are_auto_fixable,
    validate_branching_quality,
)
from smeme.qnr.generation.agentic.design_parse import parse_collect_only_question_ids
from smeme.qnr.helpers.validation import validate_graph_for_editing, validate_graph_for_generation
from smeme.qnr.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    QNRGraph,
    QNRMetadata,
    QuestionData,
)


def _funnel_graph() -> QNRGraph:
    """q3 has three edges that all target q4 (Georgia-style pseudo-branching)."""
    return QNRGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Product injury?",
                    type="radio",
                    options=["Yes", "No", "Unsure"],
                    required=True,
                ),
            ),
            GraphNode(
                id="q2",
                type="question",
                data=QuestionData(
                    text="Manufacturer?",
                    type="radio",
                    options=["Yes", "No", "Unsure"],
                    required=True,
                ),
            ),
            GraphNode(
                id="q3",
                type="question",
                data=QuestionData(
                    text="Defect type?",
                    type="radio",
                    options=[
                        "Yes - Design defect",
                        "Yes - Manufacturing defect",
                        "Unsure",
                    ],
                    required=True,
                ),
            ),
            GraphNode(
                id="q4",
                type="question",
                data=QuestionData(
                    text="Follow up?",
                    type="radio",
                    options=["Yes", "No"],
                    required=True,
                ),
            ),
            GraphNode(
                id="conclusion_1",
                type="conclusion",
                data=ConclusionData(title="Win", summary="Eligible"),
            ),
            GraphNode(
                id="conclusion_3",
                type="conclusion",
                data=ConclusionData(title="Out", summary="Not eligible"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="q2", condition="Yes"),
            GraphEdge(source="q1", target="q2", condition="Unsure"),
            GraphEdge(source="q1", target="conclusion_3", condition="No"),
            GraphEdge(source="q2", target="q3", condition="Yes"),
            GraphEdge(source="q2", target="q3", condition="Unsure"),
            GraphEdge(source="q2", target="conclusion_3", condition="No"),
            GraphEdge(source="q3", target="q4", condition="Yes - Design defect"),
            GraphEdge(source="q3", target="q4", condition="Yes - Manufacturing defect"),
            GraphEdge(source="q3", target="q4", condition="Unsure"),
            GraphEdge(source="q4", target="conclusion_1", condition="Yes"),
            GraphEdge(source="q4", target="conclusion_3", condition="No"),
        ],
        metadata=QNRMetadata(title="Funnel fixture"),
    )


def _prefix_funnel_graph() -> QNRGraph:
    """Q1→Q2→Q3→Q4 pass-through with no early split."""
    return QNRGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(text="Q1", type="radio", options=["A", "B"], required=True),
            ),
            GraphNode(
                id="q2",
                type="question",
                data=QuestionData(text="Q2", type="radio", options=["A", "B"], required=True),
            ),
            GraphNode(
                id="q3",
                type="question",
                data=QuestionData(text="Q3", type="radio", options=["A", "B"], required=True),
            ),
            GraphNode(
                id="q4",
                type="question",
                data=QuestionData(text="Q4", type="radio", options=["A", "B"], required=True),
            ),
            GraphNode(
                id="conclusion_1",
                type="conclusion",
                data=ConclusionData(title="Done", summary="End"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="q2", condition="A"),
            GraphEdge(source="q1", target="q2", condition="B"),
            GraphEdge(source="q2", target="q3", condition="A"),
            GraphEdge(source="q2", target="q3", condition="B"),
            GraphEdge(source="q3", target="q4", condition="A"),
            GraphEdge(source="q3", target="q4", condition="B"),
            GraphEdge(source="q4", target="conclusion_1", condition="A"),
            GraphEdge(source="q4", target="conclusion_1", condition="B"),
        ],
        metadata=QNRMetadata(title="Prefix funnel"),
    )


def _intake_then_branch_graph() -> QNRGraph:
    """Q1 single-target intake is OK when Q2 splits."""
    return QNRGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="In scope?",
                    type="radio",
                    options=["Yes", "Maybe"],
                    required=True,
                ),
            ),
            GraphNode(
                id="q2",
                type="question",
                data=QuestionData(text="Detail?", type="radio", options=["A", "B"], required=True),
            ),
            GraphNode(
                id="conclusion_1",
                type="conclusion",
                data=ConclusionData(title="Yes path", summary="Proceed"),
            ),
            GraphNode(
                id="conclusion_2",
                type="conclusion",
                data=ConclusionData(title="No path", summary="Stop"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="q2", condition="Yes"),
            GraphEdge(source="q1", target="q2", condition="Maybe"),
            GraphEdge(source="q2", target="conclusion_1", condition="A"),
            GraphEdge(source="q2", target="conclusion_2", condition="B"),
        ],
        metadata=QNRMetadata(title="Intake then branch"),
    )


def _branching_graph() -> QNRGraph:
    return QNRGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Eligible category?",
                    type="radio",
                    options=["Yes", "No"],
                    required=True,
                ),
            ),
            GraphNode(
                id="q2",
                type="question",
                data=QuestionData(
                    text="Detail?",
                    type="radio",
                    options=["A", "B"],
                    required=True,
                ),
            ),
            GraphNode(
                id="conclusion_1",
                type="conclusion",
                data=ConclusionData(title="Yes path", summary="Proceed"),
            ),
            GraphNode(
                id="conclusion_2",
                type="conclusion",
                data=ConclusionData(title="No path", summary="Stop"),
            ),
            GraphNode(
                id="conclusion_3",
                type="conclusion",
                data=ConclusionData(title="Alt outcome", summary="Other path"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="q2", condition="Yes"),
            GraphEdge(source="q1", target="conclusion_2", condition="No"),
            GraphEdge(source="q2", target="conclusion_1", condition="A"),
            GraphEdge(source="q2", target="conclusion_3", condition="B"),
        ],
        metadata=QNRMetadata(title="Good branching"),
    )


def test_fake_branching_is_error_with_diagnostic():
    assessment = assess_branching_quality(_funnel_graph())
    fake = [d for d in assessment.diagnostics if d.code == "FAKE_BRANCHING"]
    assert len(fake) == 1
    assert fake[0].node_id == "q3"
    assert fake[0].suggestion


def test_prefix_funnel_is_error():
    assessment = assess_branching_quality(_prefix_funnel_graph())
    assert any(d.code == "PREFIX_FUNNEL" for d in assessment.diagnostics)


def test_intake_single_target_is_warning_not_error():
    assessment = assess_branching_quality(_intake_then_branch_graph())
    early = [d for d in assessment.diagnostics if d.code == "EARLY_SINGLE_TARGET" and d.node_id == "q1"]
    assert len(early) == 1
    assert early[0].severity == "warning"
    assert not assessment.errors


def test_validate_graph_for_generation_blocks_fake_branching():
    result = validate_graph_for_generation(_funnel_graph())
    assert result["is_valid"] is False
    assert any(error.startswith(BRANCHING_QUALITY_PREFIX) for error in result["errors"])


def test_validate_graph_for_generation_accepts_intake_then_branch():
    result = validate_graph_for_generation(_intake_then_branch_graph())
    assert result["is_valid"] is True
    assert any("Early gate 'q1'" in warning for warning in result["warnings"])


def test_validate_graph_for_editing_allows_funnel():
    result = validate_graph_for_editing(_funnel_graph())
    assert result["is_valid"] is True


def test_validate_graph_for_generation_accepts_discriminating_tree():
    result = validate_graph_for_generation(_branching_graph())
    assert result["is_valid"] is True


def test_branching_metrics_emitted():
    assessment = assess_branching_quality(_branching_graph())
    assert assessment.metrics.question_count == 2
    assert assessment.metrics.reachable_conclusion_count == 3


def test_branching_quality_errors_not_auto_fixable():
    errors = validate_branching_quality(_funnel_graph())
    assert branching_quality_errors_are_auto_fixable(errors) is False


def test_collect_only_skips_fake_branching_error():
    design = """
#### Q1: Evidence quality
- **Type**: radio
- **Node kind**: collect_only
- **Options**: High, Low
"""
    collect_only_ids = parse_collect_only_question_ids(design)
    graph = QNRGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Evidence quality",
                    type="radio",
                    options=["High", "Low"],
                    required=True,
                    help_text="Needed for memo wording only.",
                ),
            ),
            GraphNode(
                id="q2",
                type="question",
                data=QuestionData(text="Next", type="radio", options=["A"], required=True),
            ),
            GraphNode(
                id="conclusion_1",
                type="conclusion",
                data=ConclusionData(title="End", summary="Done"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="q2", condition="High"),
            GraphEdge(source="q1", target="q2", condition="Low"),
            GraphEdge(source="q2", target="conclusion_1", condition="A"),
        ],
        metadata=QNRMetadata(title="Collect only"),
    )
    assessment = assess_branching_quality(graph, collect_only_question_ids=collect_only_ids)
    assert not any(d.code == "FAKE_BRANCHING" and d.node_id == "q1" for d in assessment.diagnostics)
