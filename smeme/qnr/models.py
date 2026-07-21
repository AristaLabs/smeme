"""QNR graph models - semantic graph structure for questionnaires.

This module defines the core data models for QNR graphs:
- QNRGraph: The complete graph structure (nodes + edges + metadata)
- GraphNode: Individual nodes (questions or conclusions)
- GraphEdge: Connections between nodes with optional conditions
- QuestionData: Question-specific content and configuration
- ConclusionData: Conclusion-specific content (terminal outcomes)
- QNRMetadata: Graph-level metadata (title, description, etc.)

IMPORTANT: These models are designed for IMMUTABILITY. After construction,
do not modify nodes or edges lists directly. Use editor operations
(smeme.qnr.editor.operations) to create transformed copies instead.

These models are used for:
- LLM structured output (OpenAI response_format)
- Database persistence (serialized to JSONB)
- Editor operations (immutable transformations)
- Viewer rendering (layout calculation)
- Session navigation (path traversal)
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag
from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped
from sqlmodel import Field as SQLField
from sqlmodel import Relationship

from smeme.core.models import BaseSQLModel

if TYPE_CHECKING:
    from smeme.core.models import User

# ============================================================================
# Node and Question Types
# ============================================================================

NodeType = Literal["question", "conclusion"]
"""
Node types in a QNR graph:
- question: A question that gathers information from the user
- conclusion: A terminal outcome that represents the result of a decision path
"""

QuestionType = Literal["radio"]
"""Question nodes are radio-only: exclusive choice among a finite non-empty option set."""


# ============================================================================
# Graph Data Models (Pydantic for validation & LLM structured output)
# ============================================================================


class QuestionData(BaseModel):
    """Question-specific data for question nodes (radio-only).

    Attributes:
        text: The question text displayed to the user
        type: Always ``radio`` (kept for stable JSON graph_data)
        options: Non-empty list of mutually exclusive option labels
        required: If False, user can skip; affects edge validation rules
        help_text: Optional explanatory text for the question

    Validation Rules (enforced at graph level):
    - options: at least one label, no duplicates (see validate_graph)
    - required=False: Graph must have default edge from this node for skip path
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="Question text displayed to user")
    type: QuestionType = Field(default="radio", description="Question input kind (radio only)")
    options: list[str] = Field(
        min_length=1,
        description="Radio option labels (finite, mutually exclusive)",
    )
    required: bool = Field(
        default=True,
        description="If False, user can skip. Graph must have default edge for skip path.",
    )
    help_text: str | None = Field(default=None, description="Help text for question")


class ConclusionData(BaseModel):
    """Conclusion-specific data for terminal outcome nodes.

    Conclusions represent the endpoint of a decision path in the QNR.
    They are reached when a user's answers lead to a specific outcome.

    Attributes:
        title: Short title for the conclusion (e.g., "Form an LLC")
        summary: Explanation of what this conclusion means for the user
        recommendations: Actionable next steps based on this conclusion
        severity: Optional indicator of urgency/importance (info, warning, critical)

    Design Principles (per QNR_CONCLUSION_NODES_PLAN.md):
    - Conclusions form an exclusive disjunction: exactly ONE is reached per session
    - Questions discriminate which conclusion applies
    - Edges to conclusions must be CONDITIONAL (no default edges to conclusions)
    - At least TWO conclusions required per QNR
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="Short title for the conclusion")
    summary: str = Field(description="Explanation of what this conclusion means")
    recommendations: list[str] = Field(
        default_factory=list,
        description="Actionable next steps based on this conclusion",
    )
    severity: Literal["info", "warning", "critical"] | None = Field(
        default="info",
        description="Urgency/importance indicator for UI styling",
    )


def _get_node_data_discriminator(v: dict | QuestionData | ConclusionData) -> str:
    """Discriminator function to determine node data type.

    Works for both raw dict (from JSON) and model instances.
    Uses parent node's 'type' field when available via context,
    otherwise infers from data structure.
    """
    if isinstance(v, QuestionData):
        return "question"
    if isinstance(v, ConclusionData):
        return "conclusion"
    # For raw dicts, check for distinguishing fields
    if isinstance(v, dict):
        # ConclusionData has 'title' and 'summary' but no 'text'
        # QuestionData has 'text' and 'type' (question type like radio/text)
        if "title" in v and "summary" in v and "text" not in v:
            return "conclusion"
        return "question"
    return "question"


class GraphNode(BaseModel):
    """Node in the QNR graph - either a question or a conclusion.

    Two node types:
    - question: Gathers information, has outgoing edges
    - conclusion: Terminal outcome, no outgoing edges (by design)

    Entry and terminal status:
    - Entry node: No incoming edges (questionnaire starting point)
    - Terminal node: No outgoing edges (conclusion nodes, or legacy question nodes)

    Attributes:
        id: Unique identifier (must start with letter, alphanumeric + underscore/hyphen)
        type: Node type - "question" or "conclusion"
        data: QuestionData for questions, ConclusionData for conclusions
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Unique node identifier (e.g., 'q1', 'conclusion_llc')")
    type: NodeType = Field(
        default="question",
        description="Node type: 'question' or 'conclusion'",
    )
    data: Annotated[
        Annotated[QuestionData, Tag("question")] | Annotated[ConclusionData, Tag("conclusion")],
        Discriminator(_get_node_data_discriminator),
    ] = Field(description="QuestionData for questions, ConclusionData for conclusions")

    def is_question(self) -> bool:
        """Check if this node is a question node."""
        return self.type == "question"

    def is_conclusion(self) -> bool:
        """Check if this node is a conclusion node."""
        return self.type == "conclusion"

    @property
    def question_data(self) -> QuestionData | None:
        """Get question data if this is a question node."""
        if self.type == "question" and isinstance(self.data, QuestionData):
            return self.data
        return None

    @property
    def conclusion_data(self) -> ConclusionData | None:
        """Get conclusion data if this is a conclusion node."""
        if self.type == "conclusion" and isinstance(self.data, ConclusionData):
            return self.data
        return None


