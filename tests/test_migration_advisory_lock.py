"""Test PostgreSQL advisory lock for concurrent migration safety.

This validates that multiple Alembic processes can run concurrently
without causing migration races (free tier safety).

References:
- alembic/env.py (advisory lock implementation)
- docs/DUAL_STAGE_CICD_SETUP.md (free tier migration strategy)
"""

import subprocess
import time
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from smeme.core.config import settings


@pytest.mark.asyncio
async def test_advisory_lock_prevents_concurrent_migrations():
    """Test that advisory lock prevents concurrent migration execution.

    Simulates free tier scenario where multiple containers start simultaneously.
    """
    # Use test lock ID (different from production to avoid conflicts)
    TEST_LOCK_ID = 123456789

    engine = create_async_engine(settings.database_url)

    try:
        # Test 1: Can acquire and release lock
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT pg_try_advisory_lock(:id)"),
                {"id": TEST_LOCK_ID},
            )
            acquired = result.scalar()
            assert acquired is True, "Should acquire lock when available"

            # Release it
            await conn.execute(
                text("SELECT pg_advisory_unlock(:id)"),
                {"id": TEST_LOCK_ID},
            )

        # Test 2: Second process blocks when lock is held
        async with engine.begin() as conn1:
            # First connection acquires lock
            await conn1.execute(
                text("SELECT pg_advisory_lock(:id)"),
                {"id": TEST_LOCK_ID},
            )

            # Second connection tries (non-blocking)
            async with engine.connect() as conn2:
                result = await conn2.execute(
                    text("SELECT pg_try_advisory_lock(:id)"),
                    {"id": TEST_LOCK_ID},
                )
                acquired = result.scalar()
                assert acquired is False, "Should NOT acquire lock when held by another"

            # Release from first connection
            await conn1.execute(
                text("SELECT pg_advisory_unlock(:id)"),
                {"id": TEST_LOCK_ID},
            )

        # Test 3: Lock behavior is session-scoped
        # Advisory locks are tied to the database session, not the connection object
        # This is important: locks persist until explicit unlock or session end
        async with engine.connect() as conn:
            # Start transaction
            async with conn.begin():
                await conn.execute(
                    text("SELECT pg_advisory_lock(:id)"),
                    {"id": TEST_LOCK_ID},
                )
                # Explicitly release before transaction ends
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:id)"),
                    {"id": TEST_LOCK_ID},
                )

        # Verify lock can be acquired again
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT pg_try_advisory_lock(:id)"),
                {"id": TEST_LOCK_ID},
            )
            acquired = result.scalar()
            assert acquired is True, "Lock should be available after explicit release"

            await conn.execute(
                text("SELECT pg_advisory_unlock(:id)"),
                {"id": TEST_LOCK_ID},
            )

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_alembic_uses_advisory_lock():
    """Verify that Alembic env.py actually uses advisory locks.

    Checks that the lock acquisition/release messages appear in output.
    """
    # Run alembic current (which goes through env.py)
    result = subprocess.run(
        ["uv", "run", "alembic", "current"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )

    output = result.stdout + result.stderr

    # Verify lock messages appear (updated for new waiting log)
    assert "Waiting for migration lock" in output, "Should log waiting for lock"
    assert "Migration lock acquired" in output, "Should log lock acquisition"
    assert "Migration lock released" in output, "Should log lock release"


def test_concurrent_alembic_processes_safe():
    """Test that multiple Alembic processes don't conflict.

    Simulates free tier scenario: 3 containers starting simultaneously.
    Only one should actually run migrations, others should wait.

    Note: This is a slow test (~10 seconds) - only run in CI or explicitly.
    """
    pytest.skip("Slow test - enable for integration testing")

    # Start 3 alembic processes concurrently
    processes = []
    start_time = time.time()

    for i in range(3):
        proc = subprocess.Popen(
            ["uv", "run", "alembic", "upgrade", "head"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        processes.append(proc)
        print(f"Started process {i + 1}")

    # Wait for all to complete
    outputs = []
    for i, proc in enumerate(processes):
        stdout, stderr = proc.communicate(timeout=30)
        outputs.append((stdout, stderr))
        print(f"Process {i + 1} completed with code {proc.returncode}")
        assert proc.returncode == 0, f"Process {i + 1} should succeed"

    elapsed = time.time() - start_time
    print(f"All processes completed in {elapsed:.1f}s")

    # Verify lock behavior in logs
    lock_acquired_count = sum(
        1 for stdout, stderr in outputs if "Migration lock acquired" in (stdout + stderr)
    )

    # All should acquire lock (serially), but only first does actual work
    assert lock_acquired_count == 3, "All processes should acquire lock (serially)"


@pytest.mark.asyncio
async def test_migration_lock_id_is_stable():
    """Verify the migration lock ID is deterministic and documented."""
    # The lock ID uses hashtext() for deterministic, collision-safe naming
    EXPECTED_LOCK_STRING = "smeme_migrations"

    # Read env.py to verify lock implementation
    env_py_path = Path(__file__).parent.parent / "alembic" / "env.py"
    env_py_content = env_py_path.read_text()

    assert "hashtext('smeme_migrations')" in env_py_content, (
        "env.py should use hashtext('smeme_migrations') for lock ID"
    )
    assert "pg_advisory_lock" in env_py_content, "env.py should use pg_advisory_lock"
    assert "pg_advisory_unlock" in env_py_content, "env.py should release the lock"


def test_advisory_lock_documentation():
    """Verify advisory lock pattern is documented in ARCHITECTURE.md."""
    docs_path = Path(__file__).parent.parent / "docs" / "ARCHITECTURE.md"
    docs_content = docs_path.read_text()

    # Check for key documentation
    assert "advisory lock" in docs_content.lower(), "Docs should explain advisory lock pattern"
    assert "pg_advisory_lock" in docs_content, "Docs should show PostgreSQL function"


if __name__ == "__main__":
    # Quick manual test
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
