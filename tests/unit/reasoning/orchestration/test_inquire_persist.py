"""Phase 6 durable Inquire session service tests.

Requires an isolated Postgres (``TEST_DATABASE_URL``). Skips when unavailable.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from smeme.core.models import DecisionTree, InquirySession, ReasoningCompiledArtifact, User
from smeme.decision_tree.models import DTGraph
from smeme.mcp.inquire.handlers import InquireHandlerError
from smeme.reasoning.artifact_identity import compute_identity_fields_from_stored_artifact
from smeme.reasoning.graph_hash import canonical_graph_hash
from smeme.reasoning.ir.serialize import ir_to_json
from smeme.reasoning.ir.types import IR_FORMAT_VERSION
from smeme.reasoning.orchestration.inquire.persist import (
    STATUS_ACTIVE,
    STATUS_STOPPED,
    admit_to_session,
    get_task_for_session,
    next_directive,
    start_inquiry,
    verify_session,
)
from smeme.reasoning.orchestration.inquire.persist.service import abandon_session
from smeme.reasoning.version import REASONING_COMPILER_VERSION
from tests.unit.reasoning.runtime.inquire_fixtures import (
    compile_golden,
    fork_g2_graph,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.usefixtures("_db_ready"),
]


@pytest_asyncio.fixture(scope="module")
async def _db_ready(test_session_factory):
    """Skip module if inquiry tables or DB connection unavailable."""
    try:
        async with test_session_factory() as db:
            await db.execute(text("SELECT 1 FROM inquiry_sessions LIMIT 0"))
    except Exception as exc:  # noqa: BLE001 — intentional skip gate
        pytest.skip(f"Inquire persist DB unavailable: {exc}")


def _choice_for(catalog: dict, qid: str) -> str:
    opts = catalog[qid]["options"]
    if "Yes" in opts:
        return "Yes"
    if "B" in opts:
        return "B"
    return opts[0]


async def _seed_deployed_inquire_tree(session_factory):
    fixture = compile_golden(fork_g2_graph())
    graph_dict = fixture.graph.model_dump(mode="json")
    live_hash = canonical_graph_hash(fixture.graph)
    uid = uuid4()
    async with session_factory() as db:
        user = User(
            id=uid,
            email=f"inquire_{uid.hex[:8]}@example.com",
            hashed_password="unused",
            is_active=True,
            is_verified=True,
            clerk_user_id=f"user_{uid.hex[:8]}",
            username=f"inquire_{uid.hex[:8]}",
        )
        db.add(user)
        await db.flush()
        tree = DecisionTree(
            title="Inquire Phase 6",
            author_id=uid,
            graph_data=graph_dict,
            mcp_discoverable=True,
            reasoning_status="compiled",
        )
        db.add(tree)
        await db.flush()
        artifact = ReasoningCompiledArtifact(
            decision_tree_id=tree.id,
            ir_json=ir_to_json(fixture.ir),
            graph_hash=live_hash,
            compiler_version=REASONING_COMPILER_VERSION,
            ir_format_version=IR_FORMAT_VERSION,
            artifact_version=1,
        )
        artifact.ir_hash, artifact.artifact_hash = (
            compute_identity_fields_from_stored_artifact(artifact)
        )
        db.add(artifact)
        await db.flush()
        tree.current_artifact_id = artifact.id
        await db.commit()
        await db.refresh(user)
        await db.refresh(tree)
        await db.refresh(artifact)
        return user, tree, artifact, fixture


async def _drive_to_stop(session_factory, user, session_id: UUID) -> dict:
    out: dict | None = None
    for step in range(12):
        async with session_factory() as db:
            nxt = await next_directive(db, user=user, inquiry_session_id=session_id)
        action = nxt["directive"]["action"]
        if action == "STOP" or nxt["status"] == STATUS_STOPPED:
            return nxt
        if action == "ACQUIRE":
            qid = nxt["directive"]["question_id"]
            async with session_factory() as db:
                row = await db.get(InquirySession, session_id)
                assert row is not None
                choice = _choice_for(row.worksheet_catalog, qid)
                out = await admit_to_session(
                    db,
                    user=user,
                    inquiry_session_id=session_id,
                    expected_revision=nxt["revision"],
                    question_id=qid,
                    selected_option=choice,
                    provenance_id=f"p-{qid}-{step}",
                    idempotency_key=f"admit-{step}",
                )
            if out["directive"]["action"] == "STOP" or out["status"] == STATUS_STOPPED:
                return out
            continue
        if action == "VERIFY":
            key = nxt["directive"]["verification_key"]
            live = nxt["directive"]["option"]
            observations = [
                {
                    "evaluation_id": item["evaluation_id"],
                    "question_id": item["task"]["question_id"],
                    "selected_option": live,
                    "provenance_id": f"pv-{key['question_id']}-{i}",
                }
                for i, item in enumerate(nxt["evaluations"])
            ]
            async with session_factory() as db:
                out = await verify_session(
                    db,
                    user=user,
                    inquiry_session_id=session_id,
                    expected_revision=nxt["revision"],
                    verification_key=key,
                    observations=observations,
                    idempotency_key=f"verify-{step}",
                )
            if out["directive"]["action"] == "STOP" or out["status"] == STATUS_STOPPED:
                return out
            continue
        msg = f"unexpected action {action}"
        raise AssertionError(msg)
    raise AssertionError("did not reach STOP")


async def test_green_loop_start_admit_verify_stop(test_session_factory) -> None:
    user, tree, artifact, fixture = await _seed_deployed_inquire_tree(test_session_factory)
    graph = DTGraph.model_validate(tree.graph_data)

    async with test_session_factory() as db:
        started = await start_inquiry(
            db,
            user=user,
            decision_tree=tree,
            artifact=artifact,
            graph=graph,
        )
    assert started["directive"]["action"] == "ACQUIRE"
    session_id = UUID(started["inquiry_session_id"])
    assert started["revision"] == 1

    async with test_session_factory() as db:
        task = await get_task_for_session(
            db,
            user=user,
            inquiry_session_id=session_id,
            question_id=started["directive"]["question_id"],
        )
    assert set(task.keys()) == {"question_id", "stem", "options"}
    assert task["stem"] == fixture.catalog[task["question_id"]].stem

    final = await _drive_to_stop(test_session_factory, user, session_id)
    assert final["directive"]["stop_reason"] == "verified_resolved_consequence"
    async with test_session_factory() as db:
        row = await db.get(InquirySession, session_id)
        assert row is not None
        assert row.status == STATUS_STOPPED


async def test_abstain_does_not_bump_revision(test_session_factory) -> None:
    user, tree, artifact, _ = await _seed_deployed_inquire_tree(test_session_factory)
    graph = DTGraph.model_validate(tree.graph_data)
    async with test_session_factory() as db:
        started = await start_inquiry(
            db, user=user, decision_tree=tree, artifact=artifact, graph=graph
        )
    session_id = UUID(started["inquiry_session_id"])
    revision = started["revision"]
    qid = started["directive"]["question_id"]

    async with test_session_factory() as db:
        abstain = await admit_to_session(
            db,
            user=user,
            inquiry_session_id=session_id,
            expected_revision=revision,
            question_id=qid,
            selected_option=None,
            provenance_id=None,
            idempotency_key="abstain-1",
        )
    assert abstain["admit_status"] == "abstained"
    assert abstain["revision"] == revision


async def test_insufficient_does_not_bump_revision(test_session_factory) -> None:
    user, tree, artifact, _ = await _seed_deployed_inquire_tree(test_session_factory)
    graph = DTGraph.model_validate(tree.graph_data)
    async with test_session_factory() as db:
        started = await start_inquiry(
            db, user=user, decision_tree=tree, artifact=artifact, graph=graph
        )
    session_id = UUID(started["inquiry_session_id"])

    for step in range(6):
        async with test_session_factory() as db:
            nxt = await next_directive(db, user=user, inquiry_session_id=session_id)
        if nxt["directive"]["action"] == "VERIFY":
            rev_before = nxt["revision"]
            key = nxt["directive"]["verification_key"]
            observations = [
                {
                    "evaluation_id": item["evaluation_id"],
                    "question_id": item["task"]["question_id"],
                    "selected_option": None,
                    "provenance_id": None,
                }
                for item in nxt["evaluations"]
            ]
            async with test_session_factory() as db:
                out = await verify_session(
                    db,
                    user=user,
                    inquiry_session_id=session_id,
                    expected_revision=rev_before,
                    verification_key=key,
                    observations=observations,
                    idempotency_key="insuff-1",
                )
            assert out["decision"]["kind"] == "insufficient"
            assert out["revision"] == rev_before
            assert out["status"] == STATUS_ACTIVE
            assert out["directive"]["action"] == "VERIFY"
            return
        assert nxt["directive"]["action"] == "ACQUIRE"
        qid = nxt["directive"]["question_id"]
        async with test_session_factory() as db:
            row = await db.get(InquirySession, session_id)
            assert row is not None
            choice = _choice_for(row.worksheet_catalog, qid)
            await admit_to_session(
                db,
                user=user,
                inquiry_session_id=session_id,
                expected_revision=nxt["revision"],
                question_id=qid,
                selected_option=choice,
                provenance_id=f"p-{qid}",
                idempotency_key=f"adm-{step}",
            )
    raise AssertionError("never reached VERIFY")


async def test_idempotency_replay_and_conflict(test_session_factory) -> None:
    user, tree, artifact, _ = await _seed_deployed_inquire_tree(test_session_factory)
    graph = DTGraph.model_validate(tree.graph_data)
    async with test_session_factory() as db:
        started = await start_inquiry(
            db, user=user, decision_tree=tree, artifact=artifact, graph=graph
        )
    session_id = UUID(started["inquiry_session_id"])
    qid = started["directive"]["question_id"]
    rev = started["revision"]

    async with test_session_factory() as db:
        first = await admit_to_session(
            db,
            user=user,
            inquiry_session_id=session_id,
            expected_revision=rev,
            question_id=qid,
            selected_option="Yes",
            provenance_id="p1",
            idempotency_key="same-key",
        )
    async with test_session_factory() as db:
        replay = await admit_to_session(
            db,
            user=user,
            inquiry_session_id=session_id,
            expected_revision=rev,
            question_id=qid,
            selected_option="Yes",
            provenance_id="p1",
            idempotency_key="same-key",
        )
    assert replay == first

    async with test_session_factory() as db:
        with pytest.raises(InquireHandlerError) as exc:
            await admit_to_session(
                db,
                user=user,
                inquiry_session_id=session_id,
                expected_revision=first["revision"],
                question_id=qid,
                selected_option="Yes",
                provenance_id="p-other",
                idempotency_key="same-key",
            )
    assert exc.value.code == "inquire_idempotency_conflict"


async def test_revision_conflict(test_session_factory) -> None:
    user, tree, artifact, _ = await _seed_deployed_inquire_tree(test_session_factory)
    graph = DTGraph.model_validate(tree.graph_data)
    async with test_session_factory() as db:
        started = await start_inquiry(
            db, user=user, decision_tree=tree, artifact=artifact, graph=graph
        )
    session_id = UUID(started["inquiry_session_id"])
    async with test_session_factory() as db:
        with pytest.raises(InquireHandlerError) as exc:
            await admit_to_session(
                db,
                user=user,
                inquiry_session_id=session_id,
                expected_revision=999,
                question_id=started["directive"]["question_id"],
                selected_option="Yes",
                provenance_id="p",
                idempotency_key="bad-rev",
            )
    assert exc.value.code == "inquire_revision_conflict"


async def test_cross_user_not_found(test_session_factory) -> None:
    user, tree, artifact, _ = await _seed_deployed_inquire_tree(test_session_factory)
    graph = DTGraph.model_validate(tree.graph_data)
    async with test_session_factory() as db:
        started = await start_inquiry(
            db, user=user, decision_tree=tree, artifact=artifact, graph=graph
        )
    other = User(
        id=uuid4(),
        email=f"other_{uuid4().hex[:8]}@example.com",
        hashed_password="x",
        is_active=True,
        is_verified=True,
        clerk_user_id=f"user_other_{uuid4().hex[:8]}",
        username=f"other_{uuid4().hex[:8]}",
    )
    async with test_session_factory() as db:
        db.add(other)
        await db.commit()
        await db.refresh(other)
    async with test_session_factory() as db:
        with pytest.raises(InquireHandlerError) as exc:
            await next_directive(
                db,
                user=other,
                inquiry_session_id=UUID(started["inquiry_session_id"]),
            )
    assert exc.value.code == "not_found"


async def test_frozen_catalog_survives_graph_edit(test_session_factory) -> None:
    user, tree, artifact, fixture = await _seed_deployed_inquire_tree(test_session_factory)
    graph = DTGraph.model_validate(tree.graph_data)
    async with test_session_factory() as db:
        started = await start_inquiry(
            db, user=user, decision_tree=tree, artifact=artifact, graph=graph
        )
    session_id = UUID(started["inquiry_session_id"])
    qid = started["directive"]["question_id"]
    async with test_session_factory() as db:
        before = await get_task_for_session(
            db, user=user, inquiry_session_id=session_id, question_id=qid
        )

    async with test_session_factory() as db:
        row = await db.get(DecisionTree, tree.id)
        assert row is not None
        gd = dict(row.graph_data)
        for node in gd.get("nodes", []):
            if node.get("id") == qid and isinstance(node.get("data"), dict):
                node["data"]["text"] = "EDITED STEM MUST NOT LEAK"
        row.graph_data = gd
        await db.commit()

    async with test_session_factory() as db:
        after = await get_task_for_session(
            db, user=user, inquiry_session_id=session_id, question_id=qid
        )
    assert after == before
    assert after["stem"] == fixture.catalog[qid].stem


async def test_next_stop_while_active_is_invariant(test_session_factory) -> None:
    user, tree, artifact, _ = await _seed_deployed_inquire_tree(test_session_factory)
    graph = DTGraph.model_validate(tree.graph_data)
    async with test_session_factory() as db:
        started = await start_inquiry(
            db, user=user, decision_tree=tree, artifact=artifact, graph=graph
        )
    session_id = UUID(started["inquiry_session_id"])
    await _drive_to_stop(test_session_factory, user, session_id)

    async with test_session_factory() as db:
        row = await db.get(InquirySession, session_id)
        assert row is not None
        assert row.status == STATUS_STOPPED
        row.status = STATUS_ACTIVE
        await db.commit()

    async with test_session_factory() as db:
        with pytest.raises(InquireHandlerError) as exc:
            await next_directive(db, user=user, inquiry_session_id=session_id)
    assert exc.value.code == "inquire_session_invariant"


async def test_abandon_session(test_session_factory) -> None:
    user, tree, artifact, _ = await _seed_deployed_inquire_tree(test_session_factory)
    graph = DTGraph.model_validate(tree.graph_data)
    async with test_session_factory() as db:
        started = await start_inquiry(
            db, user=user, decision_tree=tree, artifact=artifact, graph=graph
        )
        out = await abandon_session(
            db,
            user=user,
            inquiry_session_id=UUID(started["inquiry_session_id"]),
        )
    assert out["status"] == "ABANDONED"


async def test_reject_stale_replay_on_admit(test_session_factory) -> None:
    """Chat-style mutation-identity keys: replay immediate retries, reject after advance."""
    user, tree, artifact, _ = await _seed_deployed_inquire_tree(test_session_factory)
    graph = DTGraph.model_validate(tree.graph_data)
    async with test_session_factory() as db:
        started = await start_inquiry(
            db, user=user, decision_tree=tree, artifact=artifact, graph=graph
        )
    session_id = UUID(started["inquiry_session_id"])
    qid = started["directive"]["question_id"]
    rev = started["revision"]
    async with test_session_factory() as db:
        row = await db.get(InquirySession, session_id)
        assert row is not None
        choice = _choice_for(row.worksheet_catalog, qid)

    stable_key = "chat-stable-admit-1"
    async with test_session_factory() as db:
        first = await admit_to_session(
            db,
            user=user,
            inquiry_session_id=session_id,
            expected_revision=rev,
            question_id=qid,
            selected_option=choice,
            provenance_id="p-stale-1",
            idempotency_key=stable_key,
            reject_stale_replay=True,
        )
    assert first["revision"] > rev

    async with test_session_factory() as db:
        replay = await admit_to_session(
            db,
            user=user,
            inquiry_session_id=session_id,
            expected_revision=first["revision"],
            question_id=qid,
            selected_option=choice,
            provenance_id="p-stale-1",
            idempotency_key=stable_key,
            reject_stale_replay=True,
        )
    assert replay == first

    # Advance session with a different admit (new key / different question).
    async with test_session_factory() as db:
        nxt = await next_directive(db, user=user, inquiry_session_id=session_id)
    if nxt["directive"]["action"] == "ACQUIRE":
        q2 = nxt["directive"]["question_id"]
        async with test_session_factory() as db:
            row = await db.get(InquirySession, session_id)
            assert row is not None
            choice2 = _choice_for(row.worksheet_catalog, q2)
            await admit_to_session(
                db,
                user=user,
                inquiry_session_id=session_id,
                expected_revision=nxt["revision"],
                question_id=q2,
                selected_option=choice2,
                provenance_id="p-advance",
                idempotency_key="advance-key",
            )
    elif nxt["status"] == STATUS_STOPPED or nxt["directive"]["action"] == "STOP":
        pytest.skip("fixture stopped after first admit; cannot advance for stale test")
    else:
        pytest.skip(f"unexpected directive {nxt['directive']['action']!r} after first admit")

    async with test_session_factory() as db:
        with pytest.raises(InquireHandlerError) as exc:
            await admit_to_session(
                db,
                user=user,
                inquiry_session_id=session_id,
                expected_revision=nxt["revision"],
                question_id=qid,
                selected_option=choice,
                provenance_id="p-stale-1",
                idempotency_key=stable_key,
                reject_stale_replay=True,
            )
    assert exc.value.code == "inquire_idempotency_conflict"


async def test_chat_evaluate_continue_replay_and_stale(test_session_factory) -> None:
    from smeme.mcp.inquire.chat_facade import (
        chat_admit_idempotency_key,
        chat_evaluate_continue,
    )

    user, tree, artifact, _ = await _seed_deployed_inquire_tree(test_session_factory)
    graph = DTGraph.model_validate(tree.graph_data)
    async with test_session_factory() as db:
        started = await start_inquiry(
            db, user=user, decision_tree=tree, artifact=artifact, graph=graph
        )
    session_id = UUID(started["inquiry_session_id"])
    qid = started["directive"]["question_id"]
    async with test_session_factory() as db:
        row = await db.get(InquirySession, session_id)
        assert row is not None
        choice = _choice_for(row.worksheet_catalog, qid)

    key = chat_admit_idempotency_key(
        inquiry_session_id=session_id,
        question_id=qid,
        selected_option=choice,
        provenance_id="p-chat-1",
    )
    assert key.startswith("chat-")
    assert len(key) > 10

    async with test_session_factory() as db:
        first = await chat_evaluate_continue(
            db,
            user=user,
            inquiry_session_id=session_id,
            question_id=qid,
            selected_option=choice,
            provenance_id="p-chat-1",
        )
    async with test_session_factory() as db:
        replay = await chat_evaluate_continue(
            db,
            user=user,
            inquiry_session_id=session_id,
            question_id=qid,
            selected_option=choice,
            provenance_id="p-chat-1",
        )
    assert replay == first
    assert "error" not in first or first.get("error", {}).get("code") != "inquire_idempotency_conflict"

    if first.get("_chat_stop") or first.get("error"):
        pytest.skip("session ended after first continue; cannot advance for stale test")

    # Advance with a different answer identity.
    q2 = first["task"]["question_id"]
    async with test_session_factory() as db:
        row = await db.get(InquirySession, session_id)
        assert row is not None
        choice2 = _choice_for(row.worksheet_catalog, q2)
    async with test_session_factory() as db:
        await chat_evaluate_continue(
            db,
            user=user,
            inquiry_session_id=session_id,
            question_id=q2,
            selected_option=choice2,
            provenance_id="p-chat-2",
        )

    async with test_session_factory() as db:
        with pytest.raises(InquireHandlerError) as exc:
            await chat_evaluate_continue(
                db,
                user=user,
                inquiry_session_id=session_id,
                question_id=qid,
                selected_option=choice,
                provenance_id="p-chat-1",
            )
    assert exc.value.code == "inquire_idempotency_conflict"


async def test_chat_settled_run_returns_unverified_report(test_session_factory) -> None:
    from sqlalchemy import func, select

    from smeme.core.models import InquiryAdmittedAssertion, ReasoningEvaluationRun
    from smeme.mcp.inquire.chat_facade import (
        CHAT_ISOLATED_VERIFICATION_NOT_RUN,
        admitted_apply_envelope_for_session,
        chat_evaluate_continue,
        chat_evaluate_start,
        merge_chat_stop_onto_apply,
        should_persist_chat_report,
    )
    from smeme.reasoning.ir.serialize import ir_from_json
    from smeme.reasoning.orchestration.inquire.persist import record_chat_report_issued
    from smeme.reasoning.persistence import persist_reasoning_evaluation_run
    from smeme.reasoning.runtime.evaluate import evaluate_reasoning
    from smeme.reasoning.runtime.ingest_envelope import prepare_evaluate_ingest
    from smeme.reasoning.runtime.report_builder import build_evaluation_report

    user, tree, artifact, _ = await _seed_deployed_inquire_tree(test_session_factory)
    graph = DTGraph.model_validate(tree.graph_data)
    async with test_session_factory() as db:
        started = await chat_evaluate_start(
            db, user=user, decision_tree=tree, artifact=artifact, graph=graph
        )
    session_id = UUID(started["inquiry_session_id"])
    assert started.get("harness_next") == "continue_evaluate"
    assert "task" in started

    last = started
    last_question = started["task"]["question_id"]
    last_option = ""
    last_provenance = ""
    for step in range(8):
        last_question = last["task"]["question_id"]
        async with test_session_factory() as db:
            row = await db.get(InquirySession, session_id)
            assert row is not None
            last_option = _choice_for(row.worksheet_catalog, last_question)
            last_provenance = f"p-settle-{step}"
            last = await chat_evaluate_continue(
                db,
                user=user,
                inquiry_session_id=session_id,
                question_id=last_question,
                selected_option=last_option,
                provenance_id=last_provenance,
            )
        if last.get("_chat_stop"):
            break
        assert last.get("harness_next") == "continue_evaluate"
    else:
        raise AssertionError("chat run did not settle")

    assert last["status"] == STATUS_ACTIVE
    assert last["stop_reason"] == CHAT_ISOLATED_VERIFICATION_NOT_RUN
    assert should_persist_chat_report(last) is True

    async def _admitted_count() -> int:
        async with test_session_factory() as db:
            n = await db.scalar(
                select(func.count())
                .select_from(InquiryAdmittedAssertion)
                .where(InquiryAdmittedAssertion.session_id == session_id)
            )
        return int(n or 0)

    admitted_after_settle = await _admitted_count()
    assert admitted_after_settle == 2

    async with test_session_factory() as db:
        replay_before_event = await chat_evaluate_continue(
            db,
            user=user,
            inquiry_session_id=session_id,
            question_id=last_question,
            selected_option=last_option,
            provenance_id=last_provenance,
        )
    assert replay_before_event.get("_chat_report_already_issued") is True
    assert should_persist_chat_report(replay_before_event) is False
    assert replay_before_event["stop_reason"] == CHAT_ISOLATED_VERIFICATION_NOT_RUN
    assert await _admitted_count() == admitted_after_settle

    async with test_session_factory() as db:
        envelope = await admitted_apply_envelope_for_session(
            db, user=user, inquiry_session_id=session_id
        )
        ir = ir_from_json(dict(artifact.ir_json))
        _flat, ingest_env, warnings, harness_next = prepare_evaluate_ingest(ir, envelope)
        eval_result, audit = evaluate_reasoning(
            ir, raw_answers=_flat, skip_ir_validation=True
        )
        report = build_evaluation_report(
            graph=graph, envelope=ingest_env, eval_result=eval_result
        )
        merged = merge_chat_stop_onto_apply(
            {"report": report, "warnings": warnings, "harness_next": harness_next},
            inquiry_session_id=str(session_id),
            stop_reason=last["stop_reason"],
        )
        assert merged["status"] == STATUS_ACTIVE
        assert merged["report"]["result_kind"] == "concluded"
        assert merged["report"]["inquire_stop_reason"] == CHAT_ISOLATED_VERIFICATION_NOT_RUN
        assert merged["harness_next"] != "continue_evaluate"
        row = await persist_reasoning_evaluation_run(
            db,
            decision_tree_id=tree.id,
            result=eval_result,
            audit=audit,
            caller_user_id=user.id,
            ingest_warnings=list(merged["warnings"] or []),
            report=dict(merged["report"]),
            artifact=artifact,
        )
        await record_chat_report_issued(
            db,
            user=user,
            inquiry_session_id=session_id,
            payload={
                "stop_reason": last["stop_reason"],
                "evaluation_run_id": str(row.id),
                "revision": last["revision"],
            },
        )
        stored_id = row.id

    async with test_session_factory() as db:
        stored = await db.get(ReasoningEvaluationRun, stored_id)
        assert stored is not None
        assert stored.report.get("result_kind") == "concluded"
        assert stored.report.get("inquire_stop_reason") == CHAT_ISOLATED_VERIFICATION_NOT_RUN
        assert stored.report.get("inquire_stop_reason") != "verified_resolved_consequence"
        warning_codes = [w.get("code") for w in (stored.ingest_warnings or [])]
        assert "inquire_verification_not_run" in warning_codes

    async with test_session_factory() as db:
        replay_after_event = await chat_evaluate_continue(
            db,
            user=user,
            inquiry_session_id=session_id,
            question_id=last_question,
            selected_option=last_option,
            provenance_id=last_provenance,
        )
        session_row = await db.get(InquirySession, session_id)
    assert replay_after_event.get("_chat_report_already_issued") is True
    assert should_persist_chat_report(replay_after_event) is False
    assert session_row is not None
    assert session_row.status == STATUS_ACTIVE
    assert await _admitted_count() == admitted_after_settle

    async with test_session_factory() as db:
        n_runs = await db.scalar(
            select(func.count())
            .select_from(ReasoningEvaluationRun)
            .where(ReasoningEvaluationRun.decision_tree_id == tree.id)
        )
    assert int(n_runs or 0) == 1

