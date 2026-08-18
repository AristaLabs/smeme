"""Phase 4 blind verification policy tests. Policy-oriented; no LLM."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from smeme.reasoning.orchestration.inquire.types import (
    AbstainedExtraction,
    AnsweredExtraction,
)
from smeme.reasoning.orchestration.inquire.verification import (
    DEFAULT_PV_VERSION,
    DEFAULT_VERIFICATION_POLICY,
    DefaultVerificationPolicy,
    EvaluationId,
    PresentationVariant,
    VerificationObservation,
    build_option_order_schedule,
    render_blind_task,
    run_verification,
    schedule_size,
)
from smeme.reasoning.runtime.assumptions import EMPTY_ASSUMPTIONS
from smeme.reasoning.runtime.consistency_gate import PremiseInvariantError
from smeme.reasoning.runtime.inquire import (
    admit_assertion,
    analyze_inquiry,
    apply_verification_decision,
)
from smeme.reasoning.runtime.inquire.policy import VerificationRequest
from smeme.reasoning.runtime.inquire.transition import Insufficient, Retain
from smeme.reasoning.runtime.inquire.types import (
    ExtractionTask,
    InquiryBudget,
    WorksheetItem,
)
from tests.unit.reasoning.runtime.inquire_fixtures import (
    SENTINEL_ARTIFACT,
    compile_golden,
    fork_g2_graph,
    sentinel_provenance,
)

_BUDGET = InquiryBudget()
_PV = DEFAULT_PV_VERSION


def _answered(qid: str, option: str, *, tag: str | None = None) -> AnsweredExtraction:
    return AnsweredExtraction(
        question_id=qid,
        selected_option=option,
        provenance_id=sentinel_provenance(tag or f"p-{qid}"),
    )


@dataclass
class ScriptedExtractor:
    scripts: dict[str, list[AnsweredExtraction | AbstainedExtraction]]
    seen: list[ExtractionTask] = field(default_factory=list)

    def extract(self, task: ExtractionTask) -> AnsweredExtraction | AbstainedExtraction:
        self.seen.append(task)
        queue = self.scripts.get(task.question.question_id)
        if not queue:
            msg = f"no script for {task.question.question_id!r}"
            raise AssertionError(msg)
        return queue.pop(0)


def _resolved_base(fixture):
    return admit_assertion(
        fixture.ir,
        admit_assertion(
            fixture.ir,
            (),
            question_id="q1",
            option="Yes",
            provenance_id=sentinel_provenance("p-q1"),
        ),
        question_id="q2",
        option="B",
        provenance_id=sentinel_provenance("p-q2"),
    )


def test_schedule_size_adaptive() -> None:
    assert schedule_size(("Only",)) == 1
    assert schedule_size(("Yes", "No")) == 2
    assert schedule_size(("A", "B", "C")) == 3
    assert schedule_size(("A", "B", "C", "D")) == 3


def test_schedule_deterministic_ids_and_identity_first() -> None:
    options = ("A", "B", "C")
    schedule = build_option_order_schedule(options)
    assert len(schedule) == 3
    assert [req.evaluation_id for req in schedule] == [
        EvaluationId("eval-0"),
        EvaluationId("eval-1"),
        EvaluationId("eval-2"),
    ]
    assert schedule[0].presentation.option_order == ("A", "B", "C")
    assert schedule[0].evaluator_slot == "ISOLATED"
    assert schedule[1].presentation.option_order != schedule[0].presentation.option_order


def test_binary_schedule_has_two_trials() -> None:
    schedule = build_option_order_schedule(("Yes", "No"))
    assert len(schedule) == 2
    assert schedule[0].presentation.option_order == ("Yes", "No")
    assert schedule[1].presentation.option_order == ("No", "Yes")


def test_one_option_schedule_size_one() -> None:
    schedule = build_option_order_schedule(("Only",))
    assert len(schedule) == 1
    assert schedule[0].evaluation_id == EvaluationId("eval-0")


def test_render_permutes_options_keeps_stem() -> None:
    fixture = compile_golden(fork_g2_graph())
    presentation = PresentationVariant(option_order=("B", "A"))
    task = render_blind_task(fixture.catalog, "q2", presentation)
    assert task.question.stem == fixture.catalog["q2"].stem
    assert task.question.options == ("B", "A")
    blob = str(task)
    assert "VERIFY" not in blob
    assert "verification_key" not in blob


def test_retain_when_all_binary_trials_reproduce_live() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _resolved_base(fixture)
    directive = analyze_inquiry(
        fixture.ir,
        admitted,
        EMPTY_ASSUMPTIONS,
        frozenset(),
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=_PV,
    )
    assert directive.action == "VERIFY"
    assert directive.question_id == "q1"
    extractor = ScriptedExtractor(
        scripts={
            "q1": [
                _answered("q1", "Yes", tag="p-v0"),
                _answered("q1", "Yes", tag="p-v1"),
            ],
        }
    )
    battery = run_verification(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        directive=directive,
        worksheet_catalog=fixture.catalog,
        extractor=extractor,
        artifact_identity=SENTINEL_ARTIFACT,
    )
    assert isinstance(battery.step.decision, Retain)
    assert battery.step.status == "applied"
    assert any(key.question_id == "q1" for key in battery.step.verified)
    assert len(extractor.seen) == 2
    assert extractor.seen[0].question.options == ("Yes", "No")
    assert extractor.seen[1].question.options == ("No", "Yes")


def test_insufficient_on_disagreement() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _resolved_base(fixture)
    directive = analyze_inquiry(
        fixture.ir,
        admitted,
        EMPTY_ASSUMPTIONS,
        frozenset(),
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=_PV,
    )
    extractor = ScriptedExtractor(
        scripts={
            "q1": [
                _answered("q1", "Yes", tag="p-v0"),
                _answered("q1", "No", tag="p-v1"),
            ],
        }
    )
    battery = run_verification(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        directive=directive,
        worksheet_catalog=fixture.catalog,
        extractor=extractor,
        artifact_identity=SENTINEL_ARTIFACT,
    )
    assert isinstance(battery.step.decision, Insufficient)
    assert battery.step.verified == frozenset()


def test_insufficient_on_abstention() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _resolved_base(fixture)
    directive = analyze_inquiry(
        fixture.ir,
        admitted,
        EMPTY_ASSUMPTIONS,
        frozenset(),
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=_PV,
    )
    extractor = ScriptedExtractor(
        scripts={
            "q1": [
                _answered("q1", "Yes", tag="p-v0"),
                AbstainedExtraction(question_id="q1"),
            ],
        }
    )
    battery = run_verification(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        directive=directive,
        worksheet_catalog=fixture.catalog,
        extractor=extractor,
        artifact_identity=SENTINEL_ARTIFACT,
    )
    assert isinstance(battery.step.decision, Insufficient)


def test_insufficient_when_all_agree_on_alternative() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _resolved_base(fixture)
    directive = analyze_inquiry(
        fixture.ir,
        admitted,
        EMPTY_ASSUMPTIONS,
        frozenset(),
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=_PV,
    )
    extractor = ScriptedExtractor(
        scripts={
            "q1": [
                _answered("q1", "No", tag="p-alt0"),
                _answered("q1", "No", tag="p-alt1"),
            ],
        }
    )
    battery = run_verification(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        directive=directive,
        worksheet_catalog=fixture.catalog,
        extractor=extractor,
        artifact_identity=SENTINEL_ARTIFACT,
    )
    assert isinstance(battery.step.decision, Insufficient)
    live = next(item for item in battery.step.admitted if item.question_id == "q1")
    assert live.option == "Yes"


def test_observe_rejects_unscheduled_duplicate_mismatch_and_noncanonical() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _resolved_base(fixture)
    directive = analyze_inquiry(
        fixture.ir,
        admitted,
        EMPTY_ASSUMPTIONS,
        frozenset(),
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=_PV,
    )
    key = directive.verification_key
    assert key is not None
    policy = DefaultVerificationPolicy()
    state = policy.initial_state(
        VerificationRequest(verification_key=key),
        canonical_options=("Yes", "No"),
    )
    req0 = state.schedule[0]

    with pytest.raises(PremiseInvariantError, match="unscheduled"):
        policy.observe(
            state,
            VerificationObservation(
                evaluation_id=EvaluationId("eval-99"),
                question_id=key.question_id,
                selected_option="Yes",
                provenance_id=sentinel_provenance("p"),
                presentation=req0.presentation,
            ),
        )

    observed = policy.observe(
        state,
        VerificationObservation(
            evaluation_id=req0.evaluation_id,
            question_id=key.question_id,
            selected_option="Yes",
            provenance_id=sentinel_provenance("p"),
            presentation=req0.presentation,
        ),
    )
    with pytest.raises(PremiseInvariantError, match="duplicate"):
        policy.observe(
            observed,
            VerificationObservation(
                evaluation_id=req0.evaluation_id,
                question_id=key.question_id,
                selected_option="Yes",
                provenance_id=sentinel_provenance("p2"),
                presentation=req0.presentation,
            ),
        )

    with pytest.raises(PremiseInvariantError, match="presentation mismatch"):
        policy.observe(
            state,
            VerificationObservation(
                evaluation_id=req0.evaluation_id,
                question_id=key.question_id,
                selected_option="Yes",
                provenance_id=sentinel_provenance("p"),
                presentation=PresentationVariant(option_order=("No", "Yes")),
            ),
        )

    with pytest.raises(PremiseInvariantError, match="does not match"):
        policy.observe(
            state,
            VerificationObservation(
                evaluation_id=req0.evaluation_id,
                question_id="q2",
                selected_option="Yes",
                provenance_id=sentinel_provenance("p"),
                presentation=req0.presentation,
            ),
        )

    with pytest.raises(PremiseInvariantError, match="not in"):
        policy.observe(
            state,
            VerificationObservation(
                evaluation_id=req0.evaluation_id,
                question_id=key.question_id,
                selected_option="Maybe",
                provenance_id=sentinel_provenance("p"),
                presentation=req0.presentation,
            ),
        )


def test_protocol_error_is_not_insufficient() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _resolved_base(fixture)
    directive = analyze_inquiry(
        fixture.ir,
        admitted,
        EMPTY_ASSUMPTIONS,
        frozenset(),
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=_PV,
    )

    class BadIdExtractor:
        def extract(self, task: ExtractionTask):
            return _answered("q7", "Yes")

    with pytest.raises(PremiseInvariantError, match="does not match"):
        run_verification(
            ir=fixture.ir,
            admitted=admitted,
            verified=frozenset(),
            directive=directive,
            worksheet_catalog=fixture.catalog,
            extractor=BadIdExtractor(),
            artifact_identity=SENTINEL_ARTIFACT,
        )


def test_pv_version_mismatch_fail_closed() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _resolved_base(fixture)
    directive = analyze_inquiry(
        fixture.ir,
        admitted,
        EMPTY_ASSUMPTIONS,
        frozenset(),
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version="other-pv",
    )

    class Echo:
        def extract(self, task: ExtractionTask):
            return _answered(task.question.question_id, "Yes")

    with pytest.raises(PremiseInvariantError, match="pv_version"):
        run_verification(
            ir=fixture.ir,
            admitted=admitted,
            verified=frozenset(),
            directive=directive,
            worksheet_catalog=fixture.catalog,
            extractor=Echo(),
            artifact_identity=SENTINEL_ARTIFACT,
            verification_policy=DEFAULT_VERIFICATION_POLICY,
        )


def test_one_option_retain_records_schedule_len_one() -> None:
    """Honest N_q=1: reproduce live → Retain; len(schedule)==1."""
    catalog = {"q1": WorksheetItem(stem="Only choice?", options=("Only",))}
    # Use policy state directly — no IR needed for schedule honesty.
    from smeme.reasoning.runtime.inquire.types import VerificationKey

    key = VerificationKey(
        artifact_identity=SENTINEL_ARTIFACT,
        question_id="q1",
        option="Only",
        provenance_identity="p-only",
        pv_version=_PV,
    )
    policy = DefaultVerificationPolicy()
    state = policy.initial_state(
        VerificationRequest(verification_key=key),
        canonical_options=catalog["q1"].options,
    )
    assert len(state.schedule) == 1
    req = policy.next_evaluation(state)
    assert req is not None
    state = policy.observe(
        state,
        VerificationObservation(
            evaluation_id=req.evaluation_id,
            question_id="q1",
            selected_option="Only",
            provenance_id=sentinel_provenance("p-only-v"),
            presentation=req.presentation,
        ),
    )
    assert isinstance(policy.decision(state), Retain)


def test_changing_pv_version_invalidates_prior_retain() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _resolved_base(fixture)
    q1 = next(item for item in admitted if item.question_id == "q1")
    retained = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        assertion=q1,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=_PV,
        decision=Retain(),
    )
    # ANALYZE with a different pv_version must not treat prior keys as verified.
    other_pv = "pv-other-algorithm"
    directive = analyze_inquiry(
        fixture.ir,
        retained.admitted,
        EMPTY_ASSUMPTIONS,
        retained.verified,
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=other_pv,
    )
    assert directive.action == "VERIFY"
    assert directive.question_id == "q1"


def test_blindness_across_verify_renditions() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _resolved_base(fixture)
    directive = analyze_inquiry(
        fixture.ir,
        admitted,
        EMPTY_ASSUMPTIONS,
        frozenset(),
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=_PV,
    )
    extractor = ScriptedExtractor(
        scripts={
            "q1": [
                _answered("q1", "Yes", tag="p0"),
                _answered("q1", "Yes", tag="p1"),
            ],
        }
    )
    run_verification(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        directive=directive,
        worksheet_catalog=fixture.catalog,
        extractor=extractor,
        artifact_identity=SENTINEL_ARTIFACT,
    )
    for task in extractor.seen:
        blob = str(task)
        for forbidden in ("VERIFY", "ACQUIRE", "verification_key", "S_R", "conclusion"):
            assert forbidden not in blob
        assert not hasattr(task, "action")
