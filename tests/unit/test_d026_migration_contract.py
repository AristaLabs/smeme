"""D026 migration adds nullable legal audit columns without backfill."""

from __future__ import annotations

from pathlib import Path


def test_d026_migration_file_is_additive_only():
    path = (
        Path(__file__).resolve().parents[1]
        / ".."
        / "alembic"
        / "versions"
        / "b1d026a0cce7_d026_user_legal_acceptance_audit.py"
    )
    # parents[1] is tests/; resolve via repo root relative to this file
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "b1d026a0cce7_d026_user_legal_acceptance_audit.py"
    )
    text = path.read_text()
    assert "legal_accepted_at" in text
    assert "terms_version" in text
    assert "privacy_version" in text
    assert "nullable=True" in text
    assert "op.alter_column" not in text
    assert "UPDATE" not in text.upper()
    assert 'down_revision: Union[str, Sequence[str], None] = "a7c3e9f1b204"' in text
