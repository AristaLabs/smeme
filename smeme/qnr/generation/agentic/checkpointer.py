"""PostgreSQL checkpointer configuration for persistent workflow state."""

import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from smeme.core.config import settings
from smeme.core.logging import get_logger

logger = get_logger(__name__)


async def check_connection(conn: AsyncConnection) -> None:
    """Check if connection is alive with a simple query.

    This is called by the pool before returning a connection to verify
    it's still healthy. If this raises an exception, the pool will
    discard the connection and get/create a new one.
    """
    await conn.execute("SELECT 1")


class CheckpointerManager:
    """Manages the PostgreSQL checkpointer lifecycle."""

    def __init__(self) -> None:
        self._pool: AsyncConnectionPool | None = None
        self._checkpointer: AsyncPostgresSaver | None = None

    async def initialize(self) -> AsyncPostgresSaver:
        """Initialize connection pool and checkpointer.

        This should be called during application startup.
        """
        if self._checkpointer is not None:
            return self._checkpointer

        # Convert SQLAlchemy URL to psycopg format
        # Remove '+asyncpg' or other dialect suffixes from the URL
        conninfo = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

        # Create connection pool (don't open in constructor - use open() instead)
        self._pool = AsyncConnectionPool(
            conninfo=conninfo,
            min_size=2,
            max_size=10,
            timeout=30,
            max_idle=300,  # Close connections idle for 5+ minutes (helps with NeonDB timeouts)
            max_lifetime=1800,  # Replace connections after 30 mins (helps with NeonDB)
            reconnect_timeout=60,  # Retry failed connections for up to 60s
            check=check_connection,  # Validate connections on checkout
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
            },
            open=False,  # Don't open in constructor (deprecated)
        )

        # Open the pool explicitly
        await self._pool.open()

        logger.info("Initializing PostgreSQL checkpointer connection pool")

        # Create checkpointer with pool
        self._checkpointer = AsyncPostgresSaver(self._pool)

        # Set up checkpoint tables (idempotent)
        async with self._pool.connection() as _:
            await self._checkpointer.setup()

        logger.info("PostgreSQL checkpointer initialized successfully")

        return self._checkpointer

    async def get_checkpointer(self) -> AsyncPostgresSaver:
        """Get the initialized checkpointer.

        Raises:
            RuntimeError: If checkpointer not initialized
        """
        if self._checkpointer is None:
            msg = "Checkpointer not initialized. Call initialize() during startup."
            raise RuntimeError(msg)
        return self._checkpointer

    async def shutdown(self) -> None:
        """Close connection pool gracefully."""
        if self._pool:
            logger.info("Closing PostgreSQL checkpointer connection pool")
            await self._pool.close()
            self._pool = None
            self._checkpointer = None

    async def delete_checkpoints_for_thread(self, thread_id: str) -> int:
        """Delete all LangGraph checkpoint data for a thread.

        Removes rows from checkpoint_blobs, checkpoint_writes, and checkpoints
        so derived text and workflow state are cleaned up when a generation
        completes or expires (per §4.8 / §9.3).

        Args:
            thread_id: LangGraph thread ID (matches checkpoints.thread_id)

        Returns:
            Total rows deleted across all tables
        """
        if self._pool is None:
            logger.warning("Checkpointer pool not initialized, skipping checkpoint cleanup")
            return 0

        table_allowlist = ("checkpoint_blobs", "checkpoint_writes", "checkpoints")

        async def _delete_table(table: str) -> int:
            try:
                async with self._pool.connection() as conn:
                    cur = await conn.execute(
                        f"DELETE FROM {table} WHERE thread_id = %s",
                        (thread_id,),
                    )
                    return cur.rowcount
            except Exception as e:
                logger.debug("Checkpoint cleanup: %s (may not exist): %s", table, e)
                return 0

        counts = await asyncio.gather(*(_delete_table(t) for t in table_allowlist))
        total = sum(counts)

        if total > 0:
            logger.debug("Deleted %d checkpoint rows for thread %s", total, thread_id)
        return total

    async def delete_orphaned_checkpoints(self) -> int:
        """Delete checkpoint rows with no matching in_progress_qnr_generations row.

        Compensates for rare failures where generation rows were removed but
        LangGraph checkpoint blobs remained (account delete, deferred abandon).

        Returns:
            Total rows deleted across all checkpoint tables
        """
        if self._pool is None:
            logger.warning("Checkpointer pool not initialized, skipping orphan checkpoint cleanup")
            return 0

        table_allowlist = ("checkpoint_blobs", "checkpoint_writes", "checkpoints")

        async def _delete_orphans(table: str) -> int:
            try:
                async with self._pool.connection() as conn:
                    cur = await conn.execute(
                        f"""
                        DELETE FROM {table} c
                        WHERE NOT EXISTS (
                            SELECT 1 FROM in_progress_qnr_generations g
                            WHERE g.langgraph_thread_id = c.thread_id
                        )
                        """
                    )
                    return cur.rowcount
            except Exception as e:
                logger.debug("Orphan checkpoint cleanup: %s (may not exist): %s", table, e)
                return 0

        counts = await asyncio.gather(*(_delete_orphans(t) for t in table_allowlist))
        total = sum(counts)

        if total > 0:
            logger.info("Deleted %d orphan checkpoint rows", total)
        return total


# Global instance
checkpointer_manager = CheckpointerManager()
