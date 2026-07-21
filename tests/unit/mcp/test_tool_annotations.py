"""M2 — MCP tool annotations (`tools/list`).

Microsoft 365 Copilot treats tools **without** ``readOnlyHint`` / ``destructiveHint``
as destructive and confirms on every call.  These tests assert every registered
reasoning tool advertises annotations, and that read vs compute tools carry the
correct hints.  Annotations are server-side, so this also benefits Claude /
ChatGPT / Cursor.

See docs/planning/sprint-m365-copilot-cowork-plugin.md (Phase 2, M2-1/M2-2).
"""

from __future__ import annotations

import asyncio

from smeme.core.config import settings as process_settings
from smeme.mcp.reasoning_fastmcp import (
    get_or_create_fastmcp,
    reset_mcp_runtime_for_tests,
)

# Read-only tools: safe to auto-run, no environment change.
READ_ONLY_TOOLS = {
    "smeme_reasoning_capabilities",
    "smeme_reasoning_guidance_check",
    "smeme_reasoning_guidance_get",
    "smeme_reasoning_list",
    "smeme_reasoning_validate_answers",
    "smeme_reasoning_list_conclusions",
    "smeme_reasoning_template_check",
    "smeme_reasoning_template_get",
    "smeme_authoring_design_guidance",
    "smeme_authoring_validate_graph",
}

# Compute/metered tools: not read-only, but not destructive (no data is
# overwritten or deleted — they consume reasoning quota and return a report).
COMPUTE_TOOLS = {
    "smeme_reasoning_evaluate",
    "smeme_reasoning_what_if",
    "smeme_reasoning_how_to_reach",
    "smeme_reasoning_decisive_support",
    "smeme_reasoning_edit_affects_path",
    "smeme_authoring_create_draft",
}


def _test_settings():
    return process_settings.model_copy(
        update={
            "environment": "testing",
            "mcp_enabled": True,
            "mcp_authoring_graph_tools_enabled": True,
        }
    )


def _list_tools():
    reset_mcp_runtime_for_tests()
    try:
        mcp = get_or_create_fastmcp(_test_settings())
        tools = asyncio.run(mcp.list_tools())
    finally:
        reset_mcp_runtime_for_tests()
    return {t.name: t for t in tools}


def test_every_tool_has_annotations_with_title():
    by_name = _list_tools()
    assert by_name, "no tools registered"
    for name, tool in by_name.items():
        assert tool.annotations is not None, f"{name} missing annotations"
        assert tool.annotations.title, f"{name} missing annotations.title"
        assert tool.annotations.readOnlyHint is not None, (
            f"{name} must set readOnlyHint (Copilot treats unset as destructive)"
        )


def test_read_only_tools_marked_read_only():
    by_name = _list_tools()
    for name in READ_ONLY_TOOLS:
        assert name in by_name, f"expected tool {name} to be registered"
        assert by_name[name].annotations.readOnlyHint is True, (
            f"{name} should be readOnlyHint=True"
        )


def test_compute_tools_not_read_only_but_not_destructive():
    by_name = _list_tools()
    for name in COMPUTE_TOOLS:
        assert name in by_name, f"expected tool {name} to be registered"
        ann = by_name[name].annotations
        assert ann.readOnlyHint is False, f"{name} should be readOnlyHint=False"
        assert ann.destructiveHint is False, (
            f"{name} should be destructiveHint=False (consumes quota, not destructive)"
        )


def test_read_only_and_compute_sets_cover_all_tools():
    """Guard: any newly added tool must be classified here (fails loudly)."""
    by_name = _list_tools()
    classified = READ_ONLY_TOOLS | COMPUTE_TOOLS
    unclassified = set(by_name) - classified
    assert not unclassified, (
        f"new MCP tool(s) missing annotation classification in this test: {unclassified}"
    )
