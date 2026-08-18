"""Inquire MCP FastMCP registration gate."""

from __future__ import annotations

import asyncio

from smeme.core.config import settings as process_settings
from smeme.mcp.reasoning_fastmcp import (
    get_or_create_fastmcp,
    reasoning_capabilities_document,
    reset_mcp_runtime_for_tests,
)

INQUIRE_TOOLS = {
    "smeme_inquire_analyze",
    "smeme_inquire_get_task",
    "smeme_inquire_admit",
    "smeme_inquire_verify",
}


def _settings(*, inquire: bool):
    return process_settings.model_copy(
        update={
            "environment": "testing",
            "mcp_enabled": True,
            "mcp_authoring_graph_tools_enabled": False,
            "mcp_inquire_tools_enabled": inquire,
        }
    )


def test_inquire_tools_off_by_default_in_capabilities() -> None:
    doc = reasoning_capabilities_document(
        cap_settings=_settings(inquire=False),
    )
    assert "inquire" not in doc
    for name in INQUIRE_TOOLS:
        assert name not in doc["reasoning"]["tools"]


def test_inquire_tools_registered_when_enabled() -> None:
    reset_mcp_runtime_for_tests()
    try:
        mcp = get_or_create_fastmcp(_settings(inquire=True))
        names = {t.name for t in asyncio.run(mcp.list_tools())}
    finally:
        reset_mcp_runtime_for_tests()
    assert INQUIRE_TOOLS <= names
    doc = reasoning_capabilities_document(cap_settings=_settings(inquire=True))
    assert doc["inquire"]["persist_v1"] is False
    assert doc["inquire"]["pv_authority"] == "server"
    assert doc["inquire"]["verification_battery"] == "core"


def test_inquire_tools_absent_when_disabled() -> None:
    reset_mcp_runtime_for_tests()
    try:
        mcp = get_or_create_fastmcp(_settings(inquire=False))
        names = {t.name for t in asyncio.run(mcp.list_tools())}
    finally:
        reset_mcp_runtime_for_tests()
    assert names.isdisjoint(INQUIRE_TOOLS)
