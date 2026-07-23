"""Tests for permanent workflow (version family) delete."""

from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update

from smeme.app_factory import create_core_app as create_app
from smeme.core.models import (
    QNR,
    Memo,
    QNRSession,
    ReasoningCompiledArtifact,
    User,
)
from smeme.qnr.helpers.workflow_delete import DELETE_CONFIRM_PHRASE
from tests.conftest import auth_as

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _delete_workflow(client, qnr_id, *, confirm_phrase: str):
    return await client.delete(
        f"/qnr/{qnr_id}/delete",
        params={"confirm_phrase": confirm_phrase},
    )


def _minimal_graph(title: str = "Test QNR") -> dict:
    from smeme.qnr.models import (
        ConclusionData,
        DTGraph,
        GraphEdge,
        GraphNode,
        QNRMetadata,
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
        metadata=QNRMetadata(title=title),
    )
    return g.model_dump(mode="json")


@pytest_asyncio.fixture
async def delete_user(test_session_factory):
    uid = uuid4().hex[:8]
    email = f"del_{uid}@example.com"

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password="unused",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"deluser_{uid}",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        root = QNR(
            author_id=user.id,
            title=f"Root {uid}",
            graph_data=_minimal_graph(f"Root {uid}"),
            is_public=False,
            is_current=False,
            version_number=1,
            is_archived=False,
        )
        session.add(root)
        await session.commit()
        await session.refresh(root)

        current = QNR(
            author_id=user.id,
            title=f"Current {uid}",
            graph_data=_minimal_graph(f"Current {uid}"),
            is_public=False,
            is_current=True,
            version_number=2,
            parent_qnr_id=root.id,
            is_archived=False,
        )
        session.add(current)
        await session.commit()
        await session.refresh(current)

        qnr_session = QNRSession(user_id=user.id, qnr_id=current.id)
        session.add(qnr_session)
        await session.commit()
        await session.refresh(qnr_session)

        memo = Memo(
            session_id=qnr_session.id,
            user_id=user.id,
            title="Memo",
            summary="s",
            recommendations="r",
        )
        session.add(memo)
        await session.commit()

        artifact = ReasoningCompiledArtifact(
            qnr_id=current.id,
            ir_json={"atoms": []},
            graph_hash="abc123",
            compiler_version="1",
            ir_format_version=1,
        )
        session.add(artifact)
        await session.commit()

    yield {"user": user, "root": root, "current": current}

    async with test_session_factory() as session:
        family_ids = [root.id, current.id]
        await session.execute(delete(Memo).where(Memo.session_id.in_(
            select(QNRSession.id).where(QNRSession.qnr_id.in_(family_ids))
        )))
        await session.execute(delete(QNRSession).where(QNRSession.qnr_id.in_(family_ids)))
        await session.execute(
            delete(ReasoningCompiledArtifact).where(ReasoningCompiledArtifact.qnr_id.in_(family_ids))
        )
        await session.execute(
            update(QNR).where(QNR.id.in_(family_ids)).values(parent_qnr_id=None)
        )
        await session.execute(delete(QNR).where(QNR.id.in_(family_ids)))
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


async def test_dashboard_shows_delete_ui_by_default(client, app_with_db, delete_user):
    with auth_as(app_with_db, delete_user["user"]):
        r = await client.get("/qnr/dashboard")
    assert r.status_code == 200
    assert b"delete-confirm" in r.content
    assert b"archive-confirm" not in r.content


async def test_delete_wrong_phrase_returns_400(client, app_with_db, delete_user):
    qnr_id = delete_user["current"].id
    with auth_as(app_with_db, delete_user["user"]):
        r = await _delete_workflow(client, qnr_id, confirm_phrase="wrong phrase")
    assert r.status_code == 400


async def test_delete_non_author_returns_403(client, app_with_db, delete_user, test_session_factory):
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

    qnr_id = delete_user["current"].id
    with auth_as(app_with_db, other):
        r = await _delete_workflow(client, qnr_id, confirm_phrase=DELETE_CONFIRM_PHRASE)
    assert r.status_code == 403

    async with test_session_factory() as session:
        await session.execute(delete(User).where(User.id == other.id))
        await session.commit()


async def test_delete_non_current_version_returns_400(client, app_with_db, delete_user):
    qnr_id = delete_user["root"].id
    with auth_as(app_with_db, delete_user["user"]):
        r = await _delete_workflow(client, qnr_id, confirm_phrase=DELETE_CONFIRM_PHRASE)
    assert r.status_code == 400


async def test_delete_removes_entire_family_and_related_rows(
    client, app_with_db, delete_user, test_session_factory
):
    user = delete_user["user"]
    qnr_id = delete_user["current"].id
    title = delete_user["current"].title
    family_ids = {delete_user["root"].id, delete_user["current"].id}

    with auth_as(app_with_db, user):
        r = await _delete_workflow(client, qnr_id, confirm_phrase=DELETE_CONFIRM_PHRASE)

    assert r.status_code == 200
    assert b"permanently deleted" in r.content
    assert title.encode() in r.content  # success flash
    assert b"No decision trees yet" in r.content

    async with test_session_factory() as session:
        remaining_qnrs = await session.execute(select(QNR.id).where(QNR.id.in_(family_ids)))
        assert remaining_qnrs.scalars().all() == []

        remaining_sessions = await session.execute(
            select(func.count(QNRSession.id)).where(QNRSession.qnr_id.in_(family_ids))
        )
        assert remaining_sessions.scalar() == 0

        remaining_artifacts = await session.execute(
            select(func.count(ReasoningCompiledArtifact.qnr_id)).where(
                ReasoningCompiledArtifact.qnr_id.in_(family_ids)
            )
        )
        assert remaining_artifacts.scalar() == 0

        root_count = await session.execute(
            select(func.count(QNR.id)).where(
                QNR.author_id == user.id,
                QNR.parent_qnr_id.is_(None),
            )
        )
        assert root_count.scalar() == 0

