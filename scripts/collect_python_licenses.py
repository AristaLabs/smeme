#!/usr/bin/env python3
"""Collect license/notice files from an installed Python environment.

Usage:
  scripts/collect_python_licenses.py <venv-or-site-packages> <output-dir>

Writes:
  <output-dir>/<dist-name>/...  copied license files
  <output-dir>/MANIFEST.tsv     package, version, relative path, sha256
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

LICENSE_NAME_RE = re.compile(
    r"(?i)^(license|licence|copying|notice|authors|copyright)([.-].*)?$"
)


def find_site_packages(root: Path) -> Path:
    if root.name == "site-packages" and root.is_dir():
        return root
    matches = sorted(root.glob("lib/python*/site-packages"))
    if not matches:
        raise SystemExit(f"No site-packages under {root}")
    return matches[-1]


def is_license_path(path: Path) -> bool:
    name = path.name
    if LICENSE_NAME_RE.match(name):
        return True
    # dist-info/licenses/ trees
    return "licenses" in path.parts and path.is_file()


def dist_name_from_dist_info(dist_info: Path) -> tuple[str, str]:
    # e.g. z3_solver-4.16.0.0.dist-info
    stem = dist_info.name.removesuffix(".dist-info")
    if "-" not in stem:
        return stem, ""
    name, version = stem.rsplit("-", 1)
    return name, version


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)

    site = find_site_packages(Path(sys.argv[1]).resolve())
    out = Path(sys.argv[2]).resolve()
    out.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, str, str, str]] = []

    for dist_info in sorted(site.glob("*.dist-info")):
        pkg, version = dist_name_from_dist_info(dist_info)
        candidates: list[Path] = []
        for path in dist_info.rglob("*"):
            if path.is_file() and is_license_path(path):
                candidates.append(path)
        # Also top-level package dirs sometimes ship LICENSE next to code
        # (skip huge trees; only immediate LICENSE* beside import roots is rare)

        if not candidates:
            continue

        dest_root = out / pkg
        dest_root.mkdir(parents=True, exist_ok=True)
        for src in candidates:
            rel = src.relative_to(dist_info)
            dest = dest_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = src.read_bytes()
            dest.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            rows.append((pkg, version, f"{pkg}/{rel.as_posix()}", digest))

    manifest = out / "MANIFEST.tsv"
    with manifest.open("w", encoding="utf-8") as fh:
        fh.write("package\tversion\tpath\tsha256\n")
        for row in rows:
            fh.write("\t".join(row) + "\n")

    print(f"Collected {len(rows)} license files from {site} into {out}")


if __name__ == "__main__":
    main()
