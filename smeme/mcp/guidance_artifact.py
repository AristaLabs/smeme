"""Build connector-safe guidance markdown from cowork skill sources."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / "plugin" / "agent-skills"
GENERATED_PATH = Path(__file__).resolve().parent / "_generated_guidance.py"

GUIDANCE_CONTENT_VERSION = "1.1.0"

_SKILL_ORDER: tuple[tuple[str, str], ...] = (
    ("smeme-reasoning-plugin", "Core (from smeme-reasoning-plugin)"),
    ("smeme-reasoning-slot-fill", "Slot-fill (from smeme-reasoning-slot-fill)"),
    ("smeme-reasoning-outcomes", "Outcomes (from smeme-reasoning-outcomes)"),
)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
_INSTALLED_VERSION_COMMENT_RE = re.compile(
    r"^<!--\s*installed_plugin_version:\s*[^\s>]+\s*-->\s*\n?",
    re.MULTILINE,
)
# Strips from this ### through the next ## heading. Do not add unrelated ### sections
# between "Plugin version check" and the following ## in smeme-reasoning-plugin/SKILL.md.
_PLUGIN_VERSION_SECTION_RE = re.compile(
    r"(?:\A|\n+)### Plugin version check\n.*?(?=\n## )",
    re.DOTALL,
)
_DOWNLOAD_BUNDLE_RE = re.compile(
    r"Download the latest bundle from your SMEme dashboard[^.\n]*\.?",
    re.IGNORECASE,
)
_CONNECTOR_GUIDANCE_REPLACEMENT = (
    "Guidance content is served by `smeme_reasoning_guidance_get` and refreshed automatically."
)

_BLIND_PROTOCOL_DENYLIST = (
    "graph_data",
    "edge_id",
    "compiled_theory",
)
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def strip_yaml_frontmatter(text: str) -> str:
    """Remove leading YAML frontmatter block if present."""
    return _FRONTMATTER_RE.sub("", text, count=1)


def normalize_guidance_section_body(text: str) -> str:
    """NFC-normalize and strip trailing whitespace per line."""
    normalized = unicodedata.normalize("NFC", text)
    lines = [line.rstrip() for line in normalized.splitlines()]
    return "\n".join(lines).strip()


def connector_safe_transform(body: str) -> str:
    """Adapt zip-oriented skill prose for connector-only MCP agents."""
    out = _INSTALLED_VERSION_COMMENT_RE.sub("", body)
    out = _PLUGIN_VERSION_SECTION_RE.sub("\n", out)
    return _DOWNLOAD_BUNDLE_RE.sub(_CONNECTOR_GUIDANCE_REPLACEMENT, out)


def load_transformed_skill_bodies(
    skills_root: Path | None = None,
) -> list[tuple[str, str]]:
    """Read skill files in stitch order; return (section title, transformed body) pairs."""
    root = skills_root or SKILLS_ROOT
    sections: list[tuple[str, str]] = []
    for skill_dir, section_title in _SKILL_ORDER:
        path = root / skill_dir / "SKILL.md"
        if not path.is_file():
            msg = f"missing guidance source skill: {path}"
            raise FileNotFoundError(msg)
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            msg = f"empty guidance source skill: {path}"
            raise ValueError(msg)
        body = normalize_guidance_section_body(
            connector_safe_transform(strip_yaml_frontmatter(raw))
        )
        sections.append((section_title, body))
    return sections


def canonical_digest_input(sections: list[tuple[str, str]]) -> str:
    """Concatenated transformed bodies for digest hashing (no rendered metadata)."""
    return "\n---\n".join(body for _, body in sections)


def guidance_content_digest(sections: list[tuple[str, str]]) -> str:
    """SHA-256 digest prefixed with ``sha256:`` over canonical UTF-8 bodies."""
    payload = canonical_digest_input(sections).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def render_guidance_markdown(
    *,
    sections: list[tuple[str, str]],
    content_version: str,
    content_digest: str,
) -> str:
    """Render the full guidance document served by ``guidance_get``."""
    parts = [
        "# SMEme Reasoning — Agent Guidance",
        "",
        "_This content is served by `smeme_reasoning_guidance_get`. It is the canonical",
        "runtime contract for using SMEme reasoning tools over MCP._",
        "",
        f"_Content version: {content_version} · Digest: {content_digest}_",
        "",
        "---",
        "",
    ]
    for index, (section_title, body) in enumerate(sections):
        if index > 0:
            parts.extend(["", "---", ""])
        parts.extend([f"## {section_title}", "", body])
    return "\n".join(parts) + "\n"


def build_guidance_artifact(
    *,
    skills_root: Path | None = None,
    content_version: str = GUIDANCE_CONTENT_VERSION,
) -> tuple[str, str, str]:
    """Return (version, digest, markdown) for the guidance artifact."""
    sections = load_transformed_skill_bodies(skills_root=skills_root)
    digest = guidance_content_digest(sections)
    markdown = render_guidance_markdown(
        sections=sections,
        content_version=content_version,
        content_digest=digest,
    )
    return content_version, digest, markdown


def render_generated_module(
    *,
    content_version: str,
    content_digest: str,
    content_markdown: str,
) -> str:
    """Python module source for ``smeme/mcp/_generated_guidance.py``."""
    return (
        '"""Generated by scripts/build_guidance_artifact.py — do not edit by hand."""\n\n'
        "from __future__ import annotations\n\n"
        f'GUIDANCE_CONTENT_VERSION = "{content_version}"\n'
        f'GUIDANCE_CONTENT_DIGEST = "{content_digest}"\n'
        f"GUIDANCE_CONTENT_MARKDOWN = {content_markdown!r}\n"
    )


def write_generated_module(
    path: Path | None = None,
    *,
    skills_root: Path | None = None,
    content_version: str = GUIDANCE_CONTENT_VERSION,
) -> Path:
    """Build and write the committed guidance artifact module."""
    version, digest, markdown = build_guidance_artifact(
        skills_root=skills_root,
        content_version=content_version,
    )
    out = path or GENERATED_PATH
    out.write_text(
        render_generated_module(
            content_version=version,
            content_digest=digest,
            content_markdown=markdown,
        ),
        encoding="utf-8",
    )
    return out


def assert_blind_protocol_safe(markdown: str) -> None:
    """Raise ValueError if generated guidance leaks denylisted internal fields or UUIDs."""
    lower = markdown.lower()
    for token in _BLIND_PROTOCOL_DENYLIST:
        if token in lower:
            msg = f"guidance markdown contains denylisted token: {token}"
            raise ValueError(msg)
    if _UUID_RE.search(markdown):
        raise ValueError("guidance markdown contains workflow UUID pattern")
