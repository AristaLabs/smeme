"""Payload-decoding tests shared by standalone MCP examples."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import make_dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import create_model

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
SPEC = importlib.util.spec_from_file_location(
    "mcp_tool_decode_for_tests",
    EXAMPLES / "mcp_tool_decode.py",
)
assert SPEC is not None
assert SPEC.loader is not None
DECODE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DECODE
SPEC.loader.exec_module(DECODE)
decode_tool_message = DECODE.decode_tool_message
error_payload = DECODE.error_payload
payload = DECODE.payload
transport_is_error = DECODE.transport_is_error


def test_decodes_generated_model_and_plain_result_wrappers() -> None:
    generated = create_model("Output", result=(str, ...))
    plain = make_dataclass("PlainOutput", [("result", object)])

    assert payload(generated(result='{"status":"ok"}')) == {"status": "ok"}
    assert payload(plain(result='{"status":"ok"}')) == {"status": "ok"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"status": "ok"}, {"status": "ok"}),
        ('{"status":"ok"}', {"status": "ok"}),
        ("not-json", {"_raw": "not-json"}),
    ],
)
def test_decodes_data_wrappers(value, expected) -> None:
    assert payload(SimpleNamespace(data=value)) == expected


def test_decodes_structured_content_and_text_blocks() -> None:
    assert payload(SimpleNamespace(structured_content={"status": "ok"})) == {"status": "ok"}
    assert payload(
        SimpleNamespace(
            data=None,
            structured_content=None,
            content=[{"type": "text", "text": '{"status":"ok"}'}],
        )
    ) == {"status": "ok"}


def test_exact_sanitized_htr5_shape_surfaces_semantic_error() -> None:
    encoded = (
        '{"error":{"code":"target_not_reachable_under_locks",'
        '"message":"Conclusion cannot be reached with the current answers and locked '
        'questions (q9).","target_conclusion_title":"Withhold at Reduced Treaty Rate",'
        '"locked_question_ids":["q9"]}}'
    )
    message = SimpleNamespace(
        artifact={
            "isError": False,
            "structured_content": {"result": encoded},
        },
        status="success",
    )

    decoded = decode_tool_message(message)

    assert error_payload(decoded) == {
        "code": "target_not_reachable_under_locks",
        "message": (
            "Conclusion cannot be reached with the current answers and locked questions (q9)."
        ),
        "target_conclusion_title": "Withhold at Reduced Treaty Rate",
        "locked_question_ids": ["q9"],
    }
    assert transport_is_error(message) is False


def test_transport_error_flags_cover_tool_message_and_artifact() -> None:
    assert transport_is_error(SimpleNamespace(status="error", artifact=None))
    assert transport_is_error(SimpleNamespace(status="success", artifact={"isError": True}))
