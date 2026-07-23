"""Unit tests for account deletion pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi_users.db import SQLAlchemyUserDatabase
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from smeme.auth.account_delete import (
    DELETE_ACCOUNT_CONFIRM_PHRASE,
    DeleteAccountStatus,
    delete_user_account,
    phrase_matches,
)
from smeme.auth.clerk_auth import get_or_create_user_for_clerk
from smeme.auth.manager import UserManager
from smeme.core.models import DecisionTree, Memo, DecisionTreeSession, User, UserAuditLog
from smeme.app_factory import create_core_app as create_app
from smeme.decision_tree.models import InProgressDecisionTreeGeneration
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
        ],
        edges=[GraphEdge(source="q1", target="c1", condition="Yes")],
        metadata=DTGraphMetadata(title=title),
    )
    return g.model_dump(mode="json")


@pytest_asyncio.fixture
async def account_user(test_session_factory):
    uid = uuid4().hex[:8]
    email = f"acctdel_{uid}@example.com"
    clerk_id = f"user_clerk_{uid}"

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password="unused",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"acctdel_{uid}",
            clerk_user_id=clerk_id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        decision_tree = DecisionTree(
            author_id=user.id,
            title=f"Workflow {uid}",
            graph_data=_minimal_graph(),
            is_public=False,
            is_current=True,
            version_number=1,
            is_archived=False,
        )
        session.add(decision_tree)
        await session.commit()
        await session.refresh(decision_tree)

        decision_tree_session = DecisionTreeSession(user_id=user.id, decision_tree_id=decision_tree.id)
        session.add(decision_tree_session)
        await session.commit()
        await session.refresh(decision_tree_session)

        session.add(
            Memo(
                session_id=decision_tree_session.id,
                user_id=user.id,
                title="Memo",
                summary="s",
                recommendations="r",
            )
        )
        session.add(
            InProgressDecisionTreeGeneration(
                user_id=user.id,
                langgraph_thread_id=str(uuid4()),
                user_prompt_preview="test prompt",
            )
        )
        await session.commit()

    yield {"user": user, "email": email, "clerk_user_id": clerk_id}


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


def _delete_patches():
    clerk_mock = AsyncMock()
    return (
        patch(
            "smeme.auth.account_delete.checkpointer_manager.delete_checkpoints_for_thread",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "smeme.auth.account_delete.cancel_subscription_if_needed",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "smeme.auth.account_delete.Clerk",
            return_value=MagicMock(users=MagicMock(delete_async=clerk_mock)),
        ),
        clerk_mock,
    )


class TestPhraseMatching:
    pytestmark: list = []

    def test_exact_match(self):
        assert phrase_matches("delete my account permanently")

    def test_case_insensitive(self):
        assert phrase_matches("DELETE MY ACCOUNT PERMANENTLY")

    def test_whitespace_trimmed(self):
        assert phrase_matches("  delete my account permanently  ")

    def test_wrong_phrase(self):
        assert not phrase_matches("delete my account")


class TestDeleteUserAccount:
    async def test_removes_user_and_owned_data(self, test_session_factory, account_user):
        user_id = account_user["user"].id
        cp_patch, provider_patch, clerk_patch, _clerk = _delete_patches()
        with cp_patch, provider_patch, clerk_patch:
            async with test_session_factory() as session:
                db_user = (
                    await session.execute(select(User).where(User.id == user_id))
                ).scalar_one()
                result = await delete_user_account(session, db_user, actor="profile")

        assert result.status == DeleteAccountStatus.DELETED

        async with test_session_factory() as session:
            assert (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none() is None
            assert (
                await session.scalar(
                    select(func.count()).select_from(DecisionTree).where(DecisionTree.author_id == user_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DecisionTreeSession)
                    .where(DecisionTreeSession.user_id == user_id)
                )
            ) == 0
            audit = (
                (
                    await session.execute(
                        select(UserAuditLog).where(UserAuditLog.event_type == "account.deleted")
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit) >= 1

    async def test_idempotent_when_user_gone(self, test_session_factory, account_user):
        user = account_user["user"]
        cp_patch, provider_patch, clerk_patch, _ = _delete_patches()
        with cp_patch, provider_patch, clerk_patch:
            async with test_session_factory() as session:
                db_user = (
                    await session.execute(select(User).where(User.id == user.id))
                ).scalar_one()
                await delete_user_account(session, db_user, actor="clerk_webhook")
            async with test_session_factory() as session:
                result = await delete_user_account(session, user, actor="clerk_webhook")
        assert result.status == DeleteAccountStatus.ALREADY_DELETED

    async def test_resignup_same_email_creates_fresh_user(self, test_session_factory, account_user):
        user = account_user["user"]
        email = account_user["email"]
        old_id = user.id
        new_clerk_id = f"user_clerk_new_{uuid4().hex[:8]}"

        cp_patch, provider_patch, clerk_patch, _ = _delete_patches()
        with cp_patch, provider_patch, clerk_patch:
            async with test_session_factory() as session:
                db_user = (
                    await session.execute(select(User).where(User.id == old_id))
                ).scalar_one()
                await delete_user_account(session, db_user, actor="profile")

        mock_clerk_user = MagicMock()
        mock_clerk_user.email_addresses = [MagicMock(email_address=email)]

        async with test_session_factory() as session:
            manager = UserManager(SQLAlchemyUserDatabase(session, User))
            with patch("smeme.auth.clerk_auth.Clerk") as clerk_cls:
                clerk_cls.return_value.users.get_async = AsyncMock(return_value=mock_clerk_user)
                new_user = await get_or_create_user_for_clerk(session, manager, new_clerk_id)

        assert new_user is not None
        assert new_user.id != old_id
        assert new_user.email == email

        async with test_session_factory() as session:
            decision_tree_count = await session.scalar(
                select(func.count()).select_from(DecisionTree).where(DecisionTree.author_id == new_user.id)
            )
        assert decision_tree_count == 0


class TestProfileDeleteRoutes:
    async def test_delete_account_wrong_phrase_returns_400(self, client, app_with_db, account_user):
        with auth_as(app_with_db, account_user["user"]):
            response = await client.post(
                "/auth/profile/delete-account",
                data={"confirm_phrase": "wrong phrase"},
                headers={"HX-Request": "true"},
            )
        assert response.status_code == 400
        assert "delete my account permanently" in response.text

    async def test_delete_account_success_redirects(
        self, client, app_with_db, account_user, test_session_factory
    ):
        user_id = account_user["user"].id
        cp_patch, provider_patch, clerk_patch, _ = _delete_patches()
        with cp_patch, provider_patch, clerk_patch, auth_as(app_with_db, account_user["user"]):
            response = await client.post(
                "/auth/profile/delete-account",
                data={"confirm_phrase": DELETE_ACCOUNT_CONFIRM_PHRASE},
                headers={"HX-Request": "true"},
            )
        assert response.status_code == 200
        assert response.headers.get("HX-Redirect") == "/auth/logout"

        async with test_session_factory() as session:
            assert (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none() is None

    async def test_profile_shows_delete_button(self, client, app_with_db, account_user):
        with auth_as(app_with_db, account_user["user"]):
            response = await client.get("/auth/profile/dashboard")
        assert response.status_code == 200
        assert "Delete account permanently" in response.text
        assert "delete-account-modal" in response.text
