"""OpenAI client dependency injection."""

from functools import lru_cache

from openai import AsyncOpenAI

from smeme.core.config import settings


@lru_cache(maxsize=1)
def get_openai_client() -> AsyncOpenAI:
    """
    Get OpenAI client (cached singleton).

    Why singleton?
    - OpenAI client is thread-safe and can be reused
    - Connection pooling built into httpx (underlying library)
    - Creating per-request is wasteful

    Why lru_cache?
    - FastAPI best practice for singleton dependencies
    - Can be overridden in tests via app.dependency_overrides
    - Only creates one instance across entire application

    Official guidance:
    - FastAPI: Use @lru_cache for singleton dependencies
    - OpenAI SDK: Client is thread-safe, reuse across requests
    - LangGraph: Pass runtime dependencies via config["configurable"]

    Returns:
        AsyncOpenAI: Configured OpenAI client singleton
    """
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not configured. Enable AI generation with a valid key, "
            "or set SMEME_AI_GENERATION_ENABLED=false."
        )
    return AsyncOpenAI(
        api_key=api_key,
        timeout=30.0,
        max_retries=3,
    )
