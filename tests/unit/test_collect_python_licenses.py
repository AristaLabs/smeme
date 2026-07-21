"""Smoke tests for Core notice harvest used by Dockerfile.core / LR-06."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def test_collect_python_licenses_writes_manifest(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    venv = root / ".venv"
    if not venv.exists():
        return

    script = root / "scripts" / "collect_python_licenses.py"
    out = tmp_path / "licenses"
    argv = ["collect_python_licenses.py", str(venv), str(out)]
    old_argv = sys.argv
    try:
        sys.argv = argv
        runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv = old_argv

    manifest = out / "MANIFEST.tsv"
    assert manifest.is_file()
    lines = manifest.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].startswith("package\tversion\tpath\tsha256")
    assert len(lines) > 10
