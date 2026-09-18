"""Focused tests for the standalone LangGraph Inquire example."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

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


def test_prompt_supports_admit_edit_and_reject() -> None:
    proposal = {"raw": "Yes", "value": "Yes", "options": ["Yes", "No"]}

    answers = iter(["a", "source-1"])
    assert example.prompt_admission(proposal, lambda _: next(answers)) == {
        "admit": True,
        "value": "Yes",
        "provenance_id": "source-1",
    }
    answers = iter(["e", "2", "source-2"])
    assert example.prompt_admission(proposal, lambda _: next(answers)) == {
        "admit": True,
        "value": "No",
        "provenance_id": "source-2",
    }
    assert example.prompt_admission(proposal, lambda _: "r") == {"admit": False}


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

    paused_again = await app.ainvoke(Command(resume={"admit": False}), config)
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
