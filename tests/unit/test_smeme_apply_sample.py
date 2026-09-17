"""Regression tests for the standalone FastMCP Apply example."""

from __future__ import annotations

import runpy
from dataclasses import make_dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import create_model


@pytest.fixture(scope="module")
def script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "examples" / "smeme_apply_sample.py"


@pytest.fixture(scope="module")
def payload(script_path):
    return runpy.run_path(str(script_path))["_payload"]


def test_script_declares_isolated_uv_dependencies(script_path) -> None:
    source = script_path.read_text(encoding="utf-8")

    assert source.startswith("# /// script\n")
    assert '# requires-python = ">=3.13"' in source
    assert '#   "fastmcp==4.0.3",' in source
    assert "# ///\n" in source


def test_canned_answers_include_provenance_for_every_question(script_path) -> None:
    namespace = runpy.run_path(str(script_path))
    envelope = namespace["_canned_ingest_envelope"]()
    answers = envelope["answers"]
    evidence_items = envelope["evidence_items"]
    evidence_refs = envelope["evidence_refs"]

    evidence_ids = {item["id"] for item in evidence_items}
    assert set(evidence_refs) == set(answers)
    assert all(refs and set(refs) <= evidence_ids for refs in evidence_refs.values())


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


@pytest.mark.parametrize(
    ("output_name", "result", "expected"),
    [
        (
            "smeme_reasoning_capabilitiesOutput",
            '{"reasoning":{"tools":["smeme_reasoning_list"]}}',
            {"reasoning": {"tools": ["smeme_reasoning_list"]}},
        ),
        (
            "smeme_reasoning_listOutput",
            '{"decision_trees":[{"id":"sample","title":"SMEme Sample"}]}',
            {"decision_trees": [{"id": "sample", "title": "SMEme Sample"}]},
        ),
    ],
)
def test_payload_decodes_fastmcp_data_wrapped_plain_result(
    payload, output_name, result, expected
) -> None:
    output_type = make_dataclass(output_name, [("result", object)])
    inner = output_type(result=result)
    outer = SimpleNamespace(data=inner)

    assert repr(inner).startswith(f"{output_name}(result=")
    assert not callable(getattr(inner, "model_dump", None))
    assert payload(outer) == expected


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


def test_payload_data_unwrap_is_cycle_safe(payload) -> None:
    cycle = SimpleNamespace()
    cycle.data = cycle

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
