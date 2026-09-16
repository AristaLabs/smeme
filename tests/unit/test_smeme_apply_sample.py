"""Regression tests for the standalone FastMCP Apply example."""

from __future__ import annotations

import runpy
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
