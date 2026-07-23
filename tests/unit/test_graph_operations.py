"""Unit tests for DecisionTree graph operations.

These are pure unit tests - no database, no async, no network.
All operations are pure functions that take a graph and return a modified graph.

Tests cover:
- Node operations (create, update, delete for question and conclusion nodes)
- Edge operations (create, update, delete)
- Error cases (duplicate IDs, missing nodes, wrong node types)
- Immutability guarantees (original graph unchanged after operations)
- Condition normalization (empty string → None)
"""

import pytest

from smeme.decision_tree.editor.operations import (
    apply_operation,
    create_conclusion_node,
    create_edge,
    create_node,
    delete_edge,
    delete_node,
    update_conclusion_node,
    update_edge,
    update_node,
)
from smeme.decision_tree.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    DTGraphMetadata,
    QuestionData,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def empty_graph() -> DTGraph:
    """Empty graph for testing node creation."""
    return DTGraph(
        nodes=[],
        edges=[],
        metadata=DTGraphMetadata(title="Test Graph"),
    )


@pytest.fixture
def simple_graph() -> DTGraph:
    """Graph with one question and one conclusion for testing operations."""
    return DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="What is your preference?",
                    type="radio",
                    options=["Option A", "Option B"],
                    required=True,
                ),
            ),
            GraphNode(
                id="conclusion_1",
                type="conclusion",
                data=ConclusionData(
                    title="Result",
                    summary="Based on your selection",
                    recommendations=["Do this", "Do that"],
                    severity="info",
                ),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="conclusion_1", condition=None),
        ],
        metadata=DTGraphMetadata(title="Simple Test Graph"),
    )


@pytest.fixture
def multi_edge_graph() -> DTGraph:
    """Graph with multiple conditional edges for edge operation testing."""
    return DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Pick one",
                    type="radio",
                    options=["A", "B", "C"],
                    required=True,
                ),
            ),
            GraphNode(
                id="q2",
                type="question",
                data=QuestionData(
                    text="Follow-up for A",
                    type="radio",
                    options=["Y", "N"],
                    required=True,
                ),
            ),
            GraphNode(
                id="conclusion_a",
                type="conclusion",
                data=ConclusionData(
                    title="Path A",
                    summary="You chose A",
                ),
            ),
            GraphNode(
                id="conclusion_b",
                type="conclusion",
                data=ConclusionData(
                    title="Path B",
                    summary="You chose B",
                ),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="q2", condition="A"),
            GraphEdge(source="q1", target="conclusion_b", condition="B"),
            GraphEdge(source="q2", target="conclusion_a", condition="Y"),
        ],
        metadata=DTGraphMetadata(title="Multi-Edge Test Graph"),
    )


# =============================================================================
# Node Creation Tests
# =============================================================================


