"""MCP persistence models (usage metering and cost telemetry)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped
from sqlmodel import Field

from smeme.core.models import BaseSQLModel

SQLField = Field  # noqa: N816 — match smeme.core.models convention


class McpToolInvocation(BaseSQLModel, table=True):
    """Append-only MCP tool invocation row for metering and cost telemetry."""

    model_config = {"arbitrary_types_allowed": True}

    __tablename__ = "mcp_tool_invocations"
    __table_args__ = (
        Index("ix_mcp_tool_invocations_created_at", "created_at"),
        Index("ix_mcp_tool_invocations_tool_outcome", "tool_name", "outcome"),
        Index("ix_mcp_tool_invocations_user_created", "user_id", "created_at"),
    )

    id: UUID = SQLField(default_factory=uuid4, primary_key=True)

    user_id: UUID = SQLField(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        description="Authenticated SMEme user (set only after successful get_mcp_user)",
    )

    tool_name: str = SQLField(
        sa_column=Column(String(80), nullable=False),
        description="MCP tool identifier, e.g. smeme_reasoning_evaluate_answers",
    )

    outcome: str = SQLField(
        sa_column=Column(String(64), nullable=False),
        description="ok when no error.code in tool JSON; otherwise stable error.code",
    )

    decision_tree_id: UUID | None = SQLField(
        default=None,
        sa_column=Column(sa.Uuid(), nullable=True),
        description="Decision tree UUID when the tool accepted a decision_tree_id parameter",
    )

    oauth_client_id: str | None = SQLField(
        default=None,
        sa_column=Column(String(255), nullable=True),
        description="Clerk OAuth app client_id or azp from the access JWT when available",
    )

    duration_ms: int = SQLField(
        sa_column=Column(Integer, nullable=False),
        description="Wall-clock handler time for the MCP tool call",
    )

    reasoning_ms: int | None = SQLField(
        default=None,
        sa_column=Column(Integer, nullable=True),
        description="Time spent in evaluate_reasoning / Z3 kernel (when measured)",
    )

    question_count: int | None = SQLField(default=None, sa_column=Column(Integer, nullable=True))
    edge_count: int | None = SQLField(default=None, sa_column=Column(Integer, nullable=True))
    answered_count: int | None = SQLField(default=None, sa_column=Column(Integer, nullable=True))

    sat_calls: int | None = SQLField(
        default=None,
        sa_column=Column(Integer, nullable=True),
        description="Solver checks for how_to_reach-style tools (future)",
    )

    quota_weight: Mapped[float] = Field(
        sa_column=Column(Numeric(6, 2), nullable=False),
        description="Billable units toward plan allowance (e.g. evaluate=1, how_to_reach=2.5)",
    )

    estimated_cost_usd_micros: int | None = SQLField(
        default=None,
        sa_column=Column(Integer, nullable=True),
        description="Internal COGS estimate in micro-dollars (1e-6 USD); not customer-facing",
    )

    cost_metadata: dict[str, Any] = SQLField(
        default_factory=dict,
        sa_column=Column(
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        description="Extensible timing and size fields for p50/p95 analysis",
    )

    created_at: Mapped[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


__all__ = ["McpToolInvocation"]
