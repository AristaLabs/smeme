#!/usr/bin/env python3
"""Scan user-facing surfaces for artifact misuse of legacy product labels.

Flags user-visible uses of *workflow* (and optionally *questionnaire*) when they
refer to the decision-tree product artifact. Allows LangGraph execution terms,
stable wire identifiers, and lines listed in product_vocabulary_allowlist.txt.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_PATH = ROOT / "scripts" / "product_vocabulary_allowlist.txt"

SCAN_ROOTS = (
    ROOT / "smeme" / "templates",
    ROOT / "agent-skills",
)
MCP_SCAN_FILES = (
    ROOT / "smeme" / "mcp" / "reasoning_fastmcp.py",
    ROOT / "smeme" / "mcp" / "authoring_graph.py",
    ROOT / "smeme" / "mcp" / "reasoning_template_worksheet.py",
)

SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".woff2"}

# Product-artifact workflow (case-insensitive). Questionnaire as optional second pass.
WORKFLOW_PATTERN = re.compile(
    r"\b(?:"
    r"workflows?|"
    r"new\s+workflow|"
    r"create\s+(?:new\s+)?workflow|"
    r"build(?:ing)?\s+(?:a\s+)?workflow|"
    r"your\s+workflow|"
    r"this\s+workflow|"
    r"the\s+workflow|"
    r"per-workflow|"
    r"workflow\s+(?:structure|design|editor|limit|actions?|version)"
    r")\b",
    re.IGNORECASE,
)
QUESTIONNAIRE_PATTERN = re.compile(
    r"\b(?:questionnaires?|qnr\s+questionnaire)\b",
    re.IGNORECASE,
)

# Inline allow: LangGraph / execution / wire identifiers on the same line.
LINE_ALLOW_PATTERNS = (
    re.compile(r"workflow_launch_link|workflow_title|workflow_pick_required"),
    re.compile(r"usage_summary\.workflows|count_active_root_workflows"),
    re.compile(r"QuotaDimension\.WORKFLOWS|dimension=\"workflows\""),
    re.compile(r"get_compiled_workflow|LangGraph|langgraph|checkpointer"),
    re.compile(r"TypedDict.*workflow|workflow state|workflow_module"),
    re.compile(r"/qnr/agentic/|wizard-start|in-progress wizard"),
    re.compile(r"questionnaire_design_edited|questionnaire_design\b"),
    re.compile(r"\bqnr_id\b|/qnr/|compile_qnr"),
    re.compile(r"download-workflow|/docs/download-workflow"),
    re.compile(r"macro workflow_launch|Workflow launch \(dashboard"),
    re.compile(r"HTMX swap target \(QNR workflow"),
    re.compile(r"foreign national property tax workflow"),  # example prompt in docs
    re.compile(r"published workflow appears", re.IGNORECASE),  # agent skill deploy note
    re.compile(r"smeme-workflow-author"),  # historical skill slug in changelogs / renames
)


def _load_allowlist() -> set[str]:
    if not ALLOWLIST_PATH.is_file():
        return set()
    entries: set[str] = set()
    for raw in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(line)
    return entries


def _line_allowed(line: str, file_allowlist: set[str]) -> bool:
    stripped = line.strip()
    if stripped in file_allowlist:
        return True
    for pat in LINE_ALLOW_PATTERNS:
        if pat.search(line):
            return True
    return False


def _scan_file(path: Path, *, check_questionnaire: bool) -> list[str]:
    file_allowlist = _load_allowlist()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    bad: list[str] = []
    rel = path.relative_to(ROOT)
    for i, line in enumerate(text.splitlines(), start=1):
        if _line_allowed(line, file_allowlist):
            continue
        if WORKFLOW_PATTERN.search(line):
            bad.append(f"{rel}:{i}:workflow:{line.strip()[:200]}")
        if check_questionnaire and QUESTIONNAIRE_PATTERN.search(line):
            bad.append(f"{rel}:{i}:questionnaire:{line.strip()[:200]}")
    return bad


def main() -> int:
    check_questionnaire = "--questionnaire" in sys.argv
    bad: list[str] = []

    for base in SCAN_ROOTS:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() in SKIP_SUFFIXES:
                continue
            bad.extend(_scan_file(path, check_questionnaire=check_questionnaire))

    for path in MCP_SCAN_FILES:
        if path.is_file():
            bad.extend(_scan_file(path, check_questionnaire=check_questionnaire))

    if bad:
        print("\n".join(bad), file=sys.stderr)
        print(
            "\nERROR: product vocabulary check failed — artifact 'workflow' / "
            "'questionnaire' in user-facing copy.\n"
            "Use 'decision tree' for the product artifact. Allowlist: "
            "scripts/product_vocabulary_allowlist.txt",
            file=sys.stderr,
        )
        return 1
    print("Product vocabulary check: clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