class TestCreateNode:
    """Tests for create_node function."""

    def test_create_question_node(self, empty_graph: DTGraph):
        """Create a basic radio question node."""
        result = create_node(
            empty_graph,
            node_id="q1",
            question_text="What is your name?",
            question_type="radio",
            options=["A", "B"],
        )

        assert len(result.nodes) == 1
        assert result.nodes[0].id == "q1"
        assert result.nodes[0].type == "question"
        assert result.nodes[0].data.text == "What is your name?"
        assert result.nodes[0].data.type == "radio"
        assert result.nodes[0].data.options == ["A", "B"]
        assert result.nodes[0].data.required is True

    def test_create_radio_node_with_options(self, empty_graph: DTGraph):
        """Create a radio node with options."""
        result = create_node(
            empty_graph,
            node_id="q1",
            question_text="Choose one",
            question_type="radio",
            options=["Yes", "No", "Maybe"],
        )

        assert result.nodes[0].data.type == "radio"
        assert result.nodes[0].data.options == ["Yes", "No", "Maybe"]

    def test_invalid_question_type_raises(self, empty_graph: DTGraph):
        with pytest.raises(ValueError, match="Only radio"):
            create_node(
                empty_graph,
                node_id="q1",
                question_text="Bad",
                question_type="checkbox",
                options=["Item 1", "Item 2"],
            )

    def test_create_node_with_help_text(self, empty_graph: DTGraph):
        """Create a node with help text."""
        result = create_node(
            empty_graph,
            node_id="q1",
            question_text="Enter your email",
            question_type="radio",
            options=["A", "B"],
            help_text="We won't spam you",
        )

        assert result.nodes[0].data.help_text == "We won't spam you"

    def test_create_node_duplicate_id_raises(self, simple_graph: DTGraph):
        """Creating a node with existing ID should raise ValueError."""
        with pytest.raises(ValueError, match="Node 'q1' already exists"):
            create_node(
                simple_graph,
                node_id="q1",
                question_text="Duplicate",
                question_type="radio",
                options=["X", "Y"],
            )

    def test_create_node_immutability(self, empty_graph: DTGraph):
        """Original graph should not be modified."""
        original_node_count = len(empty_graph.nodes)

        create_node(
            empty_graph,
            node_id="new_node",
            question_text="New question",
            question_type="radio",
            options=["1", "2"],
        )

        assert len(empty_graph.nodes) == original_node_count


class TestCreateConclusionNode:
    """Tests for create_conclusion_node function."""

    def test_create_conclusion_node(self, empty_graph: DTGraph):
        """Create a basic conclusion node."""
        result = create_conclusion_node(
            empty_graph,
            node_id="conclusion_1",
            title="Final Result",
            summary="This is the conclusion",
        )

        assert len(result.nodes) == 1
        assert result.nodes[0].id == "conclusion_1"
        assert result.nodes[0].type == "conclusion"
        assert result.nodes[0].data.title == "Final Result"
        assert result.nodes[0].data.summary == "This is the conclusion"
        assert result.nodes[0].data.recommendations == []
        assert result.nodes[0].data.severity == "info"

    def test_create_conclusion_with_recommendations(self, empty_graph: DTGraph):
        """Create conclusion with recommendations."""
        result = create_conclusion_node(
            empty_graph,
            node_id="conclusion_1",
            title="Action Required",
            summary="You need to act",
            recommendations=["Step 1", "Step 2", "Step 3"],
            severity="warning",
        )

        assert result.nodes[0].data.recommendations == ["Step 1", "Step 2", "Step 3"]
        assert result.nodes[0].data.severity == "warning"

    def test_create_conclusion_critical_severity(self, empty_graph: DTGraph):
        """Create conclusion with critical severity."""
        result = create_conclusion_node(
            empty_graph,
            node_id="conclusion_urgent",
            title="Urgent Action",
            summary="Immediate attention required",
            severity="critical",
        )

        assert result.nodes[0].data.severity == "critical"

    def test_create_conclusion_duplicate_id_raises(self, simple_graph: DTGraph):
        """Creating conclusion with existing ID should raise ValueError."""
        with pytest.raises(ValueError, match="Node 'conclusion_1' already exists"):
            create_conclusion_node(
                simple_graph,
                node_id="conclusion_1",
                title="Duplicate",
                summary="This should fail",
            )


# =============================================================================
# Node Update Tests
# =============================================================================


