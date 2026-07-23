"""Tavily search client dependency injection.

Provides web search capabilities for agentic decision-tree generation.
"""

from functools import lru_cache

from tavily import AsyncTavilyClient

from smeme.core.config import settings


class TavilyNotConfiguredError(Exception):
    """Raised when Tavily API key is not configured."""


@lru_cache(maxsize=1)
def get_tavily_client() -> AsyncTavilyClient:
    """
    Get Tavily client (cached singleton).

    Why singleton?
    - Tavily client can be reused across requests
    - Connection pooling built in
    - Creating per-request is wasteful

    Why lru_cache?
    - FastAPI best practice for singleton dependencies
    - Can be overridden in tests via app.dependency_overrides
    - Only creates one instance across entire application

    Raises:
        TavilyNotConfiguredError: If TAVILY_API_KEY is not set

    Returns:
        AsyncTavilyClient: Configured Tavily client singleton
    """
    if not settings.tavily_api_key:
        raise TavilyNotConfiguredError(
            "TAVILY_API_KEY not configured. "
            "Set it in .env to enable agentic decision-tree generation with web search."
        )

    return AsyncTavilyClient(api_key=settings.tavily_api_key)


def is_tavily_configured() -> bool:
    """Check if Tavily API key is configured."""
    return settings.tavily_api_key is not None
