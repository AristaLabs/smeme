"""Database configuration and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from smeme.core.config import settings
from smeme.core.models import (  # noqa: F401
    DecisionTree,
    DecisionTreeLexiconDraft,
    DecisionTreeResearchCorpus,
    DecisionTreeSession,
    Memo,
    ReasoningCompiledArtifact,
    ReasoningEvaluationRun,
    User,
)

# Import all models so Alembic autogenerate can detect them
# IMPORTANT: Alembic env.py imports this module, so these imports ensure
# all models are registered with metadata before autogenerate runs.

# Determine pool configuration based on environment
# Development: Smaller pool (local Docker postgres)
# Staging/Production: Larger pool (Neon serverless)
if settings.is_production:
    pool_config = {
        "pool_size": 20,  # Persistent connections
        "max_overflow": 40,  # Additional burst connections
    }
elif settings.environment.lower() == "staging":
    pool_config = {
        "pool_size": 10,
        "max_overflow": 20,
    }
else:  # development
    pool_config = {
        "pool_size": 5,
        "max_overflow": 10,
    }

# Hosted PostgreSQL requires TLS; local Docker PostgreSQL may reject SSL upgrade.
_db_url_lower = settings.database_url.lower()
_requires_ssl = (
    "neon" in _db_url_lower or settings.is_production or settings.environment.lower() == "staging"
)
_connect_args: dict = {
    "server_settings": {
        "application_name": "smeme_platform",
    },
}
if _requires_ssl:
    _connect_args["ssl"] = True

# Create async engine with connection pooling and health checks
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
    # Transaction isolation
    isolation_level="READ COMMITTED",  # Explicit Postgres default (prevents async/migration edge cases)
    # Connection pool settings (prevent exhaustion)
    **pool_config,
    pool_pre_ping=True,  # Test connection health before use (important for Neon)
    pool_recycle=3600,  # Recycle connections after 1 hour (handles Neon auto-suspend)
    connect_args=_connect_args,
)

# Create async session factory
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency to get database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
