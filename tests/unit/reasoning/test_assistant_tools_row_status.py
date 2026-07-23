"""Tests for dashboard Tools column state (graph hash vs artifact)."""

from __future__ import annotations

from uuid import uuid4

from smeme.core.models import DecisionTree, ReasoningCompiledArtifact
from smeme.reasoning.assistant_tools_row_status import reasoning_tools_row_state
from smeme.reasoning.ir.types import IR_FORMAT_VERSION
from tests.unit.test_decision_tree_dashboard import _minimal_graph


def test_not_built_without_compiled_status():
    q = DecisionTree(
        id=uuid4(),
        author_id=uuid4(),
        title="t",
        graph_data=_minimal_graph(),
        reasoning_status=None,
    )
    assert reasoning_tools_row_state(q, None) == "not_built"


def test_not_built_without_artifact():
    q = DecisionTree(
        id=uuid4(),
        author_id=uuid4(),
        title="t",
        graph_data=_minimal_graph(),
        reasoning_status="compiled",
    )
    assert reasoning_tools_row_state(q, None) == "not_built"


def test_live_when_hashes_match():
    g = _minimal_graph()
    q = DecisionTree(
        id=uuid4(),
        author_id=uuid4(),
        title="t",
        graph_data=g,
        reasoning_status="compiled",
    )
    from smeme.decision_tree.helpers.db_queries import parse_graph_data
    from smeme.reasoning.graph_hash import canonical_graph_hash

    h = canonical_graph_hash(parse_graph_data(q))
    art = ReasoningCompiledArtifact(
        id=uuid4(),
        decision_tree_id=q.id,
        ir_json={"version": 1, "nodes": [], "edges": []},
        graph_hash=h,
        compiler_version="test",
        ir_format_version=IR_FORMAT_VERSION,
    )
    assert reasoning_tools_row_state(q, art) == "live"


def test_stale_when_graph_changed():
    g = _minimal_graph()
    q = DecisionTree(
        id=uuid4(),
        author_id=uuid4(),
        title="t",
        graph_data=g,
        reasoning_status="compiled",
    )
    art = ReasoningCompiledArtifact(
        id=uuid4(),
        decision_tree_id=q.id,
        ir_json={"version": 1, "nodes": [], "edges": []},
        graph_hash="0" * 64,
        compiler_version="test",
        ir_format_version=IR_FORMAT_VERSION,
    )
    assert reasoning_tools_row_state(q, art) == "stale"