class GraphEdge(BaseModel):
    """Edge connecting nodes in the graph.

    Edges define navigation flow between questions.

    Condition Matching Rules (question sources are radio-only):
    - radio: Match against the selected option label (case-insensitive strip in the viewer)
    - None/empty: Default edge (followed when no conditional edge matches)

    Validation Rules:
    - Conditions must be simple literals (no operators like =, >)
    - Non-default conditions must match an option label on the source question
    - Only one default edge (condition=None) allowed per source node
    - Optional questions (required=False) must have a default edge
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="Source node ID")
    target: str = Field(description="Target node ID")
    condition: str | None = Field(
        default=None,
        description="Condition for conditional edges; None = default/fallback edge",
    )


class QNRMetadata(BaseModel):
    """Metadata for a QNR. Title is required."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="QNR title (required)")
    description: str | None = Field(default=None, description="QNR description")
    category: str | None = Field(default=None, description="QNR category")
    estimated_time: int | None = Field(
        default=None, description="Estimated completion time (minutes)"
    )
    version: str = Field(default="1.0.0", description="QNR version")
    tags: list[str] = Field(default_factory=list, description="QNR tags")


class QNRGraph(BaseModel):
    """Complete graph structure for a QNR.

    A directed graph of nodes (questions and conclusions) connected by edges.
    The graph defines the structure and navigation flow of a questionnaire.

    Node Types:
    - question: Gathers information, can have outgoing edges
    - conclusion: Terminal outcome, no outgoing edges

    IMMUTABILITY: Do not modify nodes/edges after construction.
    Use editor operations to create transformed copies.

    Graph Invariants (enforced by validation):
    - At least one question node
    - Exactly one entry node (no incoming edges)
    - At least TWO conclusion nodes (disjunction principle)
    - Every path must end at a conclusion
    - Conclusion nodes have NO outgoing edges
    - Edges to conclusions must be CONDITIONAL (no defaults)
    - All edge sources/targets reference existing nodes
    - No self-loops, no duplicate edges
    - Metadata with title is required
    """

    model_config = ConfigDict(extra="forbid")

    nodes: list[GraphNode] = Field(
        default_factory=list, description="List of nodes (questions and conclusions)"
    )
    edges: list[GraphEdge] = Field(
        default_factory=list, description="List of edges connecting nodes"
    )
    metadata: QNRMetadata = Field(description="Graph-level metadata (required)")

    # =========================================================================
    # Lookup Helpers (computed on each call - safe for immutable usage)
    # =========================================================================

    @property
    def node_map(self) -> dict[str, GraphNode]:
        """Lookup table: node_id -> GraphNode."""
        return {node.id: node for node in self.nodes}

    @property
    def node_ids(self) -> set[str]:
        """Set of all node IDs."""
        return {node.id for node in self.nodes}

    def _build_outgoing_map(self) -> dict[str, list[GraphEdge]]:
        """Build outgoing edges map (internal helper)."""
        result: dict[str, list[GraphEdge]] = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            if edge.source in result:
                result[edge.source].append(edge)
        return result

    def _build_incoming_map(self) -> dict[str, list[GraphEdge]]:
        """Build incoming edges map (internal helper)."""
        result: dict[str, list[GraphEdge]] = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            if edge.target in result:
                result[edge.target].append(edge)
        return result

    # =========================================================================
    # Node Queries
    # =========================================================================

    def get_node(self, node_id: str) -> GraphNode | None:
        """Get node by ID, or None if not found."""
        return self.node_map.get(node_id)

    def get_outgoing_edges(self, node_id: str) -> list[GraphEdge]:
        """Get all edges originating from a node."""
        return [e for e in self.edges if e.source == node_id]

    def get_incoming_edges(self, node_id: str) -> list[GraphEdge]:
        """Get all edges targeting a node."""
        return [e for e in self.edges if e.target == node_id]

    def has_conditional_edges(self, node_id: str) -> bool:
        """Check if node has any conditional outgoing edges."""
        return any(
            edge.condition is not None and edge.condition.strip()
            for edge in self.get_outgoing_edges(node_id)
        )

    def get_default_edge(self, node_id: str) -> GraphEdge | None:
        """Get the default (unconditional) outgoing edge from a node."""
        for edge in self.get_outgoing_edges(node_id):
            if edge.condition is None or not edge.condition.strip():
                return edge
        return None

    # =========================================================================
    # Graph Structure Queries
    # =========================================================================

    def get_entry_nodes(self) -> list[GraphNode]:
        """Get nodes with no incoming edges (questionnaire starting points)."""
        incoming_map = self._build_incoming_map()
        return [node for node in self.nodes if not incoming_map.get(node.id)]

    def get_terminal_nodes(self) -> list[GraphNode]:
        """Get nodes with no outgoing edges (questionnaire ending points)."""
        outgoing_map = self._build_outgoing_map()
        return [node for node in self.nodes if not outgoing_map.get(node.id)]

    # =========================================================================
    # Node Type Queries
    # =========================================================================

    def get_question_nodes(self) -> list[GraphNode]:
        """Get all question nodes (nodes with type='question')."""
        return [node for node in self.nodes if node.type == "question"]

    def get_conclusion_nodes(self) -> list[GraphNode]:
        """Get all conclusion nodes (nodes with type='conclusion')."""
        return [node for node in self.nodes if node.type == "conclusion"]

    @property
    def conclusion_ids(self) -> set[str]:
        """Set of all conclusion node IDs."""
        return {node.id for node in self.nodes if node.type == "conclusion"}

    @property
    def question_ids(self) -> set[str]:
        """Set of all question node IDs."""
        return {node.id for node in self.nodes if node.type == "question"}

    def is_conclusion_node(self, node_id: str) -> bool:
        """Check if a node is a conclusion node."""
        node = self.get_node(node_id)
        return node is not None and node.type == "conclusion"

    def is_question_node(self, node_id: str) -> bool:
        """Check if a node is a question node."""
        node = self.get_node(node_id)
        return node is not None and node.type == "question"

    def has_conclusions(self) -> bool:
        """Check if graph has any conclusion nodes."""
        return any(node.type == "conclusion" for node in self.nodes)

    @property
    def entry_node_id(self) -> str | None:
        """
        ID of the entry question (the sole node with no incoming edges).

        Returns None if:
        - Graph has no nodes
        - All nodes have incoming edges (invalid graph)
        - Multiple entry nodes (invalid graph; fails validation)

        For publication-valid graphs, this is always the unique entry node ID.
        """
        entry_nodes = self.get_entry_nodes()
        if entry_nodes:
            return entry_nodes[0].id
        return None

    def get_first_question_id(self) -> str | None:
        """Alias for entry_node_id (backward compatibility).

        Entry is the unique node with no incoming edges when the graph passes validation.
        Valid graphs require that entry to be a question, not a conclusion.
        """
        return self.entry_node_id


