"""Unit tests for MCP authoring design guidance artifact generation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from smeme.mcp._generated_design_guidance import (
    DESIGN_GUIDANCE_DIGEST,
    DESIGN_GUIDANCE_MARKDOWN,
    DESIGN_GUIDANCE_VERSION,
)
from smeme.mcp.design_guidance_artifact import (
    DESIGN_GUIDANCE_CONTENT_VERSION as BUILD_VERSION,
)
from smeme.mcp.design_guidance_artifact import (
    DESIGN_SOURCE_PATH,
    GENERATED_PATH,
    assert_blind_protocol_safe,
    build_design_guidance_artifact,
    design_content_digest,
    load_design_source,
    render_generated_module,
)


def test_build_design_guidance_artifact_matches_committed_module() -> None:
    version, digest, markdown = build_design_guidance_artifact(content_version=BUILD_VERSION)
    expected = render_generated_module(
        content_version=version,
        content_digest=digest,
        content_markdown=markdown,
    )
    assert GENERATED_PATH.read_text(encoding="utf-8") == expected


def test_digest_aligns_with_generated_constants() -> None:
    body = load_design_source()
    assert design_content_digest(body) == DESIGN_GUIDANCE_DIGEST
    assert DESIGN_GUIDANCE_DIGEST.startswith("sha256:")
    assert DESIGN_GUIDANCE_VERSION == BUILD_VERSION


def test_generated_markdown_content() -> None:
    assert DESIGN_GUIDANCE_MARKDOWN.strip()
    assert "Product constraints" in DESIGN_GUIDANCE_MARKDOWN
    assert "Conclusion-driven" in DESIGN_GUIDANCE_MARKDOWN or "conclusions" in DESIGN_GUIDANCE_MARKDOWN
    assert "smeme_authoring_validate_graph" in DESIGN_GUIDANCE_MARKDOWN
    assert "help_text" in DESIGN_GUIDANCE_MARKDOWN
    assert "extra=forbid" in DESIGN_GUIDANCE_MARKDOWN
    assert 'required: true' in DESIGN_GUIDANCE_MARKDOWN or '"required": true' in DESIGN_GUIDANCE_MARKDOWN
    assert "conjunctive" in DESIGN_GUIDANCE_MARKDOWN.lower()
    assert "q7a" in DESIGN_GUIDANCE_MARKDOWN or "duplicate" in DESIGN_GUIDANCE_MARKDOWN.lower()
    assert_blind_protocol_safe(DESIGN_GUIDANCE_MARKDOWN)


def test_blind_protocol_guard() -> None:
    assert_blind_protocol_safe("safe design text")
    with pytest.raises(ValueError, match="UUID"):
        assert_blind_protocol_safe("id 550e8400-e29b-41d4-a716-446655440000")
    with pytest.raises(ValueError, match="graph_data"):
        assert_blind_protocol_safe("leaked graph_data")


def test_source_path_exists() -> None:
    assert DESIGN_SOURCE_PATH.is_file()
    assert DESIGN_SOURCE_PATH.relative_to(Path(__file__).resolve().parents[2])


def test_render_module_shape() -> None:
    text = render_generated_module(
        content_version="1.0.0",
        content_digest="sha256:" + ("a" * 64),
        content_markdown="# hi",
    )
    assert 'DESIGN_GUIDANCE_VERSION = "1.0.0"' in text
    assert re.search(r'DESIGN_GUIDANCE_DIGEST = "sha256:[0-9a-f]{64}"', text)
    assert "DESIGN_GUIDANCE_MARKDOWN = " in text
