"""Capabilities payload shape and MCP surface version coupling."""

from __future__ import annotations

import json
import re

from smeme.core.config import settings
from smeme.mcp.reasoning_fastmcp import (
    REASONING_CAPABILITIES_MCP_SURFACE,
    REASONING_CAPABILITIES_VERSION,
    reasoning_capabilities_document,
)

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def test_reasoning_capabilities_version_is_semver() -> None:
    assert SEMVER_RE.fullmatch(REASONING_CAPABILITIES_VERSION)


def test_reasoning_capabilities_document_shape() -> None:
    doc = reasoning_capabilities_document()
    assert doc["service"] == "smeme"
    assert SEMVER_RE.fullmatch(doc["version"])
    assert doc["version"] == REASONING_CAPABILITIES_VERSION
    assert doc["reasoning_mcp_surface"] == REASONING_CAPABILITIES_MCP_SURFACE
    expected_tools = [
        "smeme_reasoning_list",
        "smeme_reasoning_validate_answers",
        "smeme_reasoning_evaluate",
        "smeme_reasoning_what_if",
        "smeme_reasoning_how_to_reach",
        "smeme_reasoning_decisive_support",
        "smeme_reasoning_edit_affects_path",
        "smeme_reasoning_list_conclusions",
        "smeme_reasoning_template_check",
        "smeme_reasoning_template_get",
        "smeme_reasoning_guidance_check",
        "smeme_reasoning_guidance_get",
    ]
    if settings.mcp_authoring_graph_tools_enabled:
        expected_tools.extend(
            [
                "smeme_authoring_design_guidance",
                "smeme_authoring_validate_graph",
                "smeme_authoring_create_draft",
                "smeme_authoring_get_draft",
                "smeme_authoring_update_draft",
            ]
        )
    assert doc["reasoning"]["tools"] == expected_tools
    assert doc["reasoning"]["harness_next_enum"] == [
        "phase_1_continue",
        "phase_2_ok",
        "user_input_needed",
    ]
    assert doc["reasoning"]["ingest_envelope"]["provenance_envelope"] is True
    assert doc["reasoning"]["ingest_envelope"]["evidence_locator_v1"] is True
    assert doc["reasoning"]["ingest_envelope"]["grounding_error_details_v1"] is True
    assert doc["reasoning"]["evaluate_response"]["report_v1"] is True
    assert doc["reasoning"]["evaluate_response"]["decision_tree_warnings_review_v1"] is True
    assert doc["reasoning"]["list_response"]["review_metadata_v1"] is True
    assert doc["reasoning"]["counterfactual"]["how_to_reach_reach_mode"] == [
        "entailed",
        "possible",
    ]
    assert doc["reasoning"]["counterfactual"]["decisive_support"] is True
    assert doc["reasoning"]["counterfactual"]["edit_affects_path"] is True
    assert doc["reasoning"]["counterfactual"]["assumptions"]["force_unreachable_ids"] is True
    assert doc["reasoning"]["counterfactual"]["assumptions"]["tools"] == [
        "smeme_reasoning_evaluate",
        "smeme_reasoning_what_if",
        "smeme_reasoning_how_to_reach",
        "smeme_reasoning_decisive_support",
        "smeme_reasoning_edit_affects_path",
    ]
    assert "what_if" in doc["reasoning"]["query_modes"]["assume"]
    assert doc["reasoning"]["query_modes"]["path_under_edit"] == (
        "smeme_reasoning_edit_affects_path"
    )
    assert doc["reasoning"]["query_modes"]["minimal_sufficient_evidence"].startswith(
        "smeme_reasoning_decisive_support"
    )
    assert "abduce" not in doc["reasoning"]["query_modes"]
    assert "abduce_algebraic" not in doc["reasoning"]["query_modes"]
    assert doc["reasoning"]["query_modes"]["repair"].startswith("smeme_reasoning_how_to_reach")
    assert doc["reasoning"]["query_modes"]["assume"].startswith("force_reachable")
    assert "Bearer" in doc["reasoning"]["auth"]
    dumped = json.dumps(doc)
    roundtrip = json.loads(dumped)
    assert roundtrip == doc


def test_reasoning_capabilities_document_has_stable_top_level_keys() -> None:
    doc = reasoning_capabilities_document()
    expected_keys = {
        "service",
        "version",
        "latest_plugin_version",
        "reasoning_mcp_surface",
        "guidance",
        "reasoning",
        "docs",
    }
    if settings.mcp_authoring_graph_tools_enabled:
        expected_keys |= {"authoring_graph", "authoring_design"}
    assert set(doc.keys()) == expected_keys
    # latest_plugin_version is an unambiguous alias for skill-side version comparison.
    assert doc["latest_plugin_version"] == doc["version"]
