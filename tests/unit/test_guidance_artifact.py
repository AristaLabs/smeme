"""Unit tests for MCP guidance artifact generation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from smeme.mcp._generated_guidance import (
    GUIDANCE_CONTENT_DIGEST,
    GUIDANCE_CONTENT_MARKDOWN,
    GUIDANCE_CONTENT_VERSION,
)
from smeme.mcp.guidance_artifact import (
    GUIDANCE_CONTENT_VERSION as BUILD_VERSION,
    SKILLS_ROOT,
    assert_blind_protocol_safe,
    build_guidance_artifact,
    canonical_digest_input,
    connector_safe_transform,
    guidance_content_digest,
    load_transformed_skill_bodies,
    render_generated_module,
    strip_yaml_frontmatter,
    write_generated_module,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_PATH = REPO_ROOT / "smeme" / "mcp" / "_generated_guidance.py"


def test_strip_yaml_frontmatter() -> None:
    raw = "---\nname: x\n---\n\n# Body\n"
    assert strip_yaml_frontmatter(raw) == "# Body\n"


def test_connector_safe_transform_removes_zip_only_copy() -> None:
    body = (
        "<!-- installed_plugin_version: 2.12.0 -->\n\n"
        "### Plugin version check\n\n"
        "Every **success** response includes `_server_plugin_version`.\n\n"
        "> Download the latest bundle from your SMEme dashboard for the most accurate skill instructions.\n\n"
        "## Workflow (happy path)\n"
    )
    out = connector_safe_transform(body)
    assert "installed_plugin_version" not in out
    assert "Plugin version check" not in out
    assert "Download the latest bundle" not in out
    assert "## Workflow (happy path)" in out


def test_build_guidance_artifact_matches_committed_module() -> None:
    version, digest, markdown = build_guidance_artifact(content_version=BUILD_VERSION)
    expected = render_generated_module(
        content_version=version,
        content_digest=digest,
        content_markdown=markdown,
    )
    assert GENERATED_PATH.read_text(encoding="utf-8") == expected


def test_digest_is_stable_for_same_sources() -> None:
    sections_a = load_transformed_skill_bodies()
    sections_b = load_transformed_skill_bodies()
    assert guidance_content_digest(sections_a) == guidance_content_digest(sections_b)


def test_digest_does_not_include_rendered_metadata() -> None:
    sections = load_transformed_skill_bodies()
    base_digest = guidance_content_digest(sections)
    tampered = list(sections)
    title, body = tampered[0]
    tampered[0] = (title, body + "\n\n<!-- metadata-only change -->")
    assert guidance_content_digest(tampered) != base_digest
    assert "metadata-only change" not in canonical_digest_input(sections)


def test_digest_prefix_and_generated_constants_align() -> None:
    sections = load_transformed_skill_bodies()
    assert GUIDANCE_CONTENT_DIGEST == guidance_content_digest(sections)
    assert GUIDANCE_CONTENT_DIGEST.startswith("sha256:")
    assert GUIDANCE_CONTENT_VERSION == BUILD_VERSION


def test_generated_markdown_is_non_empty_and_connector_safe() -> None:
    assert GUIDANCE_CONTENT_MARKDOWN.strip()
    assert "installed_plugin_version" not in GUIDANCE_CONTENT_MARKDOWN
    assert "Download the latest bundle" not in GUIDANCE_CONTENT_MARKDOWN
    assert "SMEme Reasoning — Agent Guidance" in GUIDANCE_CONTENT_MARKDOWN
    assert_blind_protocol_safe(GUIDANCE_CONTENT_MARKDOWN)


def test_blind_protocol_guard_rejects_uuid_and_denylisted_tokens() -> None:
    assert_blind_protocol_safe("safe guidance text")
    with pytest.raises(ValueError, match="UUID"):
        assert_blind_protocol_safe("workflow id 550e8400-e29b-41d4-a716-446655440000")
    with pytest.raises(ValueError, match="graph_data"):
        assert_blind_protocol_safe("leaked graph_data field")


def test_load_transformed_skill_bodies_fails_on_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_transformed_skill_bodies(skills_root=tmp_path)


def test_write_generated_module_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "_generated_guidance.py"
    write_generated_module(out, skills_root=SKILLS_ROOT)
    text = out.read_text(encoding="utf-8")
    assert 'GUIDANCE_CONTENT_VERSION = "' in text
    assert "GUIDANCE_CONTENT_MARKDOWN = " in text
    assert re.search(r'GUIDANCE_CONTENT_DIGEST = "sha256:[0-9a-f]{64}"', text)
