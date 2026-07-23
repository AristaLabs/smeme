"""Authorization tests for starting workflow sessions."""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from smeme.core.models import DecisionTree, DecisionTreeSession, User
from tests.conftest import auth_as

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture
async def private_workflow_start_fixture(test_session_factory):
    uid = uuid4().hex[:8]

    async with test_session_factory() as session:
        owner = User(
            email=f"start_owner_{uid}@example.com",
            hashed_password="unused",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"startowner_{uid}",
        )
        other = User(
            email=f"start_other_{uid}@example.com",
            hashed_password="unused",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"startother_{uid}",
        )
        session.add_all([owner, other])
        await session.commit()
        await session.refresh(owner)
        await session.refresh(other)

        decision_tree = DecisionTree(
            author_id=owner.id,
            title=f"Private start test {uid}",
            graph_data={"nodes": [], "edges": []},
            is_public=False,
            is_current=True,
            is_archived=False,
        )
        session.add(decision_tree)
        await session.commit()
        await session.refresh(decision_tree)

    yield {"owner": owner, "other": other, "decision_tree": decision_tree}

    async with test_session_factory() as session:
        await session.execute(delete(DecisionTreeSession).where(DecisionTreeSession.decision_tree_id == decision_tree.id))
        await session.execute(delete(DecisionTree).where(DecisionTree.id == decision_tree.id))
        await session.execute(delete(User).where(User.id.in_([owner.id, other.id])))
        await session.commit()


async def test_private_workflow_start_denies_non_author(
    client, app, private_workflow_start_fixture
):
    other = private_workflow_start_fixture["other"]
    decision_tree = private_workflow_start_fixture["decision_tree"]

    with auth_as(app, other):
        response = await client.post("/decision-trees/start", data={"decision_tree_id": str(decision_tree.id)})

    assert response.status_code == 404
    assert "decision tree not found" in response.text.lower()