class TestUpdateNode:
    """Tests for update_node function."""

    def test_update_question_text(self, simple_graph: DTGraph):
        """Update question text."""
        result = update_node(
            simple_graph,
            node_id="q1",
            question_text="Updated question text",
            question_type="radio",
            options=["Option A", "Option B"],
        )

        updated_node = next(n for n in result.nodes if n.id == "q1")
        assert updated_node.data.text == "Updated question text"

    def test_update_question_type_stays_radio(self, simple_graph: DTGraph):
        """Update options while remaining radio-only."""
        result = update_node(
            simple_graph,
            node_id="q1",
            question_text="What is your preference?",
            question_type="radio",
            options=["Option A", "Option B", "Option C"],
        )

        updated_node = next(n for n in result.nodes if n.id == "q1")
        assert updated_node.data.type == "radio"
        assert len(updated_node.data.options) == 3

    def test_update_question_options(self, simple_graph: DTGraph):
        """Update question options."""
        result = update_node(
            simple_graph,
            node_id="q1",
            question_text="What is your preference?",
            question_type="radio",
            options=["New A", "New B", "New C"],
        )

        updated_node = next(n for n in result.nodes if n.id == "q1")
        assert updated_node.data.options == ["New A", "New B", "New C"]

    def test_update_nonexistent_node_raises(self, simple_graph: DTGraph):
        """Updating non-existent node should raise ValueError."""
        with pytest.raises(ValueError, match="Node 'nonexistent' not found"):
            update_node(
                simple_graph,
                node_id="nonexistent",
                question_text="This will fail",
                question_type="radio",
                options=["A", "B"],
            )

    def test_update_conclusion_as_question_raises(self, simple_graph: DTGraph):
        """Using update_node on conclusion should raise ValueError."""
        with pytest.raises(
            ValueError,
            match="Node 'conclusion_1' is a conclusion node. Use update_conclusion_node instead.",
        ):
            update_node(
                simple_graph,
                node_id="conclusion_1",
                question_text="This should fail",
                question_type="radio",
                options=["A", "B"],
            )

    def test_update_node_immutability(self, simple_graph: DTGraph):
        """Original graph should not be modified."""
        original_text = simple_graph.nodes[0].data.text

        update_node(
            simple_graph,
            node_id="q1",
            question_text="Changed text",
            question_type="radio",
            options=["Option A", "Option B"],
        )

        assert simple_graph.nodes[0].data.text == original_text


class TestUpdateConclusionNode:
    """Tests for update_conclusion_node function."""

    def test_update_conclusion_title(self, simple_graph: DTGraph):
        """Update conclusion title."""
        result = update_conclusion_node(
            simple_graph,
            node_id="conclusion_1",
            title="New Title",
            summary="Based on your selection",
        )

        updated_node = next(n for n in result.nodes if n.id == "conclusion_1")
        assert updated_node.data.title == "New Title"

    def test_update_conclusion_summary(self, simple_graph: DTGraph):
        """Update conclusion summary."""
        result = update_conclusion_node(
            simple_graph,
            node_id="conclusion_1",
            title="Result",
            summary="Updated summary content",
        )

        updated_node = next(n for n in result.nodes if n.id == "conclusion_1")
        assert updated_node.data.summary == "Updated summary content"

    def test_update_conclusion_severity(self, simple_graph: DTGraph):
        """Update conclusion severity."""
        result = update_conclusion_node(
            simple_graph,
            node_id="conclusion_1",
            title="Result",
            summary="Based on your selection",
            severity="critical",
        )

        updated_node = next(n for n in result.nodes if n.id == "conclusion_1")
        assert updated_node.data.severity == "critical"

    def test_update_nonexistent_conclusion_raises(self, simple_graph: DTGraph):
        """Updating non-existent node should raise ValueError."""
        with pytest.raises(ValueError, match="Node 'fake' not found"):
            update_conclusion_node(
                simple_graph,
                node_id="fake",
                title="This will fail",
                summary="Never created",
            )

    def test_update_question_as_conclusion_raises(self, simple_graph: DTGraph):
        """Using update_conclusion_node on question should raise ValueError."""
        with pytest.raises(
            ValueError,
            match="Node 'q1' is not a conclusion node. Use update_node instead.",
        ):
            update_conclusion_node(
                simple_graph,
                node_id="q1",
                title="This should fail",
                summary="Wrong function",
            )


# =============================================================================
# Node Deletion Tests
# =============================================================================


