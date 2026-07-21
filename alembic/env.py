"""Alembic environment configuration."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from smeme.core.config import settings

# Import all models to ensure they're registered with SQLModel metadata
from smeme.core.models import (  # noqa: F401
    BaseSQLModel,
    Memo,
    QNR,
    QNRSession,
    ReasoningCompiledArtifact,
    ReasoningEvaluationRun,
    User,
    UserAuditLog,
)
from smeme.mcp.models import McpToolInvocation  # noqa: F401
from smeme.qnr.models import InProgressQNRGeneration  # noqa: F401

# SAAS-ONLY: present in private overlay / monorepo; optional in public Core image (D023).
try:
    from smeme.landing.models import TeamsWaitlistSignup  # noqa: F401
except ModuleNotFoundError:
    TeamsWaitlistSignup = None  # type: ignore[misc, assignment]

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# Use BaseSQLModel.metadata which has naming conventions applied
target_metadata = BaseSQLModel.metadata


def include_object(object, name, type_, reflected, compare_to):
    """Exclude non-SQLModel tables from autogenerate.

    Autogenerate compares DB schema to SQLModel metadata. Tables that exist
    in the DB but are NOT defined as SQLModel models get flagged for removal.
    Excluding them prevents Alembic from suggesting op.drop_table() for them.

    Excluded:
    - checkpoint_* : Managed by LangGraph's AsyncPostgresSaver.setup()
    - stripe_events: Created in migration bb8be63 for webhook idempotency; not a SQLModel table
    """
    # Ignore checkpoint tables (managed by LangGraph)
    if type_ == "table" and name in (
        "checkpoints",
        "checkpoint_writes",
        "checkpoint_migrations",
        "checkpoint_blobs",
    ):
        return False

    # Ignore raw tables not in SQLModel metadata (see LESSONS_LEARNED: Autogenerate Drops Tables)
    if type_ == "table" and name == "stripe_events":
        return False

    # Ignore indexes on checkpoint tables
    if (
        type_ == "index"
        and name
        and any(
            checkpoint_table in name
            for checkpoint_table in ["checkpoints", "checkpoint_writes", "checkpoint_blobs"]
        )
    ):
        return False

    return True


def render_item(type_, obj, autogen_context):
    """Custom renderer to ensure sqlmodel is imported in migrations."""
    # Detect if SQLModel types are used and add import
    if "sqlmodel" in str(type(obj)):
        autogen_context.imports.add("import sqlmodel")
    return False  # Return False to use default rendering


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = str(settings.database_url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with a connection.

    Uses PostgreSQL advisory lock to prevent concurrent migrations on free tier.
    Lock is held for the entire migration duration (prevents races).

    Lock ID is deterministic (hashtext('smeme_migrations')) to prevent collisions
    with other apps sharing the same database.
    """
    print("⏳ Waiting for migration lock (another container may be migrating)...")

    # Acquire advisory lock (BLOCKING - waits if another process holds it)
    # This is CRITICAL: lock must be held during entire migration
    # Uses hashtext() for deterministic, collision-safe, self-documenting lock ID
    connection.execute(text("SELECT pg_advisory_lock(hashtext('smeme_migrations'))"))

    print("✅ Migration lock acquired - proceeding with migrations")

    try:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_item=render_item,  # Use custom renderer
            include_object=include_object,  # Exclude LangGraph tables
        )

        with context.begin_transaction():
            context.run_migrations()

    finally:
        # Always release lock (even if migration fails)
        connection.execute(text("SELECT pg_advisory_unlock(hashtext('smeme_migrations'))"))
        print("🔓 Migration lock released")


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async support."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = str(settings.database_url)

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        # CRITICAL: Explicitly commit the transaction
        # Without this, async context manager auto-rolls back on exit
        await connection.commit()

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
