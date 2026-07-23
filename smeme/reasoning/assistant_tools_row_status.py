"""Dashboard row state: saved graph hash vs compiled artifact (MCP / evaluate path)."""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import DecisionTree, ReasoningCompiledArtifact
from smeme.decision_tree.helpers.db_queries import parse_graph_data
from smeme.reasoning.graph_hash import canonical_graph_hash

ToolsRowState = Literal["not_built", "live", "stale"]


def reasoning_tools_row_state(
    decision_tree: DecisionTree, artifact: ReasoningCompiledArtifact | None
) -> ToolsRowState:
    """Return **Live** / **Not built** / **Stale** for dashboard copy (hash-based when possible)."""
    if decision_tree.reasoning_status != "compiled" or artifact is None:
        return "not_built"
    try:
        graph = parse_graph_data(decision_tree)
        live_hash = canonical_graph_hash(graph)
    except ValidationError:
        return "not_built"
    if live_hash != artifact.graph_hash:
        return "stale"
    return "live"


async def reasoning_tools_row_state_for_decision_tree(
    db: AsyncSession, decision_tree: DecisionTree
) -> ToolsRowState:
    """Load artifact (if any) and return Live / Stale / Not built for one DecisionTree."""
    result = await db.execute(
        select(ReasoningCompiledArtifact).where(
            ReasoningCompiledArtifact.decision_tree_id == decision_tree.id
        )
    )
    artifact = result.scalar_one_or_none()
    return reasoning_tools_row_state(decision_tree, artifact)