class TestDeleteNode:
    """Tests for delete_node function."""

    def test_delete_question_node(self, simple_graph: DTGraph):
        """Delete a question node."""
        result = delete_node(simple_graph, node_id="q1")

        assert len(result.nodes) == 1
        assert not any(n.id == "q1" for n in result.nodes)
        # Edge from q1 should also be removed
        assert not any(e.source == "q1" for e in result.edges)

    def test_delete_conclusion_node(self, simple_graph: DTGraph):
        """Delete a conclusion node."""
        result = delete_node(simple_graph, node_id="conclusion_1")

        assert len(result.nodes) == 1
        assert not any(n.id == "conclusion_1" for n in result.nodes)
        # Edge to conclusion_1 should also be removed
        assert not any(e.target == "conclusion_1" for e in result.edges)

    def test_delete_node_removes_all_connected_edges(self, multi_edge_graph: DTGraph):
        """Deleting a node removes all edges connected to it."""
        result = delete_node(multi_edge_graph, node_id="q1")

        # q1 had two outgoing edges (to q2 and conclusion_b)
        assert not any(e.source == "q1" or e.target == "q1" for e in result.edges)
        # Edge from q2 -> conclusion_a should remain
        assert any(e.source == "q2" and e.target == "conclusion_a" for e in result.edges)

    def test_delete_nonexistent_node_raises(self, simple_graph: DTGraph):
        """Deleting non-existent node should raise ValueError."""
        with pytest.raises(ValueError, match="Node 'nonexistent' not found"):
            delete_node(simple_graph, node_id="nonexistent")

    def test_delete_node_immutability(self, simple_graph: DTGraph):
        """Original graph should not be modified."""
        original_node_count = len(simple_graph.nodes)
        original_edge_count = len(simple_graph.edges)

        delete_node(simple_graph, node_id="q1")

        assert len(simple_graph.nodes) == original_node_count
        assert len(simple_graph.edges) == original_edge_count


# =============================================================================
# Edge Creation Tests
# =============================================================================


class TestCreateEdge:
    """Tests for create_edge function."""

    def test_create_default_edge(self, simple_graph: DTGraph):
        """Create an edge without condition (default path)."""
        # Add another node first
        graph = create_node(
            simple_graph,
            node_id="q2",
            question_text="Follow-up",
            question_type="radio",
            options=["Y", "N"],
        )

        result = create_edge(graph, source="q1", target="q2")

        new_edge = next(
            (e for e in result.edges if e.source == "q1" and e.target == "q2"),
            None,
        )
        assert new_edge is not None
        assert new_edge.condition is None

    def test_create_conditional_edge(self, simple_graph: DTGraph):
        """Create an edge with a condition."""
        # Add another node first
        graph = create_node(
            simple_graph,
            node_id="q2",
            question_text="Follow-up",
            question_type="radio",
            options=["Y", "N"],
        )

        result = create_edge(graph, source="q1", target="q2", condition="Option A")

        new_edge = next(
            (
                e
                for e in result.edges
                if e.source == "q1" and e.target == "q2" and e.condition == "Option A"
            ),
            None,
        )
        assert new_edge is not None

    def test_create_edge_missing_source_raises(self, simple_graph: DTGraph):
        """Creating edge from non-existent source should raise ValueError."""
        with pytest.raises(ValueError, match="Source node 'fake' not found"):
            create_edge(simple_graph, source="fake", target="conclusion_1")

    def test_create_edge_missing_target_raises(self, simple_graph: DTGraph):
        """Creating edge to non-existent target should raise ValueError."""
        with pytest.raises(ValueError, match="Target node 'fake' not found"):
            create_edge(simple_graph, source="q1", target="fake")

    def test_create_duplicate_edge_raises(self, simple_graph: DTGraph):
        """Creating duplicate edge should raise ValueError."""
        # Edge q1 -> conclusion_1 already exists
        with pytest.raises(
            ValueError,
            match="Edge from 'q1' to 'conclusion_1' with condition 'None' already exists",
        ):
            create_edge(simple_graph, source="q1", target="conclusion_1")

    def test_create_edge_same_nodes_different_condition_allowed(self, multi_edge_graph: DTGraph):
        """Multiple edges between same nodes with different conditions are allowed."""
        # Add edge from q1 to conclusion_a with condition "C"
        # (q1 already has edges to q2 with "A" and conclusion_b with "B")
        result = create_edge(multi_edge_graph, source="q1", target="conclusion_a", condition="C")

        edges_from_q1 = [e for e in result.edges if e.source == "q1"]
        assert len(edges_from_q1) == 3

    def test_create_edge_immutability(self, simple_graph: DTGraph):
        """Original graph should not be modified."""
        # Add a node to create edge to
        graph = create_node(
            simple_graph,
            node_id="q2",
            question_text="Follow-up",
            question_type="radio",
            options=["Y", "N"],
        )
        original_edge_count = len(graph.edges)

        create_edge(graph, source="q1", target="q2", condition="Option A")

        assert len(graph.edges) == original_edge_count


