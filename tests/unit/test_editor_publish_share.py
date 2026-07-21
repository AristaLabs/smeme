"""Unit tests for editor publish (deploy) endpoint."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from smeme.core.models import QNR, ReasoningCompiledArtifact, User
from smeme.app_factory import create_core_app as create_app
from smeme.qnr.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    QNRGraph,
    QNRMetadata,
    QuestionData,
)
from smeme.reasoning.ir.serialize import ir_to_json
from smeme.reasoning.publish_readiness import PublishReadiness
from smeme.reasoning.qnr_bridge import compile_qnr_to_ir
from tests.conftest import auth_as

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _publishable_graph() -> dict:
    g = QNRGraph(
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
        metadata=QNRMetadata(title="Publish test QNR"),
    )
    return g.model_dump(mode="json")


def _mock_ready_readiness() -> PublishReadiness:
    graph = QNRGraph.model_validate(_publishable_graph())
    ir = compile_qnr_to_ir(graph)
    return PublishReadiness(
        ready=True,
        ir_json=ir_to_json(ir),
        graph_hash="a" * 64,
    )


@pytest_asyncio.fixture
async def premium_owner(test_session_factory):
    uid = uuid4().hex[:10]
    email = f"pub_owner_{uid}@example.com"

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password="unused_in_clerk_mode",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"pubowner_{uid}",
            is_premium=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        qnr = QNR(
            author_id=user.id,
            title=f"Publish test {uid}",
            graph_data=_publishable_graph(),
            is_public=False,
            reasoning_status=None,
        )
        session.add(qnr)
        await session.commit()
        await session.refresh(qnr)

    yield {"user": user, "qnr": qnr}

    async with test_session_factory() as session:
        await session.execute(
            delete(ReasoningCompiledArtifact).where(ReasoningCompiledArtifact.qnr_id == qnr.id)
        )
        await session.execute(delete(QNR).where(QNR.id == qnr.id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


@pytest_asyncio.fixture
async def free_owner(test_session_factory):
    uid = uuid4().hex[:10]
    email = f"free_owner_{uid}@example.com"

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password="unused_in_clerk_mode",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"freeowner_{uid}",
            is_premium=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        qnr = QNR(
            author_id=user.id,
            title=f"Free QNR {uid}",
            graph_data=_publishable_graph(),
            is_public=False,
            reasoning_status=None,
        )
        session.add(qnr)
        await session.commit()
        await session.refresh(qnr)

    yield {"user": user, "qnr": qnr}

    async with test_session_factory() as session:
        await session.execute(delete(QNR).where(QNR.id == qnr.id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


@pytest_asyncio.fixture
async def other_user(test_session_factory):
    uid = uuid4().hex[:10]
    email = f"other_user_{uid}@example.com"

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password="unused_in_clerk_mode",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"otheruser_{uid}",
            is_premium=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    yield user

    async with test_session_factory() as session:
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


async def test_publish_sets_reasoning_status_compiled(
    client, app_with_db, premium_owner, test_session_factory
):
    qnr_id = premium_owner["qnr"].id
    user = premium_owner["user"]

    with (
        patch(
            "smeme.qnr.editor.routes.assess_publish_readiness",
            new=AsyncMock(return_value=_mock_ready_readiness()),
        ),
        auth_as(app_with_db, user),
    ):
        r = await client.post(f"/qnr/editor/{qnr_id}/publish", follow_redirects=False)

    assert r.status_code in (303, 200)

    async with test_session_factory() as session:
        result = await session.execute(select(QNR).where(QNR.id == qnr_id))
        updated_qnr = result.scalar_one()

    assert updated_qnr.reasoning_status == "compiled"
    assert updated_qnr.is_public is False


async def test_publish_redirects_to_dashboard_when_return_next_dashboard(
    client, app_with_db, premium_owner
):
    qnr_id = premium_owner["qnr"].id
    user = premium_owner["user"]

    with (
        patch(
            "smeme.qnr.editor.routes.assess_publish_readiness",
            new=AsyncMock(return_value=_mock_ready_readiness()),
        ),
        auth_as(app_with_db, user),
    ):
        r = await client.post(
            f"/qnr/editor/{qnr_id}/publish",
            data={"return_next": "dashboard"},
            follow_redirects=False,
        )

    assert r.status_code == 303
    assert r.headers["location"] == "/qnr/dashboard?deployed=1"


async def test_publish_redirects_to_editor_success_when_no_return_next(
    client, app_with_db, premium_owner
):
    qnr_id = premium_owner["qnr"].id
    user = premium_owner["user"]

    with (
        patch(
            "smeme.qnr.editor.routes.assess_publish_readiness",
            new=AsyncMock(return_value=_mock_ready_readiness()),
        ),
        auth_as(app_with_db, user),
    ):
        r = await client.post(
            f"/qnr/editor/{qnr_id}/publish",
            follow_redirects=False,
        )

    assert r.status_code == 303
    assert r.headers["location"] == f"/qnr/{qnr_id}/editor?reasoning_compiled=1"


async def test_publish_redirects_to_tools_tab_when_return_next_tools(
    client, app_with_db, premium_owner
):
    qnr_id = premium_owner["qnr"].id
    user = premium_owner["user"]

    with (
        patch(
            "smeme.qnr.editor.routes.assess_publish_readiness",
            new=AsyncMock(return_value=_mock_ready_readiness()),
        ),
        auth_as(app_with_db, user),
    ):
        r = await client.post(
            f"/qnr/editor/{qnr_id}/publish",
            data={"return_next": "tools"},
            follow_redirects=False,
        )

    assert r.status_code == 303
    assert r.headers["location"] == f"/qnr/{qnr_id}/editor?view=tools&reasoning_compiled=1"


async def test_publish_does_not_set_is_public(
    client, app_with_db, premium_owner, test_session_factory
):
    qnr_id = premium_owner["qnr"].id
    user = premium_owner["user"]

    with (
        patch(
            "smeme.qnr.editor.routes.assess_publish_readiness",
            new=AsyncMock(
                return_value=PublishReadiness(
                    ready=True,
                    ir_json=_mock_ready_readiness().ir_json,
                    graph_hash="b" * 64,
                )
            ),
        ),
        auth_as(app_with_db, user),
    ):
        await client.post(f"/qnr/editor/{qnr_id}/publish", follow_redirects=False)

    async with test_session_factory() as session:
        result = await session.execute(select(QNR).where(QNR.id == qnr_id))
        updated_qnr = result.scalar_one()

    assert updated_qnr.is_public is False


async def test_publish_allows_free_user(
    client, app_with_db, free_owner, test_session_factory
):
    """Deploy is not premium-gated."""
    qnr_id = free_owner["qnr"].id
    user = free_owner["user"]

    with (
        patch(
            "smeme.qnr.editor.routes.assess_publish_readiness",
            new=AsyncMock(return_value=_mock_ready_readiness()),
        ),
        auth_as(app_with_db, user),
    ):
        r = await client.post(f"/qnr/editor/{qnr_id}/publish", follow_redirects=False)

    assert r.status_code in (303, 200)

    async with test_session_factory() as session:
        result = await session.execute(select(QNR).where(QNR.id == qnr_id))
        updated_qnr = result.scalar_one()

    assert updated_qnr.reasoning_status == "compiled"


async def test_publish_returns_403_for_non_owner(client, app_with_db, premium_owner, other_user):
    qnr_id = premium_owner["qnr"].id

    with auth_as(app_with_db, other_user):
        r = await client.post(f"/qnr/editor/{qnr_id}/publish", follow_redirects=False)

    assert r.status_code == 403


async def test_publish_returns_404_for_unknown_qnr(client, app_with_db, premium_owner):
    unknown_id = uuid4()

    with auth_as(app_with_db, premium_owner["user"]):
        r = await client.post(f"/qnr/editor/{unknown_id}/publish")

    assert r.status_code == 404
