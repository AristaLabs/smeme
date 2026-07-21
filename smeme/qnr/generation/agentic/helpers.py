"""Shared helper models and functions for agentic QNR generation.

Extracted from legacy nodes/build.py (Sprint 6 cleanup).
These models and functions are used by the build subgraph.
"""

from pydantic import BaseModel

from smeme.qnr.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    QNRGraph,
    QNRMetadata,
    QuestionData,
)

# =============================================================================
# Simplified Models for LLM Structured Output (no discriminated unions)
# =============================================================================


class LLMSimpleEdge(BaseModel):
    """Simplified edge model for LLM parsing."""

    source: str
    target: str
    condition: str | None = None


class LLMSimpleMetadata(BaseModel):
    """Simplified metadata model for LLM parsing."""

    title: str
    description: str | None = None
    category: str | None = None
    estimated_time: int | None = None
    version: str = "1.0.0"
    tags: list[str] = []


class LLMSimpleNode(BaseModel):
    """Simplified node model for LLM parsing - avoids discriminated unions."""

    id: str
    type: str  # "question" or "conclusion"
    # For questions
    text: str | None = None
    question_type: str | None = None  # LLM may emit legacy values; coerced to radio at conversion
    options: list[str] | None = None
    required: bool | None = None
    help_text: str | None = None
    # For conclusions
    title: str | None = None
    summary: str | None = None
    recommendations: list[str] | None = None
    severity: str | None = None


class LLMSimpleGraph(BaseModel):
    """Simplified graph model for LLM structured output."""

    nodes: list[LLMSimpleNode]
    edges: list[LLMSimpleEdge]
    metadata: LLMSimpleMetadata


# =============================================================================
# Conversion Utilities
# =============================================================================


def convert_simple_graph_to_qnr_graph(simple_graph: LLMSimpleGraph) -> QNRGraph:
    """Convert simplified LLM graph to full QNRGraph with proper discriminated unions.

    This mechanical conversion handles the complexity of discriminated unions
    that the LLM can't generate directly.

    Args:
        simple_graph: Simplified graph structure from LLM

    Returns:
        QNRGraph: Full graph with proper discriminated union types
    """
    nodes = []
    for simple_node in simple_graph.nodes:
        if simple_node.type == "question":
            opts = [o for o in (simple_node.options or []) if o and str(o).strip()]
            if not opts:
                opts = ["Yes", "No"]
            data = QuestionData(
                text=simple_node.text or "",
                type="radio",
                options=opts,
                required=simple_node.required if simple_node.required is not None else True,
                help_text=simple_node.help_text,
            )
        elif simple_node.type == "conclusion":
            data = ConclusionData(
                title=simple_node.title or "",
                summary=simple_node.summary or "",
                recommendations=simple_node.recommendations or [],
                severity=simple_node.severity or "info",
            )
        else:
            # Default to question if type is unclear
            data = QuestionData(
                text=simple_node.text or f"Question {simple_node.id}",
                type="radio",
                options=["Yes", "No"],
            )

        node = GraphNode(
            id=simple_node.id,
            type=simple_node.type,
            data=data,
        )
        nodes.append(node)

    # Convert edges
    edges = []
    for simple_edge in simple_graph.edges:
        edge = GraphEdge(
            source=simple_edge.source,
            target=simple_edge.target,
            condition=simple_edge.condition,
        )
        edges.append(edge)

    # Create metadata
    metadata = QNRMetadata(**simple_graph.metadata.__dict__)

    return QNRGraph(nodes=nodes, edges=edges, metadata=metadata)
