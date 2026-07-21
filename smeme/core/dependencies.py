"""Centralized FastAPI dependencies for the entire application.

This module serves as a dependency hub, re-exporting commonly used dependencies
from their respective modules for convenient import by routes.

Benefits:
- Single import location for routes
- Easier to refactor/change implementations
- Clear dependency inventory
- Follows FastAPI 2025 pattern of centralized dependency management
"""

from typing import Annotated

from fastapi import Depends
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from tavily import AsyncTavilyClient

from smeme.auth.manager import UserManager
from smeme.auth.manager import get_user_manager as _get_user_manager

# Auth dependencies
from smeme.auth.users import (
    current_active_user as _current_active_user,
)
from smeme.auth.users import (
    current_active_verified_user as _current_active_verified_user,
)
from smeme.auth.users import (
    current_superuser as _current_superuser,
)
from smeme.auth.users import (
    get_current_user_optional as _get_current_user_optional,
)

# Database dependencies
from smeme.core.database import get_db as _get_db
from smeme.core.llm import get_openai_client as _get_openai_client
from smeme.core.models import User
from smeme.core.search import get_tavily_client as _get_tavily_client

# ============================================================================
# Type Aliases for Annotated Dependencies (FastAPI 2025 Pattern)
# ============================================================================

# Database session
AsyncSessionDep = Annotated[AsyncSession, Depends(_get_db)]

# OpenAI client
OpenAIClientDep = Annotated[AsyncOpenAI, Depends(_get_openai_client)]

# Tavily client (web search for agentic generation)
TavilyClientDep = Annotated[AsyncTavilyClient, Depends(_get_tavily_client)]

# User authentication
CurrentUser = Annotated[User, Depends(_current_active_user)]
CurrentVerifiedUser = Annotated[User, Depends(_current_active_verified_user)]
CurrentSuperuser = Annotated[User, Depends(_current_superuser)]
OptionalUser = Annotated[User | None, Depends(_get_current_user_optional)]

# User manager (for password/email operations)
UserManagerDep = Annotated[UserManager, Depends(_get_user_manager)]

# ============================================================================
# Legacy/Backward Compatibility (can be removed once all routes migrated)
# ============================================================================

# Re-export functions for routes that haven't migrated to Annotated pattern
get_db = _get_db
get_openai_client = _get_openai_client
get_tavily_client = _get_tavily_client
current_active_user = _current_active_user
current_active_verified_user = _current_active_verified_user
current_superuser = _current_superuser
get_current_user_optional = _get_current_user_optional

__all__ = [
    # Type aliases (preferred, FastAPI 2025)
    "AsyncSessionDep",
    "OpenAIClientDep",
    "TavilyClientDep",
    "CurrentUser",
    "CurrentVerifiedUser",
    "CurrentSuperuser",
    "OptionalUser",
    "UserManagerDep",
    # Function exports (legacy)
    "get_db",
    "get_openai_client",
    "get_tavily_client",
    "current_active_user",
    "current_active_verified_user",
    "current_superuser",
    "get_current_user_optional",
]
