"""Unit tests for DecisionTree dashboard, session-start routes, and in-app docs.

Covers:
- GET /decision-trees/dashboard returns 200 for authenticated user
- Dashboard renders the user's own current non-archived DecisionTree titles
- Dashboard requires authentication
- GET /docs (hub), /docs/creator-dashboard, /docs/mcp require auth; return 200 when signed in
- POST /decision-trees/start creates a DecisionTreeSession row with no payment gate
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from smeme.app_factory import create_core_app as create_app
from smeme.core.config import settings as process_settings
from smeme.core.models import DecisionTree, DecisionTreeSession, User
from smeme.mcp.urls import mcp_connector_url
from tests.conftest import auth_as

pytestmark = pytest.mark.asyncio(loop_scope="session")


# =============================================================================
# Fixtures
# =============================================================================


def _minimal_graph(title: str = "Test Decision Tree") -> dict:
    from smeme.decision_tree.models import (
        ConclusionData,
        DTGraph,
        DTGraphMetadata,
        GraphEdge,
        GraphNode,
        QuestionData,
    )

    g = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(text="Q?", type="radio", options=["Yes", "No"], required=True),
            ),
            GraphNode(id="c1", type="conclusion", data=ConclusionData(title="A", summary="a")),
            GraphNode(id="c2", type="conclusion", data=ConclusionData(title="B", summary="b")),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="c2", condition="No"),
        ],
        metadata=DTGraphMetadata(title=title),
    )
    return g.model_dump(mode="json")


@pytest_asyncio.fixture
async def dashboard_user(test_session_factory):
    """Free-tier user with one active DecisionTree."""
    uid = uuid4().hex[:8]
    email = f"dash_{uid}@example.com"

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password="unused_in_clerk_mode",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"dashuser_{uid}",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        my_decision_tree = DecisionTree(
            author_id=user.id,
            title=f"My DecisionTree {uid}",
            graph_data=_minimal_graph(f"My DecisionTree {uid}"),
            is_public=False,
            is_current=True,
            is_archived=False,
        )
        session.add(my_decision_tree)
        await session.commit()
        await session.refresh(my_decision_tree)

    yield {"user": user, "my_decision_tree": my_decision_tree}

    async with test_session_factory() as session:
        await session.execute(delete(DecisionTreeSession).where(DecisionTreeSession.decision_tree_id == my_decision_tree.id))
        await session.execute(delete(DecisionTree).where(DecisionTree.id == my_decision_tree.id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


@pytest_asyncio.fixture
async def app_with_db(test_session_factory):
    from smeme.core.database import get_db

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


# =============================================================================
# GET /decision-trees/dashboard
# =============================================================================


async def test_dashboard_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/decision-trees/dashboard")
    assert r.status_code == 200


async def test_dashboard_requires_auth(client):
    r = await client.get("/decision-trees/dashboard")
    assert r.status_code in (302, 401, 403)


async def test_dashboard_shows_authored_decision_tree_title(client, app_with_db, dashboard_user):
    """The user's own current non-archived DecisionTree title appears in the response body."""
    title = dashboard_user["my_decision_tree"].title
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/decision-trees/dashboard")
    assert r.status_code == 200
    assert title.encode() in r.content


async def test_dashboard_prunes_completed_generation_rows(monkeypatch, dashboard_user):
    """Saved workflows should not continue occupying the in-progress dashboard slot."""
    from smeme.decision_tree import routes as decision_tree_routes
    from smeme.decision_tree.generation.agentic import workflow as workflow_module
    from smeme.decision_tree.generation.agentic.services import checkpoint_manager

    decision_tree_id = dashboard_user["my_decision_tree"].id
    generation = SimpleNamespace(
        id=uuid4(),
        langgraph_thread_id="completed-thread",
    )
    cleaned_threads: list[str] = []

    class FakeWorkflow:
        async def aget_state(self, config):
            return SimpleNamespace(
                values={"decision_tree_id": str(decision_tree_id), "final_status": "has_errors"},
            )

    async def fake_get_compiled_workflow():
        return FakeWorkflow()

    async def fake_complete_generation(db, thread_id):
        cleaned_threads.append(thread_id)

    monkeypatch.setattr(workflow_module, "get_compiled_workflow", fake_get_compiled_workflow)
    monkeypatch.setattr(checkpoint_manager, "complete_generation", fake_complete_generation)

    active = await decision_tree_routes._prune_completed_dashboard_generations(
        db=object(),
        current_user=dashboard_user["user"],
        generations=[generation],
    )

    assert active == []
    assert cleaned_threads == ["completed-thread"]


async def test_dashboard_hides_archive_ui(client, app_with_db, dashboard_user):
    """Archive affordances removed from product."""
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/decision-trees/dashboard")
    assert r.status_code == 200
    assert b"archive-confirm" not in r.content
    assert b'id="archived-heading"' not in r.content
    assert b"Restore archived workflow" not in r.content
    assert b"delete-confirm" in r.content


