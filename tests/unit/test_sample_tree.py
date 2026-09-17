"""Per-user sample tree: fixture concludes, helper is idempotent, doors share it."""

from __future__ import annotations

import asyncio
import json
import runpy
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from smeme.app_factory import create_core_app as create_app
from smeme.core.models import DecisionTree, ReasoningCompiledArtifact, User
from smeme.decision_tree.models import DTGraph
from smeme.decision_tree.sample_tree import (
    CANNED_RAW_ANSWERS,
    EXPECTED_CONCLUSION_ID,
    EXPECTED_RESULT_KIND,
    SAMPLE_KEY,
    SAMPLE_TITLE,
    ensure_sample_tree,
    sample_graph,
)
from smeme.reasoning.artifact_deploy import load_current_compiled_artifact
from smeme.reasoning.assistant_tools_row_status import reasoning_tools_row_state
from smeme.reasoning.ir.serialize import ir_from_json
from smeme.reasoning.publish_readiness import assess_publish_readiness_sync
from smeme.reasoning.runtime.evaluate import evaluate_reasoning
from smeme.reasoning.runtime.ingest_envelope import (
    ParsedIngestEnvelope,
    parse_ingest_envelope_dict,
    validate_reasoning_ingest_envelope,
)
from smeme.reasoning.runtime.report_builder import build_evaluation_report
from tests.conftest import auth_as


def _canned_report(graph: DTGraph):
    readiness = assess_publish_readiness_sync(graph)
    assert readiness.ready, (
        readiness.validation_errors,
        readiness.compile_error,
        [i.message for i in readiness.preflight_issues],
    )
    assert readiness.ir is not None
    eval_result, _audit = evaluate_reasoning(
        readiness.ir, raw_answers=CANNED_RAW_ANSWERS, skip_ir_validation=True
    )
    report = build_evaluation_report(
        graph=graph,
        envelope=ParsedIngestEnvelope(
            answers=dict(CANNED_RAW_ANSWERS),
            evidence_items=[],
            evidence_refs={},
        ),
        eval_result=eval_result,
    )
    return eval_result, report


def test_sample_graph_deploys_and_canned_answers_conclude() -> None:
    graph = sample_graph()
    eval_result, report = _canned_report(graph)
    assert eval_result.status == "SAT_UNIQUE"
    assert eval_result.true_conclusion_id == EXPECTED_CONCLUSION_ID
    assert report["result_kind"] == EXPECTED_RESULT_KIND


def test_canonical_fixture_keeps_graph_regression_answers_in_sync() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "smeme"
        / "decision_tree"
        / "fixtures"
        / "smeme_sample_v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    regression = fixture["graph"]["metadata"]["regression_fixtures"][0]
    assert regression["raw_answers"] == fixture["canned_raw_answers"]
    assert regression["expected_conclusion_id"] == fixture["expected_conclusion_id"]
    assert fixture["sample_key"] == SAMPLE_KEY
    assert fixture["title"] == SAMPLE_TITLE


def test_example_selects_only_durably_identified_sample() -> None:
    script_path = Path(__file__).resolve().parents[2] / "examples" / "smeme_apply_sample.py"
    namespace = runpy.run_path(str(script_path))
    assert namespace["CANNED_RAW_ANSWERS"] == CANNED_RAW_ANSWERS
    assert namespace["_pick_tree"]([{"id": "unrelated", "title": "Another tree"}]) is None
    assert namespace["_pick_tree"]([{"id": "collision", "title": SAMPLE_TITLE}]) is None


def test_example_canned_envelope_passes_grounding_validation() -> None:
    script_path = Path(__file__).resolve().parents[2] / "examples" / "smeme_apply_sample.py"
    namespace = runpy.run_path(str(script_path))
    envelope = parse_ingest_envelope_dict(namespace["_canned_ingest_envelope"]())
    readiness = assess_publish_readiness_sync(sample_graph())

    assert readiness.ir is not None
    warnings, harness_next = validate_reasoning_ingest_envelope(readiness.ir, envelope)
    assert warnings == []
    assert harness_next == "phase_2_ok"


