"""Canonical, opt-in ACME account fixture."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from smeme.billing.providers import hosted_quota_enforcement_scope
from smeme.core.models import DecisionTree, ReasoningCompiledArtifact, User
from smeme.decision_tree.acme_example import (
    ACME_EXAMPLE_DISCLAIMER,
    ACME_EXAMPLE_PUBLIC_GRAPH_HASH,
    ACME_EXAMPLE_SAMPLE_KEY,
    ACME_EXAMPLE_SOURCE_GRAPH_HASH,
    ACME_EXAMPLE_TITLE,
    AcmeExampleError,
    acme_example_graph,
    ensure_acme_example_tree,
)
from smeme.decision_tree.deploy import DeployNotReadyError
from smeme.decision_tree.sample_tree import sample_graph
from smeme.reasoning.artifact_deploy import load_current_compiled_artifact
from smeme.reasoning.assistant_tools_row_status import reasoning_tools_row_state
from smeme.reasoning.graph_hash import canonical_graph_hash


async def _make_user(session, *, prefix: str, is_premium: bool = True) -> User:
    suffix = uuid4().hex[:10]
    user = User(
        email=f"{prefix}_{suffix}@example.com",
        hashed_password="unused_in_clerk_mode",
        is_active=True,
        is_verified=True,
        is_superuser=False,
        username=f"{prefix}{suffix}"[:40],
        is_premium=is_premium,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest_asyncio.fixture
async def acme_owner(test_session_factory):
    async with test_session_factory() as session:
        user = await _make_user(session, prefix="acme")
        user_id = user.id
    yield user_id
    async with test_session_factory() as session:
        tree_ids = (
            (
                await session.execute(
                    select(DecisionTree.id).where(DecisionTree.author_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        if tree_ids:
            await session.execute(
                delete(ReasoningCompiledArtifact).where(
                    ReasoningCompiledArtifact.decision_tree_id.in_(tree_ids)
                )
            )
            await session.execute(delete(DecisionTree).where(DecisionTree.id.in_(tree_ids)))
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


def test_acme_fixture_preserves_identity_hash_and_full_disclaimer() -> None:
    assert ACME_EXAMPLE_SAMPLE_KEY == "smeme_acme_xborder_withholding_v1"
    assert (
        canonical_graph_hash(acme_example_graph())
        == ACME_EXAMPLE_PUBLIC_GRAPH_HASH
        == "8ef94026608f5901a4ae10a4f0a706886e384b11968002b55b3dc1d565c4467e"
    )
    assert (
        ACME_EXAMPLE_SOURCE_GRAPH_HASH
        == "0aa2e969c7ecc57336904cc19599d0aa5aed8025686e4a526e47fee5a1ab4858"
    )
    assert acme_example_graph().metadata.regression_fixtures == []
    assert acme_example_graph().metadata.title == ACME_EXAMPLE_TITLE
    assert ACME_EXAMPLE_DISCLAIMER.startswith("Fictional technical demonstration only.")
    assert "must not be used to determine obligations in any real transaction" in (
        ACME_EXAMPLE_DISCLAIMER
    )
    assert "not been reviewed by qualified tax counsel" in ACME_EXAMPLE_DISCLAIMER


@pytest.mark.asyncio
async def test_ensure_acme_example_none_user_noops(test_session_factory):
    async with test_session_factory() as session:
        assert await ensure_acme_example_tree(None, session) is None


@pytest.mark.asyncio
async def test_ensure_acme_example_is_idempotent_deployed_listed_and_owned(
    test_session_factory,
    acme_owner,
):
    async with test_session_factory() as session:
        owner = await session.get(User, acme_owner)
        first = await ensure_acme_example_tree(owner, session)
        second = await ensure_acme_example_tree(owner, session)

        assert first is not None
        assert second is not None
        assert second.id == first.id
        assert second.author_id == acme_owner
        assert second.sample_key == ACME_EXAMPLE_SAMPLE_KEY
        assert second.mcp_discoverable is True
        count = await session.scalar(
            select(func.count())
            .select_from(DecisionTree)
            .where(
                DecisionTree.author_id == acme_owner,
                DecisionTree.sample_key == ACME_EXAMPLE_SAMPLE_KEY,
            )
        )
        assert count == 1

        artifact = await load_current_compiled_artifact(session, second)
        assert artifact is not None
        assert artifact.graph_hash == ACME_EXAMPLE_PUBLIC_GRAPH_HASH
        assert reasoning_tools_row_state(second, artifact) == "live"


@pytest.mark.asyncio
async def test_same_title_collision_does_not_claim_user_tree(test_session_factory, acme_owner):
    async with test_session_factory() as session:
        owner = await session.get(User, acme_owner)
        collision = DecisionTree(
            author_id=acme_owner,
            title=ACME_EXAMPLE_TITLE,
            graph_data=sample_graph().model_dump(mode="json"),
            sample_key=None,
        )
        session.add(collision)
        await session.commit()
        await session.refresh(collision)

        example = await ensure_acme_example_tree(owner, session)
        assert example is not None
        assert example.id != collision.id
        assert example.sample_key == ACME_EXAMPLE_SAMPLE_KEY
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DecisionTree)
                .where(DecisionTree.author_id == acme_owner)
            )
            == 2
        )


@pytest.mark.asyncio
async def test_acme_example_is_strictly_account_scoped(test_session_factory, acme_owner):
    async with test_session_factory() as session:
        owner = await session.get(User, acme_owner)
        other = await _make_user(session, prefix="acme_other")
        other_id = other.id
        owner_tree = await ensure_acme_example_tree(owner, session)
        other_tree = await ensure_acme_example_tree(other, session)

        assert owner_tree is not None
        assert other_tree is not None
        assert owner_tree.id != other_tree.id
        assert owner_tree.author_id == acme_owner
        assert other_tree.author_id == other_id

    async with test_session_factory() as session:
        tree_ids = (
            (
                await session.execute(
                    select(DecisionTree.id).where(DecisionTree.author_id == other_id)
                )
            )
            .scalars()
            .all()
        )
        await session.execute(
            delete(ReasoningCompiledArtifact).where(
                ReasoningCompiledArtifact.decision_tree_id.in_(tree_ids)
            )
        )
        await session.execute(delete(DecisionTree).where(DecisionTree.id.in_(tree_ids)))
        await session.execute(delete(User).where(User.id == other_id))
        await session.commit()


@pytest.mark.asyncio
async def test_concurrent_acme_load_creates_one_tree(test_session_factory, acme_owner):
    async def run_once():
        async with test_session_factory() as session:
            owner = await session.get(User, acme_owner)
            tree = await ensure_acme_example_tree(owner, session)
            assert tree is not None
            return tree.id

    first_id, second_id = await asyncio.gather(run_once(), run_once())
    assert first_id == second_id

    async with test_session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DecisionTree)
                .where(
                    DecisionTree.author_id == acme_owner,
                    DecisionTree.sample_key == ACME_EXAMPLE_SAMPLE_KEY,
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_quota_blocks_new_fixture_but_not_active_reuse(
    test_session_factory,
    acme_owner,
):
    async with test_session_factory() as session:
        owner = await session.get(User, acme_owner)
        owner.is_premium = False
        session.add(owner)
        await session.commit()
        fixture = await ensure_acme_example_tree(owner, session)
        assert fixture is not None
        for index in range(2):
            session.add(
                DecisionTree(
                    author_id=acme_owner,
                    title=f"Existing {index}",
                    graph_data=sample_graph().model_dump(mode="json"),
                    is_current=True,
                    is_archived=False,
                )
            )
        await session.commit()

        with hosted_quota_enforcement_scope():
            reused = await ensure_acme_example_tree(owner, session)
        assert reused is not None
        assert reused.id == fixture.id

        new_owner = await _make_user(session, prefix="acme_quota", is_premium=False)
        new_owner_id = new_owner.id
        for index in range(3):
            session.add(
                DecisionTree(
                    author_id=new_owner_id,
                    title=f"At cap {index}",
                    graph_data=sample_graph().model_dump(mode="json"),
                    is_current=True,
                    is_archived=False,
                )
            )
        await session.commit()

        with (
            hosted_quota_enforcement_scope(),
            pytest.raises(
                AcmeExampleError,
                match="allows 3 active decision trees",
            ) as exc_info,
        ):
            await ensure_acme_example_tree(new_owner, session)
        assert exc_info.value.code == "quota_exceeded"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DecisionTree)
                .where(
                    DecisionTree.author_id == new_owner_id,
                    DecisionTree.sample_key == ACME_EXAMPLE_SAMPLE_KEY,
                )
            )
            == 0
        )

    async with test_session_factory() as session:
        await session.execute(delete(DecisionTree).where(DecisionTree.author_id == new_owner_id))
        await session.execute(delete(User).where(User.id == new_owner_id))
        await session.commit()


@pytest.mark.asyncio
async def test_deploy_failure_rolls_back_and_retry_succeeds(
    test_session_factory,
    acme_owner,
    monkeypatch,
):
    import smeme.decision_tree.acme_example as acme_module

    real_compile = acme_module.compile_and_persist_current_graph

    async def fail_deploy(*_args, **_kwargs):
        raise DeployNotReadyError(SimpleNamespace(ready=False))

    async with test_session_factory() as session:
        owner = await session.get(User, acme_owner)
        monkeypatch.setattr(acme_module, "compile_and_persist_current_graph", fail_deploy)
        with pytest.raises(AcmeExampleError, match="could not be Deployed") as exc_info:
            await ensure_acme_example_tree(owner, session)
        assert exc_info.value.code == "deploy_failed"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DecisionTree)
                .where(
                    DecisionTree.author_id == acme_owner,
                    DecisionTree.sample_key == ACME_EXAMPLE_SAMPLE_KEY,
                )
            )
            == 0
        )

        monkeypatch.setattr(acme_module, "compile_and_persist_current_graph", real_compile)
        await session.refresh(owner)
        retried = await ensure_acme_example_tree(owner, session)
        assert retried is not None
        assert retried.mcp_discoverable is True
