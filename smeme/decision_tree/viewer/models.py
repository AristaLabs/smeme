"""Viewer-specific models for DecisionTree graph visualization.

These models are ephemeral outputs of the Viewer Workflow.
They are NEVER used by the Editor Workflow.
"""

from typing import Any, NotRequired, TypedDict
from uuid import UUID

from pydantic import BaseModel, Field

from smeme.decision_tree.models import DTGraph

# =============================================================================
# Ephemeral Visualization Models (Viewer-Only Outputs)
# =============================================================================


class NodePosition(BaseModel):
    """Position of a node in the visualization (ephemeral, never persisted)."""

    x: float = Field(description="X coordinate in pixels")
    y: float = Field(description="Y coordinate in pixels")
    layer: int = Field(description="Hierarchical layer (0 = entry points)")


class VisualNode(BaseModel):
    """
    Visual representation of a node (ephemeral, viewer-only).

    Combines semantic data (from DTGraph) with visual layout.
    """

    id: str = Field(description="Node ID")
    label: str = Field(description="Display label (truncated question text)")
    tooltip: str | None = Field(
        default=None,
        description="Full hover text (question/conclusion text plus id)",
    )
    type: str = Field(default="question", description="Node type (always 'question')")
    position: NodePosition = Field(description="Visual position")
    is_selected: bool = Field(default=False, description="Whether node is selected")
    is_entry: bool = Field(default=False, description="Whether node is an entry point")
    is_terminal: bool = Field(default=False, description="Whether node is terminal")
    has_errors: bool = Field(default=False, description="Whether node has validation errors")
    has_warnings: bool = Field(default=False, description="Whether node has validation warnings")


class VisualEdge(BaseModel):
    """
    Visual representation of an edge (ephemeral, viewer-only).

    Combines semantic data (from DTGraph) with visual styling.

    Note: When multiple edges exist between the same source and target nodes,
    they are grouped into a single VisualEdge with multiple conditions.
    """

    source: str = Field(description="Source node ID")
    target: str = Field(description="Target node ID")
    condition: str | None = Field(
        default=None, description="Primary condition label (for single condition)"
    )
    conditions: list[str] = Field(
        default_factory=list, description="All conditions (when multiple exist)"
    )
    is_default: bool = Field(default=False, description="Whether this includes a default edge")
    is_highlighted: bool = Field(
        default=False, description="Whether edge is highlighted (connected to selected node)"
    )


class GraphVisualization(BaseModel):
    """
    Complete graph visualization output (ephemeral, viewer-only).

    This is the final output of the Viewer Workflow, containing:
    - Visual nodes with positions
    - Visual edges with styling
    - Layout metadata

    IMPORTANT: Never persisted, never used by Editor.
    """

    nodes: list[VisualNode] = Field(description="Visual nodes with positions")
    edges: list[VisualEdge] = Field(description="Visual edges with styling")
    width: int = Field(description="Canvas width in pixels")
    height: int = Field(description="Canvas height in pixels")
    selected_node_id: str | None = Field(default=None, description="ID of selected node (if any)")


# =============================================================================
# Viewer Workflow State (TypedDict for LangGraph)
# =============================================================================


class DecisionTreeViewerState(TypedDict):
    """
    LangGraph state for Viewer Workflow.

    The Viewer Workflow is read-only and fast (caching-friendly).
    """

    # Input
    decision_tree_id: UUID
    user_id: UUID
    selected_node_id: NotRequired[str | None]  # Optional node selection

    # Loaded data
    graph: NotRequired[DTGraph]  # Loaded from cache or DB
    decision_tree_title: NotRequired[str]
    is_public: NotRequired[bool]  # Controls public visibility
    was_ever_public: NotRequired[bool]  # Track if DecisionTree was ever public
    is_read_only: NotRequired[bool]  # Computed: is_public or was_ever_public
    is_owner: NotRequired[bool]  # Current user is the workflow author
    version_number: NotRequired[int]  # DecisionTree version (v1, v2, v3, etc.)
    parent_decision_tree: NotRequired[Any]  # Parent DecisionTree object if this is a child version
    intended_audience: NotRequired[str | None]  # Economics metadata (Sprint 6)
    use_case: NotRequired[str | None]  # Economics metadata (Sprint 6)
    reasoning_status: NotRequired[
        str | None
    ]  # "compiled" once reasoning artifact published, else None
    research_corpus_present: NotRequired[bool]
    research_corpus_bytes: NotRequired[int]
    research_corpus_body: NotRequired[str]
    tools_row_state: NotRequired[str]  # live | stale | not_built
    editor_view: NotRequired[str]
    warnings: NotRequired[list[str]]  # Validation warnings for drafts (legacy)
    validation_data: NotRequired[dict[str, Any]]  # Structured validation data (categorized)
    validation_issue_rows: NotRequired[list[dict[str, Any]]]
    node_validation_status: NotRequired[
        dict[str, dict[str, list[str]]]
    ]  # Node-specific errors/warnings

    # Visualization output
    visualization: NotRequired[GraphVisualization]
    rendered_html: NotRequired[str]
