#!/usr/bin/env python3
"""Fail when the operator image pin drifts from the Core release lineage.

``.env.core.example`` is the authoritative default for the pull-only self-host
path: ``scripts/init_core_env.sh`` copies it verbatim and
``docker-compose.core.yml`` refuses to start without ``SMEME_CORE_IMAGE``. A
stale pin there silently boots an old image no matter which tag the operator
checked out, so it is checked against the release tag rather than reviewed by
eye.

Three rules:

1. Every literal ``ghcr.io/aristalabs/smeme:vMAJOR.MINOR.PATCH`` in the
   operator surface matches the ``.env.core.example`` pin.
2. On a release tag build the pin equals the tag. Otherwise the pin is at least
   the newest reachable release tag, which leaves room for the bump to land in
   the release PR before the tag exists.
3. The pin is not a release recorded as defective in §14 of
   ``docs/spec/decision-dag-calculus.md``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = ROOT / ".env.core.example"

# Operator-facing files that name a concrete image tag.
PINNED_SURFACE = (
    Path("README.md"),
    Path("docs/guides/self-host-quickstart.md"),
    Path("docs/guides/self-host-env.md"),
)

# Consequence-surface defects recorded in the calculus correction record (§14).
# Images built from these tags keep the incorrect behavior, so they must never
# be the default pin.
DEFECTIVE_VERSIONS = {
    "v0.9.9": "entailment/possibility/cause defects on an unsatisfiable base (calculus §14)",
    "v0.9.10": "entailment/possibility/cause defects on an unsatisfiable base (calculus §14)",
}

_PIN = re.compile(r"(?m)^SMEME_CORE_IMAGE=(\S+)\s*$")
_IMAGE_TAG = re.compile(r"ghcr\.io/aristalabs/smeme:(v\d+\.\d+\.\d+)")
_VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def _parse(version: str) -> tuple[int, int, int]:
    m = _VERSION.match(version)
    if not m:
        message = f"not a release version: {version}"
        raise SystemExit(message)
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _latest_release_tag() -> str | None:
    """Highest vMAJOR.MINOR.PATCH tag, or None in a tagless checkout.

    Uses the tag list rather than ``git describe`` so the comparison still runs
    under the shallow CI checkout, where the newest release tag is often not
    reachable from HEAD and ``describe`` would return nothing.
    """
    try:
        out = subprocess.run(
            ["git", "tag", "--list", "v*.*.*"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    tags = [t for t in out.stdout.split() if _VERSION.match(t)]
    return max(tags, key=_parse) if tags else None


def main() -> int:
    errors: list[str] = []

    if not ENV_EXAMPLE.is_file():
        print("missing .env.core.example", file=sys.stderr)
        return 1

    pins = _PIN.findall(ENV_EXAMPLE.read_text(encoding="utf-8"))
    if len(pins) != 1:
        print(
            f".env.core.example must set SMEME_CORE_IMAGE exactly once (found {len(pins)})",
            file=sys.stderr,
        )
        return 1

    pinned_image = pins[0]
    tag_match = _IMAGE_TAG.fullmatch(pinned_image)
    if not tag_match:
        # A digest pin is legitimate for operators but not as the shipped
        # default: the example has to name a human-readable release.
        print(
            f".env.core.example must pin a release tag, got: {pinned_image}",
            file=sys.stderr,
        )
        return 1

    pinned = tag_match.group(1)

    if pinned in DEFECTIVE_VERSIONS:
        errors.append(
            f"default pin {pinned} is a recorded defective release — {DEFECTIVE_VERSIONS[pinned]}"
        )

    for rel in PINNED_SURFACE:
        path = ROOT / rel
        if not path.is_file():
            errors.append(f"missing required file: {rel}")
            continue
        for found in sorted(set(_IMAGE_TAG.findall(path.read_text(encoding="utf-8")))):
            if found != pinned:
                errors.append(f"{rel} names image {found} but .env.core.example pins {pinned}")

    github_ref = os.environ.get("GITHUB_REF", "")
    release_tag = (
        github_ref.removeprefix("refs/tags/") if github_ref.startswith("refs/tags/") else ""
    )

    if _VERSION.match(release_tag):
        if pinned != release_tag:
            errors.append(
                f"release {release_tag} must ship with .env.core.example pinned to {release_tag} (found {pinned})"
            )
    else:
        latest = _latest_release_tag()
        if latest is None:
            print("note: no release tags reachable; skipping lineage comparison")
        elif _parse(pinned) < _parse(latest):
            errors.append(
                f"default pin {pinned} is older than the newest release {latest}; "
                "bump .env.core.example and the operator docs"
            )

    if errors:
        print("Core image pin drift detected:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(
        f"OK: operator image pin {pinned} aligned (.env.core.example ↔ README ↔ self-host guides)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
