#!/usr/bin/env python3
"""Generate smeme/mcp/_generated_design_guidance.py from plugin/cowork-skills source."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smeme.mcp.design_guidance_artifact import (  # noqa: E402
    DESIGN_GUIDANCE_CONTENT_VERSION,
    GENERATED_PATH,
    build_design_guidance_artifact,
    render_generated_module,
    write_generated_module,
)


def _expected_module_text() -> str:
    version, digest, markdown = build_design_guidance_artifact(
        content_version=DESIGN_GUIDANCE_CONTENT_VERSION
    )
    return render_generated_module(
        content_version=version,
        content_digest=digest,
        content_markdown=markdown,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if committed _generated_design_guidance.py does not match current sources",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=GENERATED_PATH,
        help=f"output path (default: {GENERATED_PATH.relative_to(ROOT)})",
    )
    args = parser.parse_args(argv)

    if args.check:
        if not args.output.is_file():
            print(f"ERROR: missing {args.output}", file=sys.stderr)
            return 1
        committed = args.output.read_text(encoding="utf-8")
        expected = _expected_module_text()
        if committed != expected:
            print(
                f"ERROR: {args.output} is stale — run: "
                "python scripts/build_design_guidance_artifact.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {args.output} matches current cowork skill sources")
        return 0

    out = write_generated_module(args.output)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
