"""Focused tests for the standalone LangGraph Inquire example."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from zipfile import ZipFile

import pytest
from langgraph.types import Command


def _load_example() -> ModuleType:
    examples = Path(__file__).resolve().parents[2] / "examples"
    sys.path.insert(0, str(examples))
    path = examples / "smeme_langgraph_withholding.py"
    spec = importlib.util.spec_from_file_location("smeme_langgraph_example_for_tests", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


example = _load_example()


def _public_case_zip(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "smeme-acme-dataset-distributed.zip"
    manifest = {
        "sample_key": example.ACME_SAMPLE_KEY,
        "cases": [
            {
                "case_id": "matter-123",
                "sources": [
                    {
                        "source_id": "ACME-123-REG-001",
                        "title": "Business register extract",
                        "relative_locator": "distributed/matter-123/register.json",
                    }
                ],
            }
        ],
    }
    with ZipFile(path, "w") as zf:
        zf.writestr("dataset_manifest.json", json.dumps(manifest))
        zf.writestr(
            "distributed/matter-123/register.json",
            '{"jurisdiction":"Fictionland","entity_type":"corporation"}',
        )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


class FakeTool:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, object]] = []

    async def ainvoke(self, arguments: dict[str, object]) -> SimpleNamespace:
        self.calls.append(arguments)
        value = self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]
        return SimpleNamespace(
            artifact={"structured_content": value, "isError": False},
            status="success",
        )


def _tools() -> dict[str, FakeTool]:
    required = [
        "smeme_reasoning_list",
        "smeme_reasoning_evaluate",
        "smeme_reasoning_evaluate_continue",
    ]
    return {
        "smeme_reasoning_capabilities": FakeTool([{"reasoning": {"tools": required}}]),
        "smeme_reasoning_list": FakeTool(
            [{"decision_trees": [{"id": "tree-1", "title": "Chosen"}]}]
        ),
        "smeme_reasoning_evaluate": FakeTool(
            [
                {
                    "harness_next": "continue_evaluate",
                    "inquiry_session_id": "session-1",
                    "task": {
                        "question_id": "q1",
                        "stem": "Question?",
                        "options": ["Yes", "No"],
                    },
                }
            ]
        ),
        "smeme_reasoning_evaluate_continue": FakeTool(
            [{"report": {"result_kind": "concluded", "headline": "Done"}}]
        ),
    }


def test_missing_tool_fails_before_graph_construction() -> None:
    tools = _tools()
    del tools["smeme_reasoning_evaluate_continue"]

    with pytest.raises(example.IntegrationError, match="missing required tools"):
        example.build_graph(tools)


@pytest.mark.asyncio
async def test_explicit_tree_id_is_mandatory_and_listed() -> None:
    tools = _tools()
    bootstrap, *_ = example.make_nodes(tools)

    with pytest.raises(example.IntegrationError, match="decision_tree_id is required"):
        await bootstrap({"matter_context": "matter"})
    with pytest.raises(example.IntegrationError, match="not present"):
        await bootstrap({"matter_context": "matter", "decision_tree_id": "other"})
    assert tools["smeme_reasoning_evaluate"].calls == []


@pytest.mark.asyncio
async def test_semantic_error_with_protocol_success_is_actionable() -> None:
    message = SimpleNamespace(
        artifact={
            "isError": False,
            "structured_content": {
                "result": (
                    '{"error":{"code":"target_not_reachable_under_locks",'
                    '"message":"Target blocked.","locked_question_ids":["q9"]}}'
                )
            },
        },
        status="success",
    )

    with pytest.raises(
        example.IntegrationError,
        match="semantic error target_not_reachable_under_locks",
    ):
        example._require_payload(message, "smeme_reasoning_how_to_reach")


@pytest.mark.asyncio
async def test_model_factory_is_lazy_and_injectable() -> None:
    created = 0

    class Model:
        async def ainvoke(self, prompt: str) -> SimpleNamespace:
            assert "Options: ['Yes', 'No']" in prompt
            return SimpleNamespace(content="Yes")

    def factory() -> Model:
        nonlocal created
        created += 1
        return Model()

    provider = example.make_openai_proposal_provider(factory)
    assert created == 0
    state = {
        "matter_context": "matter",
        "open_task": {
            "question_id": "q1",
            "stem": "Question?",
            "options": ["Yes", "No"],
        },
    }

    assert (await provider(state))["value"] == "Yes"
    assert (await provider(state))["value"] == "Yes"
    assert created == 1


def test_public_case_bundle_loads_verified_sources_without_extracting(tmp_path: Path) -> None:
    path, digest = _public_case_zip(tmp_path)

    bundle = example.load_public_case_bundle(path, "matter-123", expected_sha256=digest)

    assert bundle.sha256 == digest
    assert bundle.sources[0].source_id == "ACME-123-REG-001"
    assert bundle.sources[0].title == "Business register extract"
    assert '"entity_type":"corporation"' in bundle.matter_context()


def test_public_case_bundle_rejects_unsafe_member(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.zip"
    with ZipFile(path, "w") as zf:
        zf.writestr("../escape.txt", "no")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(example.IntegrationError, match="unsafe path"):
        example.load_public_case_bundle(path, "matter-123", expected_sha256=digest)


@pytest.mark.asyncio
async def test_model_proposal_is_grounded_in_public_case_source() -> None:
    created = 0

    class Model:
        async def ainvoke(self, prompt: str) -> SimpleNamespace:
            assert "SOURCE ACME-123-REG-001" in prompt
            assert '"Yes"' in prompt
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "option": "Yes",
                        "source_id": "ACME-123-REG-001",
                        "excerpt": '"entity_type":"corporation"',
                    }
                )
            )

    def factory() -> Model:
        nonlocal created
        created += 1
        return Model()

    provider = example.make_openai_proposal_provider(factory)
    state = {
        "matter_context": (
            "SOURCE ACME-123-REG-001\n"
            'Content:\n{"jurisdiction":"Fictionland","entity_type":"corporation"}'
        ),
        "source_catalog": {
            "ACME-123-REG-001": {
                "title": "Business register extract",
                "relative_locator": "distributed/matter-123/register.json",
                "content": '{"jurisdiction":"Fictionland","entity_type":"corporation"}',
            }
        },
        "open_task": {
            "question_id": "q1",
            "stem": "Is the payee a corporation?",
            "options": ["Yes", "No"],
        },
    }

    proposal = await provider(state)

    assert proposal["value"] == "Yes"
    assert proposal["source_id"] == "ACME-123-REG-001"
    assert proposal["excerpt_verified"] is True
    assert proposal["excerpt_validation"] == "exact"
    assert created == 1


@pytest.mark.asyncio
async def test_model_proposal_retries_once_after_nonverbatim_excerpt() -> None:
    responses = iter(
        [
            {
                "option": "Yes",
                "source_id": "source-1",
                "excerpt": "a paraphrase",
            },
            {
                "option": "Yes",
                "source_id": "source-1",
                "excerpt": "exact source text",
            },
        ]
    )
    prompts: list[str] = []

    class Model:
        async def ainvoke(self, prompt: str) -> SimpleNamespace:
            prompts.append(prompt)
            return SimpleNamespace(content=json.dumps(next(responses)))

    provider = example.make_openai_proposal_provider(lambda: Model())
    proposal = await provider(
        {
            "matter_context": "SOURCE source-1\nContent:\nexact source text",
            "source_catalog": {
                "source-1": {
                    "title": "Source",
                    "relative_locator": "source.txt",
                    "content": "exact source text",
                }
            },
            "open_task": {
                "question_id": "q1",
                "stem": "Question?",
                "options": ["Yes", "No"],
            },
        }
    )

    assert len(prompts) == 2
    assert "excerpt_not_found_in_source" in prompts[1]
    assert proposal["value"] == "Yes"
    assert proposal["excerpt"] == "exact source text"
    assert proposal["excerpt_verified"] is True
    assert proposal["excerpt_validation"] == "exact"


def test_model_proposal_accepts_only_deterministic_whitespace_normalization() -> None:
    task = {"question_id": "q1", "options": ["Yes", "No"]}
    catalog = {
        "source-1": {
            "title": "Wrapped email",
            "relative_locator": "message.eml",
            "content": "first line\ncontinues here",
        }
    }

    proposal = example._validated_source_proposal(
        '{"option":"Yes","source_id":"source-1","excerpt":"first line continues here"}',
        task,
        catalog,
    )

    assert proposal["value"] == "Yes"
    assert proposal["excerpt_verified"] is True
    assert proposal["excerpt_validation"] == "normalized_whitespace"


def test_model_proposal_rejects_excerpt_not_found_in_source() -> None:
    task = {"question_id": "q1", "options": ["Yes", "No"]}
    catalog = {
        "source-1": {
            "title": "Source",
            "relative_locator": "source.txt",
            "content": "The source says something else.",
        }
    }

    proposal = example._validated_source_proposal(
        '{"option":"Yes","source_id":"source-1","excerpt":"invented"}',
        task,
        catalog,
    )

    assert proposal["value"] is None
    assert proposal["candidate_value"] == "Yes"
    assert proposal["source_id"] == "source-1"
    assert proposal["excerpt"] == "invented"
    assert proposal["excerpt_verified"] is False
    assert proposal["proposal_error"] == "excerpt_not_found_in_source"


def test_prompt_shows_stem_and_supports_admit_edit_and_reject(
    capsys: pytest.CaptureFixture[str],
) -> None:
    proposal = {
        "stem": "Is the payee foreign?",
        "raw": "Yes",
        "value": "Yes",
        "options": ["Yes", "No"],
    }

    answers = iter(["a", "source-1"])
    assert example.prompt_admission(proposal, lambda _: next(answers)) == {
        "admit": True,
        "value": "Yes",
        "provenance_id": "source-1",
    }
    assert "Question: Is the payee foreign?" in capsys.readouterr().out
    answers = iter(["e", "2", "source-2"])
    assert example.prompt_admission(proposal, lambda _: next(answers)) == {
        "admit": True,
        "value": "No",
        "provenance_id": "source-2",
    }
    assert example.prompt_admission(proposal, lambda _: "r") == {
        "admit": False,
        "rejected": True,
    }


def test_prompt_can_confirm_dataset_option_and_source_together(
    capsys: pytest.CaptureFixture[str],
) -> None:
    proposal = {
        "stem": "Is the payee a corporation?",
        "raw": "{}",
        "value": "Yes",
        "options": ["Yes", "No"],
        "source_id": "ACME-123-REG-001",
        "source_title": "Business register extract",
        "excerpt": '"entity_type":"corporation"',
    }

    assert example.prompt_admission(proposal, lambda _: "a") == {
        "admit": True,
        "value": "Yes",
        "provenance_id": "ACME-123-REG-001",
    }
    output = capsys.readouterr().out
    assert "Business register extract" in output
    assert '"entity_type":"corporation"' in output


def test_reviewed_admission_requires_exact_validated_option_and_source() -> None:
    proposal = {
        "value": "Foreign person",
        "source_id": "ACME-123-EML-001",
        "excerpt_verified": True,
    }

    assert example.reviewed_admission_decision(
        proposal,
        "Foreign person",
        "ACME-123-EML-001",
    ) == {
        "admit": True,
        "value": "Foreign person",
        "provenance_id": "ACME-123-EML-001",
    }
    with pytest.raises(example.IntegrationError, match="option differs"):
        example.reviewed_admission_decision(
            proposal,
            "U.S. person (valid Form W-9 on file)",
            "ACME-123-EML-001",
        )
    with pytest.raises(example.IntegrationError, match="source differs"):
        example.reviewed_admission_decision(
            proposal,
            "Foreign person",
            "ACME-123-TAX-001",
        )


def test_manual_prompt_accepts_option_number_directly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    proposal = {
        "stem": "Is the payee foreign?",
        "raw": "No model proposal; operator selection required.",
        "value": None,
        "options": ["Yes", "No"],
    }
    answers = iter(["1", "source-1"])

    assert example.prompt_admission(proposal, lambda _: next(answers)) == {
        "admit": True,
        "value": "Yes",
        "provenance_id": "source-1",
    }
    assert "Selection mode: manual operator selection" in capsys.readouterr().out
    invalid_then_reject = iter(["", "not-a-number", "0", "r"])
    assert example.prompt_admission(proposal, lambda _: next(invalid_then_reject)) == {
        "admit": False,
        "rejected": True,
    }
    output = capsys.readouterr().out
    assert output.count("Enter an option number from 1 to 2, or r.") == 3


def test_prompt_reprompts_invalid_actions_and_blank_provenance(
    capsys: pytest.CaptureFixture[str],
) -> None:
    proposal = {
        "stem": "Is the payee foreign?",
        "raw": "Yes",
        "value": "Yes",
        "options": ["Yes", "No"],
    }
    answers = iter(["reject", "", "a", "", " ", "source-1"])

    assert example.prompt_admission(proposal, lambda _: next(answers)) == {
        "admit": True,
        "value": "Yes",
        "provenance_id": "source-1",
    }
    output = capsys.readouterr().out
    assert output.count("Enter a, e, or r.") == 2
    assert output.count("Provenance id cannot be blank") == 2


def test_empty_provenance_can_explicitly_cancel_without_rejection() -> None:
    proposal = {
        "stem": "Is the payee foreign?",
        "raw": "No model proposal; operator selection required.",
        "value": None,
        "options": ["Yes", "No"],
    }
    answers = iter(["1", "", "c"])

    assert example.prompt_admission(proposal, lambda _: next(answers)) == {
        "admit": False,
        "cancelled": True,
    }


def test_terminal_summary_keeps_report_qualifications_and_verification_status() -> None:
    report = {"result_kind": "concluded", "headline": "Done"}
    summary = example._terminal_summary(
        {
            "report": report,
            "terminal_payload": {
                "status": "STOPPED",
                "harness_next": "user_input_needed",
                "stop_reason": "resolving_support_incomplete",
                "inquire_stop_reason": "resolving_support_incomplete",
                "inquire_operational_status": "budget",
                "inquire_diagnostics": {
                    "phase": "resolving_support",
                    "sat_calls": 2015,
                },
                "warnings": [{"code": "missing_evidence_ref", "message": "Missing evidence"}],
                "report": report,
            },
        }
    )
    assert summary["report"] == report
    assert summary["status"] == "STOPPED"
    assert summary["harness_next"] == "user_input_needed"
    assert summary["stop_reason"] == "resolving_support_incomplete"
    assert summary["inquire_stop_reason"] == "resolving_support_incomplete"
    assert summary["inquire_operational_status"] == "budget"
    assert summary["inquire_diagnostics"]["phase"] == "resolving_support"
    assert summary["warnings"] == [{"code": "missing_evidence_ref", "message": "Missing evidence"}]

    verification = example._terminal_summary(
        {
            "report": {
                "error": {
                    "code": "isolated_evaluations_required",
                    "message": "Run isolated verification.",
                    "status": "verification_required",
                }
            },
            "terminal_payload": {
                "error": {
                    "code": "isolated_evaluations_required",
                    "message": "Run isolated verification.",
                    "status": "verification_required",
                }
            },
        }
    )
    assert verification["verification_required"]["code"] == "isolated_evaluations_required"
    assert "report" not in verification
    assert "terminal_error" not in verification


@pytest.mark.asyncio
async def test_rejection_loops_without_continuation_then_admission_calls_once() -> None:
    tools = _tools()
    app = example.build_graph(tools)
    config = {"configurable": {"thread_id": "rejection-test"}}

    paused = await app.ainvoke(
        {"matter_context": "matter", "decision_tree_id": "tree-1"},
        config,
    )
    assert paused["__interrupt__"]
    assert paused["__interrupt__"][0].value["proposal"]["stem"] == "Question?"

    paused_again = await app.ainvoke(
        Command(resume={"admit": False, "rejected": True}),
        config,
    )
    assert paused_again["__interrupt__"]
    assert tools["smeme_reasoning_evaluate_continue"].calls == []

    result = await app.ainvoke(
        Command(
            resume={
                "admit": True,
                "value": "Yes",
                "provenance_id": "source-1",
            }
        ),
        config,
    )
    assert result["report"]["result_kind"] == "concluded"
    assert tools["smeme_reasoning_evaluate_continue"].calls == [
        {
            "inquiry_session_id": "session-1",
            "question_id": "q1",
            "selected_option": "Yes",
            "provenance_id": "source-1",
        }
    ]


@pytest.mark.asyncio
async def test_grounded_proposal_human_admission_advances_to_solver_task() -> None:
    tools = _tools()
    tools["smeme_reasoning_evaluate_continue"] = FakeTool(
        [
            {
                "harness_next": "continue_evaluate",
                "inquiry_session_id": "session-1",
                "task": {
                    "question_id": "q2",
                    "stem": "Next solver question?",
                    "options": ["Present", "Absent"],
                },
            }
        ]
    )

    async def grounded_provider(state: dict[str, object]) -> dict[str, object]:
        task = state["open_task"]
        assert isinstance(task, dict)
        return {
            "question_id": task["question_id"],
            "raw": "{}",
            "value": task["options"][0],
            "source_id": "ACME-123-REG-001",
            "source_title": "Business register extract",
            "source_locator": "distributed/matter-123/register.json",
            "excerpt": '"entity_type":"corporation"',
            "excerpt_verified": True,
        }

    app = example.build_graph(tools, proposal_provider=grounded_provider)
    config = {"configurable": {"thread_id": "grounded-advance-test"}}
    paused = await app.ainvoke(
        {
            "matter_context": "SOURCE ACME-123-REG-001",
            "source_catalog": {
                "ACME-123-REG-001": {
                    "title": "Business register extract",
                    "relative_locator": "distributed/matter-123/register.json",
                    "content": '{"entity_type":"corporation"}',
                }
            },
            "decision_tree_id": "tree-1",
        },
        config,
    )
    proposal = paused["__interrupt__"][0].value["proposal"]
    assert proposal["question_id"] == "q1"
    assert proposal["source_id"] == "ACME-123-REG-001"
    assert proposal["excerpt_verified"] is True

    advanced = await app.ainvoke(
        Command(
            resume={
                "admit": True,
                "value": proposal["value"],
                "provenance_id": proposal["source_id"],
            }
        ),
        config,
    )

    assert advanced["__interrupt__"][0].value["proposal"]["question_id"] == "q2"
    assert tools["smeme_reasoning_evaluate_continue"].calls == [
        {
            "inquiry_session_id": "session-1",
            "question_id": "q1",
            "selected_option": "Yes",
            "provenance_id": "ACME-123-REG-001",
        }
    ]
