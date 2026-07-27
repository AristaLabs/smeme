"""Publish path must not commit partial state when the gate fails or commit errors."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.database import get_db
from smeme.core.models import (
    DecisionTree,
    DecisionTreeResearchCorpus,
    ReasoningCompiledArtifact,
    User,
)
from smeme.app_factory import create_core_app as create_app
from smeme.decision_tree.helpers.db_queries import parse_graph_data
from smeme.decision_tree.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    DTGraphMetadata,
    QuestionData,
)
from smeme.reasoning.cevi.induction import induce_published_evidence_contract_at_publish
from smeme.reasoning.ir.types import IR_FORMAT_VERSION
from smeme.reasoning.publish_readiness import assess_publish_readiness
from smeme.reasoning.published_evidence_contract import (
    AtomGlossEntryV1,
    DefaultsPolicyV1,
    OptionParaphraseSetV1,
    PublishedEvidenceContractV1,
    PublishedEvidenceProvenanceV1,
    cevi_fingerprint,
    contract_to_stored_json,
    validated_contract_with_ir_json,
)
from tests.conftest import auth_as

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _publishable_graph() -> dict:
    g = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Pick",
                    type="radio",
                    options=["Yes", "No"],
                    required=True,
                ),
            ),
            GraphNode(
                id="c1",
                type="conclusion",
                data=ConclusionData(title="Branch Alpha", summary="first outcome detail"),
            ),
            GraphNode(
                id="c2",
                type="conclusion",
                data=ConclusionData(title="Branch Beta", summary="second outcome detail"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="c2", condition="No"),
        ],
        metadata=DTGraphMetadata(title="reasoning publish integration"),
    )
    return g.model_dump(mode="json")


def _one_conclusion_graph() -> dict:
    g = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Only",
                    type="radio",
                    options=["A"],
                    required=True,
                ),
            ),
            GraphNode(
                id="c1",
                type="conclusion",
                data=ConclusionData(title="Only outcome", summary="x"),
            ),
        ],
        edges=[GraphEdge(source="q1", target="c1", condition="A")],
        metadata=DTGraphMetadata(title="invalid conclusions count"),
    )
    return g.model_dump(mode="json")


@pytest_asyncio.fixture
async def app_for_publish(test_session_factory):
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
async def premium_owner_publishable_decision_tree(test_session_factory):
    from uuid import uuid4

    suffix = uuid4().hex[:10]
    email = f"rs_pub_{suffix}@example.com"

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password="unused_in_clerk_mode",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"rspub{suffix}",
            is_premium=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        decision_tree = DecisionTree(
            author_id=user.id,
            title="Reasoning publish integration",
            graph_data=_publishable_graph(),
            is_public=False,
            reasoning_status=None,
        )
        session.add(decision_tree)
        await session.commit()
        await session.refresh(decision_tree)
        decision_tree_id = decision_tree.id

    yield {"email": email, "decision_tree_id": decision_tree_id, "user_id": user.id, "user": user}

    async with test_session_factory() as session:
        await session.execute(
            delete(ReasoningCompiledArtifact).where(ReasoningCompiledArtifact.decision_tree_id == decision_tree_id)
        )
        await session.execute(delete(DecisionTreeResearchCorpus).where(DecisionTreeResearchCorpus.decision_tree_id == decision_tree_id))
        await session.execute(delete(DecisionTree).where(DecisionTree.id == decision_tree_id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


@pytest_asyncio.fixture
async def premium_owner_invalid_decision_tree(test_session_factory):
    from uuid import uuid4

    suffix = uuid4().hex[:10]
    email = f"rs_blk_{suffix}@example.com"

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password="unused_in_clerk_mode",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"rsblk{suffix}",
            is_premium=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        decision_tree = DecisionTree(
            author_id=user.id,
            title="Invalid graph",
            graph_data=_one_conclusion_graph(),
            is_public=False,
            reasoning_status=None,
        )
        session.add(decision_tree)
        await session.commit()
        await session.refresh(decision_tree)
        decision_tree_id = decision_tree.id

    yield {"email": email, "decision_tree_id": decision_tree_id, "user": user}

    async with test_session_factory() as session:
        await session.execute(delete(DecisionTree).where(DecisionTree.id == decision_tree_id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


async def _count_artifacts(session, decision_tree_id) -> int:
    r = await session.execute(
        select(func.count())
        .select_from(ReasoningCompiledArtifact)
        .where(ReasoningCompiledArtifact.decision_tree_id == decision_tree_id)
    )
    return int(r.scalar_one())


@pytest.mark.golden_matrix
async def test_publish_gate_failure_rolls_back(
    app_for_publish, premium_owner_invalid_decision_tree, test_session_factory
):
    """GM-PUBLISH-ROLLBACK: publish gate failure must not commit partial artifact state."""
    data = premium_owner_invalid_decision_tree
    transport = ASGITransport(app=app_for_publish)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with auth_as(app_for_publish, data["user"]):
            resp = await client.post(
                f"/decision-trees/editor/{data['decision_tree_id']}/publish",
                follow_redirects=False,
            )
    assert resp.status_code == 400

    async with test_session_factory() as session:
        decision_tree = (await session.execute(select(DecisionTree).where(DecisionTree.id == data["decision_tree_id"]))).scalar_one()
        assert decision_tree.is_public is False
        assert await _count_artifacts(session, data["decision_tree_id"]) == 0


@pytest.mark.golden_matrix
async def test_publish_happy_path_persists_contract_and_hash(
    app_for_publish, premium_owner_publishable_decision_tree, test_session_factory
):
    """GM-PUBLISH-HAPPY: successful publish persists contract row + matching hash."""
    data = premium_owner_publishable_decision_tree
    transport = ASGITransport(app=app_for_publish)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with auth_as(app_for_publish, data["user"]):
            resp = await client.post(
                f"/decision-trees/editor/{data['decision_tree_id']}/publish",
                follow_redirects=False,
            )
    assert resp.status_code == 303

    async with test_session_factory() as session:
        decision_tree = (await session.execute(select(DecisionTree).where(DecisionTree.id == data["decision_tree_id"]))).scalar_one()
        assert decision_tree.is_public is False
        assert decision_tree.reasoning_status == "compiled"
        assert await _count_artifacts(session, data["decision_tree_id"]) == 1
        art = (
            await session.execute(
                select(ReasoningCompiledArtifact).where(
                    ReasoningCompiledArtifact.decision_tree_id == data["decision_tree_id"]
                )
            )
        ).scalar_one()
        assert art.cevi_contract_json is not None
        assert art.cevi_contract_hash is not None
        assert len(art.cevi_contract_hash) == 64
        assert art.research_corpus_hash is None
        assert art.cevi_legal_validation_status == "not_required"
        assert art.cevi_legal_validation_error is None
        c = PublishedEvidenceContractV1.model_validate(art.cevi_contract_json)
        assert c.kind == "corpus_partial"
        assert cevi_fingerprint(c) == art.cevi_contract_hash
        expected, corpus_snap = induce_published_evidence_contract_at_publish(
            ir_json=art.ir_json,
            graph=parse_graph_data(decision_tree),
            graph_hash=art.graph_hash,
            ir_format_version=IR_FORMAT_VERSION,
            corpus_body=None,
            legal_at_publish=False,
        )
        assert corpus_snap.sha256_hex is None
        assert contract_to_stored_json(expected) == art.cevi_contract_json
        assert art.artifact_version == 1
        assert art.artifact_hash is not None
        assert len(art.artifact_hash) == 64
        assert art.ir_hash is not None
        assert decision_tree.current_artifact_id == art.id


@pytest.mark.golden_matrix
async def test_publish_idempotent_redeploy_same_version(
    app_for_publish, premium_owner_publishable_decision_tree, test_session_factory
):
    """Identical redeploy returns the same artifact version and row (D025)."""
    data = premium_owner_publishable_decision_tree
    transport = ASGITransport(app=app_for_publish)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with auth_as(app_for_publish, data["user"]):
            first = await client.post(
                f"/decision-trees/editor/{data['decision_tree_id']}/publish",
                follow_redirects=False,
            )
            assert first.status_code == 303
            second = await client.post(
                f"/decision-trees/editor/{data['decision_tree_id']}/publish",
                follow_redirects=False,
            )
            assert second.status_code == 303

    async with test_session_factory() as session:
        assert await _count_artifacts(session, data["decision_tree_id"]) == 1
        art = (
            await session.execute(
                select(ReasoningCompiledArtifact).where(
                    ReasoningCompiledArtifact.decision_tree_id == data["decision_tree_id"]
                )
            )
        ).scalar_one()
        decision_tree = (
            await session.execute(select(DecisionTree).where(DecisionTree.id == data["decision_tree_id"]))
        ).scalar_one()
        assert art.artifact_version == 1
        assert decision_tree.current_artifact_id == art.id


@pytest.mark.golden_matrix
async def test_publish_contract_validates_and_round_trips(
    app_for_publish, premium_owner_publishable_decision_tree, test_session_factory
):
    """Non-empty CEVI contract persists only after IR-aware validation."""
    from smeme.reasoning.cevi.corpus_normalize import build_research_corpus_snapshot

    data = premium_owner_publishable_decision_tree

    def fake_induce(
        *,
        ir_json: dict,
        graph: DTGraph,
        graph_hash: str,
        ir_format_version: int,
        corpus_body: str | None,
        legal_at_publish: bool,
    ):
        contract = PublishedEvidenceContractV1(
            kind="corpus_partial",
            atom_glosses={
                "node:q1": AtomGlossEntryV1(text="Pick Yes or No."),
            },
            option_paraphrases={
                "node:q1": OptionParaphraseSetV1(
                    by_option={
                        "Yes": ("yep", "sure"),
                        "No": ("nope",),
                    },
                ),
            },
            defaults=DefaultsPolicyV1(world_assumption="closed_world"),
            provenance=PublishedEvidenceProvenanceV1(
                research_corpus_hash=None,
                graph_hash=graph_hash,
                ir_format_version=ir_format_version,
                legal=legal_at_publish,
            ),
        )
        snap = build_research_corpus_snapshot(corpus_body)
        return contract, snap

    transport = ASGITransport(app=app_for_publish)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with auth_as(app_for_publish, data["user"]):
            with patch(
                "smeme.decision_tree.editor.routes.induce_published_evidence_contract_at_publish",
                side_effect=fake_induce,
            ):
                resp = await client.post(
                    f"/decision-trees/editor/{data['decision_tree_id']}/publish",
                    follow_redirects=False,
                )
    assert resp.status_code == 303

    async with test_session_factory() as session:
        art = (
            await session.execute(
                select(ReasoningCompiledArtifact).where(
                    ReasoningCompiledArtifact.decision_tree_id == data["decision_tree_id"]
                )
            )
        ).scalar_one()
        assert art.cevi_contract_json is not None
        assert art.ir_json is not None
        round_tripped = validated_contract_with_ir_json(art.cevi_contract_json, ir_json=art.ir_json)
        assert round_tripped.atom_glosses["node:q1"].text == "Pick Yes or No."
        assert set(round_tripped.option_paraphrases["node:q1"].by_option.keys()) == {"Yes", "No"}
        assert cevi_fingerprint(round_tripped) == art.cevi_contract_hash


@pytest.mark.golden_matrix
async def test_publish_persists_research_corpus_hash_when_corpus_saved(
    app_for_publish, premium_owner_publishable_decision_tree, test_session_factory
):
    """Corpus bytes at publish time freeze into artifact + contract provenance."""
    from smeme.reasoning.cevi.corpus_normalize import normalized_corpus_sha256_or_none

    data = premium_owner_publishable_decision_tree
    decision_tree_id = data["decision_tree_id"]
    body = (
        "SME research corpus for Pick Yes No. Branch Alpha versus Branch Beta "
        "first outcome detail second outcome detail.\n"
    )
    async with test_session_factory() as session:
        session.add(DecisionTreeResearchCorpus(decision_tree_id=decision_tree_id, body_text=body))
        await session.commit()

    expected_hash = normalized_corpus_sha256_or_none(body)
    assert expected_hash is not None

    transport = ASGITransport(app=app_for_publish)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with auth_as(app_for_publish, data["user"]):
            resp = await client.post(
                f"/decision-trees/editor/{decision_tree_id}/publish",
                follow_redirects=False,
            )
    assert resp.status_code == 303

    async with test_session_factory() as session:
        art = (
            await session.execute(
                select(ReasoningCompiledArtifact).where(ReasoningCompiledArtifact.decision_tree_id == decision_tree_id)
            )
        ).scalar_one()
        assert art.research_corpus_hash == expected_hash
        c = PublishedEvidenceContractV1.model_validate(art.cevi_contract_json)
        assert c.provenance.research_corpus_hash == expected_hash
        assert len(c.corpus_chunk_manifest) >= 1
        assert any(len(g.corpus_chunk_ids) >= 1 for g in c.atom_glosses.values())


async def test_publish_commit_failure_no_durable_publish(
    app_for_publish, premium_owner_publishable_decision_tree, test_session_factory
):
    data = premium_owner_publishable_decision_tree

    async def boom_commit(self) -> None:
        raise RuntimeError("simulated commit failure")

    transport = ASGITransport(app=app_for_publish)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with auth_as(app_for_publish, data["user"]):
            with patch.object(AsyncSession, "commit", boom_commit):
                with pytest.raises(RuntimeError, match="simulated commit failure"):
                    await client.post(
                        f"/decision-trees/editor/{data['decision_tree_id']}/publish",
                        follow_redirects=False,
                    )

    async with test_session_factory() as session:
        decision_tree = (await session.execute(select(DecisionTree).where(DecisionTree.id == data["decision_tree_id"]))).scalar_one()
        assert decision_tree.is_public is False
        assert await _count_artifacts(session, data["decision_tree_id"]) == 0