# =============================================================================
# Edge Update Tests
# =============================================================================


class TestUpdateEdge:
    """Tests for update_edge function."""

    def test_update_edge_target(self, multi_edge_graph: DTGraph):
        """Update edge target."""
        result = update_edge(
            multi_edge_graph,
            source="q1",
            old_target="q2",
            new_target="conclusion_a",
            old_condition="A",
            condition="A",
        )

        # Old edge should be gone
        assert not any(
            e.source == "q1" and e.target == "q2" and e.condition == "A" for e in result.edges
        )
        # New edge should exist
        assert any(
            e.source == "q1" and e.target == "conclusion_a" and e.condition == "A"
            for e in result.edges
        )

    def test_update_edge_condition(self, multi_edge_graph: DTGraph):
        """Update edge condition."""
        result = update_edge(
            multi_edge_graph,
            source="q1",
            old_target="q2",
            new_target="q2",
            old_condition="A",
            condition="New Condition",
        )

        updated_edge = next(
            (e for e in result.edges if e.source == "q1" and e.target == "q2"),
            None,
        )
        assert updated_edge is not None
        assert updated_edge.condition == "New Condition"

    def test_update_edge_condition_normalization_empty_to_none(self, multi_edge_graph: DTGraph):
        """Empty string condition should be normalized to None."""
        result = update_edge(
            multi_edge_graph,
            source="q1",
            old_target="q2",
            new_target="q2",
            old_condition="A",
            condition="",  # Empty string
        )

        updated_edge = next(
            (e for e in result.edges if e.source == "q1" and e.target == "q2"),
            None,
        )
        assert updated_edge.condition is None

    def test_update_edge_condition_normalization_whitespace_to_none(
        self, multi_edge_graph: DTGraph
    ):
        """Whitespace-only condition should be normalized to None."""
        result = update_edge(
            multi_edge_graph,
            source="q1",
            old_target="q2",
            new_target="q2",
            old_condition="A",
            condition="   ",  # Whitespace only
        )

        updated_edge = next(
            (e for e in result.edges if e.source == "q1" and e.target == "q2"),
            None,
        )
        assert updated_edge.condition is None

    def test_update_edge_not_found_raises(self, simple_graph: DTGraph):
        """Updating non-existent edge should raise ValueError."""
        with pytest.raises(
            ValueError,
            match="Edge from 'q1' to 'nonexistent' with condition 'None' not found",
        ):
            update_edge(
                simple_graph,
                source="q1",
                old_target="nonexistent",
                new_target="conclusion_1",
            )

    def test_update_edge_invalid_new_target_raises(self, simple_graph: DTGraph):
        """Updating edge to non-existent target should raise ValueError."""
        with pytest.raises(ValueError, match="Target node 'fake' not found"):
            update_edge(
                simple_graph,
                source="q1",
                old_target="conclusion_1",
                new_target="fake",
            )

    def test_update_edge_immutability(self, multi_edge_graph: DTGraph):
        """Original graph should not be modified."""
        original_edge = next(
            e for e in multi_edge_graph.edges if e.source == "q1" and e.condition == "A"
        )
        original_target = original_edge.target

        update_edge(
            multi_edge_graph,
            source="q1",
            old_target="q2",
            new_target="conclusion_a",
            old_condition="A",
            condition="A",
        )

        # Original should be unchanged
        current_edge = next(
            e for e in multi_edge_graph.edges if e.source == "q1" and e.condition == "A"
        )
        assert current_edge.target == original_target


