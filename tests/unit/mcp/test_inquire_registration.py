"""Inquire MCP FastMCP registration — chat vs orchestrator mounts."""

from __future__ import annotations

import asyncio

from smeme.core.config import settings as process_settings
from smeme.mcp.reasoning_fastmcp import (
    get_or_create_fastmcp,
    get_or_create_orchestrator_fastmcp,
    reasoning_capabilities_document,
    reset_mcp_runtime_for_tests,
)

INQUIRE_TOOLS = {
    "smeme_inquire_start",
    "smeme_inquire_next",
    "smeme_inquire_get_task",
    "smeme_inquire_admit",
    "smeme_inquire_verify",
}

CHAT_FACADE_TOOLS = {
    "smeme_reasoning_evaluate",
    "smeme_reasoning_evaluate_continue",
    "smeme_reasoning_evaluate_answers",
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


def test_inquire_tools_off_by_default_in_chat_capabilities() -> None:
    doc = reasoning_capabilities_document(
        cap_settings=_settings(inquire=False),
    )
    assert "inquire" not in doc
    for name in INQUIRE_TOOLS:
        assert name not in doc["reasoning"]["tools"]
    assert "smeme_reasoning_evaluate_continue" in doc["reasoning"]["tools"]
    assert "smeme_reasoning_evaluate_answers" in doc["reasoning"]["tools"]
    assert doc["reasoning"]["query_modes"]["apply"] == "smeme_reasoning_evaluate_answers"


def test_inquire_tools_on_orchestrator_not_chat_fastmcp() -> None:
    reset_mcp_runtime_for_tests()
    try:
        chat = get_or_create_fastmcp(_settings(inquire=True))
        chat_names = {t.name for t in asyncio.run(chat.list_tools())}
        orch = get_or_create_orchestrator_fastmcp(_settings(inquire=True))
        assert orch is not None
        orch_names = {t.name for t in asyncio.run(orch.list_tools())}
    finally:
        reset_mcp_runtime_for_tests()
    assert chat_names.isdisjoint(INQUIRE_TOOLS)
    assert CHAT_FACADE_TOOLS <= chat_names
    assert orch_names >= INQUIRE_TOOLS
    assert "smeme_inquire_guidance_get" in orch_names
    doc = reasoning_capabilities_document(
        cap_settings=_settings(inquire=True), surface="orchestrator"
    )
    assert doc["inquire"]["protocol"] == "explicit_orchestration"
    assert doc["inquire"]["isolated_evaluations_required"] is True
    assert doc["inquire"]["evaluator_isolation"] == "caller_responsibility"
    assert doc["inquire"]["persist_v1"] is True


def test_inquire_orchestrator_absent_when_disabled() -> None:
    reset_mcp_runtime_for_tests()
    try:
        assert get_or_create_orchestrator_fastmcp(_settings(inquire=False)) is None
        mcp = get_or_create_fastmcp(_settings(inquire=False))
        names = {t.name for t in asyncio.run(mcp.list_tools())}
    finally:
        reset_mcp_runtime_for_tests()
    assert names.isdisjoint(INQUIRE_TOOLS)
    assert CHAT_FACADE_TOOLS <= names
