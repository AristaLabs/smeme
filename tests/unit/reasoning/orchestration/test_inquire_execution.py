"""Phase 3 Inquire execution-boundary tests. Fake extractor + fake ``P_v`` only."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from smeme.reasoning.runtime.assumptions import EMPTY_ASSUMPTIONS
from smeme.reasoning.runtime.consistency_gate import PremiseInvariantError
from smeme.reasoning.runtime.inquire import (
    analyze_inquiry,
    build_extractor_issue,
)
from smeme.reasoning.runtime.inquire.policy import (
    AlwaysInsufficientPolicy,
    AlwaysRetainPolicy,
    AlwaysRetractPolicy,
    ReplaceWith,
    VerificationPolicy,
    VerificationRequest,
    VerificationResult,
)
from smeme.reasoning.runtime.inquire.transition import Retain
from smeme.reasoning.runtime.inquire.types import (
    CanonicalProvenanceId,
    ExtractionTask,
    InquiryBudget,
    InquiryDirective,
)
from smeme.reasoning.orchestration.inquire import (
    AbstainedExtraction,
    AnsweredExtraction,
    admit_extraction,
    execute_directive,
    step,
    verify_extraction,
)
from tests.unit.reasoning.runtime.inquire_fixtures import (
    SENTINEL_ARTIFACT,
    SENTINEL_PV_VERSION,
    compile_golden,
    fork_g2_graph,
    sentinel_provenance,
)

_BUDGET = InquiryBudget()


@dataclass
class ScriptedExtractor:
    """Returns scripted results keyed by ``question_id`` (FIFO per id)."""

    scripts: dict[str, list[AnsweredExtraction | AbstainedExtraction]]
    seen: list[ExtractionTask] = field(default_factory=list)

    def extract(self, task: ExtractionTask) -> AnsweredExtraction | AbstainedExtraction:
        self.seen.append(task)
        qid = task.question.question_id
        queue = self.scripts.get(qid)
        if not queue:
            msg = f"no scripted extraction for {qid!r}"
            raise AssertionError(msg)
        return queue.pop(0)


@dataclass
class RecordingPolicy:
    """Wraps a real fake policy and records ``decide`` calls."""

    inner: VerificationPolicy
    calls: list[tuple[VerificationRequest, VerificationResult]] = field(default_factory=list)

    def decide(
        self, request: VerificationRequest, result: VerificationResult
    ):
        self.calls.append((request, result))
        return self.inner.decide(request, result)


def _answered(qid: str, option: str, *, tag: str | None = None) -> AnsweredExtraction:
    return AnsweredExtraction(
        question_id=qid,
        selected_option=option,
        provenance_id=sentinel_provenance(tag or f"p-{qid}"),
    )


def test_same_task_indistinguishability_acquire_vs_verify() -> None:
    fixture = compile_golden(fork_g2_graph())
    acquire_task = build_extractor_issue(fixture.catalog, "q2")
    verify_task = build_extractor_issue(fixture.catalog, "q2")
    assert acquire_task == verify_task
    assert acquire_task.question.stem
    assert acquire_task.question.options == ("A", "B")
    blob = str(acquire_task)
    for forbidden in ("VERIFY", "ACQUIRE", "verification_key", "conclusion", "S_R"):
        assert forbidden not in blob


def test_recording_extractor_never_sees_mode() -> None:
    fixture = compile_golden(fork_g2_graph())
    extractor = ScriptedExtractor(
        scripts={
            "q1": [
                _answered("q1", "Yes"),
                _answered("q1", "Yes", tag="p-q1-verify"),
            ],
            "q2": [
                _answered("q2", "B"),
                _answered("q2", "B", tag="p-q2-verify"),
            ],
        }
    )
    policy = RecordingPolicy(AlwaysRetainPolicy())
    admitted: tuple = ()
    verified: frozenset = frozenset()

    # ACQUIRE q1
    out = step(
        ir=fixture.ir,
        admitted=admitted,
        assumptions=EMPTY_ASSUMPTIONS,
        verified=verified,
        budget=_BUDGET,
        worksheet_catalog=fixture.catalog,
        extractor=extractor,
        policy=policy,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert out.status == "acquired"
    assert out.directive.action == "ACQUIRE"
    admitted, verified = out.admitted, out.verified

    # ACQUIRE q2
    out = step(
        ir=fixture.ir,
        admitted=admitted,
        assumptions=EMPTY_ASSUMPTIONS,
        verified=verified,
        budget=_BUDGET,
        worksheet_catalog=fixture.catalog,
        extractor=extractor,
        policy=policy,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert out.status == "acquired"
    admitted, verified = out.admitted, out.verified

    # VERIFY q1 (policy runs; extractor may or may not be called depending on path)
    out = step(
        ir=fixture.ir,
        admitted=admitted,
        assumptions=EMPTY_ASSUMPTIONS,
        verified=verified,
        budget=_BUDGET,
        worksheet_catalog=fixture.catalog,
        extractor=extractor,
        policy=policy,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert out.status == "verified"
    assert out.directive.action == "VERIFY"

    for task in extractor.seen:
        assert not hasattr(task, "action")
        assert not hasattr(task, "verification_key")
        blob = str(task)
        assert "VERIFY" not in blob
        assert "ACQUIRE" not in blob


def test_green_loop_retain_walk_to_stop() -> None:
    fixture = compile_golden(fork_g2_graph())
    extractor = ScriptedExtractor(
        scripts={
            "q1": [
                _answered("q1", "Yes"),
                _answered("q1", "Yes", tag="p-q1-verify"),
            ],
            "q2": [
                _answered("q2", "B"),
                _answered("q2", "B", tag="p-q2-verify"),
            ],
        }
    )
    policy = AlwaysRetainPolicy()
    admitted: tuple = ()
    verified: frozenset = frozenset()
    statuses: list[str] = []
    actions: list[str] = []

    for _ in range(6):
        out = step(
            ir=fixture.ir,
            admitted=admitted,
            assumptions=EMPTY_ASSUMPTIONS,
            verified=verified,
            budget=_BUDGET,
            worksheet_catalog=fixture.catalog,
            extractor=extractor,
            policy=policy,
            artifact_identity=SENTINEL_ARTIFACT,
            pv_version=SENTINEL_PV_VERSION,
        )
        statuses.append(out.status)
        actions.append(out.directive.action)
        admitted, verified = out.admitted, out.verified
        if out.status == "stop":
            break

    assert actions[0] == "ACQUIRE"
    assert actions[1] == "ACQUIRE"
    assert "VERIFY" in actions
    assert statuses[-1] == "stop"
    assert out.directive.stop_reason == "verified_resolved_consequence"
    assert {item.question_id: item.option for item in admitted} == {"q1": "Yes", "q2": "B"}


def test_acquire_abstain_does_not_mutate_and_reissues() -> None:
    fixture = compile_golden(fork_g2_graph())
    extractor = ScriptedExtractor(
        scripts={
            "q1": [
                AbstainedExtraction(question_id="q1"),
                _answered("q1", "Yes"),
            ],
        }
    )
    policy = AlwaysRetainPolicy()
    out1 = step(
        ir=fixture.ir,
        admitted=(),
        assumptions=EMPTY_ASSUMPTIONS,
        verified=frozenset(),
        budget=_BUDGET,
        worksheet_catalog=fixture.catalog,
        extractor=extractor,
        policy=policy,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert out1.status == "abstained"
    assert out1.admitted == ()
    assert out1.directive.action == "ACQUIRE"
    assert out1.directive.question_id == "q1"

    out2 = step(
        ir=fixture.ir,
        admitted=out1.admitted,
        assumptions=EMPTY_ASSUMPTIONS,
        verified=out1.verified,
        budget=_BUDGET,
        worksheet_catalog=fixture.catalog,
        extractor=extractor,
        policy=policy,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert out2.status == "acquired"
    assert out2.directive.action == "ACQUIRE"
    assert out2.directive.question_id == "q1"
    assert {item.question_id: item.option for item in out2.admitted} == {"q1": "Yes"}


def test_mismatched_result_question_id_rejected_before_policy() -> None:
    fixture = compile_golden(fork_g2_graph())
    # Seed resolved base so ANALYZE issues VERIFY q1.
    from smeme.reasoning.runtime.inquire import admit_assertion

    admitted = admit_assertion(
        fixture.ir,
        (),
        question_id="q1",
        option="Yes",
        provenance_id=sentinel_provenance("p-q1"),
    )
    admitted = admit_assertion(
        fixture.ir,
        admitted,
        question_id="q2",
        option="B",
        provenance_id=sentinel_provenance("p-q2"),
    )
    directive = analyze_inquiry(
        fixture.ir,
        admitted,
        EMPTY_ASSUMPTIONS,
        frozenset(),
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert directive.action == "VERIFY"
    assert directive.question_id == "q1"

    class MismatchExtractor:
        def extract(self, task: ExtractionTask):
            return _answered("q7", "Yes")

    policy = RecordingPolicy(AlwaysRetainPolicy())
    with pytest.raises(PremiseInvariantError, match="does not match"):
        execute_directive(
            ir=fixture.ir,
            admitted=admitted,
            verified=frozenset(),
            directive=directive,
            worksheet_catalog=fixture.catalog,
            extractor=MismatchExtractor(),
            policy=policy,
            artifact_identity=SENTINEL_ARTIFACT,
            pv_version=SENTINEL_PV_VERSION,
        )
    assert policy.calls == []


def test_verify_constructs_verification_request_from_directive_key() -> None:
    fixture = compile_golden(fork_g2_graph())
    from smeme.reasoning.runtime.inquire import admit_assertion

    admitted = admit_assertion(
        fixture.ir,
        (),
        question_id="q1",
        option="Yes",
        provenance_id=sentinel_provenance("p-q1"),
    )
    admitted = admit_assertion(
        fixture.ir,
        admitted,
        question_id="q2",
        option="B",
        provenance_id=sentinel_provenance("p-q2"),
    )
    directive = analyze_inquiry(
        fixture.ir,
        admitted,
        EMPTY_ASSUMPTIONS,
        frozenset(),
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert directive.verification_key is not None
    task = build_extractor_issue(fixture.catalog, directive.question_id)  # type: ignore[arg-type]
    result = _answered(directive.question_id, "Yes", tag="p-q1-fresh")  # type: ignore[arg-type]
    policy = RecordingPolicy(AlwaysRetainPolicy())
    step_out = verify_extraction(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        directive=directive,
        task=task,
        result=result,
        policy=policy,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert step_out.status == "applied"
    assert isinstance(step_out.decision, Retain)
    assert len(policy.calls) == 1
    request, kernel_result = policy.calls[0]
    assert request.verification_key == directive.verification_key
    assert kernel_result.payload is result


def test_verify_does_not_auto_replace_on_option_disagreement() -> None:
    fixture = compile_golden(fork_g2_graph())
    from smeme.reasoning.runtime.inquire import admit_assertion

    admitted = admit_assertion(
        fixture.ir,
        (),
        question_id="q1",
        option="Yes",
        provenance_id=sentinel_provenance("p-q1"),
    )
    admitted = admit_assertion(
        fixture.ir,
        admitted,
        question_id="q2",
        option="B",
        provenance_id=sentinel_provenance("p-q2"),
    )
    # Advance to VERIFY q2 with q1 already retained.
    q1 = next(item for item in admitted if item.question_id == "q1")
    from smeme.reasoning.runtime.inquire import apply_verification_decision

    retained = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        assertion=q1,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=Retain(),
    )
    directive = analyze_inquiry(
        fixture.ir,
        retained.admitted,
        EMPTY_ASSUMPTIONS,
        retained.verified,
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert directive.action == "VERIFY"
    assert directive.question_id == "q2"
    assert directive.option == "B"

    class DisagreeExtractor:
        def extract(self, task: ExtractionTask):
            return _answered("q2", "A", tag="p-disagree")

    # AlwaysRetain ignores payload: disagreement must not become REPLACE.
    out = execute_directive(
        ir=fixture.ir,
        admitted=retained.admitted,
        verified=retained.verified,
        directive=directive,
        worksheet_catalog=fixture.catalog,
        extractor=DisagreeExtractor(),
        policy=AlwaysRetainPolicy(),
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert out.status == "verified"
    live_q2 = next(item for item in out.admitted if item.question_id == "q2")
    assert live_q2.option == "B"


def test_verify_bridge_retract_via_policy() -> None:
    fixture = compile_golden(fork_g2_graph())
    from smeme.reasoning.runtime.inquire import admit_assertion, apply_verification_decision

    admitted = admit_assertion(
        fixture.ir,
        (),
        question_id="q1",
        option="Yes",
        provenance_id=sentinel_provenance("p-q1"),
    )
    admitted = admit_assertion(
        fixture.ir,
        admitted,
        question_id="q2",
        option="B",
        provenance_id=sentinel_provenance("p-q2"),
    )
    q1 = next(item for item in admitted if item.question_id == "q1")
    retained = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        assertion=q1,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=Retain(),
    )
    directive = analyze_inquiry(
        fixture.ir,
        retained.admitted,
        EMPTY_ASSUMPTIONS,
        retained.verified,
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert directive.question_id == "q2"

    class EchoExtractor:
        def extract(self, task: ExtractionTask):
            return _answered(task.question.question_id, "B")

    out = execute_directive(
        ir=fixture.ir,
        admitted=retained.admitted,
        verified=retained.verified,
        directive=directive,
        worksheet_catalog=fixture.catalog,
        extractor=EchoExtractor(),
        policy=AlwaysRetractPolicy(),
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert {item.question_id: item.option for item in out.admitted} == {"q1": "Yes"}


def test_admit_extraction_rejects_option_not_in_task() -> None:
    fixture = compile_golden(fork_g2_graph())
    task = build_extractor_issue(fixture.catalog, "q1")
    with pytest.raises(PremiseInvariantError, match="not among"):
        admit_extraction(
            fixture.ir,
            (),
            task=task,
            result=AnsweredExtraction(
                question_id="q1",
                selected_option="Maybe",
                provenance_id=CanonicalProvenanceId("p"),
            ),
        )


def test_stop_execute_is_identity() -> None:
    fixture = compile_golden(fork_g2_graph())

    class Boom:
        def extract(self, task: ExtractionTask):
            raise AssertionError("extractor must not run on STOP")

    directive = InquiryDirective(action="STOP", stop_reason="operational_unknown")
    out = execute_directive(
        ir=fixture.ir,
        admitted=(),
        verified=frozenset(),
        directive=directive,
        worksheet_catalog=fixture.catalog,
        extractor=Boom(),
        policy=AlwaysRetainPolicy(),
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert out.status == "stop"
    assert out.task is None
    assert out.result is None


def test_verify_insufficient_via_policy() -> None:
    fixture = compile_golden(fork_g2_graph())
    from smeme.reasoning.runtime.inquire import admit_assertion

    admitted = admit_assertion(
        fixture.ir,
        (),
        question_id="q1",
        option="Yes",
        provenance_id=sentinel_provenance("p-q1"),
    )
    admitted = admit_assertion(
        fixture.ir,
        admitted,
        question_id="q2",
        option="B",
        provenance_id=sentinel_provenance("p-q2"),
    )
    directive = analyze_inquiry(
        fixture.ir,
        admitted,
        EMPTY_ASSUMPTIONS,
        frozenset(),
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )

    class AbstainExtractor:
        def extract(self, task: ExtractionTask):
            return AbstainedExtraction(question_id=task.question.question_id)

    out = execute_directive(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        directive=directive,
        worksheet_catalog=fixture.catalog,
        extractor=AbstainExtractor(),
        policy=AlwaysInsufficientPolicy(),
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert out.status == "verified"
    assert out.admitted == admitted
    assert out.verified == frozenset()


def test_verify_replace_via_policy() -> None:
    fixture = compile_golden(fork_g2_graph())
    from smeme.reasoning.runtime.inquire import admit_assertion, apply_verification_decision

    admitted = admit_assertion(
        fixture.ir,
        (),
        question_id="q1",
        option="Yes",
        provenance_id=sentinel_provenance("p-q1"),
    )
    admitted = admit_assertion(
        fixture.ir,
        admitted,
        question_id="q2",
        option="B",
        provenance_id=sentinel_provenance("p-q2"),
    )
    q1 = next(item for item in admitted if item.question_id == "q1")
    retained = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        assertion=q1,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=Retain(),
    )
    directive = analyze_inquiry(
        fixture.ir,
        retained.admitted,
        EMPTY_ASSUMPTIONS,
        retained.verified,
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    new_p = sentinel_provenance("p-q2-replaced")

    class Echo:
        def extract(self, task: ExtractionTask):
            return _answered(task.question.question_id, "A")

    out = execute_directive(
        ir=fixture.ir,
        admitted=retained.admitted,
        verified=retained.verified,
        directive=directive,
        worksheet_catalog=fixture.catalog,
        extractor=Echo(),
        policy=ReplaceWith(option="A", provenance_id=new_p),
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    live_q2 = next(item for item in out.admitted if item.question_id == "q2")
    assert live_q2.option == "A"
    assert live_q2.provenance_id == new_p