async def test_docs_index_requires_auth(client):
    r = await client.get("/docs")
    assert r.status_code in (302, 401, 403)


async def test_docs_index_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs")
    assert r.status_code == 200
    assert b"Deploy" in r.content and b"Listed" in r.content
    from smeme.docs.constants import DOCS_VERSION

    assert DOCS_VERSION.encode() in r.content
    assert b"/docs/creator-dashboard" in r.content
    assert b"/docs/download-workflow" in r.content
    assert b"/docs/mcp" in r.content
    assert b"marketplace" not in r.content.lower()
    assert b"revenue" not in r.content.lower()


async def test_docs_introduction_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs/introduction")
    assert r.status_code == 200
    assert b"How to fix" in r.content
    assert b"Deploy, list" in r.content


async def test_docs_creator_dashboard_requires_auth(client):
    r = await client.get("/docs/creator-dashboard")
    assert r.status_code in (302, 401, 403)


async def test_docs_creator_dashboard_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs/creator-dashboard")
    assert r.status_code == 200
    assert b"Deploy, validate" in r.content
    assert b"How to fix" in r.content
    assert b"Live" in r.content and b"Stale" in r.content
    assert b"marketplace" not in r.content.lower()
    assert b"revenue" not in r.content.lower()


async def test_docs_download_workflow_requires_auth(client):
    r = await client.get("/docs/download-workflow")
    assert r.status_code in (302, 401, 403)


async def test_docs_download_workflow_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs/download-workflow")
    assert r.status_code == 200
    assert b"Download your decision tree" in r.content
    assert b"smeme_export_version" in r.content
    assert b"Re-import" in r.content


async def test_docs_mcp_requires_auth(client):
    r = await client.get("/docs/mcp")
    assert r.status_code in (302, 401, 403)


async def test_docs_mcp_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs/mcp")
    assert r.status_code == 200
    assert b"Connect your agent" in r.content
    assert b"smeme_reasoning" in r.content
    assert b"does not install SMEme" in r.content
    if process_settings.mcp_enabled:
        assert b"install-claude" in r.content
        assert b"install-chatgpt" in r.content
        assert b"Developer mode" in r.content
        assert b"create dialog" in r.content
        assert b"Advanced settings" in r.content
        assert b"Customize" in r.content
        assert b"chatgpt.com" in r.content
        assert b"browser" in r.content
        assert mcp_connector_url(process_settings).encode() in r.content
    else:
        assert b"MCP is not enabled on this server" in r.content


async def test_mcp_discoverable_toggle_requires_owner(client, app_with_db, dashboard_user, test_session_factory):
    """Non-owner cannot toggle discoverability (403)."""
    from sqlalchemy import delete

    uid = uuid4().hex[:8]
    async with test_session_factory() as session:
        other = User(
            email=f"other_{uid}@example.com",
            hashed_password="x",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"other_{uid}",
        )
        session.add(other)
        await session.commit()
        await session.refresh(other)

    qid = dashboard_user["my_decision_tree"].id
    with auth_as(app_with_db, other):
        r = await client.post(
            "/decision-trees/mcp/discoverable",
            data={"decision_tree_id": str(qid), "enabled": "true"},
            follow_redirects=False,
        )
    assert r.status_code == 403

    async with test_session_factory() as session:
        await session.execute(delete(User).where(User.id == other.id))
        await session.commit()


# =============================================================================
# POST /decision-trees/start — no payment gate
# =============================================================================


async def test_start_decision_tree_creates_session_without_payment_gate(
    client, app_with_db, dashboard_user, test_session_factory
):
    """POST /decision-trees/start must create a DecisionTreeSession and return 200 with no billing redirect.

    Before Phase 1 this route checked price_cents and redirected free-tier users
    to /billing/session-pay/...  That gate is gone; any authenticated user can
    start a session on any DecisionTree directly.
    """
    user = dashboard_user["user"]
    decision_tree_id = dashboard_user["my_decision_tree"].id

    with auth_as(app_with_db, user):
        r = await client.post("/decision-trees/start", data={"decision_tree_id": str(decision_tree_id)})

    # Must not redirect to billing
    assert r.status_code == 200
    assert "session-pay" not in str(r.headers.get("location", ""))
    assert "session-pay" not in r.text

    # A DecisionTreeSession row must exist in the DB
    async with test_session_factory() as session:
        result = await session.execute(
            select(DecisionTreeSession).where(
                DecisionTreeSession.user_id == user.id,
                DecisionTreeSession.decision_tree_id == decision_tree_id,
            )
        )
        decision_tree_session = result.scalar_one_or_none()

    assert decision_tree_session is not None
