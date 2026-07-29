"""Integration: validation issue click selects node (Phase 4)."""

from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from smeme.core.database import get_db
from smeme.core.models import DecisionTree, User
from smeme.app_factory import create_core_app as create_app
from smeme.decision_tree.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    DTGraphMetadata,
    QuestionData,
)
from tests.conftest import auth_as

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture
async def app_with_db(test_session_factory):
    application = create_app()

    async def override_get_db():
        async with test_session_factory() as session:
            try:
                yield session
            finally:
                await session.close()

    application.dependency_overrides[get_db] = override_get_db
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app_with_db):
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def owner_with_invalid_graph(test_session_factory):
    uid = uuid4().hex[:10]
    email = f"val_jump_{uid}@example.com"

    graph = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Pick one",
                    type="radio",
                    options=["Yes", "Yes"],
                    required=True,
                ),
            ),
            GraphNode(id="c1", type="conclusion", data=ConclusionData(title="A", summary="a")),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
        ],
        metadata=DTGraphMetadata(title="Validation jump test"),
    )

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password="unused",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"valjump_{uid}",
            is_premium=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        decision_tree = DecisionTree(
            author_id=user.id,
            title=f"Validation jump {uid}",
            graph_data=graph.model_dump(mode="json"),
            is_public=False,
        )
        session.add(decision_tree)
        await session.commit()
        await session.refresh(decision_tree)

    yield {"user": user, "decision_tree_id": decision_tree.id}

    async with test_session_factory() as session:
        await session.execute(delete(DecisionTree).where(DecisionTree.author_id == user.id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


async def test_editor_shows_clickable_validation_issue(
    client, app_with_db, owner_with_invalid_graph
):
    decision_tree_id = owner_with_invalid_graph["decision_tree_id"]
    user = owner_with_invalid_graph["user"]

    with auth_as(app_with_db, user):
        r = await client.get(f"/decision-trees/{decision_tree_id}/editor")

    assert r.status_code == 200
    assert 'id="validation-issues-panel"' in r.text
    assert "validation-issue-row" in r.text
    assert 'data-node-id="q1"' in r.text
    assert "Jump to node" in r.text
    assert 'data-action="editor-scroll-to-validation-issues"' in r.text
    assert '/static/js/editor.js' in r.text


async def test_validation_issue_selects_node_in_sidebar(
    client, app_with_db, owner_with_invalid_graph
):
    decision_tree_id = owner_with_invalid_graph["decision_tree_id"]
    user = owner_with_invalid_graph["user"]

    with auth_as(app_with_db, user):
        r = await client.post(
            "/decision-trees/editor/select_node_with_decision_tree",
            data={"decision_tree_id": str(decision_tree_id), "node_id": "q1"},
        )

    assert r.status_code == 200
    assert "ID: q1" in r.text
    assert 'id="view-graph"' in r.text
    assert 'data-node-id="q1"' in r.text
    assert 'id="checklist-card-q1"' in r.text
    assert "ring-2 ring-brand-500" in r.text


async def test_validate_realtime_includes_jump_links(
    client, app_with_db, owner_with_invalid_graph
):
    decision_tree_id = owner_with_invalid_graph["decision_tree_id"]
    user = owner_with_invalid_graph["user"]

    with auth_as(app_with_db, user):
        r = await client.get(f"/decision-trees/editor/validate/{decision_tree_id}")

    assert r.status_code == 200
    assert "Jump to node" in r.text
    assert 'data-node-id="q1"' in r.text
    assert 'name="decision_tree_id"' in r.text
    assert "validation-issue-row" in r.text
