"""Unit tests for MCP tool discoverability helpers."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete

from smeme.core.models import DecisionTree, User
from smeme.mcp.assistant_decision_tree_access import (
    assistant_tools_discoverability_violation,
    select_decision_trees_for_assistant_tools_list,
    serialize_decision_trees_for_assistant_list,
)


@pytest.mark.asyncio(loop_scope="session")
async def test_select_list_excludes_compiled_when_not_discoverable(test_session_factory):
    uid = uuid4().hex[:8]
    async with test_session_factory() as session:
        user = User(
            email=f"at_{uid}@example.com",
            hashed_password="x",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"at_{uid}",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        from tests.unit.test_decision_tree_dashboard import _minimal_graph

        q = DecisionTree(
            author_id=user.id,
            title="Hidden compiled",
            graph_data=_minimal_graph(),
            is_public=False,
            is_current=True,
            is_archived=False,
            reasoning_status="compiled",
            mcp_discoverable=False,
        )
        session.add(q)
        await session.commit()
        await session.refresh(q)

        r = await session.execute(select_decision_trees_for_assistant_tools_list(user.id))
        rows = list(r.scalars().all())
        assert rows == []

        q.mcp_discoverable = True
        session.add(q)
        await session.commit()

        r2 = await session.execute(select_decision_trees_for_assistant_tools_list(user.id))
        rows2 = list(r2.scalars().all())
        assert len(rows2) == 1
        assert rows2[0].id == q.id

        await session.execute(delete(DecisionTree).where(DecisionTree.id == q.id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


def test_serialize_list_keeps_listed_rows(monkeypatch):
    """Regression: D024 rename must not discard ORM rows before payload build."""
    monkeypatch.setattr(
        "smeme.billing.access_policy.is_workflow_pick_required",
        lambda _user: False,
    )
    monkeypatch.setattr(
        "smeme.billing.access_policy.is_decision_tree_live",
        lambda _user, _dt: True,
    )
    user = SimpleNamespace()
    row_id = uuid4()
    row = SimpleNamespace(
        id=row_id,
        title="Foreign Foundations",
        is_public=False,
        reasoning_status="compiled",
        intended_audience="attorneys",
        use_case="tax",
    )
    entries = serialize_decision_trees_for_assistant_list(user, [row])
    assert len(entries) == 1
    assert entries[0]["id"] == str(row_id)
    assert entries[0]["title"] == "Foreign Foundations"
    assert entries[0]["reasoning_status"] == "compiled"
    assert "accessible" not in entries[0]


def test_discoverability_violation_when_false():
    q = DecisionTree(
        id=uuid4(),
        author_id=uuid4(),
        title="t",
        graph_data={"nodes": [], "edges": [], "metadata": {"title": "x"}},
        mcp_discoverable=False,
    )
    v = assistant_tools_discoverability_violation(q)
    assert v is not None
    assert v[0] == "not_discoverable"


def test_discoverability_violation_when_true():
    q = DecisionTree(
        id=uuid4(),
        author_id=uuid4(),
        title="t",
        graph_data={"nodes": [], "edges": [], "metadata": {"title": "x"}},
        mcp_discoverable=True,
    )
    assert assistant_tools_discoverability_violation(q) is None