# ============================================================================
# In-Progress QNR Generation Tracking (for persistent workflow state)
# ============================================================================


class InProgressQNRGeneration(BaseSQLModel, table=True):
    """Tracks in-progress QNR generation workflows for user lookup.

    This is a lightweight lookup table that links users to their active
    LangGraph workflow threads. The actual workflow state is stored in
    the LangGraph checkpointer tables.

    Lifecycle:
    - Created when user starts a new QNR generation
    - Updated on each checkpoint (last_checkpoint_at)
    - Deleted when workflow completes or expires
    """

    __tablename__ = "in_progress_qnr_generations"

    # Primary key
    id: UUID = SQLField(
        default_factory=uuid4,
        primary_key=True,
        description="Unique ID for this generation session",
    )

    # User reference (for lookup)
    user_id: UUID = SQLField(
        foreign_key="users.id",
        index=True,
        description="User who initiated this generation",
    )

    # LangGraph thread ID (links to checkpoints table)
    langgraph_thread_id: str = SQLField(
        max_length=36,
        unique=True,
        index=True,
        description="LangGraph thread ID (links to checkpoint state)",
    )

    # User-facing metadata
    user_prompt_preview: str = SQLField(
        max_length=200,
        description="First 200 chars of user's query for display",
    )

    # Timestamps
    started_at: datetime = SQLField(
        default_factory=lambda: datetime.now(UTC),
        description="When generation was initiated",
        sa_type=DateTime(timezone=True),
    )

    last_checkpoint_at: datetime = SQLField(
        default_factory=lambda: datetime.now(UTC),
        index=True,
        description="Last time workflow made progress (for cleanup)",
        sa_type=DateTime(timezone=True),
    )

    expires_at: datetime = SQLField(
        index=True,
        description="Auto-cleanup after this timestamp",
        sa_type=DateTime(timezone=True),
    )

    # Graph versioning (for managing workflow updates)
    graph_version: str = SQLField(
        max_length=50,
        default="v2",
        description="Version of the workflow graph used",
    )

    # Workflow versioning (Sprint 6: Track workflow code version)
    workflow_version: str = SQLField(
        max_length=50,
        default="1.0.0",
        description="Semantic version of workflow code (e.g., '1.0.0', '1.1.0')",
        sa_column_kwargs={"server_default": sa.text("'1.0.0'")},
    )

    workflow_updated_at: datetime | None = SQLField(
        default=None,
        nullable=True,
        description="Timestamp when workflow was last updated/migrated (None = original version)",
        sa_type=DateTime(timezone=True),
    )

    # Current phase (for UI display)
    current_phase: str = SQLField(
        max_length=50,
        default="research",
        description="Current workflow phase (research|conclusions|design|build)",
    )

    # Relationships
    user: Mapped["User"] = Relationship(back_populates="in_progress_generations")

    # Indexes
    __table_args__ = (
        Index("idx_user_active_generations", "user_id", "expires_at"),
        Index("idx_cleanup_candidates", "expires_at", "last_checkpoint_at"),
    )

    def __init__(self, **kwargs: Any) -> None:
        """Set default expiration to 7 days from now if not provided."""
        if "expires_at" not in kwargs:
            kwargs["expires_at"] = datetime.now(UTC) + timedelta(days=7)
        super().__init__(**kwargs)

    def update_checkpoint_time(self) -> None:
        """Update last_checkpoint_at to now (call after each workflow progress)."""
        self.last_checkpoint_at = datetime.now(UTC)

    def is_expired(self) -> bool:
        """Check if this generation has expired."""
        return datetime.now(UTC) > self.expires_at

    def is_stale(self, threshold_minutes: int = 60) -> bool:
        """Check if workflow hasn't made progress recently."""
        threshold = datetime.now(UTC) - timedelta(minutes=threshold_minutes)
        return self.last_checkpoint_at < threshold


