"""Simple logging configuration."""

import logging

from smeme.core.config import settings


def _parse_log_level(name: str) -> int:
    level = getattr(logging, name.strip().upper(), None)
    return level if isinstance(level, int) else logging.WARNING


def setup_logging() -> None:
    """Configure application logging."""
    root_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    # ``force=True``: uvicorn configures logging before lifespan; without this, root often ends up
    # with multiple StreamHandlers and every propagated record (e.g. SQL) prints twice.
    logging.basicConfig(
        level=root_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
    )
    # Echoed SQL uses this logger at INFO; cap it so DEBUG=true does not flood the console.
    logging.getLogger("sqlalchemy.engine").setLevel(_parse_log_level(settings.sqlalchemy_log_level))


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)