# =============================================================================
# Edge Deletion Tests
# =============================================================================


class TestDeleteEdge:
    """Tests for delete_edge function."""

    def test_delete_default_edge(self, simple_graph: DTGraph):
        """Delete edge without condition."""
        result = delete_edge(simple_graph, source="q1", target="conclusion_1")

        assert len(result.edges) == 0

    def test_delete_conditional_edge(self, multi_edge_graph: DTGraph):
        """Delete edge with specific condition."""
        result = delete_edge(multi_edge_graph, source="q1", target="q2", condition="A")

        # Conditional edge should be gone
        assert not any(
            e.source == "q1" and e.target == "q2" and e.condition == "A" for e in result.edges
        )
        # Other edges should remain
        assert any(e.source == "q1" and e.target == "conclusion_b" for e in result.edges)

    def test_delete_edge_condition_normalization(self, simple_graph: DTGraph):
        """Empty string condition should match None edge."""
        result = delete_edge(simple_graph, source="q1", target="conclusion_1", condition="")

        assert len(result.edges) == 0

    def test_delete_edge_not_found_raises(self, simple_graph: DTGraph):
        """Deleting non-existent edge should raise ValueError."""
        with pytest.raises(
            ValueError,
            match="Edge from 'q1' to 'fake'",
        ):
            delete_edge(simple_graph, source="q1", target="fake")

    def test_delete_edge_wrong_condition_raises(self, multi_edge_graph: DTGraph):
        """Deleting edge with wrong condition should raise ValueError."""
        with pytest.raises(
            ValueError,
            match="Edge from 'q1' to 'q2'",
        ):
            delete_edge(multi_edge_graph, source="q1", target="q2", condition="WrongCondition")

    def test_delete_edge_immutability(self, simple_graph: DTGraph):
        """Original graph should not be modified."""
        original_edge_count = len(simple_graph.edges)

        delete_edge(simple_graph, source="q1", target="conclusion_1")

        assert len(simple_graph.edges) == original_edge_count


# =============================================================================
# Apply Operation (Dispatcher) Tests
# =============================================================================


