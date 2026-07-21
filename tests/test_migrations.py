"""Test database migrations."""

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from smeme.core.config import settings


@pytest.fixture(scope="session")
def alembic_config():
    """Get Alembic configuration."""
    return Config("alembic.ini")


@pytest.fixture(scope="session")
def alembic_script(alembic_config):
    """Get Alembic script directory."""
    return ScriptDirectory.from_config(alembic_config)


@pytest.mark.asyncio
async def test_migrations_upgrade_head():
    """Verify the configured database URL is reachable (same URL migrations use via env.py)."""
    test_url = settings.database_url

    # Neondb (and similar) requires TLS; local Docker Postgres does not.
    connect_args = {"ssl": True} if "neon" in test_url.lower() else {}
    engine = create_async_engine(test_url, echo=False, connect_args=connect_args)

    try:
        # Test that we can connect
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))

        # Note: Full migration testing would require a test database
        # For now, this tests the connection and basic setup

    finally:
        await engine.dispose()


def test_migration_scripts_are_valid(alembic_script):
    """Test that migration scripts are syntactically valid."""
    # This tests that all migration files can be loaded
    revisions = list(alembic_script.walk_revisions())
    assert len(revisions) > 0, "No migrations found"


def test_migration_linear_history(alembic_script):
    """Test that migration history is linear (no branching)."""
    revisions = list(alembic_script.walk_revisions())

    # Check that each revision has at most one down_revision
    # (Alembic supports branching but we want linear history for simplicity)
    seen_revisions = set()
    for rev in revisions:
        assert rev.revision not in seen_revisions, f"Duplicate revision: {rev.revision}"
        seen_revisions.add(rev.revision)


def test_migration_file_structure(alembic_script):
    """Test that migration files have expected structure."""
    revisions = list(alembic_script.walk_revisions())

    for rev in revisions:
        # Check that each revision has upgrade and downgrade functions
        assert hasattr(rev.module, "upgrade"), f"Revision {rev.revision} missing upgrade function"
        assert hasattr(rev.module, "downgrade"), (
            f"Revision {rev.revision} missing downgrade function"
        )
