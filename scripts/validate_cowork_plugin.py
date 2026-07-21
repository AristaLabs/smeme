#!/usr/bin/env python3
"""Validate ``plugin/cowork-skills`` (guidance / rubric authoring source) for CI.

Checks: required skill files exist, agent-safe vocabulary denylist, and that
``installed_plugin_version`` in the primary skill matches
``REASONING_CAPABILITIES_VERSION`` (MCP surface watermark).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SKILLS_SRC = ROOT / "plugin" / "cowork-skills"

_SKILL_NAMES = (
    "smeme-reasoning-plugin",
    "smeme-reasoning-slot-fill",
    "smeme-reasoning-outcomes",
)

_REASONING_CAP_VER_RE = re.compile(
    r"^REASONING_CAPABILITIES_VERSION\s*=\s*[\"']([^\"']+)[\"']\s*(?:#.*)?$",
    re.MULTILINE,
)
_INSTALLED_PLUGIN_VER_RE = re.compile(
    r"<!--\s*installed_plugin_version:\s*([^\s>]+)\s*-->"
)
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

# Agent-facing skills must not leak implementation/stack vocabulary (blind protocol + IP).
_SKILL_FORBIDDEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bZ3\b", re.IGNORECASE), "Z3"),
    (re.compile(r"\bSAT/UNSAT\b", re.IGNORECASE), "SAT/UNSAT"),
    (re.compile(r"\bSAT_\w+", re.IGNORECASE), "SAT_*"),
    (re.compile(r"\bUNSAT\b", re.IGNORECASE), "UNSAT"),
    (re.compile(r"\bSMT\b", re.IGNORECASE), "SMT"),
    (re.compile(r"\bsatisfiable\b", re.IGNORECASE), "satisfiable"),
    (re.compile(r"\bunsatisfiable\b", re.IGNORECASE), "unsatisfiable"),
    (re.compile(r"\bsolver\b(?!_timeout)", re.IGNORECASE), "solver (except wire code solver_timeout)"),
    (re.compile(r"\bentail(?:ed|ment)\b", re.IGNORECASE), "entailment / entailed"),
)


def _reasoning_capabilities_version_from_source() -> str | None:
    path = ROOT / "smeme" / "mcp" / "reasoning_fastmcp.py"
    if not path.is_file():
        print(f"Missing {path.relative_to(ROOT)}", file=sys.stderr)
        return None
    m = _REASONING_CAP_VER_RE.search(path.read_text(encoding="utf-8"))
    if not m:
        print(
            'Could not find REASONING_CAPABILITIES_VERSION = "…" in smeme/mcp/reasoning_fastmcp.py',
            file=sys.stderr,
        )
        return None
    return m.group(1)


def _skill_installed_version(capabilities_version: str) -> list[str]:
    """Check that the primary skill's installed_plugin_version comment matches capabilities."""
    errors: list[str] = []
    skill_path = SKILLS_SRC / "smeme-reasoning-plugin" / "SKILL.md"
    if not skill_path.is_file():
        return errors
    text = skill_path.read_text(encoding="utf-8")
    m = _INSTALLED_PLUGIN_VER_RE.search(text)
    if not m:
        errors.append(
            f"Missing <!-- installed_plugin_version: X.Y.Z --> in "
            f"{skill_path.relative_to(ROOT)}"
        )
    elif m.group(1) != capabilities_version:
        errors.append(
            f"installed_plugin_version {m.group(1)!r} in "
            f"{skill_path.relative_to(ROOT)} != REASONING_CAPABILITIES_VERSION "
            f"{capabilities_version!r}"
        )
    return errors


def _prose_outside_backticks(text: str) -> str:
    """Strip `` `wire identifiers` `` segments — allowed to use implementation field names."""
    return re.sub(r"`[^`]*`", "", text)


def _check_skills_agent_safe_vocabulary() -> list[str]:
    """Denylist formal-methods / stack terms in SKILL.md prose."""
    errors: list[str] = []
    for name in _SKILL_NAMES:
        path = SKILLS_SRC / name / "SKILL.md"
        if not path.is_file():
            continue
        prose = _prose_outside_backticks(path.read_text(encoding="utf-8"))
        for pattern, label_term in _SKILL_FORBIDDEN_PATTERNS:
            if pattern.search(prose):
                errors.append(
                    f"Agent-unsafe vocabulary {label_term!r} in skill "
                    f"{path} — use product terms (reasoning engine, report, results); "
                    "see plugin/cowork-skills/README.md#agent-safe-vocabulary-required"
                )
                break
    return errors


def validate_cowork_plugin_tree() -> list[str]:
    """Return human-readable validation errors (empty list means OK).

    Name kept for CI / Makefile compatibility; validates skills source only.
    """
    errors: list[str] = []

    if not SKILLS_SRC.is_dir():
        return [f"Missing {SKILLS_SRC.relative_to(ROOT)}"]

    for name in _SKILL_NAMES:
        path = SKILLS_SRC / name / "SKILL.md"
        if not path.is_file():
            errors.append(f"Missing required skill: {path.relative_to(ROOT)}")

    errors.extend(_check_skills_agent_safe_vocabulary())

    cap_ver = _reasoning_capabilities_version_from_source()
    if cap_ver is None:
        errors.append(
            "Could not find REASONING_CAPABILITIES_VERSION in smeme/mcp/reasoning_fastmcp.py"
        )
    else:
        if not _SEMVER_RE.match(cap_ver):
            errors.append(
                f"REASONING_CAPABILITIES_VERSION {cap_ver!r} must be semver MAJOR.MINOR.PATCH"
            )
        errors.extend(_skill_installed_version(cap_ver))

    return errors


def main() -> int:
    errors = validate_cowork_plugin_tree()
    if errors:
        for msg in errors:
            print(msg, file=sys.stderr)
        return 1

    print("Cowork skills OK (vocabulary + capabilities version coupling).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
