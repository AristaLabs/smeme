"""Tests for per-workflow JSON export (Tier 1 download)."""

from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from smeme.core.models import DecisionTree, User
from smeme.app_factory import create_core_app as create_app
from smeme.decision_tree.helpers.export import EXPORT_VERSION
from tests.conftest import auth_as

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _minimal_graph(title: str = "Test Decision Tree") -> dict:
    from smeme.decision_tree.models import (
        ConclusionData,
        GraphEdge,
        GraphNode,
        DTGraph,
        DTGraphMetadata,
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
async def export_users(test_session_factory):
    uid = uuid4().hex[:8]
    owner_email = f"export_owner_{uid}@example.com"
    other_email = f"export_other_{uid}@example.com"

    async with test_session_factory() as session:
        owner = User(
            email=owner_email,
            hashed_password="unused",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"export_owner_{uid}",
        )
        other = User(
            email=other_email,
            hashed_password="unused",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"export_other_{uid}",
        )
        session.add(owner)
        session.add(other)
        await session.commit()
        await session.refresh(owner)
        await session.refresh(other)

        decision_tree = DecisionTree(
            author_id=owner.id,
            title=f"My Workflow {uid}",
            graph_data=_minimal_graph(f"My Workflow {uid}"),
            is_public=False,
            is_current=True,
            version_number=1,
            is_archived=False,
        )
        session.add(decision_tree)
        await session.commit()
        await session.refresh(decision_tree)

    yield {"owner": owner, "other": other, "decision_tree": decision_tree}

    async with test_session_factory() as session:
        await session.execute(delete(DecisionTree).where(DecisionTree.id == decision_tree.id))
        await session.execute(delete(User).where(User.id.in_([owner.id, other.id])))
        await session.commit()


async def test_owner_can_download_workflow(export_users, test_session_factory):
    app = create_app()
    owner = export_users["owner"]
    decision_tree = export_users["decision_tree"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with auth_as(app, owner):
            r = await client.get(f"/decision-trees/{decision_tree.id}/download")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert "attachment" in r.headers["content-disposition"]
    assert "My_Workflow" in r.headers["content-disposition"]
    assert r.headers["content-disposition"].endswith('.smeme.json"')

    payload = r.json()
    assert payload["smeme_export_version"] == EXPORT_VERSION
    assert payload["exported_at"]
    assert payload["decision_tree"]["id"] == str(decision_tree.id)
    assert payload["decision_tree"]["title"] == decision_tree.title
    assert payload["decision_tree"]["version_number"] == 1
    assert payload["decision_tree"]["graph"]["nodes"]
    assert payload["decision_tree"]["graph"]["edges"]
    assert payload["decision_tree"]["graph"]["metadata"]["title"] == decision_tree.title


async def test_non_owner_gets_404(export_users):
    app = create_app()
    other = export_users["other"]
    decision_tree = export_users["decision_tree"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with auth_as(app, other):
            r = await client.get(f"/decision-trees/{decision_tree.id}/download")

    assert r.status_code == 404


async def test_unauthenticated_gets_401(export_users):
    app = create_app()
    decision_tree = export_users["decision_tree"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/decision-trees/{decision_tree.id}/download")

    assert r.status_code == 401