class WizardGenerationEvent(BaseSQLModel, table=True):
    """Append-only funnel events for the agentic generation wizard (Spike 1 telemetry)."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "wizard_generation_events"
    __table_args__ = (
        Index("ix_wizard_generation_events_created_at", "created_at"),
        Index("ix_wizard_generation_events_thread_id", "thread_id"),
        Index("ix_wizard_generation_events_event_phase", "event_type", "phase"),
    )

    id: UUID = SQLField(default_factory=uuid4, primary_key=True)

    user_id: UUID = SQLField(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        description="User who triggered the wizard action",
    )

    thread_id: str | None = SQLField(
        default=None,
        max_length=36,
        nullable=True,
        description="LangGraph thread ID when known",
    )

    generation_id: UUID | None = SQLField(
        default=None,
        nullable=True,
        description="InProgressQNRGeneration.id when known",
    )

    event_type: str = SQLField(
        sa_column=Column(String(50), nullable=False),
        description="wizard.phase.enter|submit|error, wizard.abandon, wizard.complete",
    )

    phase: str = SQLField(
        sa_column=Column(String(20), nullable=False),
        description="brief|research|conclusions|design|build|complete",
    )

    duration_ms: int | None = SQLField(
        default=None,
        nullable=True,
        description="Handler latency for submit/error/complete events",
    )

    event_metadata: dict[str, Any] = SQLField(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        description="action, source, qnr_id, abandon reason, etc.",
    )

    created_at: datetime = SQLField(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        description="When the event was recorded",
    )
