#!/usr/bin/env python3
"""Fail CI when templates use raw semantic callout classes outside the design system."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = ROOT / "smeme" / "templates"

# Raw light-mode callout backgrounds that should live in macros.html only.
RAW_CALLOUT_BG = re.compile(
    r"\bbg-(?:info|success|warning|danger|amber|red|green|emerald)-(?:50|100)\b"
)

ALLOWLIST = {
    TEMPLATE_ROOT / "components" / "macros.html",
}

SKIP_PARTS = {
    "decision_tree/_validation_issue_row.html",
    "decision_tree/_validation_badge.html",
    "decision_tree/_editor_tools_chip.html",
    "decision_tree/_mcp_discoverable_select.html",
    "decision_tree/_graph_checklist.html",
    "decision_tree/generation/_main_research_edit.html",  # action cards + augment panel (not callouts)
    "decision_tree/_publish_readiness_results.html",  # nested issue lists use border-l accents
    "decision_tree/_publish_blocked_standalone.html",
    "decision_tree/dashboard.html",  # inline workflow-limit hints (not full callouts)
    "auth/_delete_account_step1.html",  # modal icon avatar
    "auth/profile.html",  # usage meter tiles + danger-zone card chrome
    "decision_tree/_delete_confirm_step1.html",  # modal icon avatar
    "decision_tree/_conclusion.html",  # outcome status chips
}


def main() -> int:
    bad: list[str] = []
    for path in sorted(TEMPLATE_ROOT.rglob("*.html")):
        if path in ALLOWLIST:
            continue
        rel = path.relative_to(ROOT)
        if any(str(rel).endswith(skip) or skip in str(rel) for skip in SKIP_PARTS):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "callout(" in text or "import callout" in text or "macros.html' import alert" in text:
            # Templates already on the macro path — still flag if they mix raw bg-* callout classes.
            pass
        for i, line in enumerate(text.splitlines(), start=1):
            if RAW_CALLOUT_BG.search(line) and "dark:" not in line:
                bad.append(f"{rel}:{i}:{line.strip()[:160]}")

    if bad:
        print("\n".join(bad), file=sys.stderr)
        print(
            "\nERROR: Raw semantic callout backgrounds without dark: variants. "
            "Use callout() / alert() from components/macros.html.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
