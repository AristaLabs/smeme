"""Unit tests for scripts/validate_agent_skills.py (skills source)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import validate_agent_skills as validator


def test_validate_agent_skills_tree_passes_on_repo_skills() -> None:
    assert validator.validate_agent_skills_tree() == []


def test_check_skills_agent_safe_vocabulary_passes_on_repo_skills() -> None:
    assert validator._check_skills_agent_safe_vocabulary() == []


def test_check_skills_agent_safe_vocabulary_rejects_z3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_skill = tmp_path / "smeme-reasoning-plugin" / "SKILL.md"
    bad_skill.parent.mkdir(parents=True)
    bad_skill.write_text("Use Z3 for reasoning.\n", encoding="utf-8")
    monkeypatch.setattr(validator, "SKILLS_SRC", tmp_path)
    monkeypatch.setattr(validator, "_SKILL_NAMES", ("smeme-reasoning-plugin",))
    errors = validator._check_skills_agent_safe_vocabulary()
    assert any("Z3" in msg for msg in errors)


def test_check_skills_agent_safe_vocabulary_allows_wire_ids_in_backticks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = tmp_path / "smeme-reasoning-plugin" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "When `satisfiable` is false, read `blockers.code`.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(validator, "SKILLS_SRC", tmp_path)
    monkeypatch.setattr(validator, "_SKILL_NAMES", ("smeme-reasoning-plugin",))
    assert validator._check_skills_agent_safe_vocabulary() == []


def test_main_exit_zero_on_valid_tree() -> None:
    assert validator.main() == 0
