"""Unit tests for MCP guidance tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from smeme.core.models import User
from smeme.mcp._generated_guidance import (
    GUIDANCE_CONTENT_DIGEST,
    GUIDANCE_CONTENT_MARKDOWN,
    GUIDANCE_CONTENT_VERSION,
)
from smeme.mcp.invocation_telemetry import (
    internal_cost_units_for_tool,
    quota_weight_for_tool,
)
from smeme.mcp.reasoning_fastmcp import (
    REASONING_CAPABILITIES_VERSION,
    get_or_create_fastmcp,
    reasoning_capabilities_document,
    reset_mcp_runtime_for_tests,
)


def test_capabilities_includes_guidance_tools_and_block() -> None:
    doc = reasoning_capabilities_document()
    tools = doc["reasoning"]["tools"]
    assert "smeme_reasoning_guidance_check" in tools
    assert "smeme_reasoning_guidance_get" in tools
    assert doc["guidance"] == {
        "content_version": GUIDANCE_CONTENT_VERSION,
        "content_digest": GUIDANCE_CONTENT_DIGEST,
    }


def test_guidance_tools_have_zero_quota_weight() -> None:
    assert quota_weight_for_tool("smeme_reasoning_guidance_check") == 0.0
    assert quota_weight_for_tool("smeme_reasoning_guidance_get") == 0.0
    assert internal_cost_units_for_tool("smeme_reasoning_guidance_check") == 0.0
    assert internal_cost_units_for_tool("smeme_reasoning_guidance_get") == 0.0


@pytest.mark.asyncio
async def test_guidance_check_returns_version_and_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_mcp_runtime_for_tests()
    user = User(id=uuid4(), clerk_user_id="user_test", email="a@example.com")
    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
        AsyncMock(return_value=user),
    )

    fm = get_or_create_fastmcp()
    tool_fn = fm._tool_manager._tools["smeme_reasoning_guidance_check"].fn
    ctx = MagicMock()
    with patch("smeme.mcp.reasoning_fastmcp.request_from_mcp_context", return_value=MagicMock()):
        raw = await tool_fn(ctx)

    payload = json.loads(raw)
    assert payload["content_version"] == GUIDANCE_CONTENT_VERSION
    assert payload["content_digest"] == GUIDANCE_CONTENT_DIGEST
    assert payload["_server_plugin_version"] == REASONING_CAPABILITIES_VERSION
    assert "error" not in payload


@pytest.mark.asyncio
async def test_guidance_get_returns_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_mcp_runtime_for_tests()
    user = User(id=uuid4(), clerk_user_id="user_test", email="a@example.com")
    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
        AsyncMock(return_value=user),
    )

    fm = get_or_create_fastmcp()
    tool_fn = fm._tool_manager._tools["smeme_reasoning_guidance_get"].fn
    ctx = MagicMock()
    with patch("smeme.mcp.reasoning_fastmcp.request_from_mcp_context", return_value=MagicMock()):
        raw = await tool_fn(ctx)

    payload = json.loads(raw)
    assert payload["content_markdown"] == GUIDANCE_CONTENT_MARKDOWN
    assert payload["content_version"] == GUIDANCE_CONTENT_VERSION
    assert payload["content_digest"] == GUIDANCE_CONTENT_DIGEST
    assert "installed_plugin_version" not in payload["content_markdown"]
    assert "Download the latest bundle" not in payload["content_markdown"]


@pytest.mark.asyncio
async def test_guidance_check_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_mcp_runtime_for_tests()
    auth_err = json.dumps({"error": {"code": "auth_error", "message": "nope"}})
    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
        AsyncMock(return_value=auth_err),
    )

    fm = get_or_create_fastmcp()
    tool_fn = fm._tool_manager._tools["smeme_reasoning_guidance_check"].fn
    ctx = MagicMock()
    with patch("smeme.mcp.reasoning_fastmcp.request_from_mcp_context", return_value=MagicMock()):
        raw = await tool_fn(ctx)

    assert json.loads(raw)["error"]["code"] == "auth_error"
