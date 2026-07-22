#!/usr/bin/env python3
"""§10.2 — scan smeme/ and plugin/agent-skills/ for legacy DTQ product tokens.

Pattern intent (keep in sync with cutover plan §10.2): module paths, alias class
(`DTQ_TOOL_ERROR_CODES`), env-var prefix (`SMEME_DTQ_*`), deleted MCP/modules
(`dtq_fastmcp`, `dtq_evaluate.py`, `dtq_structural.py`), URL segment `/dtq/`,
and legacy table/column tokens (`dtq_compiled_theories`, `dtq_evaluation_runs`,
`dtq_status`).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERN = re.compile(
    r"smeme\.qnr\.dtq|DTQCompiledTheory|compile_dtq|evaluate_dtq|/dtq/|"
    r"DTQ_TOOL_ERROR_CODES|SMEME_DTQ_|dtq_fastmcp|dtq_evaluate\.py|dtq_structural\.py|"
    r"dtq_compiled_theories|dtq_evaluation_runs|\bdtq_status\b"
)
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".woff2"}


def main() -> int:
    bad: list[str] = []
    for base in (ROOT / "smeme", ROOT / "plugin" / "agent-skills"):
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in SKIP_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if PATTERN.search(line):
                    rel = path.relative_to(ROOT)
                    bad.append(f"{rel}:{i}:{line.strip()[:200]}")

    if bad:
        print("\n".join(bad), file=sys.stderr)
        print(
            "\nERROR: §10.2 deletion gate violated — DTQ references in product paths.\n"
            "See docs/planning/dtq-to-reasoning-cutover.md §0.3 and §10.2.",
            file=sys.stderr,
        )
        return 1
    print("§10.2 deletion gate: clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
