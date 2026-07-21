"""Authorization tests for starting workflow sessions."""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from smeme.core.models import QNR, QNRSession, User
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

        qnr = QNR(
            author_id=owner.id,
            title=f"Private start test {uid}",
            graph_data={"nodes": [], "edges": []},
            is_public=False,
            is_current=True,
            is_archived=False,
        )
        session.add(qnr)
        await session.commit()
        await session.refresh(qnr)

    yield {"owner": owner, "other": other, "qnr": qnr}

    async with test_session_factory() as session:
        await session.execute(delete(QNRSession).where(QNRSession.qnr_id == qnr.id))
        await session.execute(delete(QNR).where(QNR.id == qnr.id))
        await session.execute(delete(User).where(User.id.in_([owner.id, other.id])))
        await session.commit()


async def test_private_workflow_start_denies_non_author(
    client, app, private_workflow_start_fixture
):
    other = private_workflow_start_fixture["other"]
    qnr = private_workflow_start_fixture["qnr"]

    with auth_as(app, other):
        response = await client.post("/qnr/start", data={"qnr_id": str(qnr.id)})

    assert response.status_code == 404
    assert "workflow not found" in response.text.lower()