async def _make_user(session, *, prefix: str) -> User:
    suffix = uuid4().hex[:10]
    user = User(
        email=f"{prefix}_{suffix}@example.com",
        hashed_password="unused_in_clerk_mode",
        is_active=True,
        is_verified=True,
        is_superuser=False,
        username=f"{prefix}{suffix}"[:40],
        is_premium=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest_asyncio.fixture
async def sample_owner(test_session_factory):
    async with test_session_factory() as session:
        user = await _make_user(session, prefix="sample")
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


@pytest.mark.asyncio
async def test_ensure_sample_tree_none_user_noops(test_session_factory):
    async with test_session_factory() as session:
        assert await ensure_sample_tree(None, session) is None


@pytest.mark.asyncio
async def test_ensure_sample_tree_idempotent_live_listed_and_evaluates(
    test_session_factory, sample_owner
):
    async with test_session_factory() as session:
        user = await session.get(User, sample_owner)
        first = await ensure_sample_tree(user, session)
        second = await ensure_sample_tree(user, session)
        assert first is not None
        assert second is not None
        assert first.id == second.id
        assert second.sample_key == SAMPLE_KEY
        count = await session.scalar(
            select(func.count())
            .select_from(DecisionTree)
            .where(
                DecisionTree.author_id == sample_owner,
                DecisionTree.is_current.is_(True),
            )
        )
        assert count == 1
        assert second.mcp_discoverable is True
        artifact = await load_current_compiled_artifact(session, second)
        assert reasoning_tools_row_state(second, artifact) == "live"
        assert artifact is not None
        ir = ir_from_json(artifact.ir_json)
        eval_result, _audit = evaluate_reasoning(
            ir, raw_answers=CANNED_RAW_ANSWERS, skip_ir_validation=True
        )
        graph = DTGraph.model_validate(second.graph_data)
        report = build_evaluation_report(
            graph=graph,
            envelope=ParsedIngestEnvelope(
                answers=dict(CANNED_RAW_ANSWERS),
                evidence_items=[],
                evidence_refs={},
            ),
            eval_result=eval_result,
        )
        assert report["result_kind"] == EXPECTED_RESULT_KIND
        assert eval_result.true_conclusion_id == EXPECTED_CONCLUSION_ID


@pytest.mark.asyncio
async def test_same_title_does_not_claim_user_authored_tree(test_session_factory, sample_owner):
    async with test_session_factory() as session:
        owner = await session.get(User, sample_owner)
        collision = DecisionTree(
            author_id=sample_owner,
            title=SAMPLE_TITLE,
            graph_data=sample_graph().model_dump(mode="json"),
            sample_key=None,
        )
        session.add(collision)
        await session.commit()
        await session.refresh(collision)

        sample = await ensure_sample_tree(owner, session)
        assert sample is not None
        assert sample.id != collision.id
        assert sample.sample_key == SAMPLE_KEY
        count = await session.scalar(
            select(func.count())
            .select_from(DecisionTree)
            .where(DecisionTree.author_id == sample_owner)
        )
        assert count == 2


@pytest.mark.asyncio
async def test_concurrent_ensure_creates_one_sample(test_session_factory, sample_owner):
    async def run_once():
        async with test_session_factory() as session:
            owner = await session.get(User, sample_owner)
            tree = await ensure_sample_tree(owner, session)
            assert tree is not None
            return tree.id

    first_id, second_id = await asyncio.gather(run_once(), run_once())
    assert first_id == second_id

    async with test_session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(DecisionTree)
            .where(
                DecisionTree.author_id == sample_owner,
                DecisionTree.sample_key == SAMPLE_KEY,
            )
        )
        assert count == 1


@pytest.mark.asyncio
async def test_ensure_sample_tree_is_owner_scoped(test_session_factory, sample_owner):
    async with test_session_factory() as session:
        owner = await session.get(User, sample_owner)
        tree = await ensure_sample_tree(owner, session)
        other = await _make_user(session, prefix="other")
        other_id = other.id
        listed = (
            (
                await session.execute(
                    select(DecisionTree).where(
                        DecisionTree.author_id == other_id,
                        DecisionTree.mcp_discoverable.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert listed == []
        assert tree is not None
        assert tree.author_id == sample_owner
    async with test_session_factory() as session:
        await session.execute(delete(User).where(User.id == other_id))
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


@pytest.mark.asyncio
async def test_dashboard_shows_load_sample(client, app_with_db, sample_owner, test_session_factory):
    async with test_session_factory() as session:
        user = await session.get(User, sample_owner)
    with auth_as(app_with_db, user):
        r = await client.get("/decision-trees/dashboard")
    assert r.status_code == 200
    assert b"Load sample" in r.content
    assert b'action="/decision-trees/sample"' in r.content


@pytest.mark.asyncio
async def test_dashboard_load_sample_posts(client, app_with_db, sample_owner, test_session_factory):
    async with test_session_factory() as session:
        user = await session.get(User, sample_owner)
    with auth_as(app_with_db, user):
        r = await client.post("/decision-trees/sample")
    assert r.status_code == 200
    assert SAMPLE_TITLE.encode() in r.content
    async with test_session_factory() as session:
        tree = (
            await session.execute(
                select(DecisionTree).where(DecisionTree.author_id == sample_owner)
            )
        ).scalar_one()
        assert tree.mcp_discoverable is True
        assert tree.reasoning_status == "compiled"
