"""Tests for the D024 retired-namespace source scanner."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / ("check_no_" + "q" + "nr" + "_product_refs.py")

spec = importlib.util.spec_from_file_location("legacy_namespace_gate", SCRIPT)
assert spec is not None
assert spec.loader is not None
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def test_scanner_rejects_legacy_content_and_path(tmp_path: Path) -> None:
    legacy = "q" + "nr"
    smeme = tmp_path / "smeme"
    smeme.mkdir()
    (smeme / "clean.py").write_text(f"value = '{legacy}_id'\n", encoding="utf-8")
    (smeme / legacy).mkdir()
    (smeme / legacy / "module.py").write_text("value = 1\n", encoding="utf-8")

    violations = gate.scan_source_tree(tmp_path)

    assert any("clean.py" in item for item in violations)
    assert any("path contains retired namespace" in item for item in violations)


def test_scanner_excludes_historical_archaeology(tmp_path: Path) -> None:
    legacy = "q" + "nr"
    historical = tmp_path / "docs" / "historical"
    historical.mkdir(parents=True)
    (historical / "old.md").write_text(legacy, encoding="utf-8")

    assert gate.scan_source_tree(tmp_path) == []


def test_structural_gate_references_are_not_product_hits() -> None:
    text = f"{gate.GATE_TARGET}:\n\tpython {gate.GATE_SCRIPT}\n"
    assert gate._scan_text("Makefile", text) == []
