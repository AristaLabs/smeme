"""Regression tests for the standalone FastMCP Apply example."""

from __future__ import annotations

import runpy
from dataclasses import make_dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import create_model


@pytest.fixture(scope="module")
def payload():
    script = Path(__file__).resolve().parents[2] / "examples" / "smeme_apply_sample.py"
    return runpy.run_path(str(script))["_payload"]


def test_payload_decodes_fastmcp_4_typed_output(payload) -> None:
    output_type = create_model(
        "smeme_reasoning_capabilitiesOutput",
        reasoning=(dict[str, object], ...),
    )
    result = SimpleNamespace(
        data=output_type(reasoning={"tools": ["smeme_reasoning_list"]}),
        structured_content={"reasoning": {"tools": ["smeme_reasoning_list"]}},
    )

    assert payload(result) == {"reasoning": {"tools": ["smeme_reasoning_list"]}}


def test_payload_decodes_fastmcp_top_level_generated_wrapper(payload) -> None:
    capabilities_json = '{"reasoning":{"tools":["smeme_reasoning_list"]}}'
    output_type = create_model(
        "smeme_reasoning_capabilitiesOutput",
        result=(str, ...),
    )
    result = output_type(result=capabilities_json)

    assert payload(result) == {"reasoning": {"tools": ["smeme_reasoning_list"]}}


PlainCapabilitiesOutput = make_dataclass(
    "smeme_reasoning_capabilitiesOutput",
    [("result", object)],
)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            '{"reasoning":{"capabilities":{"tools":["smeme_reasoning_list"]}}}',
            {"reasoning": {"capabilities": {"tools": ["smeme_reasoning_list"]}}},
        ),
        (
            '[{"decision_trees":[{"id":"sample"}]}]',
            [{"decision_trees": [{"id": "sample"}]}],
        ),
    ],
)
def test_payload_decodes_fastmcp_plain_result_dataclass(payload, result, expected) -> None:
    wrapper = PlainCapabilitiesOutput(result=result)

    assert repr(wrapper).startswith("smeme_reasoning_capabilitiesOutput(result=")
    assert not callable(getattr(wrapper, "model_dump", None))
    assert payload(wrapper) == expected


def test_payload_plain_result_unwrap_is_safe(payload) -> None:
    mapping = {"result": '{"report":{"ok":true}}'}
    method_wrapper = SimpleNamespace(
        result=lambda: '{"report":{"ok":true}}',
        data={"report": {"ok": True}},
    )
    cycle = SimpleNamespace()
    cycle.result = cycle

    assert payload(mapping) is mapping
    assert payload(method_wrapper) == {"report": {"ok": True}}
    assert payload(cycle)["_raw"] is cycle


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"decision_trees": [{"id": "sample"}]}, {"decision_trees": [{"id": "sample"}]}),
        ('{"harness_next":"phase_2_ok"}', {"harness_next": "phase_2_ok"}),
        ("not-json", {"_raw": "not-json"}),
    ],
)
def test_payload_preserves_mapping_and_string_data(payload, data, expected) -> None:
    assert payload(SimpleNamespace(data=data)) == expected


def test_payload_decodes_legacy_content_json(payload) -> None:
    result = SimpleNamespace(data=None, structured_content=None, content='{"report":{"ok":true}}')

    assert payload(result) == {"report": {"ok": True}}