class TestApplyOperation:
    """Tests for apply_operation dispatcher function."""

    def test_apply_create_node(self, empty_graph: DTGraph):
        """Apply create_node operation via dispatcher."""
        result = apply_operation(
            empty_graph,
            "create_node",
            {
                "node_id": "q1",
                "question_text": "Test question",
                "question_type": "radio",
                "options": ["Yes", "No"],
            },
        )

        assert len(result.nodes) == 1
        assert result.nodes[0].id == "q1"

    def test_apply_create_conclusion_node(self, empty_graph: DTGraph):
        """Apply create_conclusion_node operation via dispatcher."""
        result = apply_operation(
            empty_graph,
            "create_conclusion_node",
            {
                "node_id": "conclusion_1",
                "title": "Result",
                "summary": "Summary text",
            },
        )

        assert len(result.nodes) == 1
        assert result.nodes[0].type == "conclusion"

    def test_apply_update_node(self, simple_graph: DTGraph):
        """Apply update_node operation via dispatcher."""
        result = apply_operation(
            simple_graph,
            "update_node",
            {
                "node_id": "q1",
                "question_text": "Updated via dispatcher",
                "question_type": "radio",
                "options": ["A", "B"],
            },
        )

        updated = next(n for n in result.nodes if n.id == "q1")
        assert updated.data.text == "Updated via dispatcher"

    def test_apply_update_conclusion_node(self, simple_graph: DTGraph):
        """Apply update_conclusion_node operation via dispatcher."""
        result = apply_operation(
            simple_graph,
            "update_conclusion_node",
            {
                "node_id": "conclusion_1",
                "title": "Updated Title",
                "summary": "Updated summary",
            },
        )

        updated = next(n for n in result.nodes if n.id == "conclusion_1")
        assert updated.data.title == "Updated Title"

    def test_apply_delete_node(self, simple_graph: DTGraph):
        """Apply delete_node operation via dispatcher."""
        result = apply_operation(
            simple_graph,
            "delete_node",
            {"node_id": "q1"},
        )

        assert not any(n.id == "q1" for n in result.nodes)

    def test_apply_create_edge(self, simple_graph: DTGraph):
        """Apply create_edge operation via dispatcher."""
        # Add another node first
        graph = apply_operation(
            simple_graph,
            "create_node",
            {
                "node_id": "q2",
                "question_text": "Another question",
                "question_type": "radio",
                "options": ["Option A", "Option B"],
            },
        )

        result = apply_operation(
            graph,
            "create_edge",
            {"source": "q1", "target": "q2", "condition": "Option A"},
        )

        assert any(
            e.source == "q1" and e.target == "q2" and e.condition == "Option A"
            for e in result.edges
        )

    def test_apply_update_edge(self, multi_edge_graph: DTGraph):
        """Apply update_edge operation via dispatcher."""
        result = apply_operation(
            multi_edge_graph,
            "update_edge",
            {
                "source": "q1",
                "old_target": "q2",
                "new_target": "conclusion_a",
                "old_condition": "A",
                "new_condition": "A",
            },
        )

        assert any(
            e.source == "q1" and e.target == "conclusion_a" and e.condition == "A"
            for e in result.edges
        )

    def test_apply_delete_edge(self, simple_graph: DTGraph):
        """Apply delete_edge operation via dispatcher."""
        result = apply_operation(
            simple_graph,
            "delete_edge",
            {"source": "q1", "target": "conclusion_1"},
        )

        assert len(result.edges) == 0

    def test_apply_unknown_operation_raises(self, simple_graph: DTGraph):
        """Unknown operation should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown operation: fake_operation"):
            apply_operation(simple_graph, "fake_operation", {})


# =============================================================================
# Deep Copy / Immutability Tests
# =============================================================================


class TestImmutability:
    """Tests ensuring all operations are immutable."""

    def test_nested_data_immutability(self, simple_graph: DTGraph):
        """Nested data structures should also be copied, not shared."""
        original_options = simple_graph.nodes[0].data.options.copy()

        result = update_node(
            simple_graph,
            node_id="q1",
            question_text="Same question",
            question_type="radio",
            options=["Completely", "New", "Options"],
        )

        # Original nested data unchanged
        assert simple_graph.nodes[0].data.options == original_options

    def test_chained_operations_immutability(self, empty_graph: DTGraph):
        """Multiple chained operations shouldn't affect each other."""
        # Create first node
        graph1 = create_node(
            empty_graph,
            node_id="q1",
            question_text="First",
            question_type="radio",
            options=["Y", "N"],
        )

        # Create second node
        graph2 = create_node(
            graph1,
            node_id="q2",
            question_text="Second",
            question_type="radio",
            options=["Y", "N"],
        )

        # Original empty graph unchanged
        assert len(empty_graph.nodes) == 0

        # First graph unchanged
        assert len(graph1.nodes) == 1

        # Second graph has both
        assert len(graph2.nodes) == 2
