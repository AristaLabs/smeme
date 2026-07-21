"""smeme.mcp.tool_contract — structured MCP tool error envelope."""

from __future__ import annotations

import json

import pytest

from smeme.mcp.reasoning_fastmcp import (
    REASONING_CAPABILITIES_VERSION,
    _tool_json,
)
from smeme.mcp.tool_contract import (
    INTERNAL_ERROR_MESSAGE,
    REASONING_TOOL_ERROR_CODES,
    parse_tool_error_code,
    tool_error_json,
    tool_error_payload,
)


def test_tool_json_injects_watermark() -> None:
    """_tool_json adds _server_plugin_version to every success payload."""
    payload = {"report": {"result_kind": "concluded"}, "warnings": []}
    result = json.loads(_tool_json(payload))
    assert result["_server_plugin_version"] == REASONING_CAPABILITIES_VERSION
    assert result["report"] == {"result_kind": "concluded"}


def test_tool_json_does_not_mutate_caller_dict() -> None:
    payload = {"status": "ok"}
    _tool_json(payload)
    assert "_server_plugin_version" not in payload


def test_tool_error_json_has_no_watermark() -> None:
    """Error responses intentionally exclude the server plugin version watermark."""
    data = json.loads(tool_error_json("auth_error", "not authed"))
    assert "_server_plugin_version" not in data
    assert "_server_plugin_version" not in data.get("error", {})


def test_tool_error_json_roundtrip():
    s = tool_error_json("not_found", "missing", hint="use list")
    data = json.loads(s)
    assert data == {"error": {"code": "not_found", "message": "missing", "hint": "use list"}}


def test_tool_error_payload():
    p = tool_error_payload("stale_theory", "msg", current_hash="a", compiled_hash="b")
    assert p["code"] == "stale_theory"
    assert p["current_hash"] == "a"


def test_parse_tool_error_code():
    assert parse_tool_error_code(tool_error_json("auth_error", "x")) == "auth_error"
    assert parse_tool_error_code("{}") is None
    assert parse_tool_error_code("not json") is None


@pytest.mark.parametrize("code", sorted(REASONING_TOOL_ERROR_CODES))
def test_documented_codes_in_frozenset(code: str):
    assert code in REASONING_TOOL_ERROR_CODES


def test_internal_error_message_non_empty():
    assert INTERNAL_ERROR_MESSAGE.strip()
