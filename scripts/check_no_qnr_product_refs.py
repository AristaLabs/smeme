#!/usr/bin/env python3
"""D024 gate for the retired pre-public artifact namespace.

Default mode scans the active source tree. ``--image`` exports a built Core
container filesystem and applies the same path/content checks to shipped
product files. Historical documentation is excluded only in source-tree mode.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEGACY = "q" + "nr"

CONTENT_PATTERN = re.compile(rf"(?i){LEGACY}")
PATH_PATTERN = re.compile(rf"(?i){LEGACY}")

SCAN_ROOTS = (
    "smeme",
    "tests",
    "scripts",
    "alembic",
    "agent-skills",
    "docs",
    ".github",
)
SCAN_FILES = (
    "Makefile",
    "CLAUDE.md",
    "claude.md",
    "README.md",
    "CONTRIBUTING.md",
    "pyproject.toml",
    "Dockerfile",
    "Dockerfile.core",
    "start.sh",
    "start-core.sh",
    "alembic.ini",
    "cloud-overlay-paths.json",
)
IMAGE_PREFIXES = (
    "app/smeme/",
    "app/alembic/",
    "app/agent-skills/",
)
SKIP_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".venv",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "historical",
    "build",
}
SKIP_SUFFIXES = {
    ".pyc",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".zip",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".pdf",
    ".sqlite3",
    ".db",
    ".so",
}

# The gate's mandated public command/path necessarily contains the retired token.
GATE_SCRIPT = f"scripts/check_no_{LEGACY}_product_refs.py"
GATE_TARGET = f"check-no-{LEGACY}"
PATH_EXCEPTIONS = {GATE_SCRIPT}
STRUCTURAL_REFERENCE_FILES = {
    "Makefile",
    ".github/workflows/ci-core.yml",
    "docs/operations/decision-tree-release-cutover.md",
}

# Canonical public Core does not ship the superseding private ADR.
CONTENT_ALLOWLIST_EXACT: dict[str, int] = {}


def _normalize_structural_references(rel: str, text: str) -> str:
    if rel == GATE_SCRIPT:
        return ""
    if rel in STRUCTURAL_REFERENCE_FILES:
        return text.replace(GATE_SCRIPT, "scripts/check_legacy_product_refs.py").replace(
            GATE_TARGET, "check-no-legacy"
        )
    return text


def _scan_text(rel: str, text: str) -> list[str]:
    normalized = _normalize_structural_references(rel, text)
    matches = list(CONTENT_PATTERN.finditer(normalized))
    expected = CONTENT_ALLOWLIST_EXACT.get(rel)
    if expected is not None:
        if len(matches) == expected:
            return []
        return [f"{rel}: expected exactly {expected} legacy references, found {len(matches)}"]
    if not matches:
        return []

    lines = normalized.splitlines()
    bad_lines = [
        str(index) for index, line in enumerate(lines, start=1) if CONTENT_PATTERN.search(line)
    ]
    preview = ", ".join(bad_lines[:8])
    if len(bad_lines) > 8:
        preview += ", ..."
    return [f"{rel}: legacy product references at lines {preview}"]


def _scan_path_and_bytes(rel: str, data: bytes) -> list[str]:
    violations: list[str] = []
    if PATH_PATTERN.search(rel) and rel not in PATH_EXCEPTIONS:
        violations.append(f"{rel}: path contains retired namespace")
        return violations
    if Path(rel).suffix.lower() in SKIP_SUFFIXES or b"\x00" in data[:8192]:
        return violations
    text = data.decode("utf-8", errors="replace")
    violations.extend(_scan_text(rel, text))
    return violations


def _iter_source_files(root: Path) -> Iterable[Path]:
    for name in SCAN_FILES:
        path = root / name
        if path.is_file():
            yield path
    for root_name in SCAN_ROOTS:
        base = root / root_name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if any(part in SKIP_DIR_NAMES for part in rel.parts):
                continue
            yield path


def scan_source_tree(root: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(set(_iter_source_files(root))):
        rel = path.relative_to(root).as_posix()
        try:
            data = path.read_bytes()
        except OSError as exc:
            violations.append(f"{rel}: unreadable ({exc})")
            continue
        violations.extend(_scan_path_and_bytes(rel, data))
    return violations


def scan_image(image: str) -> list[str]:
    violations: list[str] = []
    create = subprocess.run(
        ["docker", "create", image],
        check=False,
        capture_output=True,
        text=True,
    )
    if create.returncode != 0:
        detail = create.stderr.strip() or create.stdout.strip()
        return [f"image {image}: docker create failed: {detail}"]
    container_id = create.stdout.strip()

    try:
        with tempfile.TemporaryDirectory(prefix="smeme-zero-legacy-") as tmp:
            archive = Path(tmp) / "rootfs.tar"
            export = subprocess.run(
                ["docker", "export", "--output", str(archive), container_id],
                check=False,
                capture_output=True,
                text=True,
            )
            if export.returncode != 0:
                detail = export.stderr.strip() or export.stdout.strip()
                return [f"image {image}: docker export failed: {detail}"]

            with tarfile.open(archive) as rootfs:
                for member in rootfs:
                    rel = member.name.removeprefix("./").lstrip("/")
                    if not any(rel.startswith(prefix) for prefix in IMAGE_PREFIXES):
                        continue
                    product_rel = rel.removeprefix("app/")
                    if member.isdir():
                        if PATH_PATTERN.search(product_rel):
                            violations.append(
                                f"image {image}: {product_rel}: path contains retired namespace"
                            )
                        continue
                    if not member.isfile():
                        continue
                    stream = rootfs.extractfile(member)
                    if stream is None:
                        violations.append(f"image {image}: unable to read {product_rel}")
                        continue
                    violations.extend(
                        f"image {image}: {item}"
                        for item in _scan_path_and_bytes(product_rel, stream.read())
                    )
    except (OSError, tarfile.TarError) as exc:
        violations.append(f"image {image}: unable to inspect filesystem: {exc}")
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_id],
            check=False,
            capture_output=True,
            text=True,
        )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="also scan a built Core image")
    args = parser.parse_args(argv)

    violations = scan_source_tree(ROOT)
    if args.image:
        violations.extend(scan_image(args.image))

    if violations:
        print("\n".join(violations), file=sys.stderr)
        print(
            "\nERROR: retired-namespace gate violated.",
            file=sys.stderr,
        )
        return 1

    target = f" and image {args.image}" if args.image else ""
    print(f"D024 retired-namespace gate: source tree{target} clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
