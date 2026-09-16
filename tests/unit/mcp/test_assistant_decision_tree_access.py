"""Unit tests for MCP tool discoverability helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from smeme.billing.providers import hosted_quota_enforcement_scope
from smeme.core.models import DecisionTree, ReasoningCompiledArtifact, User
from smeme.mcp.assistant_decision_tree_access import (
    assistant_tools_discoverability_violation,
    select_decision_trees_for_assistant_tools_list,
    serialize_decision_trees_for_assistant_list,
)
from smeme.mcp.bearer_auth import MCPAuthError
from smeme.mcp.reasoning_fastmcp import _listed_trees_or_seed_sample


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
        graph_data={
            "nodes": [],
            "edges": [],
            "metadata": {
                "title": "Foreign Foundations",
                "effective_date": "2020-01-01",
                "review_by": "2020-12-31",
            },
        },
        is_public=False,
        reasoning_status="compiled",
        intended_audience="attorneys",
        use_case="tax",
        sample_key=None,
    )
    entries = serialize_decision_trees_for_assistant_list(user, [row])
    assert len(entries) == 1
    assert entries[0]["id"] == str(row_id)
    assert entries[0]["title"] == "Foreign Foundations"
    assert entries[0]["reasoning_status"] == "compiled"
    assert entries[0]["effective_date"] == "2020-01-01"
    assert entries[0]["review_by"] == "2020-12-31"
    assert entries[0]["warnings"][0]["code"] == "review_overdue"
    assert "accessible" not in entries[0]
    assert "sample_key" not in entries[0]


def test_serialize_list_includes_sample_key(monkeypatch):
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
        title="SMEme sample",
        graph_data={"nodes": [], "edges": [], "metadata": {"title": "SMEme sample"}},
        is_public=False,
        reasoning_status="compiled",
        intended_audience=None,
        use_case=None,
        sample_key="smeme_sample_v1",
    )
    entries = serialize_decision_trees_for_assistant_list(user, [row])
    assert entries[0]["id"] == str(row_id)
    assert entries[0]["sample_key"] == "smeme_sample_v1"


@pytest.mark.asyncio(loop_scope="session")
async def test_reasoning_list_tool_returns_listed_rows(
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory,
):
    """Exercise the registered tool so the serializer cannot be disconnected again."""
    uid = uuid4().hex[:8]
    async with test_session_factory() as session:
        user = User(
            email=f"list_tool_{uid}@example.com",
            hashed_password="x",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"list_tool_{uid}",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        from tests.unit.test_decision_tree_dashboard import _minimal_graph

        decision_tree = DecisionTree(
            author_id=user.id,
            title="Listed through MCP",
            graph_data=_minimal_graph(),
            is_public=False,
            is_current=True,
            is_archived=False,
            reasoning_status="compiled",
            mcp_discoverable=True,
        )
        session.add(decision_tree)
        await session.commit()
        await session.refresh(decision_tree)
        decision_tree_id = decision_tree.id

    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp.get_mcp_user",
        AsyncMock(return_value=user),
    )
    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp.AsyncSessionLocal",
        test_session_factory,
    )

    from smeme.mcp.reasoning_fastmcp import (
        get_or_create_fastmcp,
        reset_mcp_runtime_for_tests,
    )

    reset_mcp_runtime_for_tests()
    fm = get_or_create_fastmcp()
    tool_fn = fm._tool_manager._tools["smeme_reasoning_list"].fn
    with patch(
        "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
        return_value=MagicMock(),
    ):
        raw = await tool_fn(MagicMock())

    payload = json.loads(raw)
    assert payload["count"] == 1
    assert payload["decision_trees"][0]["id"] == str(decision_tree_id)
    assert payload["decision_trees"][0]["title"] == "Listed through MCP"

    async with test_session_factory() as session:
        await session.execute(delete(DecisionTree).where(DecisionTree.id == decision_tree_id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


@pytest.mark.asyncio
async def test_empty_reasoning_list_seeds_sample_for_existing_user(
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory,
):
    uid = uuid4().hex[:8]
    async with test_session_factory() as session:
        user = User(
            email=f"empty_list_{uid}@example.com",
            hashed_password="x",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"empty_list_{uid}",
            is_premium=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp.get_mcp_user",
        AsyncMock(return_value=user),
    )
    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp.AsyncSessionLocal",
        test_session_factory,
    )

    from smeme.decision_tree.sample_tree import SAMPLE_KEY
    from smeme.mcp.reasoning_fastmcp import (
        get_or_create_fastmcp,
        reset_mcp_runtime_for_tests,
    )

    reset_mcp_runtime_for_tests()
    fm = get_or_create_fastmcp()
    tool_fn = fm._tool_manager._tools["smeme_reasoning_list"].fn
    with patch(
        "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
        return_value=MagicMock(),
    ):
        raw = await tool_fn(MagicMock())

    payload = json.loads(raw)
    assert payload["count"] == 1
    assert payload["decision_trees"][0]["sample_key"] == SAMPLE_KEY
    assert payload["decision_trees"][0]["id"]

    async with test_session_factory() as session:
        tree_ids = (
            await session.scalars(select(DecisionTree.id).where(DecisionTree.author_id == user_id))
        ).all()
        await session.execute(
            delete(ReasoningCompiledArtifact).where(
                ReasoningCompiledArtifact.decision_tree_id.in_(tree_ids)
            )
        )
        await session.execute(delete(DecisionTree).where(DecisionTree.id.in_(tree_ids)))
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


@pytest.mark.asyncio
async def test_sample_seed_failure_is_retryable():
    from smeme.decision_tree.sample_tree import SampleTreeError

    db = AsyncMock()
    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    db.execute.return_value = empty
    user = SimpleNamespace(id=uuid4())
    winner = SimpleNamespace(id=uuid4())

    with patch(
        "smeme.decision_tree.sample_tree.ensure_sample_tree",
        new=AsyncMock(
            side_effect=[
                SampleTreeError("deploy_failed", "temporary failure"),
                winner,
            ]
        ),
    ):
        first = await _listed_trees_or_seed_sample(db, user)
        second = await _listed_trees_or_seed_sample(db, user)

    assert isinstance(first, str)
    assert json.loads(first)["error"]["code"] == "internal_error"
    assert second == [winner]
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_reasoning_list_auth_failure_does_not_seed(
    monkeypatch,
    test_session_factory,
):
    from smeme.mcp.reasoning_fastmcp import (
        get_or_create_fastmcp,
        reset_mcp_runtime_for_tests,
    )

    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp.get_mcp_user",
        AsyncMock(side_effect=MCPAuthError("blocked", reason_code="email_not_verified")),
    )
    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp.AsyncSessionLocal",
        test_session_factory,
    )
    reset_mcp_runtime_for_tests()
    fm = get_or_create_fastmcp()
    tool_fn = fm._tool_manager._tools["smeme_reasoning_list"].fn

    with (
        patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ),
        patch(
            "smeme.decision_tree.sample_tree.ensure_sample_tree",
            new=AsyncMock(),
        ) as ensure_sample,
    ):
        raw = await tool_fn(MagicMock())

    assert json.loads(raw)["error"]["code"] == "auth_error"
    ensure_sample.assert_not_called()


@pytest.mark.asyncio
async def test_empty_reasoning_list_at_tree_quota_returns_quota_exceeded(
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory,
):
    from tests.unit.test_decision_tree_dashboard import _minimal_graph

    uid = uuid4().hex[:8]
    async with test_session_factory() as session:
        user = User(
            email=f"quota_list_{uid}@example.com",
            hashed_password="x",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"quota_list_{uid}",
            is_premium=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id
        for i in range(3):
            session.add(
                DecisionTree(
                    author_id=user_id,
                    title=f"Filled slot {i + 1}",
                    graph_data=_minimal_graph(title=f"Filled slot {i + 1}"),
                    is_current=True,
                    is_archived=False,
                    mcp_discoverable=False,
                )
            )
        await session.commit()

    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp.get_mcp_user",
        AsyncMock(return_value=user),
    )
    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp.AsyncSessionLocal",
        test_session_factory,
    )

    from smeme.mcp.reasoning_fastmcp import (
        get_or_create_fastmcp,
        reset_mcp_runtime_for_tests,
    )

    reset_mcp_runtime_for_tests()
    fm = get_or_create_fastmcp()
    tool_fn = fm._tool_manager._tools["smeme_reasoning_list"].fn
    with (
        hosted_quota_enforcement_scope(),
        patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ),
    ):
        raw = await tool_fn(MagicMock())

    payload = json.loads(raw)
    assert payload["error"]["code"] == "quota_exceeded"

    async with test_session_factory() as session:
        tree_ids = (
            await session.scalars(select(DecisionTree.id).where(DecisionTree.author_id == user_id))
        ).all()
        await session.execute(delete(DecisionTree).where(DecisionTree.id.in_(tree_ids)))
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


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
