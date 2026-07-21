"""Shared access rules for MCP tool listing and evaluation (MCP transport).

``mcp_discoverable`` is an owner opt-in gate: both ``smeme_reasoning_list`` and
``smeme_reasoning_evaluate`` must enforce it so hidden UUIDs are not callable.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select

from smeme.core.models import QNR


def select_qnrs_for_assistant_tools_list(author_id: UUID) -> Select:
    """SQLAlchemy select for QNR rows exposed by ``smeme_reasoning_list``."""
    return (
        select(QNR)
        .where(QNR.author_id == author_id)
        .where(QNR.reasoning_status == "compiled")
        .where(QNR.is_current.is_(True))
        .where(QNR.mcp_discoverable.is_(True))
        .order_by(QNR.updated_at.desc())
    )


def assistant_tools_discoverability_violation(qnr: QNR) -> tuple[str, str] | None:
    """If *qnr* must not be used for MCP tool evaluation, return (code, message)."""
    if not qnr.mcp_discoverable:
        return (
            "not_discoverable",
            "This workflow is hidden from MCP tools. "
            "In the SMEme web app, set the workflow to **Listed** in the Listed column on your dashboard "
            "(/qnr/dashboard#mcp-listed), then try again.",
        )
    return None
