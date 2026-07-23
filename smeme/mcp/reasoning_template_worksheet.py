"""Blind-protocol reasoning worksheet (manifest core + markdown) for MCP template tools."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from smeme.qnr.models import DTGraph

# v1: max UTF-8 bytes for ``manifest_markdown`` or total success JSON from ``template_get`` (512 KiB).
REASONING_TEMPLATE_SUCCESS_MAX_UTF8_BYTES = 512 * 1024

_MANIFEST_SCHEMA_VERSION = 1


def utc_generated_at_iso_z() -> str:
    """UTC timestamp as ISO 8601 ending with ``Z``."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def normalize_manifest_text(s: str) -> str:
    """Unicode NFC + strip for manifest strings (labels and options)."""
    return unicodedata.normalize("NFC", s.strip())


def canonical_manifest_core_json_utf8(manifest_core: dict[str, Any]) -> bytes:
    """Canonical UTF-8 bytes for hashing (matches sprint § digest rules)."""
    return json.dumps(
        manifest_core,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def manifest_core_digest(manifest_core: dict[str, Any]) -> str:
    """SHA-256 hex (lowercase) over canonical UTF-8 JSON of ``manifest_core``."""
    return hashlib.sha256(canonical_manifest_core_json_utf8(manifest_core)).hexdigest()


def build_manifest_core(graph: DTGraph, qnr_id: UUID) -> dict[str, Any]:
    """Frozen machine manifest from question nodes only (live ``graph_data`` projection)."""
    qnodes = sorted(
        (n for n in graph.nodes if n.type == "question"),
        key=lambda n: n.id,
    )
    questions: list[dict[str, Any]] = []
    for node in qnodes:
        qd = node.question_data
        if qd is None:
            continue
        label = normalize_manifest_text(qd.text)
        opts = qd.options or []
        normalized = sorted(normalize_manifest_text(o) for o in opts)
        entry: dict[str, Any] = {
            "answer_kind": "radio",
            "id": node.id,
            "label": label,
            "options": normalized,
        }
        questions.append(entry)

    return {
        "qnr_id": str(qnr_id).lower(),
        "questions": questions,
        "schema_version": _MANIFEST_SCHEMA_VERSION,
    }


def safe_worksheet_slug(title: str, *, max_len: int = 60) -> str:
    """Filename-safe slug from title (fallback if empty)."""
    lowered = title.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    slug = slug.strip("-")
    if not slug:
        return "qnr"
    return slug[:max_len].rstrip("-") or "qnr"


def render_manifest_markdown(
    *,
    manifest_core: dict[str, Any],
    title: str,
    qnr_id: UUID,
    slug: str,
    intended_audience: str | None = None,
    use_case: str | None = None,
) -> str:
    """Per-QNR worksheet markdown (minimal frontmatter + frozen checklist).

    Drift (``in_sync``), digest, and capabilities version live on the MCP JSON envelope
    from ``smeme_reasoning_template_get`` / ``template_check`` — not duplicated in YAML.
    """
    fm_title = json.dumps(title, ensure_ascii=True)

    frontmatter: list[str] = [
        "---",
        f"title: {fm_title}",
        f'qnr_id: "{str(qnr_id).lower()}"',
        f'slug: "{slug}"',
    ]
    if intended_audience and intended_audience.strip():
        frontmatter.append(
            f"intended_audience: {json.dumps(intended_audience.strip(), ensure_ascii=True)}"
        )
    if use_case and use_case.strip():
        frontmatter.append(f"use_case: {json.dumps(use_case.strip(), ensure_ascii=True)}")
    frontmatter.append("---")

    bullets: list[str] = []
    for q in sorted(manifest_core.get("questions") or [], key=lambda x: str(x.get("id", ""))):
        qid = q.get("id", "")
        qlabel = q.get("label", "")
        opts = q.get("options") or []
        parts = [f"- **`{qid}`** — {qlabel} (radio)"]
        parts.append(f"  - Allowed values (exact strings): {', '.join(repr(o) for o in opts)}")
        bullets.append("\n".join(parts))

    per_question = "\n".join(bullets) if bullets else "- _(no question nodes)_"

    md_parts = [
        *frontmatter,
        "",
        f"# Reasoning worksheet — {title}",
        "",
        "## How to use this worksheet",
        "",
        "Map **documents, email, chat, and user input** into **`raw_answers`**: keys are **question "
        "node ids** below. The server runs all reasoning; do not infer branch order or conclusions "
        "from this file. Call **`smeme_reasoning_template_check`** first, or read drift/cache fields "
        "from the **`template_get`** JSON envelope, before **`smeme_reasoning_evaluate`**.",
        "",
        "<!-- FROZEN_MACHINE_BLOCK_START -->",
        "",
        "## Per-question prompts (unordered checklist)",
        "",
        per_question,
        "",
        "## Answer formatting",
        "",
        "Published decision trees are **radio-only**: each question has a finite option set. "
        "For **`smeme_reasoning_evaluate`**, set `raw_answers[<question_id>]` to **one** option "
        "string **exactly** as listed above (case and spacing must match). Do not send checkbox "
        "arrays or arbitrary free-form types.",
        "",
        "<!-- FROZEN_MACHINE_BLOCK_END -->",
        "",
        "## After answers are ready",
        "",
        "1. Build **`raw_answers`** keyed by question ids.",
        "2. Call **`smeme_reasoning_evaluate`** with **`raw_answers_json`** set to that object.",
        "3. Use **`persist=false`** for exploration when appropriate.",
        "",
    ]
    return "\n".join(md_parts)


def worksheet_payload_too_large(
    *,
    manifest_markdown: str,
    success_payload: dict[str, Any],
) -> bool:
    """True if UTF-8 size of markdown or full success JSON exceeds the v1 cap."""
    if len(manifest_markdown.encode("utf-8")) > REASONING_TEMPLATE_SUCCESS_MAX_UTF8_BYTES:
        return True
    raw = json.dumps(success_payload, ensure_ascii=False)
    return len(raw.encode("utf-8")) > REASONING_TEMPLATE_SUCCESS_MAX_UTF8_BYTES
