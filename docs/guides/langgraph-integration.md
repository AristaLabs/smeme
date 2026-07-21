# LangGraph Integration Guide

## Overview

This guide explains how to add LangGraph-driven features to the smeme_v2 project. It documents the architectural decisions, design patterns, and best practices established while building the QNR (Questionnaire) feature.

## Table of Contents

1. [Tech Stack](#tech-stack)
2. [Project Structure](#project-structure)
3. [Core Design Principles](#core-design-principles)
4. [LangGraph Integration Patterns](#langgraph-integration-patterns)
5. [Database Session Management](#database-session-management)
6. [External Client Management (OpenAI, etc.)](#external-client-management-openai-etc)
7. [Centralized Dependency Management](#centralized-dependency-management)
8. [State Management](#state-management)
9. [Route Integration](#route-integration)
10. [HTMX Integration](#htmx-integration)
11. [Pydantic V2 Usage Patterns](#pydantic-v2-usage-patterns)
12. [Authentication](#authentication)
13. [Database Models & Migrations](#database-models--migrations)
14. [SQLAlchemy Relationships & Cascade Rules](#sqlalchemy-relationships--cascade-rules)
15. [Common Pitfalls](#common-pitfalls)
16. [Step-by-Step Implementation](#step-by-step-implementation)
17. [Design Limitations & Constraints](#design-limitations--constraints)
18. [Performance Considerations](#performance-considerations)
19. [Structured Logging](#structured-logging)
20. [LangSmith Integration](#langsmith-integration)
21. [Linter & Formatter Configuration](#linter--formatter-configuration)
22. [Debugging Tips](#debugging-tips)
23. [Human-in-the-Loop with `interrupt_before`](#human-in-the-loop-with-interrupt_before-november-30-2025)
24. [Explicit Phase Tracking (Sprint 6)](#24-explicit-phase-tracking-sprint-6)
25. [Standardized Interrupt Payloads (Sprint 6)](#25-standardized-interrupt-payloads-sprint-6)
26. [Workflow Versioning (Sprint 6)](#26-workflow-versioning-sprint-6)

---

## Tech Stack

### Backend Core
- **FastAPI**: Modern async web framework
- **Pydantic V2**: Data validation, settings management, type safety
  - All API request/response models
  - Application settings (`smeme/core/config.py`)
  - Type hints and validation throughout
- **SQLModel**: ORM combining SQLAlchemy 2.0 + Pydantic
  - Database models inherit from both SQLModel and Pydantic
  - Automatic API serialization from DB models
- **PostgreSQL**: Primary database with JSONB support
- **Alembic**: Database migrations
- **FastAPI-Users**: Complete authentication solution
  - User registration, login, logout
  - Cookie-based session management
  - Password hashing (bcrypt)
  - User management utilities
- **LangGraph**: AI workflow orchestration & LLM validation
  - Conditional routing for validation retry logic
  - Multi-stage validation workflows
  - State management for complex LLM interactions
- **OpenAI SDK**: Direct LLM integration
  - Native Pydantic structured outputs
  - Simple, minimal dependency approach

### Frontend
- **HTMX**: Dynamic UI interactions without JavaScript
- **Jinja2**: Server-side templating
- **Tailwind CSS**: Utility-first styling

### Supporting Libraries
- **asyncpg**: Async PostgreSQL driver
- **aiocache**: Caching layer (in-memory, Redis-ready)
- **Python 3.11+**: Modern Python features (async, type hints)

---

## Project Structure

```
smeme_v2/
├── smeme/
│   ├── auth/              # Authentication module
│   │   ├── backend.py     # Auth backend configuration
│   │   ├── manager.py     # User manager
│   │   ├── models.py      # Auth-specific models
│   │   ├── routes.py      # Auth routes
│   │   └── users.py       # User utilities
│   │
│   ├── core/              # Core application components
│   │   ├── config.py      # Settings & configuration
│   │   ├── database.py    # Database setup
│   │   ├── dependencies.py # Shared dependencies
│   │   ├── logging.py     # Logging configuration
│   │   ├── middleware.py  # Custom middleware
│   │   └── models.py      # Shared/base models
│   │
│   ├── qnr/               # QNR feature (LangGraph example)
│   │   ├── helpers/       # Helper modules
│   │   │   ├── cache.py   # Caching utilities
│   │   │   ├── db_queries.py # Database queries
│   │   │   └── validation.py # Graph validation
│   │   ├── templates/     # QNR-specific templates
│   │   ├── models.py      # QNR data structures
│   │   ├── routes.py      # FastAPI routes
│   │   └── workflow.py    # LangGraph workflow
│   │
│   ├── templates/         # Global Jinja2 templates
│   │   ├── layouts/       # Layout templates
│   │   ├── auth/          # Auth templates
│   │   └── errors/        # Error pages
│   │
│   └── main.py           # Application entry point
│
├── alembic/              # Database migrations
│   ├── versions/         # Migration files
│   └── env.py           # Alembic configuration
│
├── docs/                # Documentation
├── scripts/             # Utility scripts
└── tests/               # Test suite
```

---

## Core Design Principles

### 1. **Separation of Concerns**
- **Routes** handle HTTP concerns (requests, responses, authentication)
- **Workflows** handle business logic (state transitions, decision making)
- **Helpers** provide reusable utilities (database queries, validation)
- **Models** define data structures (SQLModel for DB, Pydantic for API)

### 2. **Dependency Injection Pattern**
- Database sessions are created at the route level using FastAPI's `Depends()`
- Dependencies are passed to LangGraph via `RunnableConfig`, NOT via State
- Nodes extract dependencies from config, keeping State clean and serializable

### 3. **HTMX/Jinja First - No JavaScript Frameworks**
- **HTMX** for all dynamic interactions (no React, Vue, Angular)
- **Jinja2** for server-side rendering (no client-side frameworks)
- **Minimal JavaScript**: Only for HTMX event handlers when necessary
- **No Build Step**: No webpack, vite, or bundlers required
- **Progressive Enhancement**: Works without JavaScript, enhanced with it

### 4. **Async-First Architecture**
- All database operations use `AsyncSession`
- LangGraph workflows use async nodes (`async def`)
- Routes are async to support concurrent request handling

### 5. **Type Safety**
- Use type hints throughout (Python 3.11+ style: `list[str]` not `List[str]`)
- Pydantic models for validation
- SQLModel for database models
- TypedDict for structured dictionaries

### 6. **State Immutability**
- LangGraph State should be serializable (no DB sessions, no complex objects)
- State modifications create new state, don't mutate in place
- Use reducers for accumulating values (e.g., `messages: Annotated[list, add_messages]`)

### 7. **Pydantic V2 Throughout**
- **Settings Management**: All configuration via Pydantic `BaseSettings`
- **API Validation**: Request/response models are Pydantic models
- **Database Models**: SQLModel = SQLAlchemy + Pydantic (dual functionality)
- **Type Safety**: Pydantic validates data at runtime, complements static typing

### 8. **FastAPI-Users Integration**
- **Cookie-based Auth**: Stateful sessions, no JWT in headers
- **Dependency Injection**: `current_active_user` provides authenticated user
- **Middleware Integration**: Custom middleware handles unauthorized redirects
- **User Management**: Built-in registration, login, logout, password reset

### 9. **LangGraph for LLM Orchestration**
- **Validation as Nodes**: Each validation stage is a separate node in the workflow
- **Conditional Retry**: Use conditional edges to retry LLM calls on validation failure
- **Error Feedback Loop**: Pass validation errors back to LLM via state
- **Observable**: All retry attempts visible in LangSmith traces

### 10. **Code Quality & Observability**
- **Strict Linting**: Comprehensive Ruff configuration enforcing Python best practices
- **Type Checking**: MyPy with strict settings for runtime safety
- **Structured Logging**: JSON-compatible logging with context, timing, and metadata
- **Per-Workflow Loggers**: Named loggers for each workflow (e.g., `smeme.qnr.workflow`)

---

## LangGraph Integration Patterns

### Workflow Structure

```python
from langgraph.graph import StateGraph, END
from langgraph.types import RunnableConfig
from typing import TypedDict, Literal

# 1. Define State (must be serializable)
class MyWorkflowState(TypedDict):
    session_id: str
    current_step: str
    data: dict[str, str]
    html_output: str
    error: str | None

# 2. Define Node Functions
async def my_node(state: MyWorkflowState, config: RunnableConfig) -> MyWorkflowState:
    """Node functions access dependencies from config, not state."""
    # Extract dependencies from config
    db: AsyncSession = config["configurable"]["db"]
    user_id: int = config["configurable"]["user_id"]
    
    # Perform business logic
    result = await some_db_query(db, user_id)
    
    # Return only updated fields (LangGraph merges automatically)
    return {
        "data": result,
        "current_step": "next_step"
    }

# 3. Build Workflow
def build_my_workflow() -> StateGraph:
    """Build and compile the workflow graph."""
    workflow = StateGraph(MyWorkflowState)
    
    # Add nodes
    workflow.add_node("step1", my_node)
    workflow.add_node("step2", another_node)
    
    # Add edges
    workflow.add_edge("step1", "step2")
    workflow.add_edge("step2", END)
    
    # Set entry point
    workflow.set_entry_point("step1")
    
    return workflow.compile()

# 4. Invoke from Route
async def execute_workflow(
    session_id: str,
    db: AsyncSession,
    user_id: int
) -> MyWorkflowState:
    """Execute workflow with proper dependency injection."""
    graph = build_my_workflow()
    
    initial_state: MyWorkflowState = {
        "session_id": session_id,
        "current_step": "start",
        "data": {},
        "html_output": "",
        "error": None
    }
    
    # Pass dependencies via config, NOT state
    result = await graph.ainvoke(
        initial_state,
        config={
            "configurable": {
                "db": db,
                "user_id": user_id
            }
        }
    )
    
    return result
```

### Conditional Routing

```python
def route_based_on_condition(state: MyWorkflowState) -> Literal["path_a", "path_b", "end"]:
    """Routing functions only read state, no side effects."""
    if state.get("error"):
        return "end"
    elif state.get("condition_met"):
        return "path_a"
    else:
        return "path_b"

# Add conditional edge
workflow.add_conditional_edges(
    "decision_node",
    route_based_on_condition,
    {
        "path_a": "node_a",
        "path_b": "node_b",
        "end": END
    }
)
```

---

## Database Session Management

### Critical Rules

1. **NEVER pass `AsyncSession` in LangGraph State**
   - Sessions are not serializable
   - Will cause errors if workflow is persisted/resumed
   
2. **ALWAYS inject via `RunnableConfig`**
   ```python
   # ✅ CORRECT
   async def my_node(state: State, config: RunnableConfig) -> State:
       db: AsyncSession = config["configurable"]["db"]
   
   # ❌ WRONG - Don't put db in state
   class State(TypedDict):
       db: AsyncSession  # NO!
   ```

3. **Create session at route level**
   ```python
   @router.post("/workflow")
   async def workflow_route(
       db: AsyncSession = Depends(get_async_session),
       user: User = Depends(current_active_user)
   ):
       result = await execute_workflow(
           db=db,
           user_id=user.id
       )
   ```

---

## External Client Management (OpenAI, etc.)

### OpenAI Client Dependency Injection

Following the same pattern as database sessions, external API clients should be injected via FastAPI dependencies and passed through `RunnableConfig`.

#### 1. Create Singleton Client with `@lru_cache`

```python
# smeme/core/llm.py
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
    """
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=30.0,
        max_retries=3,
    )
```

**Official Guidance:**
- ✅ **FastAPI**: Use `@lru_cache` for singleton dependencies ([docs](https://fastapi.tiangolo.com/advanced/settings/))
- ✅ **OpenAI SDK**: Client is thread-safe, reuse across requests
- ✅ **LangGraph**: Pass runtime dependencies via `config["configurable"]`

#### 2. Inject in Routes

```python
# In your route
from smeme.core.llm import get_openai_client

@router.post("/generate")
async def generate_route(
    request: GenerateRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
    openai_client: AsyncOpenAI = Depends(get_openai_client),  # Cached singleton
):
    """Generate content using LLM."""
    
    result = await execute_workflow(
        db=db,
        openai_client=openai_client,
        user_id=user.id
    )
    
    return result
```

#### 3. Pass via RunnableConfig

```python
async def execute_workflow(
    db: AsyncSession,
    openai_client: AsyncOpenAI,
    user_id: int
) -> MyState:
    """Execute workflow with dependencies."""
    workflow = build_my_workflow()
    
    initial_state: MyState = {
        "user_id": user_id,
        # ... other state
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={
            "configurable": {
                "db": db,
                "openai_client": openai_client,  # Pass to nodes
                "user_id": user_id
            }
        }
    )
    
    return result
```

#### 4. Access in Workflow Nodes

```python
async def call_llm_node(state: MyState, config: RunnableConfig) -> MyState:
    """Call OpenAI to generate content."""
    # Extract dependencies from config
    openai_client: AsyncOpenAI = config["configurable"]["openai_client"]
    
    # Use client
    response = await openai_client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[...],
        response_format=MyPydanticModel,
    )
    
    return {"llm_response": response.choices[0].message.parsed}
```

### Runtime Parameter Configuration

Use a **single client singleton** and configure model/parameters at **call time** based on runtime context:

```python
# smeme/core/llm.py - ONE singleton client
@lru_cache(maxsize=1)
def get_openai_client() -> AsyncOpenAI:
    """Single OpenAI client with sensible connection defaults."""
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=30.0,
        max_retries=3,
    )

# Nodes decide model/params based on context
async def call_llm_node(state: MyState, config: RunnableConfig) -> MyState:
    """Call LLM with context-aware model selection."""
    client: AsyncOpenAI = config["configurable"]["openai_client"]
    
    # Decision logic based on state/context
    retry_count = state.get("retry_count", 0)
    is_complex = len(state.get("prompt", "")) > 1000
    
    # Smart model selection
    if retry_count >= 2 or is_complex:
        model = "gpt-4o"  # Use better model for retries/complex tasks
        temperature = 0.9
    else:
        model = "gpt-4o-mini"  # Default to cheaper model
        temperature = 0.5
    
    response = await client.beta.chat.completions.parse(
        model=model,  # Decided at runtime
        temperature=temperature,
        messages=[...],
        response_format=MyPydanticModel,
    )
    
    return {"result": response.choices[0].message.parsed}
```

**Why This Approach:**
- ✅ Single client (simpler, more efficient)
- ✅ Nodes decide based on runtime context (retry count, complexity, user tier)
- ✅ No need for multiple routes or client instances
- ✅ Can escalate model quality on retries
- ✅ Different nodes can use different models

**Passing Configuration from Route to Node:**

```python
@router.post("/generate")
async def generate(
    request: GenerateRequest,
    user: User = Depends(current_active_user),
    openai_client: AsyncOpenAI = Depends(get_openai_client),
):
    """Route can pass hints to nodes via config."""
    
    result = await workflow.ainvoke(
        initial_state,
        config={
            "configurable": {
                "openai_client": openai_client,
                "user_tier": user.subscription_tier,  # Nodes can use this
                "max_retries": 3 if user.is_premium else 2,
                "db": db,
            }
        }
    )

# In node - read hints and make decisions
async def node(state, config):
    client = config["configurable"]["openai_client"]
    user_tier = config["configurable"].get("user_tier", "free")
    
    # Use premium model for premium users
    model = "gpt-4o" if user_tier == "premium" else "gpt-4o-mini"
    
    response = await client.beta.chat.completions.parse(
        model=model,
        messages=[...]
    )
```

### Testing External Clients

```python
# tests/conftest.py
import pytest
from unittest.mock import AsyncMock

@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for testing."""
    mock = AsyncMock()
    mock.beta.chat.completions.parse.return_value = MockResponse(...)
    return mock

# In test
def test_generation(client, mock_openai_client):
    """Test generation with mocked OpenAI."""
    from smeme.core.llm import get_openai_client
    
    # Override dependency
    app.dependency_overrides[get_openai_client] = lambda: mock_openai_client
    
    response = client.post("/generate", json={...})
    
    assert response.status_code == 200
    mock_openai_client.beta.chat.completions.parse.assert_called_once()
```

### Database Operations in Nodes

```python
async def load_data_node(state: State, config: RunnableConfig) -> State:
    """Example of database query in a node."""
    db: AsyncSession = config["configurable"]["db"]
    
    # Query database
    result = await db.execute(
        select(MyModel).where(MyModel.id == state["item_id"])
    )
    item = result.scalar_one_or_none()
    
    if not item:
        return {"error": "Item not found"}
    
    return {
        "data": item.model_dump(),
        "error": None
    }
```

---

## State Management

### State Design Best Practices

1. **Keep State Flat and Simple**
   ```python
   # ✅ GOOD
   class State(TypedDict):
       user_id: str
       current_question: str
       answers: dict[str, str]
       is_complete: bool
   
   # ❌ AVOID - Complex nested objects
   class State(TypedDict):
       user: User  # SQLModel instance - not serializable!
       session: QNRSession  # SQLModel instance - not serializable!
   ```

2. **Use Primitive Types**
   - `str`, `int`, `float`, `bool`
   - `list[str]`, `dict[str, str]`
   - Avoid: SQLModel instances, datetime objects with timezones, custom classes

3. **Store IDs, Not Objects (UUID Serialization)**
   ```python
   # ✅ Store UUID as string in state
   state["session_id"] = str(session.id)  # UUID → string
   state["user_id"] = str(user.id)        # UUID → string
   
   # In node: Convert back to UUID
   from uuid import UUID
   
   db = config["configurable"]["db"]
   session_id = UUID(state["session_id"])  # string → UUID
   session = await db.get(QNRSession, session_id)
   ```
   
   **State vs Config Type Split:**
   - **State (TypedDict)**: Use strings for UUIDs (must be serializable)
     ```python
     class MyState(TypedDict):
         session_id: str  # UUID as string
         user_id: str     # UUID as string
     ```
   - **Config (RunnableConfig)**: Use actual UUID objects (not serialized)
     ```python
     config = {
         "configurable": {
             "user_id": user.id,  # Pass UUID directly
             "db": db,            # Pass objects
         }
     }
     
     # In node: Extract as UUID
     user_id: UUID = config["configurable"]["user_id"]
     ```

4. **Handle Optional Fields**
   ```python
   class State(TypedDict, total=False):
       error: str | None  # Optional field
       html_output: str   # Optional field
   ```

---

## Centralized Dependency Management

### Overview (FastAPI 2025 Best Practice)

As your application grows, managing dependencies across multiple routes becomes critical. The project uses a **centralized dependency hub** pattern where `smeme/core/dependencies.py` serves as the single source of truth for all shared dependencies.

### Why Centralize Dependencies?

**Problems with scattered dependencies:**
```python
# ❌ Route A
from smeme.auth.users import current_active_user
from smeme.core.database import get_db

# ❌ Route B  
from smeme.auth.users import current_active_user as get_user
from smeme.core.database import get_async_session

# ❌ Route C
from fastapi_users import FastAPIUsers
```

**Issues:**
- Inconsistent import patterns
- Hard to refactor
- Difficult to test (override in multiple places)
- No clear dependency inventory
- Poor IDE autocomplete

### Centralized Hub Pattern

#### File: `smeme/core/dependencies.py`

```python
"""Centralized FastAPI dependencies for the entire application."""

from typing import Annotated

from fastapi import Depends
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

# Import from source modules
from smeme.core.database import get_db as _get_db
from smeme.core.llm import get_openai_client as _get_openai_client
from smeme.auth.users import (
    current_active_user as _current_active_user,
    current_active_verified_user as _current_active_verified_user,
    current_superuser as _current_superuser,
)
from smeme.core.models import User

# ============================================================================
# Type Aliases for Annotated Dependencies (FastAPI 2025 Pattern)
# ============================================================================

# Database session
AsyncSessionDep = Annotated[AsyncSession, Depends(_get_db)]

# OpenAI client
OpenAIClientDep = Annotated[AsyncOpenAI, Depends(_get_openai_client)]

# User authentication
CurrentUser = Annotated[User, Depends(_current_active_user)]
CurrentVerifiedUser = Annotated[User, Depends(_current_active_verified_user)]
CurrentSuperuser = Annotated[User, Depends(_current_superuser)]

# ============================================================================
# Legacy/Backward Compatibility
# ============================================================================

# Re-export functions for routes that haven't migrated
get_db = _get_db
get_openai_client = _get_openai_client
current_active_user = _current_active_user

__all__ = [
    # Preferred (FastAPI 2025)
    "AsyncSessionDep",
    "OpenAIClientDep",
    "CurrentUser",
    # Legacy
    "get_db",
    "current_active_user",
]
```

### Modern Route Pattern (FastAPI 2025)

**Old verbose pattern:**
```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from smeme.auth.users import current_active_user
from smeme.core.database import get_db
from smeme.core.models import User

@router.post("/route")
async def my_route(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    pass
```

**New clean pattern:**
```python
from smeme.core.dependencies import AsyncSessionDep, CurrentUser

@router.post("/route")
async def my_route(
    user: CurrentUser,  # ← Self-documenting, type-safe
    db: AsyncSessionDep,
):
    pass
```

### Benefits

1. **Single Import Location**
   ```python
   # One line for all dependencies
   from smeme.core.dependencies import AsyncSessionDep, CurrentUser, OpenAIClientDep
   ```

2. **Type Safety with Annotated**
   - Better IDE autocomplete
   - Clear intent (type shows it's a dependency)
   - Follows PEP 593 standard

3. **Easy Refactoring**
   ```python
   # Change implementation once in dependencies.py
   # All routes automatically updated
   AsyncSessionDep = Annotated[AsyncSession, Depends(_get_new_db)]
   ```

4. **Testability**
   ```python
   # Override in one place
   app.dependency_overrides[_get_db] = lambda: mock_db
   # Affects all routes using AsyncSessionDep
   ```

5. **Clear Dependency Inventory**
   - See all app dependencies in one file
   - Easy to understand what's available
   - Prevents dependency duplication

### Singleton Client Pattern

For expensive-to-create clients (OpenAI, database engines, etc.):

#### File: `smeme/core/llm.py`

```python
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
    - Connection pooling built into httpx
    - Creating per-request is wasteful
    
    Why lru_cache?
    - FastAPI official pattern for singletons
    - Can override in tests via app.dependency_overrides
    - Thread-safe
    """
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=30.0,
        max_retries=3,
    )
```

### Complete Route Example

```python
"""Feature routes with centralized dependencies."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from smeme.core.dependencies import AsyncSessionDep, CurrentUser, OpenAIClientDep
from smeme.feature.workflow import build_feature_workflow
from smeme.feature.models import FeatureState

router = APIRouter(prefix="/feature", tags=["feature"])


@router.post("/execute")
async def execute_feature(
    request: Request,
    input_data: str = Form(...),
    user: CurrentUser = ...,           # ← Clean, self-documenting
    db: AsyncSessionDep = ...,         # ← Type-safe dependency
    openai: OpenAIClientDep = ...,     # ← Singleton client
) -> HTMLResponse:
    """Execute feature workflow."""
    
    workflow = build_feature_workflow()
    
    initial_state: FeatureState = {
        "input": input_data,
        "user_id": str(user.id),
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={
            "configurable": {
                "db": db,
                "openai_client": openai,
                "user_id": user.id,
            }
        }
    )
    
    return HTMLResponse(content=result["output_html"])
```

### Migration Strategy

If you have existing routes using old pattern:

1. **Keep backward compatibility** - export both patterns from dependencies.py
2. **Migrate gradually** - update routes one at a time
3. **Update tests** - override at source level
4. **Remove legacy** - once all routes migrated, remove function exports

```python
# dependencies.py supports both during migration

# New routes use this:
from smeme.core.dependencies import CurrentUser

# Old routes still work with this:
from smeme.core.dependencies import current_active_user
```

---

## Route Integration

### FastAPI Route Pattern

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/my-feature", tags=["my-feature"])

@router.post("/execute")
async def execute_workflow_route(
    request: Request,
    session_id: str,
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user)
) -> HTMLResponse:
    """Execute LangGraph workflow and return HTML response."""
    
    # 1. Validate input
    session = await db.get(MySession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    # 2. Execute workflow
    result = await execute_my_workflow(
        session_id=session_id,
        db=db,
        user_id=user.id
    )
    
    # 3. Handle errors
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    
    # 4. Return HTML for HTMX
    return HTMLResponse(content=result["html_output"])
```

### Async Workflow Execution Helper

```python
async def execute_my_workflow(
    session_id: str,
    db: AsyncSession,
    user_id: int,
    **additional_config
) -> MyWorkflowState:
    """
    Execute workflow with dependency injection.
    
    This pattern keeps routes clean and workflows reusable.
    """
    graph = build_my_workflow()
    
    initial_state: MyWorkflowState = {
        "session_id": session_id,
        "user_id": user_id,
        # ... other initial state
    }
    
    config = {
        "configurable": {
            "db": db,
            "user_id": user_id,
            **additional_config
        }
    }
    
    result = await graph.ainvoke(initial_state, config=config)
    return result
```

---

## HTMX Integration

### Frontend Pattern

```html
<!-- HTMX form submission -->
<form 
    hx-post="/my-feature/execute"
    hx-target="#content"
    hx-swap="innerHTML"
    hx-on::after-request="handleResponse(event)"
>
    <input type="hidden" name="session_id" value="{{ session.id }}">
    <input type="text" name="user_input" required>
    <button type="submit">Submit</button>
</form>

<div id="content">
    <!-- LangGraph workflow will render HTML here -->
</div>

<script>
function handleResponse(event) {
    if (event.detail.successful) {
        console.log("Workflow completed successfully");
    } else {
        console.error("Workflow error:", event.detail.xhr.responseText);
    }
}
</script>
```

### Backend HTML Response

```python
async def render_output_node(state: State, config: RunnableConfig) -> State:
    """Render HTML output for HTMX consumption."""
    request: Request = config["configurable"]["request"]
    
    # Use Jinja2 templates
    html = templates.TemplateResponse(
        "my-feature/output.html",
        {
            "request": request,
            "data": state["data"],
            "is_complete": state["is_complete"]
        }
    ).body.decode()
    
    return {"html_output": html}
```

### HTMX Redirects - Full Page vs. Content Swap

**Critical Pattern**: When an HTMX POST request needs to redirect to a new page (not just swap content), use the `HX-Redirect` header.

```python
# WRONG - HTMX follows redirect but swaps content into original target
@router.post("/create_version")
async def create_new_version(...) -> RedirectResponse:
    # ... create new version ...
    return RedirectResponse(url=f"/qnr/{new_version.id}/editor", status_code=303)
    # Result: Editor page HTML gets swapped into a button or small div ❌

# RIGHT - Force full page navigation with HX-Redirect header
@router.post("/create_version")
async def create_new_version(...) -> RedirectResponse:
    # ... create new version ...
    response = RedirectResponse(url=f"/qnr/{new_version.id}/editor", status_code=303)
    response.headers["HX-Redirect"] = f"/qnr/{new_version.id}/editor"
    return response
    # Result: Browser does full page navigation ✅
```

**Why this matters:**
- HTMX intercepts ALL requests, including redirects
- Without `HX-Redirect`, HTMX follows the redirect and swaps the HTML into `hx-target`
- This causes "weird looking pages" when full page content gets swapped into a small div
- `HX-Redirect` tells HTMX: "Do a real browser redirect, not a content swap"

**When to use `HX-Redirect`:**
- ✅ After creating a resource → redirect to its detail/edit page
- ✅ After completing a workflow → redirect to dashboard
- ✅ After publish/submit → redirect to success page
- ❌ When updating content in place (use regular HTMX swap)

**Example - After Publishing QNR:**
```python
@router.post("/{qnr_id}/publish")
async def publish_qnr(qnr_id: UUID, ...) -> RedirectResponse:
    # Publish the QNR
    qnr.status = "published"
    await db.commit()
    
    # Redirect to dashboard with full page load
    response = RedirectResponse(url="/qnr/dashboard", status_code=303)
    response.headers["HX-Redirect"] = "/qnr/dashboard"
    return response
```

**Alternative - Return HTML directly (no redirect):**
```python
# If you don't need a redirect, return HTML that HTMX will swap
@router.post("/update_node")
async def update_node(...) -> HTMLResponse:
    # Update node
    # Return updated editor view
    return HTMLResponse(content=updated_editor_html)
    # Result: HTMX swaps content into hx-target ✅
```

---

## Pydantic V2 Usage Patterns

Pydantic V2 is used throughout the application for validation, settings, and type safety. Here are the key patterns:

### 1. Settings Management

```python
# smeme/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Database
    database_url: str = "postgresql+asyncpg://user:pass@localhost/db"
    
    # Security
    secret_key: str
    
    # LangSmith
    langchain_api_key: str | None = None
    langchain_tracing_v2: bool = False

# Usage
settings = Settings()
```

### 2. API Request/Response Models

```python
from pydantic import BaseModel, Field, field_validator

class AnswerSubmitRequest(BaseModel):
    """Validate incoming answer submission."""
    
    question_node_id: str = Field(..., min_length=1)
    answer_text: str = Field(..., min_length=1, max_length=10000)
    
    @field_validator('answer_text')
    @classmethod
    def validate_answer(cls, v: str) -> str:
        """Custom validation logic."""
        if not v.strip():
            raise ValueError("Answer cannot be empty")
        return v.strip()

# In routes
@router.post("/submit")
async def submit_answer(data: AnswerSubmitRequest):
    # data is automatically validated
    pass
```

### 3. SQLModel (SQLAlchemy + Pydantic Fusion)

```python
from sqlmodel import SQLModel, Field

class User(SQLModel, table=True):
    """
    SQLModel provides both:
    1. SQLAlchemy ORM functionality (database)
    2. Pydantic validation (API serialization)
    """
    id: int = Field(primary_key=True)
    email: str = Field(unique=True, index=True)
    
    # Automatically validates on creation
    # Automatically serializes to JSON for API responses

# Direct API usage - no separate schema needed
@router.get("/users/{user_id}", response_model=User)
async def get_user(user_id: int, db: AsyncSession):
    user = await db.get(User, user_id)
    return user  # Auto-serialized by Pydantic
```

### 4. Type Safety with Pydantic

```python
# LangGraph State uses TypedDict for static typing
# But Pydantic can validate if needed
from typing import TypedDict
from pydantic import TypeAdapter

class WorkflowState(TypedDict):
    session_id: str
    data: dict[str, str]

# Validate at runtime if needed
adapter = TypeAdapter(WorkflowState)
validated_state = adapter.validate_python({"session_id": "123", "data": {}})
```

---

## Authentication

### Protected Routes with FastAPI-Users

```python
from smeme.auth.users import current_active_user
from smeme.auth.models import User

@router.get("/protected")
async def protected_route(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Only authenticated users can access."""
    # User is automatically injected by FastAPI-Users
    # If not authenticated, raises 401 Unauthorized
    # Middleware converts 401 to login redirect for browsers
    pass
```

### FastAPI-Users Configuration

FastAPI-Users is configured in the auth module:

```python
# smeme/auth/backend.py
from fastapi_users.authentication import CookieTransport, AuthenticationBackend
from fastapi_users.authentication import BearerTransport, JWTStrategy

# Cookie-based authentication (used in production)
cookie_transport = CookieTransport(
    cookie_name="session",
    cookie_max_age=3600,  # 1 hour
    cookie_httponly=True,
    cookie_secure=False,  # Set to True in production with HTTPS
    cookie_samesite="lax"
)

def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=settings.secret_key,
        lifetime_seconds=3600
    )

auth_backend = AuthenticationBackend(
    name="jwt",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

# smeme/auth/users.py - User manager and dependencies
from fastapi_users import FastAPIUsers
from smeme.auth.models import User
from smeme.auth.manager import get_user_manager

fastapi_users = FastAPIUsers[User, int](
    get_user_manager,
    [auth_backend],
)

# Export for use in routes
current_active_user = fastapi_users.current_user(active=True)
```

### Middleware for Browser Redirects

The `HTMXLoginRedirectMiddleware` automatically redirects browser requests to login:

```python
# In smeme/core/middleware.py
class HTMXLoginRedirectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Redirect 401 browser requests to login
        if response.status_code == 401:
            accept = request.headers.get("accept", "")
            is_htmx = request.headers.get("hx-request")
            
            if "text/html" in accept or is_htmx:
                return RedirectResponse(
                    url="/auth/login",
                    status_code=303
                )
        
        return response
```

### Authentication Routes

```python
# In smeme/main.py - Register auth routes
from smeme.auth.backend import auth_backend
from smeme.auth.users import fastapi_users
from smeme.auth.models import UserRead, UserCreate

# Register authentication routes
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)

app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)
```

### Passing User to Workflow

```python
@router.post("/workflow")
async def workflow_route(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
):
    result = await execute_workflow(
        db=db,
        user_id=user.id  # Pass user ID, not user object
    )
    
    # In workflow config:
    config = {
        "configurable": {
            "db": db,
            "user_id": user.id  # Store ID, not object
        }
    }
```

### Login/Logout Flow

```html
<!-- Login Form with HTMX -->
<form 
    hx-post="/auth/jwt/login"
    hx-target="#error-message"
    hx-on::after-request="if(event.detail.successful) { window.location.href = '/qnr/dashboard'; }"
>
    <input type="email" name="username" required>
    <input type="password" name="password" required>
    <button type="submit">Login</button>
</form>

<!-- Logout Button -->
<form action="/auth/logout" method="post">
    <button type="submit">Logout</button>
</form>
```

```python
# Custom logout route (in smeme/auth/routes.py)
@router.post("/logout")
async def logout(response: Response):
    """Logout user and clear session cookie."""
    redirect = RedirectResponse(url="/auth/login", status_code=303)
    
    # Clear session cookie
    redirect.delete_cookie(
        key="session",
        path="/",
        httponly=True,
        samesite="lax"
    )
    
    # Prevent caching
    redirect.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    redirect.headers["Pragma"] = "no-cache"
    redirect.headers["Expires"] = "0"
    
    return redirect
```

---

## Database Models & Migrations

> **📖 For comprehensive database schema documentation, see [DATA_SCHEMA.md](./DATA_SCHEMA.md)**
> 
> This section covers model definition patterns. For complete schema details, relationship mappings, and cascade rules, refer to the dedicated DATA_SCHEMA.md document.

### Model Best Practices

**CRITICAL**: Always review existing models in `smeme/core/models.py` before creating new ones to ensure consistency.

#### Standard Model Template

```python
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped
from sqlmodel import Field, SQLModel


class MyModel(SQLModel, table=True):
    """Example model with best practices."""
    
    model_config = {"arbitrary_types_allowed": True}  # ← First
    
    __tablename__ = "my_models"  # ← Second
    
    # Primary key
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    
    # Foreign keys (always index)
    user_id: UUID = Field(foreign_key="users.id", index=True)  # ← "users" not "user"
    
    # Data fields
    title: str = Field(max_length=500)
    data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}")
    )
    
    # Timestamps (timezone-aware with Mapped)
    created_at: Mapped[datetime] = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default_factory=lambda: datetime.now(UTC),
            server_default=sa.func.now(),
        )
    )
    
    updated_at: Mapped[datetime] = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default_factory=lambda: datetime.now(UTC),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        )
    )
```

#### Key Conventions

1. **Import Pattern**:
   - Use `from uuid import UUID, uuid4` (stdlib, not sqlalchemy.dialects.postgresql)
   - Use `import sqlalchemy as sa` for sqlalchemy functions
   - Import `Mapped` from `sqlalchemy.orm`

2. **Model Structure Order**:
   - `model_config` first
   - `__tablename__` second
   - Fields: id, foreign keys, data fields, timestamps

3. **UUID Fields**:
   - Type: `UUID` (not `uuid.UUID` or aliased types)
   - Primary key: `id: UUID = Field(default_factory=uuid4, primary_key=True)`
   - Foreign key: `user_id: UUID = Field(foreign_key="users.id", index=True)`

4. **Timestamps**:
   - Always use `Mapped[datetime]` wrapper
   - Always use `DateTime(timezone=True)` for PostgreSQL
   - Include both `default_factory` (Python) and `server_default` (SQL)
   - Never manually set timestamps that have default_factory

5. **Foreign Key Table Names**:
   - Check `__tablename__` in referenced model
   - Use plural form: `"users.id"` not `"user.id"`

6. **Dict Type Hints**:
   - Be specific: `dict[str, Any]` not `dict`
   - Import `Any` from `typing` when needed

### Critical Database Rules

1. **Always Use Timezone-Aware Datetimes**
   ```python
   # ✅ CORRECT
   from datetime import datetime, UTC
   
   created_at: datetime = Field(
       default_factory=lambda: datetime.now(UTC),
       sa_column=Column(DateTime(timezone=True))
   )
   
   # ❌ WRONG - Naive datetime
   created_at: datetime = Field(
       default_factory=datetime.now  # No timezone!
   )
   ```

2. **Use JSONB for PostgreSQL**
   ```python
   from sqlalchemy.dialects.postgresql import JSONB
   
   # ✅ Better performance & features
   data: dict = Field(sa_column=Column(JSONB))
   
   # ❌ Generic JSON (less efficient)
   data: dict = Field(sa_column=Column(JSON))
   ```

3. **Database Migrations with Alembic**
   ```bash
   # Create migration
   uv run alembic revision --autogenerate -m "Add my_feature tables"
   
   # Review migration file in alembic/versions/
   
   # Apply migration
   uv run alembic upgrade head
   ```

### Update Patterns

**Simple Update (Non-Critical Data)**
```python
async def save_simple_data(db: AsyncSession, session: MySession, data: dict):
    """For non-critical updates, update entire object."""
    session.data = data
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()
    await db.refresh(session)
```

**Atomic Update (Critical Data)**
```python
from sqlalchemy import update, func
from sqlalchemy.dialects.postgresql import JSONB

async def save_critical_data(db: AsyncSession, session_id: UUID, key: str, value: str):
    """For critical updates, use atomic JSONB operations."""
    stmt = (
        update(MySession)
        .where(MySession.id == session_id)
        .values(
            data=func.jsonb_set(
                MySession.data,
                f'{{{key}}}',
                func.to_jsonb(value),
                True
            ),
            updated_at=func.now()
        )
    )
    await db.execute(stmt)
    await db.commit()
```

**When to Use Atomic Updates:**
- Multiple users/processes might update same record
- Updates must be consistent (e.g., financial data)
- Risk of race conditions

**When Simple Updates Are Fine:**
- Single user workflow (like QNR sessions)
- AsyncSession already provides transaction isolation
- Performance not critical

---

## SQLAlchemy Relationships & Cascade Rules

> **📖 For complete relationship documentation, see [DATA_SCHEMA.md](./DATA_SCHEMA.md)**
>
> This section provides a quick reference for using ORM relationships in LangGraph workflows.

### Why Use Explicit Relationships?

Starting in November 2025, the project uses **explicit SQLAlchemy relationships** instead of manual foreign key management. This prevents an entire class of bugs:

**❌ Before (Manual Cascade - Error Prone):**
```python
# Deleting a QNR required manually managing the cascade order
session_ids = await db.execute(
    select(QNRSession.id).where(QNRSession.qnr_id == qnr_id)
)
session_ids = [row[0] for row in session_ids.all()]

if session_ids:
    # Manual cascade: Memos → Sessions → QNR
    await db.execute(delete(Memo).where(Memo.session_id.in_(session_ids)))

await db.execute(delete(QNRSession).where(QNRSession.qnr_id == qnr_id))
await db.delete(qnr)
await db.commit()

# Problems:
# - Easy to forget a table in the cascade chain
# - Wrong order = ForeignKeyViolationError at runtime
# - No visibility of dependencies in code
# - Brittle when schema evolves
```

**✅ After (ORM Relationships - Safe):**
```python
# Delete parent, cascade happens automatically
await db.delete(qnr)
await db.commit()

# Benefits:
# - Correct cascade order guaranteed by SQLAlchemy
# - Impossible to miss dependencies
# - Schema visible in model definitions
# - Type-safe access to related objects
```

### Current Relationship Map

```python
# smeme/core/models.py

from sqlalchemy.orm import Mapped, relationship

class QNR(SQLModel, table=True):
    # ... fields ...
    
    # Has many sessions
    sessions: Mapped[list["QNRSession"]] = relationship(
        "QNRSession",
        back_populates="qnr",
        cascade="all, delete-orphan",  # Delete QNR → cascade to sessions
        lazy="selectin",  # Eager load to avoid N+1 queries
    )

class QNRSession(SQLModel, table=True):
    # ... fields ...
    
    # Belongs to one QNR
    qnr: Mapped["QNR"] = relationship(
        "QNR",
        back_populates="sessions"  # Must match QNR.sessions
    )
    
    # Has many memos
    memos: Mapped[list["Memo"]] = relationship(
        "Memo",
        back_populates="session",
        cascade="all, delete-orphan",  # Delete session → cascade to memos
        lazy="selectin",
    )

class Memo(SQLModel, table=True):
    # ... fields ...
    
    # Belongs to one session
    session: Mapped["QNRSession"] = relationship(
        "QNRSession",
        back_populates="memos"  # Must match QNRSession.memos
    )
```

### Cascade Rules Explained

| Cascade Value | What It Does | Use Case |
|--------------|-------------|----------|
| `"all, delete-orphan"` | Delete parent → delete children automatically | Parent-child relationships (QNR → Sessions) |
| `"all"` | Propagate all operations | General relationships |
| `"delete"` | Only propagate deletes | When only delete should cascade |
| None (default) | No cascade | Independent entities |

**Our Rules:**
t- QNR → QNRSession: No cascade (sessions are user data and survive QNR deletion)
- QNRSession → Memo: `cascade="all, delete-orphan"`
- User → (anything): No cascade (users can exist without their data)

### Using Relationships in Routes

**Pattern 1: Delete with Automatic Cascade**
```python
@router.delete("/{qnr_id}/delete")
async def delete_qnr(
    qnr_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
):
    """Delete QNR with automatic cascade to sessions and memos."""
    qnr = await db.get(QNR, qnr_id)
    if not qnr:
        raise HTTPException(status_code=404, detail="QNR not found")
    
    if qnr.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Log what's about to be deleted
    logger.info(
        f"Deleting QNR: {qnr.title}",
        extra={
            "qnr_id": str(qnr_id),
            "session_count": len(qnr.sessions),  # Via relationship
            "user_id": str(user.id)
        }
    )
    
    # ORM handles cascade automatically
    await db.delete(qnr)
    await db.commit()
    
    return {"status": "deleted"}
```

**Pattern 2: Access Related Data**
```python
async def get_qnr_with_stats(db: AsyncSession, qnr_id: UUID):
    """Get QNR with session statistics."""
    qnr = await db.get(QNR, qnr_id)
    if not qnr:
        return None
    
    # Access via relationships (already loaded via lazy="selectin")
    session_count = len(qnr.sessions)
    completed_sessions = [s for s in qnr.sessions if s.completed_at]
    
    # Navigate to nested relationships
    memo_count = sum(len(session.memos) for session in qnr.sessions)
    
    return {
        "qnr": qnr,
        "session_count": session_count,
        "completed_count": len(completed_sessions),
        "memo_count": memo_count,
    }
```

**Pattern 3: Create with Relationships**
```python
async def create_session_workflow(
    db: AsyncSession,
    qnr_id: UUID,
    user_id: UUID,
):
    """Create session and link to QNR via relationship."""
    qnr = await db.get(QNR, qnr_id)
    if not qnr:
        raise ValueError("QNR not found")
    
    # Create session
    session = QNRSession(
        user_id=user_id,
        qnr_id=qnr.id,  # Foreign key
        current_node_id=qnr.graph_data.get("start_node"),
    )
    
    # Can also add via relationship
    # qnr.sessions.append(session)
    
    db.add(session)
    await db.commit()
    await db.refresh(session)
    
    return session
```

### Avoiding N+1 Queries

**Problem: Lazy Loading** (default behavior):
```python
# ❌ Causes N+1 queries
qnrs = await db.execute(select(QNR))
for qnr in qnrs.scalars():
    for session in qnr.sessions:  # Each iteration = 1 DB query
        print(session.id)
```

**Solution 1: Configure in Model** (our approach):
```python
# In model definition
sessions: Mapped[list["QNRSession"]] = relationship(
    ...,
    lazy="selectin"  # ← Always eager load
)

# Now this is efficient
qnrs = await db.execute(select(QNR))
for qnr in qnrs.scalars():
    for session in qnr.sessions:  # Already loaded!
        print(session.id)
```

**Solution 2: Explicit Eager Loading** (query-time):
```python
from sqlalchemy.orm import selectinload

result = await db.execute(
    select(QNR).options(selectinload(QNR.sessions))
)
qnrs = result.scalars().all()
```

### Chained `selectinload` for Nested Relationships

**🚨 Critical Pattern**: When accessing relationships on related objects (e.g., `session.qnr.parent`), you **must** chain `selectinload` to load nested relationships. Otherwise, you'll trigger lazy loading in async context → `MissingGreenlet` error.

**Problem Scenario:**
```python
# ❌ WILL FAIL with MissingGreenlet
sessions = await list_user_sessions(db, user_id)

for session in sessions:
    # session.qnr is loaded...
    # But session.qnr.parent is NOT loaded!
    if session.qnr.parent:  # ← Triggers lazy load → CRASH
        print(session.qnr.parent.title)
```

**Error Message:**
```
sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called; 
can't call await_only() here. Was IO attempted in an unexpected place?
```

**Root Cause:**
- The session's QNR is loaded via `selectinload(QNRSession.qnr)`
- But the QNR's version relationships (`parent`, `children`) are **not** loaded
- Accessing `session.qnr.parent` triggers lazy loading
- Lazy loading requires async context, but we're in synchronous template rendering
- SQLAlchemy fails with `MissingGreenlet`

**✅ Solution: Chain `selectinload`**

```python
# In smeme/qnr/helpers/db_queries.py
async def list_user_sessions(db: AsyncSession, user_id: UUID, limit: int = 20):
    """List user's recent QNR sessions with version relationships."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(QNRSession)
        .options(
            # ✅ Chain selectinload to load nested relationships
            selectinload(QNRSession.qnr).selectinload(QNR.parent),
            selectinload(QNRSession.qnr).selectinload(QNR.children),
            selectinload(QNRSession.memos),
        )
        .where(QNRSession.user_id == user_id)
        .order_by(QNRSession.updated_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
```

**How It Works:**
1. `selectinload(QNRSession.qnr)` loads the session's QNR
2. `.selectinload(QNR.parent)` **chains** to also load the QNR's parent
3. `.selectinload(QNR.children)` **chains** to also load the QNR's children
4. All relationships are now loaded → No lazy loading → No crash

**General Rule:**

> **If you access `object.relationship.nested_relationship` anywhere in your code (routes, templates, helpers), you MUST use chained `selectinload` when fetching `object`.**

**Examples:**

```python
# ✅ Loading sessions with QNR's author
selectinload(QNRSession.qnr).selectinload(QNR.author)

# ✅ Loading QNRs with sessions' memos
selectinload(QNR.sessions).selectinload(QNRSession.memos)

# ✅ Loading users with their sessions' QNRs
selectinload(User.sessions).selectinload(QNRSession.qnr)

# ❌ Missing nested load - will crash if you access session.qnr.parent
selectinload(QNRSession.qnr)  # Only loads QNR, not its relationships
```

**Debugging Tip:**

If you see `MissingGreenlet` errors:
1. Look at the traceback for which model attribute triggered it (e.g., `QNR.parent`)
2. Find where that model is loaded (e.g., via `QNRSession.qnr`)
3. Add chained `selectinload` for the missing relationship
4. Restart server and test

**Performance Note:**

Chained `selectinload` adds additional queries but prevents crashes and is still more efficient than N+1 lazy loads. For complex version trees, consider using `lazy="raise"` on relationships you don't always need, then explicitly load them only when required.

**Alternative: Database Queries Instead of Traversal**

For complex relationship traversal (e.g., walking entire version trees), consider using database queries instead of loading all relationships:

```python
# ❌ BAD: Requires loading entire version tree
def get_newer_version(current_qnr: QNR) -> QNR | None:
    family = current_qnr.get_version_family()  # Needs all parent/children loaded!
    newer = [v for v in family if v.version_number > current_qnr.version_number]
    return max(newer, key=lambda v: v.version_number) if newer else None

# ✅ GOOD: Query database directly
async def _get_root_qnr_id(db: AsyncSession, qnr: QNR) -> UUID:
    """
    Find the root QNR ID using database queries to avoid MissingGreenlet errors.
    """
    root_id = qnr.id
    current_id = qnr.id
    while True:
        result = await db.execute(
            select(QNR.parent_qnr_id).where(QNR.id == current_id)
        )
        parent_id = result.scalar_one_or_none()
        if not parent_id:
            break
        root_id = parent_id
        current_id = parent_id
    return root_id

async def get_version_family_from_db(db: AsyncSession, qnr: QNR) -> list[QNR]:
    """
    Get all versions in a QNR family using breadth-first search with database queries.
    Prevents MissingGreenlet errors in async contexts.
    """
    root_id = await _get_root_qnr_id(db, qnr)

    family_ids = {root_id}
    to_check = {root_id}

    while to_check:
        current_ids = list(to_check)
        to_check = set()

        # Find all direct children of current nodes
        result = await db.execute(
            select(QNR.id).where(QNR.parent_qnr_id.in_(current_ids))
        )

        child_ids = {row[0] for row in result.all()}

        # Add new children to family and to_check for next iteration
        new_children = child_ids - family_ids
        family_ids.update(new_children)
        to_check.update(new_children)

    # Query for all QNRs in the collected family_ids
    result = await db.execute(
        select(QNR).where(QNR.id.in_(family_ids)).order_by(QNR.version_number)
    )
    return list(result.scalars().all())
```

This approach:
- Uses **zero relationship traversal** - only database queries
- Prevents `MissingGreenlet` errors in async contexts
- Scales to arbitrary version tree depths
- Uses breadth-first search for complete family discovery

**✅ IMPLEMENTED**: Fixed silent failure when publishing v3+ versions by replacing relationship-based traversal with pure database queries.

### `back_populates` Matching Rule

**Critical**: The `back_populates` parameter must **exactly match** the relationship attribute name on the other model:

```python
# ✅ CORRECT - Names match
class QNR:
    sessions: Mapped[list["QNRSession"]] = relationship(
        back_populates="qnr"  # ← Matches QNRSession.qnr
    )

class QNRSession:
    qnr: Mapped["QNR"] = relationship(
        back_populates="sessions"  # ← Matches QNR.sessions
    )

# ❌ WRONG - Mismatch causes runtime errors
class QNR:
    sessions: Mapped[list["QNRSession"]] = relationship(
        back_populates="parent"  # ← QNRSession has no such attribute!
    )
```

### When to Use Relationships

**✅ Always use for:**
- Parent-child dependencies (QNR → Sessions)
- Delete operations (ensure cascade works)
- Accessing related data frequently
- New models going forward

**❌ Don't use for:**
- Truly independent entities (no cascade needed)
- Circular dependencies (requires careful planning)

### Testing Cascade Behavior

```python
# tests/test_cascade.py
import pytest

@pytest.mark.asyncio
async def test_qnr_cascade_delete(db: AsyncSession):
    """Test that deleting QNR cascades to sessions and memos."""
    # Create test data
    qnr = QNR(title="Test QNR", graph_data={})
    db.add(qnr)
    await db.commit()
    
    session = QNRSession(qnr_id=qnr.id, user_id=test_user.id)
    db.add(session)
    await db.commit()
    
    memo = Memo(session_id=session.id, user_id=test_user.id, ...)
    db.add(memo)
    await db.commit()
    
    # Delete QNR
    await db.delete(qnr)
    await db.commit()
    
    # Verify cascade
    assert await db.get(QNR, qnr.id) is None
    assert await db.get(QNRSession, session.id) is None  # Cascaded!
    assert await db.get(Memo, memo.id) is None  # Cascaded!
```

### Migration Path

**For new models**: Always define relationships from day one.

**For existing models**: Relationships were added in November 2025:
- ✅ QNR, QNRSession, Memo: Relationships defined
- ⚠️ Old code may still use manual cascades (working, but not ideal)
- 📝 Gradually refactor manual cascades to use ORM when touching code

**Next time you touch delete logic:**
1. Verify relationships are defined in models
2. Replace manual cascade with `await db.delete(parent)`
3. Test cascade behavior
4. Update this guide if new patterns emerge

---

## Common Pitfalls

### 1. ❌ Passing DB Session in State
```python
# WRONG
class State(TypedDict):
    db: AsyncSession  # Not serializable!

# RIGHT
async def node(state: State, config: RunnableConfig):
    db = config["configurable"]["db"]
```

### 2. ❌ Naive Datetimes
```python
# WRONG
created_at = datetime.now()  # No timezone

# RIGHT
from datetime import UTC
created_at = datetime.now(UTC)
```

### 3. ❌ Storing Complex Objects in State
```python
# WRONG
state["user"] = user  # SQLModel instance

# RIGHT
state["user_id"] = user.id  # Primitive type
```

### 4. ❌ Not Handling Optional State Fields
```python
# WRONG
current_step = state["current_step"]  # Might not exist

# RIGHT
current_step = state.get("current_step", "default")
```

### 5. ❌ Forgetting to Await Async Functions
```python
# WRONG
result = db.execute(query)  # Missing await

# RIGHT
result = await db.execute(query)
```

### 6. ❌ Not Checking Authentication in Workflow
```python
# WRONG - Assuming session belongs to user
session = await db.get(Session, session_id)

# RIGHT - Verify ownership
session = await db.get(Session, session_id)
if session.user_id != user_id:
    return {"error": "Unauthorized"}
```

### 7. ❌ Using JSON Instead of JSONB
```python
# WRONG - Less efficient in PostgreSQL
Column(JSON)

# RIGHT - PostgreSQL-specific features
Column(JSONB)
```

### 8. ❌ UUID Import and Type Inconsistency
```python
# WRONG - Using SQLAlchemy's UUID
from sqlalchemy.dialects.postgresql import UUID

# RIGHT - Use stdlib UUID
from uuid import UUID, uuid4

# WRONG - Inconsistent type annotation
id: uuid.UUID = Field(...)

# RIGHT - Simple UUID
id: UUID = Field(default_factory=uuid4, primary_key=True)
```

### 9. ❌ Wrong Foreign Key Table Names
```python
# WRONG - Assuming singular form
user_id: UUID = Field(foreign_key="user.id")

# RIGHT - Check __tablename__ in referenced model
user_id: UUID = Field(foreign_key="users.id")  # From User.__tablename__
```

### 10. ❌ Missing Mapped Wrapper for Timestamps
```python
# WRONG - Direct datetime type
created_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True))
)

# RIGHT - Use Mapped wrapper
from sqlalchemy.orm import Mapped

created_at: Mapped[datetime] = Field(
    sa_column=Column(
        DateTime(timezone=True),
        default_factory=lambda: datetime.now(UTC),
        server_default=sa.func.now(),
    )
)
```

### 11. ❌ Manually Setting Auto-Generated Timestamps
```python
# WRONG - Overriding default_factory
memo = Memo(
    title="...",
    generated_at=datetime.now(UTC),  # Has default_factory!
)

# RIGHT - Let the model handle it
memo = Memo(title="...")  # generated_at set automatically
```

### 12. ❌ UUID Serialization in State
```python
# WRONG - Passing UUID object in state
state["user_id"] = user.id  # UUID object not serializable

# RIGHT - Convert to string for state
state["user_id"] = str(user.id)  # String in state

# But pass UUID directly in config
config = {"configurable": {"user_id": user.id}}  # UUID in config
```

### 13. ❌ Wrong Import Source for `Mapped`
```python
# WRONG - Will cause ImportError on server startup
from sqlmodel import Field, SQLModel, Mapped

# RIGHT - Import from sqlalchemy.orm
from sqlalchemy.orm import Mapped
from sqlmodel import Field, SQLModel
```

**Why this matters:**
- `Mapped` is a SQLAlchemy type annotation, not part of SQLModel
- Incorrect import causes immediate server failure: `ImportError: cannot import name 'Mapped' from 'sqlmodel'`
- Easy to miss when copying model templates
- Used for all timezone-aware timestamp fields

### 14. ❌ Alembic Autogenerate with `default_factory`
```python
# WRONG - Causes SyntaxError in migration file
# Alembic tries to serialize: default_factory=<function Model.<lambda> at 0x...>

# RIGHT - Manually fix generated migration
# In migration file, remove default_factory, keep only server_default:
sa.Column('created_at', sa.DateTime(timezone=True), 
          server_default=sa.text('now()'), nullable=False)

# Also fix AutoString:
sa.Column('title', sa.String(length=500), nullable=False)  # not AutoString
```

**Fix process:**
1. Delete broken migration file
2. Create new migration with timestamp name: `YYYYMMDD_HHMM_description.py`
3. Copy structure from autogenerate output (visible in error)
4. Remove `default_factory` parameters
5. Change `sqlmodel.sql.sqltypes.AutoString` to `sa.String`

### 15. ❌ Circular Imports with Centralized Dependencies
```python
# WRONG - Creates circular import
# smeme/core/dependencies.py
from smeme.auth.users import current_active_user

# smeme/auth/manager.py
from smeme.core.dependencies import get_db  # ← Circular!

# RIGHT - Import from source module
# smeme/auth/manager.py
from smeme.core.database import get_db  # ← Direct import
```

### 16. ❌ Modern Union Syntax in SQLAlchemy String Annotations
```python
# WRONG - SQLAlchemy can't evaluate pipe syntax in string annotations
parent: "QNR | None" = Relationship(
    sa_relationship_kwargs={
        "remote_side": "QNR.id",
        "foreign_keys": "QNR.parent_qnr_id",
    }
)
# Error: InvalidRequestError: failed to locate a name ('QNR | None')

# RIGHT - Use Optional[] or Union[] for nullable relationships
from typing import Optional

parent: Optional["QNR"] = Relationship(
    sa_relationship_kwargs={
        "remote_side": "QNR.id",
        "foreign_keys": "QNR.parent_qnr_id",
    }
)
```

**Why this matters:**
- SQLAlchemy's mapper evaluates string annotations **literally** to resolve relationships
- Python 3.10+ union syntax (`X | Y`) doesn't work inside SQLAlchemy string quotes
- The mapper looks for a model class named exactly `"QNR | None"` and fails
- `Optional["Model"]` is equivalent to `Union["Model", None]` and works correctly
- This only affects **relationship** type hints, not regular fields

**When to use each:**
- ✅ Regular fields: `field: str | None` works fine
- ✅ Relationships: `relationship: Optional["Model"]` or `list["Model"]`
- ❌ Relationships: `relationship: "Model | None"` will fail

### 17. ❌ Using `lazy="selectin"` as Default for Relationships

```python
# WRONG - Auto-loads sessions on EVERY QNR fetch, updates all timestamps on commit
sessions: list["QNRSession"] = Relationship(
    back_populates="qnr",
    sa_relationship_kwargs={
        "lazy": "selectin",  # ❌ Always loads, causes side effects
    },
)

# Later when versioning:
original = await db.get(QNR, qnr_id)  # Sessions auto-loaded
original.is_current = False           # Modify QNR
await db.commit()                     # ALL sessions get updated_at refreshed!

# RIGHT - Use lazy="raise" by default, explicit selectinload when needed
sessions: list["QNRSession"] = Relationship(
    back_populates="qnr",
    sa_relationship_kwargs={
        "lazy": "raise",  # ✅ Prevents accidental loads
    },
)

# Explicitly load only when needed:
qnr = await db.execute(
    select(QNR)
    .options(selectinload(QNR.sessions))  # Load only when you need them
    .where(QNR.id == qnr_id)
)
```

**Why this matters:**
- `lazy="selectin"` makes relationships **always** eager load
- When you modify a parent object, SQLAlchemy flushes ALL loaded objects in the session
- If child objects have `onupdate=sa.func.now()`, their timestamps get updated
- This causes unintended side effects: "Why did all my sessions update when I modified a QNR?"
- `lazy="raise"` throws an error if you try to access without explicit loading
- Forces you to be intentional: "Do I really need this relationship right now?"

**When to use each:**
- ✅ `lazy="raise"`: Default for most relationships (prevents accidents)
- ✅ `lazy="selectin"`: Only for small, frequently-accessed relationships (parent, children for version chains)
- ❌ `lazy="select"`: Old-style lazy loading, causes N+1 queries
- ❌ Default (lazy): Triggers lazy loads, causes MissingGreenlet errors in async

**Example side effect:**
```python
# With lazy="selectin" on sessions:
qnr = await get_qnr_by_id(db, qnr_id)  # Loads QNR + all 1000 sessions
qnr.title = "Updated"
await db.commit()
# Result: QNR updated + 1000 sessions got updated_at refreshed! ❌

# With lazy="raise":
qnr = await get_qnr_by_id(db, qnr_id)  # Loads only QNR
qnr.title = "Updated"
await db.commit()
# Result: Only QNR updated ✅
```

### 18. ❌ Forgetting to Eagerly Load Relationships Used in Workflows
```python
# WRONG - Will cause MissingGreenlet error when accessing relationships
async def get_qnr_by_id(db: AsyncSession, qnr_id: UUID) -> QNR | None:
    result = await db.execute(select(QNR).where(QNR.id == qnr_id))
    return result.scalar_one_or_none()

# Later in workflow:
qnr = await get_qnr_by_id(db, qnr_id)
parent = qnr.parent  # ❌ Lazy load in async context = MissingGreenlet error!

# RIGHT - Eagerly load all relationships that will be accessed
from sqlalchemy.orm import selectinload

async def get_qnr_by_id(db: AsyncSession, qnr_id: UUID) -> QNR | None:
    result = await db.execute(
        select(QNR)
        .options(
            selectinload(QNR.parent),      # Eager load parent
            selectinload(QNR.children),    # Eager load children
            selectinload(QNR.sessions),    # Any other relationships
        )
        .where(QNR.id == qnr_id)
    )
    return result.scalar_one_or_none()

# Now this works:
qnr = await get_qnr_by_id(db, qnr_id)
parent = qnr.parent  # ✅ Already loaded, no database query
```

**Why this matters:**
- Accessing relationships without eager loading triggers **lazy loading**
- Lazy loading attempts a database query in whatever context it's called from
- In async contexts (LangGraph workflows, async routes), this causes `MissingGreenlet` error
- In Jinja2 templates (synchronous), lazy loading also fails because templates can't await
- Error message: `greenlet_spawn has not been called; can't call await_only() here`

**When to eagerly load:**
- ✅ Always for relationships used in LangGraph workflows
- ✅ Always for relationships accessed in Jinja2 templates
- ✅ When passing models to functions that might access relationships
- ✅ When serializing models that include relationship data

**Common places to add `selectinload`:**
```python
# Dashboard queries
sessions = await db.execute(
    select(QNRSession)
    .options(
        selectinload(QNRSession.qnr),     # For qnr.title in template
        selectinload(QNRSession.memos),   # For memo access
    )
    .where(...)
)

# Editor/Viewer queries
qnr = await db.execute(
    select(QNR)
    .options(
        selectinload(QNR.parent),         # For version chain
        selectinload(QNR.children),       # For version family
    )
    .where(...)
)
```

**Import hierarchy rule:**
```
smeme/core/database.py (defines get_db)
          ↓
smeme/auth/manager.py (imports get_db from database)
          ↓
smeme/auth/users.py (uses manager)
          ↓
smeme/core/dependencies.py (re-exports everything)
          ↓
smeme/*/routes.py (imports from dependencies)
```

**Key principle:**
- Core modules that are **re-exported** by `dependencies.py` should **NOT import** from `dependencies.py`
- They should import from their **source modules** directly
- Only **route modules** should import from `dependencies.py`

### 19. ❌ Passing Full State Dict to `interrupt()`

```python
# WRONG - Duplicates state, no type safety
async def wait_for_edit_node(state: State) -> dict:
    result = interrupt({
        "content": state["content"],
        "count": state.get("count", 0),
        "metadata": state.get("metadata"),
        # ... duplicating many state fields
    })
    return result

# Route extracts from unvalidated dict
interrupt_data = interrupt_obj.value
content = interrupt_data.get("content", "")  # No type checking
```

**Why this is problematic:**
- Duplicates data already in state (DRY violation)
- No type safety - passing arbitrary dict
- Risk of inconsistency if values differ from state
- Violates single source of truth principle

```python
# RIGHT - Pass only display content
async def wait_for_edit_node(state: State) -> dict:
    content = state.get("content", "")
    result = interrupt(content)  # Just the content to display
    return result

# Route gets metadata from state (single source of truth)
state_snapshot = await workflow.aget_state(config)
state = state_snapshot.values  # TypedDict = type safety
count = state.get("count", 0)  # IDE autocomplete, type checking
```

**Benefits:**
- ✅ Type-safe via `TypedDict` state definition
- ✅ Single source of truth (state holds all data)
- ✅ IDE autocomplete for state field access
- ✅ Easy to add new state fields without modifying interrupt
- ✅ Follows codebase patterns consistently

**Reference:** [Sprint 2 Lesson #2](../planning/sprints/SPRINT_02_RESEARCH_SUBGRAPH.md#2-interrupt-data-passing-minimal-is-better)

### 20. ❌ Assuming Subgraph Interrupts Propagate to Parent

```python
# WRONG - Parent won't see subgraph's interrupt
async def subgraph_node(state: SubgraphState) -> dict:
    result = interrupt("waiting for input")  # ❌ Local to subgraph
    return result

# Parent workflow
workflow.add_edge("parent_node", "research_subgraph")
workflow.add_edge("research_subgraph", "next_node")  # ❌ Won't stop!
```

**Problem:** When parent calls `subgraph.ainvoke()`, subgraph runs to completion. Internal interrupts are local to the subgraph execution context and don't bubble up.

**Symptom:** Workflow continues immediately to next node, skipping user interaction.

```python
# RIGHT - Add parent-level interrupt after subgraph
async def invoke_subgraph_node(state: ParentState, config) -> dict:
    # Subgraph runs to completion (no UI interrupts)
    subgraph = create_subgraph().compile()
    result = await subgraph.ainvoke(extract_input(state), config)
    return merge_output(state, result)

async def wait_for_user_edit(state: ParentState) -> dict:
    # Parent handles UI interrupt
    content = state.get("content", "")
    edited = interrupt(content)
    return {"content_edited": edited}

# Proper flow
workflow.add_edge("invoke_subgraph", "wait_for_user_edit")  # ✅ Parent interrupt
workflow.add_edge("wait_for_user_edit", "next_node")
```

**Architecture Pattern:**
- **Subgraph**: Pure logic (API calls, validation, error handling)
- **Parent Workflow**: User interaction (interrupts, form rendering, edits)

**When to use subgraphs:**
- ✅ Isolate complex logic (search + augmentation loop)
- ✅ Enable unit testing of logic independently
- ✅ Improve observability (LangSmith shows hierarchy)
- ❌ Don't use for simple sequential steps

**Reference:** [Sprint 2 Lesson #1](../planning/sprints/SPRINT_02_RESEARCH_SUBGRAPH.md#1-subgraph-interrupts-dont-propagate-to-parent)

### 21. ❌ Wrong Type for API Response in State Models

```python
# WRONG - Type doesn't match actual data
class SubgraphOutput(BaseModel):
    api_response: str | None = Field(default=None)  # ❌ API returns dict

# Causes validation error
ValidationError: Input should be a valid string 
    [type=string_type, input_value={'query': '...', 'results': [...]}]
```

**Problem:** Tavily (and most APIs) return dict/JSON, not strings. Type mismatch causes Pydantic validation failure.

```python
# RIGHT - Match actual API response structure
from typing import Any

class SubgraphOutput(BaseModel):
    api_response: dict[str, Any] | None = Field(
        default=None,
        description="Raw API response for debugging (dict from Tavily/OpenAI)",
    )
```

**Best practices:**
- ✅ Inspect actual API responses before defining types
- ✅ Use `dict[str, Any]` for unstructured API responses
- ✅ Use specific Pydantic models for structured responses you parse
- ✅ Test with real API calls early to catch type mismatches

**Common API response patterns:**
```python
# Unstructured/variable responses
tavily_raw: dict[str, Any] | None  # Search results vary by query

# Structured responses you control
class OpenAIResponse(BaseModel):
    content: str
    tokens: int

openai_response: OpenAIResponse  # Well-defined structure
```

**Reference:** [Sprint 2 Lesson #4](../planning/sprints/SPRINT_02_RESEARCH_SUBGRAPH.md#4-type-mismatches-in-subgraph-state-models)

### 22. ❌ External API Parameters Without Validation

```python
# WRONG - Passing user input directly to API
search_kwargs = {
    "query": state["user_prompt"],  # Could be 5000 chars
    "country": state["country"],    # Could be "India" instead of "india"
    "exclude_domains": state.get("exclude_domains", []),  # Could be empty
}
result = await tavily_client.search(**search_kwargs)  # ❌ 400 Bad Request
```

**Real-world API quirks discovered:**

**Tavily API:**
- ❌ Country names must be **lowercase** (`"india"` not `"India"` or `"IN"`)
- ❌ Empty `exclude_domains` list causes 400 error
- ❌ Query length limited to 400 characters

```python
# RIGHT - Validate and transform before API calls
# 1. Country mapping (ISO codes → lowercase full names)
COUNTRY_CODE_TO_NAME = {
    "us": "united states",  # lowercase, full name
    "in": "india",
    "gb": "united kingdom",
}

# 2. Validate prompt length
def validate_tavily_prompt(prompt: str) -> tuple[bool, str | None]:
    if len(prompt) > 400:
        return False, f"Prompt too long ({len(prompt)} chars). Limit: 400."
    if len(prompt.strip()) < 10:
        return False, "Prompt too short. Minimum: 10 characters."
    return True, None

# 3. Use defaults for optional params
EXCLUDE_DOMAINS = ["pinterest.com", "reddit.com", ...]  # 50+ low-quality sites

# 4. Apply validation
valid, error = validate_tavily_prompt(state["user_prompt"])
if not valid:
    return {"error": error, "degraded": True}

country_name = COUNTRY_CODE_TO_NAME.get(state["country"].lower()) if state["country"] else None
exclude = state.get("exclude_domains") or EXCLUDE_DOMAINS  # Never empty

search_kwargs = {
    "query": state["user_prompt"][:400],  # Truncate if needed
    "country": country_name,  # Properly formatted
    "exclude_domains": exclude,  # Never empty
}
```

**Key lessons:**
- ✅ Read API docs carefully (especially parameter formats)
- ✅ Add validation layer between user input and API calls
- ✅ Provide sensible defaults for optional parameters
- ✅ Test with real API early to discover undocumented quirks
- ✅ Add timeouts: `await asyncio.wait_for(api_call(), timeout=30.0)`

**Reference:** 
- [Sprint 2 Lesson #3](../planning/sprints/SPRINT_02_RESEARCH_SUBGRAPH.md#3-tavily-api-quirks)
- [Tavily API Docs](https://docs.tavily.com/documentation/api-reference/endpoint/search)

### 23. ❌ Mixing `config` and `state` for Business Data

```python
# WRONG - Country is business data, should be in state
async def search_node(state: State, config: RunnableConfig) -> dict:
    country = config["configurable"].get("country")  # ❌ Wrong place
    return {}
```

**Problem:** Can't access `country` because it's in state, not config.

**Rule of thumb:**
```python
# config["configurable"] = Infrastructure
{
    "thread_id": "abc-123",          # ✅ Infrastructure
    "user_id": UUID("..."),          # ✅ Infrastructure
    "db": AsyncSession(...),         # ✅ Infrastructure
    "openai_client": AsyncOpenAI(),  # ✅ Infrastructure
    "tavily_client": AsyncTavily(),  # ✅ Infrastructure
}

# state = Business Data (TypedDict)
{
    "user_prompt": "search query",   # ✅ User input
    "country": "us",                 # ✅ User selection
    "research_context": "...",       # ✅ Workflow output
    "augmentation_count": 3,         # ✅ Business logic counter
}
```

**RIGHT pattern:**
```python
# Include business data in subgraph input model
class ResearchSubgraphInput(BaseModel):
    user_prompt: str
    country: str | None = None  # ✅ Business data in state
    user_id: UUID

def extract_input(parent_state: dict) -> ResearchSubgraphInput:
    return ResearchSubgraphInput(
        country=parent_state.get("country"),  # ✅ From state
        # ...
    )
```

**Why this matters:**
- ✅ Clear separation: infrastructure vs business logic
- ✅ State is checkpointed (survives restarts)
- ✅ Config is transient (recreated per request)
- ✅ Type safety: `TypedDict` validates state fields

**Reference:** [Sprint 2 Lesson #5](../planning/sprints/SPRINT_02_RESEARCH_SUBGRAPH.md#5-country-parameter-must-be-in-subgraph-state)

---

## Step-by-Step Implementation

### Step 1: Plan Your Feature

1. **Define the workflow states** - What data flows through?
2. **Identify decision points** - Where does the workflow branch?
3. **List required data** - What needs to be stored in DB?
4. **Map user interactions** - What triggers workflow transitions?

### Step 2: Create Database Models

```python
# smeme/my_feature/models.py
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import JSONB, UUID
from datetime import datetime, UTC
from uuid import uuid4

class MyFeatureSession(SQLModel, table=True):
    __tablename__ = "my_feature_sessions"
    
    id: uuid.UUID = Field(
        default_factory=uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True)
    )
    user_id: int = Field(foreign_key="user.id", nullable=False)
    data: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}")
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    
    model_config = {"arbitrary_types_allowed": True}
```

### Step 3: Create Migration

```bash
# Generate migration
uv run alembic revision --autogenerate -m "Add my_feature tables"

# Review alembic/versions/xxx_add_my_feature_tables.py

# Apply migration
uv run alembic upgrade head
```

### Step 4: Define LangGraph State

```python
# smeme/my_feature/models.py
from typing import TypedDict

class MyFeatureState(TypedDict, total=False):
    """Workflow state - must be serializable."""
    session_id: str
    user_id: int
    current_step: str
    data: dict[str, str]
    html_output: str
    error: str | None
```

### Step 5: Create Helper Functions

```python
# smeme/my_feature/helpers/db_queries.py
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

async def get_session(db: AsyncSession, session_id: UUID) -> MyFeatureSession | None:
    result = await db.execute(
        select(MyFeatureSession).where(MyFeatureSession.id == session_id)
    )
    return result.scalar_one_or_none()

async def save_session(db: AsyncSession, session: MyFeatureSession):
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()
    await db.refresh(session)
```

### Step 6: Build LangGraph Workflow

```python
# smeme/my_feature/workflow.py
from langgraph.graph import StateGraph, END
from langgraph.types import RunnableConfig
from .models import MyFeatureState
from .helpers.db_queries import get_session, save_session

async def load_session_node(
    state: MyFeatureState,
    config: RunnableConfig
) -> MyFeatureState:
    """Load session from database."""
    db = config["configurable"]["db"]
    
    session = await get_session(db, state["session_id"])
    if not session:
        return {"error": "Session not found"}
    
    return {
        "data": session.data,
        "current_step": "process"
    }

async def process_node(
    state: MyFeatureState,
    config: RunnableConfig
) -> MyFeatureState:
    """Process business logic."""
    # Your logic here
    return {"current_step": "render"}

async def render_node(
    state: MyFeatureState,
    config: RunnableConfig
) -> MyFeatureState:
    """Render HTML output."""
    request = config["configurable"]["request"]
    
    html = templates.TemplateResponse(
        "my_feature/output.html",
        {"request": request, "data": state["data"]}
    ).body.decode()
    
    return {
        "html_output": html,
        "current_step": "complete"
    }

def build_my_workflow() -> StateGraph:
    """Build and compile workflow."""
    workflow = StateGraph(MyFeatureState)
    
    workflow.add_node("load_session", load_session_node)
    workflow.add_node("process", process_node)
    workflow.add_node("render", render_node)
    
    workflow.set_entry_point("load_session")
    workflow.add_edge("load_session", "process")
    workflow.add_edge("process", "render")
    workflow.add_edge("render", END)
    
    return workflow.compile()
```

### Step 7: Create Routes

```python
# smeme/my_feature/routes.py
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from smeme.core.dependencies import get_async_session
from smeme.auth.users import current_active_user
from smeme.auth.models import User
from .workflow import build_my_workflow
from .models import MyFeatureState

router = APIRouter(prefix="/my-feature", tags=["my-feature"])

async def execute_workflow(
    session_id: str,
    db: AsyncSession,
    request: Request,
    user_id: int
) -> MyFeatureState:
    """Execute workflow with dependencies."""
    graph = build_my_workflow()
    
    initial_state: MyFeatureState = {
        "session_id": session_id,
        "user_id": user_id,
        "current_step": "start",
        "data": {},
        "html_output": "",
        "error": None
    }
    
    result = await graph.ainvoke(
        initial_state,
        config={
            "configurable": {
                "db": db,
                "request": request,
                "user_id": user_id
            }
        }
    )
    
    return result

@router.post("/execute")
async def execute_route(
    request: Request,
    session_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> HTMLResponse:
    """Execute workflow and return HTML."""
    result = await execute_workflow(
        session_id=session_id,
        db=db,
        request=request,
        user_id=user.id
    )
    
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    
    return HTMLResponse(content=result["html_output"])
```

### Step 8: Register Routes

```python
# smeme/main.py
from smeme.my_feature.routes import router as my_feature_router

app.include_router(my_feature_router)
```

### Step 9: Create Templates

```html
<!-- smeme/templates/my_feature/output.html -->
{% extends "layouts/base.html" %}

{% block content %}
<div id="my-feature-output">
    <h2>Result</h2>
    <div class="data">
        {{ data }}
    </div>
    
    <form 
        hx-post="/my-feature/execute"
        hx-target="#my-feature-output"
        hx-swap="outerHTML"
    >
        <input type="hidden" name="session_id" value="{{ session.id }}">
        <button type="submit">Next</button>
    </form>
</div>
{% endblock %}
```

### Step 10: Test

```python
# tests/test_my_feature.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_workflow(client: AsyncClient, authenticated_user):
    response = await client.post(
        "/my-feature/execute",
        data={"session_id": "test-session-id"}
    )
    assert response.status_code == 200
    assert "Result" in response.text
```

---

## Design Limitations & Constraints

### 1. State Serialization
- **Limitation**: State must be JSON-serializable
- **Reason**: LangGraph may persist/resume workflows
- **Workaround**: Pass complex objects via `RunnableConfig`

### 2. Database Session Lifecycle
- **Limitation**: Sessions created per-request, not per-workflow
- **Reason**: FastAPI dependency injection pattern
- **Workaround**: Pass session via config to all nodes that need it

### 3. HTMX Partial Updates
- **Limitation**: Nodes must return complete HTML for target element
- **Reason**: HTMX swaps entire target content
- **Workaround**: Use `hx-swap` strategies (`innerHTML`, `outerHTML`, `beforeend`, etc.)

### 4. Async-Only
- **Limitation**: All operations must be async
- **Reason**: FastAPI runs in async event loop
- **Workaround**: Use `asyncio.to_thread()` for sync operations if absolutely necessary

### 5. Authentication Per-Request
- **Limitation**: User authentication checked at route level, not within workflow
- **Reason**: FastAPI-Users dependency injection
- **Workaround**: Pass `user_id` to workflow, verify ownership in nodes

---

## Performance Considerations

### 1. Database Queries
- Use eager loading with `selectinload()` for related objects
- Index frequently queried fields
- Use `JSONB` indexes for JSON field queries

### 2. Workflow Complexity
- Keep workflows focused (5-10 nodes maximum)
- Break complex workflows into sub-graphs
- Use conditional routing sparingly

### 3. State Size
- Keep state minimal (IDs, not full objects)
- Avoid large strings in state
- Use database for large data, state for references

### 4. Two-Tier Caching Pattern

The project uses a **two-tier caching strategy** for workflow data:

#### L1: aiocache (In-Memory)
- **Purpose**: Ultra-fast repeated access (~1-5ms)
- **TTL**: 1 hour
- **Use case**: Same user viewing same data multiple times

#### L2: PostgreSQL Database  
- **Purpose**: Persistence across server restarts (~150ms)
- **TTL**: Permanent (until deleted)
- **Use case**: One-and-done data (memos, generated content)

#### Implementation Pattern

```python
# smeme/feature/helpers/cache.py
from aiocache import Cache
from aiocache.serializers import PickleSerializer

feature_cache = Cache(
    Cache.MEMORY,
    serializer=PickleSerializer(),
    ttl=3600,  # 1 hour
    namespace="feature_data",
)

async def get_cached_data(key: UUID) -> Optional[Data]:
    """Get data from L1 cache."""
    cache_key = f"data_{str(key)}"
    return await feature_cache.get(cache_key)

async def cache_data(key: UUID, data: Data) -> None:
    """Populate L1 cache."""
    cache_key = f"data_{str(key)}"
    await feature_cache.set(cache_key, data)

async def invalidate_cache(key: UUID) -> None:
    """Invalidate L1 cache (call on updates/deletes)."""
    cache_key = f"data_{str(key)}"
    await feature_cache.delete(cache_key)
```

#### Workflow Node with Two-Tier Caching

```python
async def load_data_node(state: State, config: RunnableConfig) -> State:
    """Load data with two-tier caching."""
    start_time = time.time()
    db: AsyncSession = config["configurable"]["db"]
    data_id = UUID(state["data_id"])
    
    # L1: Check aiocache (~1-5ms) - FAST
    cached_data = await get_cached_data(data_id)
    if cached_data:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Data loaded from L1 cache",
            extra={
                "data_id": str(data_id),
                "cache_layer": "L1_aiocache",
                "cache_hit": True,
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "load_data",
            },
        )
        return {"data": cached_data, "already_loaded": True}
    
    # L2: Check database (~150ms) - Persistent
    result = await db.execute(
        select(Data).where(Data.id == data_id)
    )
    existing_data = result.scalar_one_or_none()
    
    if existing_data:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Data loaded from L2 database - populating L1 cache",
            extra={
                "data_id": str(data_id),
                "cache_layer": "L2_database",
                "cache_hit": True,
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "load_data",
            },
        )
        
        # Populate L1 cache for next request
        await cache_data(data_id, existing_data)
        
        return {"data": existing_data, "already_loaded": True}
    
    # Cache miss - generate new data
    logger.info(
        "Cache miss - generating new data",
        extra={"data_id": str(data_id), "cache_hit": False},
    )
    
    # ... generate data ...
    return {"already_loaded": False}
```

#### Save Node with Cache Population

```python
async def save_data_node(state: State, config: RunnableConfig) -> State:
    """Save data to database and populate L1 cache."""
    db: AsyncSession = config["configurable"]["db"]
    data_id = UUID(state["data_id"])
    
    # Save to database (L2)
    new_data = Data(...)
    db.add(new_data)
    await db.commit()
    await db.refresh(new_data)
    
    # Populate L1 cache for fast subsequent access
    await cache_data(data_id, new_data)
    
    logger.info(
        "Data saved and cached",
        extra={
            "data_id": str(data_id),
            "cache_populated": True,
        },
    )
    
    return {"data_id": str(new_data.id)}
```

#### Cache Invalidation

**Critical**: Invalidate L1 cache when data is updated or deleted:

```python
@router.delete("/data/{data_id}")
async def delete_data(
    data_id: UUID,
    db: AsyncSession = Depends(get_async_session),
):
    """Delete data and invalidate cache."""
    data = await db.get(Data, data_id)
    
    # Delete from database
    await db.delete(data)
    await db.commit()
    
    # Invalidate L1 cache
    await invalidate_cache(data_id)
    
    return {"status": "deleted"}
```

#### Performance Comparison

| Scenario | Without Cache | With Two-Tier |
|----------|---------------|---------------|
| **First access** | 150ms (DB) | 150ms (DB) + populate cache |
| **Second access (5min later)** | 150ms (DB) | **1-5ms (L1)** ⚡ |
| **After server restart** | 150ms (DB) | 150ms (DB) + populate cache |

#### Monitoring Cache Hit Rates

```python
# Structured logs capture cache performance:
# grep "cache_layer" logs/app.log | jq '.extra.cache_layer' | sort | uniq -c

# Expected metrics:
# - L1 hit rate: 70-90% (repeated access within TTL)
# - L2 hit rate: 90-99% (persistent data)
# - Cache miss: 1-10% (first-time access)
```

### 5. Workflow Compilation Caching

```python
# Cache compiled workflows (they're expensive to build)
from functools import lru_cache

@lru_cache(maxsize=1)
def get_compiled_workflow():
    return build_my_workflow()
```

---

## Structured Logging

### Overview

All LangGraph workflows use **structured logging** with context, timing, and metadata to enable:
- **Production debugging**: Filter logs by session_id, user_id, or node
- **Performance monitoring**: Track node execution times
- **Audit trails**: Full visibility into workflow execution

**Structured logging complements LangSmith tracing** (see [LangSmith Integration](#langsmith-integration) below) - logs provide detailed business logic and database operations, while LangSmith provides high-level workflow visualization and LLM call metrics.

### Logger Setup

```python
import logging
import time
from langgraph.types import RunnableConfig

# Use per-workflow named logger
logger = logging.getLogger("smeme.feature.workflow")
```

### Node Logging Pattern

```python
async def my_node(state: MyState, config: RunnableConfig) -> StateUpdate:
    """Process data with structured logging."""
    start_time = time.time()
    
    # Extract runtime context
    db: AsyncSession = config["configurable"]["db"]
    user_id: int = config["configurable"].get("user_id")
    
    # Extract state context
    session_id = str(state["session_id"])
    
    # Log entry with context
    logger.info(
        "Processing node",
        extra={
            "session_id": session_id,
            "user_id": user_id,
            "node": "my_node",
            "input_data": state.get("data_summary")  # Don't log sensitive data
        },
    )
    
    try:
        # Business logic
        result = await process_data(db, state["data"])
        
        # Log success with timing
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Node completed successfully",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "node": "my_node",
                "result_size": len(result),
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )
        
        return {"result": result}
        
    except Exception as e:
        logger.error(
            "Node failed",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "node": "my_node",
                "error": str(e),
            },
            exc_info=True,  # Include stack trace
        )
        return {"error": str(e)}
```

### Key Patterns

1. **Always include**:
   - `session_id`: Track specific user sessions
   - `user_id`: Identify which user triggered the workflow
   - `node`: Name of the current node for filtering
   
2. **Use `extra` dict**:
   - Structured metadata that can be indexed/searched
   - JSON-compatible values only (no datetime objects, serialize first)
   
3. **Measure timing**:
   - Capture `start_time = time.time()` at node entry
   - Log `elapsed_ms` at exit for performance monitoring
   
4. **Log levels**:
   - `DEBUG`: Detailed state/data inspection (development only)
   - `INFO`: Normal operation milestones
   - `WARNING`: Recoverable issues (validation failures, retries)
   - `ERROR`: Unrecoverable failures with `exc_info=True`

### Production Log Aggregation

In production, structured logs can be:
- **Filtered**: `grep 'session_id.*abc123' app.log`
- **Analyzed**: Import into ELK, Datadog, CloudWatch
- **Alerted**: Trigger alerts on error rates per node

### Example: QNR Workflow Logs

```
INFO Loading QNR | session_id=f994e9b2 user_id=42 node=load_qnr
INFO QNR loaded from cache | qnr_id=a1b2c3 cache_hit=true elapsed_ms=2.34
INFO Determining next question | session_id=f994e9b2 current_question=q1 direction=next
INFO Conditional edge matched | from_question=q1 to_question=q4_js answer=JavaScript elapsed_ms=0.87
INFO Question rendered | question_id=q4_js question_type=text is_required=true elapsed_ms=15.42
```

---

## LangSmith Integration

### Overview

**LangSmith** automatically traces all LangGraph workflows, providing:
- Visual workflow execution graphs
- Per-node timing and state inspection
- LLM call details (prompts, completions, token counts, costs)
- Error debugging across distributed systems
- Cost tracking and analytics

**No code changes needed** - LangGraph automatically instruments workflows when LangSmith is enabled.

### Setup

Enable via environment variables:

```bash
# .env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_api_key_here
LANGCHAIN_PROJECT=smeme_v2
```

Add to settings:

```python
# smeme/core/config.py
class Settings(BaseSettings):
    # ... other settings ...
    
    # LangSmith (optional - for tracing)
    langchain_api_key: str | None = None
    langchain_tracing_v2: bool = False
    langchain_project: str = "smeme_v2"
```

That's it! All `workflow.ainvoke()` calls are now traced.

### What Gets Traced

#### 1. Workflow Execution
- Start time, end time, duration
- Input state and final output state
- Success/failure status
- All nodes executed in order

#### 2. Each Node
- Node name (e.g., "load_qnr", "call_llm")
- Input state (what came into the node)
- Output state (what the node returned)
- Execution duration
- Any exceptions raised

#### 3. LLM Calls (via OpenAI SDK)
- Model name (gpt-4o, gpt-4o-mini, etc.)
- Full prompt (system + user messages)
- Full completion
- Token counts (input and output)
- **Cost** (calculated automatically)
- Temperature and other parameters
- Latency

#### 4. Conditional Edges
- Which routing function was called
- Which branch was taken
- The state values that determined the route

### Example Trace Visualization

```
Trace: qnr_workflow
├─ load_qnr (342ms)
│  ├─ Input: {qnr_id: "abc123", session: {...}}
│  └─ Output: {graph: {...}, error: null}
│
├─ determine_next_question (12ms)
│  ├─ Input: {graph: {...}, navigation_intent: "next"}
│  └─ Output: {next_question_id: "q2"}
│
├─ render_question (156ms)
│  ├─ Input: {next_question_id: "q2", session: {...}}
│  └─ Output: {rendered_output: "<div>...</div>"}
│
Total: 510ms | Status: ✅ Success


Trace: memo_generation (with LLM call)
├─ load_session (134ms)
├─ format_prompt (2ms)
├─ call_llm (2847ms) 💰 $0.0003
│  ├─ OpenAI Chat Completion
│  │  ├─ Model: gpt-4o-mini
│  │  ├─ Messages:
│  │  │  ├─ system: "You are an expert analyst..."
│  │  │  └─ user: "Based on the following..."
│  │  ├─ Response: {title: "...", summary: "...", ...}
│  │  ├─ Tokens: 487 input, 312 output
│  │  └─ Cost: $0.000297
├─ save_memo (156ms)
└─ render_memo (18ms)

Total: 3.16s | Cost: $0.0003 | Status: ✅ Success
```

### LangSmith vs Structured Logs

Use both together for complete observability:

| Feature | LangSmith | Structured Logs |
|---------|-----------|-----------------|
| **Workflow visualization** | ✅ Interactive graph | ❌ |
| **Node-level state** | ✅ Full state at each step | ✅ Custom fields |
| **LLM calls** | ✅ Prompts, tokens, costs | ❌ |
| **Business logic details** | ❌ | ✅ DB queries, validation |
| **User context** | ⚠️ If in state | ✅ Always (user_id, session_id) |
| **Performance metrics** | ✅ Per-node timing | ✅ Custom timing |
| **Error stack traces** | ✅ | ✅ With `exc_info=True` |
| **Filtering/querying** | ✅ UI-based | ✅ grep/jq |
| **Cost tracking** | ✅ Automatic | ❌ |
| **Alerting** | ✅ Built-in | ⚠️ Via log aggregation |

### Debugging Workflow

**Scenario**: User reports slow memo generation

1. **Check structured logs** (find the session):
   ```bash
   grep 'session_id.*abc123' logs/app.log
   ```
   ```
   INFO Load session | session_id=abc123 user_id=42 elapsed_ms=342
   INFO Format prompt | user_id=42 qa_count=12 elapsed_ms=2
   INFO Call LLM | user_id=42 model=gpt-4o-mini elapsed_ms=4521  # ← slow!
   ```

2. **Open LangSmith trace** (search by session_id if you tagged it):
   - Navigate to LangSmith UI
   - Find the `call_llm` node
   - Inspect the **actual prompt** sent to OpenAI
   - Check token count: 2,483 input tokens (very long!)
   - **Root cause**: Prompt too large (12 Q&A pairs)

3. **Solution**: Implement prompt compression or pagination

### Tagging Traces for Easy Search

Add metadata to traces:

```python
result = await workflow.ainvoke(
    initial_state,
    config={
        "configurable": {
            "db": db,
            "user_id": user.id
        },
        "metadata": {
            "user_id": user.id,              # Tag for filtering
            "session_id": session_id,         # Tag for filtering
            "workflow_type": "qnr_execution"  # Tag for grouping
        }
    }
)
```

Now in LangSmith, you can:
- Filter traces by user_id
- Search for specific session_id
- Group by workflow_type for analytics

### Cost Tracking

LangSmith automatically tracks costs across:
- **Per run**: See cost for each workflow execution
- **Per user**: Tag with user_id to track per-user spending
- **Per day/week/month**: Built-in time-series analytics
- **Per model**: Compare gpt-4o vs gpt-4o-mini costs

Example dashboard queries:
- "Total LLM cost this month"
- "Average cost per memo generation"
- "Which users are generating the most memos?"
- "Cost breakdown: gpt-4o vs gpt-4o-mini"

### Best Practices

1. **Always enable in production** - The visibility is worth the minimal overhead
2. **Tag with user/session IDs** - Makes debugging specific issues trivial
3. **Use metadata for filtering** - workflow_type, feature_name, etc.
4. **Review traces for failed runs** - Understand why LLM calls failed
5. **Monitor costs** - Set up alerts for unexpected spending
6. **Compare cached vs uncached runs** - Validate your caching strategy

### Privacy Considerations

LangSmith traces include:
- Full prompts and LLM responses
- State data (may contain user information)
- Session IDs and user IDs

**For sensitive data:**
- Use LangSmith's data retention policies
- Consider self-hosted LangSmith (enterprise)
- Filter PII from state before tracing
- Use redaction in structured logs

---

## Linter & Formatter Configuration

### Overview

The project uses **Ruff** (linter + formatter) and **MyPy** (type checker) with strict configurations to enforce code quality, consistency, and type safety.

### Configuration (`pyproject.toml`)

```toml
# ============================================================================
# Linting & Formatting
# ============================================================================

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort (import sorting)
    "N",    # pep8-naming
    "UP",   # pyupgrade (Python 3.13+ idioms)
    "ANN",  # flake8-annotations (type hints)
    "ASYNC",# flake8-async
    "B",    # flake8-bugbear
    "C4",   # flake8-comprehensions
    "DTZ",  # flake8-datetimez (timezone-aware datetimes)
    "T10",  # flake8-debugger
    "EM",   # flake8-errmsg
    "ISC",  # flake8-implicit-str-concat
    "ICN",  # flake8-import-conventions
    "PIE",  # flake8-pie
    "PT",   # flake8-pytest-style
    "RET",  # flake8-return
    "SIM",  # flake8-simplify
    "PTH",  # flake8-use-pathlib
]
ignore = [
    "ANN101",  # Missing type annotation for self
    "ANN102",  # Missing type annotation for cls
    "ANN401",  # Dynamically typed expressions (Any)
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["ANN"]  # Don't require type hints in tests
"alembic/versions/*" = ["ALL"]  # Skip linting migration files

[tool.ruff.lint.isort]
known-first-party = ["smeme"]
section-order = ["future", "standard-library", "third-party", "first-party", "local-folder"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
line-ending = "auto"

# ============================================================================
# Type Checking
# ============================================================================

[tool.mypy]
python_version = "3.13"
warn_return_any = true
warn_unused_configs = true
warn_redundant_casts = true
warn_unused_ignores = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
disallow_untyped_decorators = false  # FastAPI uses untyped decorators
no_implicit_optional = true
strict_equality = true
warn_no_return = true

# Pydantic plugin for better validation
plugins = ["pydantic.mypy"]

# Exclude patterns
exclude = [
    "^alembic/versions/.*\\.py$",  # Skip migration files
    "^build/",
    "^dist/",
]

[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false  # Relax for tests

[[tool.mypy.overrides]]
module = [
    "aiocache.*",
    "langgraph.*",
    "langsmith.*",
]
ignore_missing_imports = true  # These don't have type stubs yet
```

### Running Linters

```bash
# Format code
ruff format .

# Check linting
ruff check .

# Auto-fix linting issues
ruff check --fix .

# Type checking
mypy smeme/
```

### Pre-Commit Integration

```bash
# Install pre-commit hooks (optional)
pip install pre-commit
pre-commit install

# Run manually
pre-commit run --all-files
```

### Key Enforcements

1. **Type Hints Required** (`ANN`):
   - All functions must have parameter and return type hints
   - Exceptions: `self`, `cls`, tests
   
2. **Timezone-Aware Datetimes** (`DTZ`):
   - Enforces `datetime.now(UTC)` instead of naive `datetime.now()`
   - Critical for database timestamp consistency
   
3. **Modern Python** (`UP`):
   - Enforces `list[str]` over `List[str]`
   - Enforces `X | None` over `Optional[X]`
   
4. **Import Sorting** (`I`):
   - Automatic import organization
   - Sections: stdlib → third-party → first-party → local
   
5. **Async Best Practices** (`ASYNC`):
   - Detects blocking operations in async functions
   - Enforces proper `await` usage

---

## Debugging Tips

### 1. Query Logs by Session
```bash
# Filter production logs by session_id
grep 'session_id.*abc123' logs/app.log | jq '.extra'
```

### 2. Inspect LangGraph Execution
```python
# In development, log each step
result = await graph.ainvoke(
    initial_state,
    config={
        "configurable": {"db": db, "user_id": user.id},
        "callbacks": [YourCallbackHandler()]  # Optional
    }
)
```

### 3. Database Query Logging
```python
# In smeme/core/database.py
engine = create_async_engine(
    settings.database_url,
    echo=True,  # Log all SQL queries
    future=True
)
```

### 4. HTMX Request Inspection
```javascript
// In browser console
document.body.addEventListener('htmx:beforeRequest', function(evt) {
    console.log('HTMX Request:', evt.detail);
});

document.body.addEventListener('htmx:afterRequest', function(evt) {
    console.log('HTMX Response:', evt.detail);
});
```

---

## Conclusion

This guide establishes patterns for integrating LangGraph workflows into the smeme_v2 FastAPI application. Key takeaways:

1. **Dependency Injection**: Always use `RunnableConfig` for non-serializable dependencies
2. **State Hygiene**: Keep state simple, serializable, and minimal
3. **Database Patterns**: Use timezone-aware datetimes, JSONB for PostgreSQL, and appropriate update strategies
4. **HTMX Integration**: Return complete HTML fragments from workflow nodes
5. **Authentication**: Handle at route level, pass user_id to workflow
6. **Testing**: Test workflows both in isolation and integrated with routes

Following these patterns ensures maintainable, scalable LangGraph features that integrate seamlessly with FastAPI, SQLModel, and HTMX.

---

## Further Reading

### Project Documentation
- **[DATA_SCHEMA.md](./DATA_SCHEMA.md)** - Complete database schema, relationships, and ORM patterns
- **[QNR_EDITOR_REFACTOR_SUMMARY.md](./QNR_EDITOR_REFACTOR_SUMMARY.md)** - Pydantic @as_form pattern and editor architecture

### Core Framework & Libraries
- [FastAPI Documentation](https://fastapi.tiangolo.com/) - Modern async web framework
- [Pydantic V2 Documentation](https://docs.pydantic.dev/latest/) - Data validation and settings
- [SQLModel Documentation](https://sqlmodel.tiangolo.com/) - SQL databases with Python (SQLAlchemy + Pydantic)
- [FastAPI-Users Documentation](https://fastapi-users.github.io/fastapi-users/) - Authentication for FastAPI
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/) - AI workflow orchestration
- [OpenAI API Documentation](https://platform.openai.com/docs/api-reference) - Direct LLM integration

### Frontend & Database
- [HTMX Documentation](https://htmx.org/) - High power tools for HTML
- [PostgreSQL JSONB](https://www.postgresql.org/docs/current/datatype-json.html) - JSON Binary data type
- [Alembic Documentation](https://alembic.sqlalchemy.org/) - Database migrations
- [SQLAlchemy 2.0](https://docs.sqlalchemy.org/en/20/) - SQL toolkit and ORM
- [SQLAlchemy Relationships](https://docs.sqlalchemy.org/en/20/orm/basic_relationships.html) - ORM relationship patterns

### Python & Best Practices
- [Python Type Hints](https://docs.python.org/3/library/typing.html) - Type annotation support
- [asyncio Documentation](https://docs.python.org/3/library/asyncio.html) - Asynchronous I/O

### 16. Jinja2 Template Injection Pattern

#### Overview

Template engines (like Jinja2) can be injected via `RunnableConfig` just like database sessions and API clients. This provides better testability and flexibility.

#### Pattern Comparison

**Legacy Pattern (module-level):**
```python
# ❌ OLD - Hard to test, tight coupling
from jinja2 import Environment, FileSystemLoader

jinja_env = Environment(loader=FileSystemLoader("smeme/templates"))

async def render_node(state, config):
    template = jinja_env.get_template("output.html")
    html = template.render(data=state["data"])
    return {"rendered_output": html}
```

**Modern Pattern (dependency injection via config):**
```python
# ✅ NEW - Testable, flexible, consistent
from starlette.templating import Jinja2Templates

# In routes.py
templates = Jinja2Templates(directory="smeme/templates")

# Pass via config
result = await workflow.ainvoke(
    state,
    config={
        "configurable": {
            "db": db,
            "templates": templates,  # Inject like any other dependency
        }
    }
)

# In workflow node
async def render_node(state, config):
    templates = config["configurable"]["templates"]
    response = templates.TemplateResponse(
        "output.html",
        context={"data": state["data"]}
    )
    return {"rendered_output": response.body.decode()}
```

#### Why Inject via Config?

Following the **same pattern as OpenAI client and database sessions**:

1. **Testability**: Can inject mock templates in tests
   ```python
   # In tests
   mock_templates = MockJinja2Templates()
   config = {"configurable": {"templates": mock_templates}}
   ```

2. **Flexibility**: Can use different template directories for testing
   ```python
   test_templates = Jinja2Templates(directory="tests/fixtures/templates")
   ```

3. **Consistency**: All external dependencies follow the same injection pattern
   ```python
   config = {
       "configurable": {
           "db": db,                    # Database session
           "openai_client": client,     # OpenAI client
           "templates": templates,      # Template engine
           "user_id": user.id,          # Runtime context
       }
   }
   ```

4. **No Filesystem Coupling**: Workflow doesn't hardcode template paths
   - Easier to move/refactor template directories
   - Can swap template engines without touching workflow code

#### When to Use Each Pattern

| Scenario | Module-Level | Dependency Injection |
|----------|-------------|---------------------|
| **Simple read-only workflows** | ✅ Acceptable | ✅ Better |
| **Workflows with write operations** | ⚠️ Avoid | ✅ Required |
| **New features** | ❌ Don't use | ✅ Always use |
| **Testing required** | ❌ Hard to test | ✅ Easy to test |
| **Template path may change** | ❌ Hard to refactor | ✅ Flexible |

#### Migration Strategy

Existing workflows using module-level Jinja2 (like `smeme/qnr/workflow.py`) can stay as-is for now, but **all new workflows should use dependency injection**.

**Gradual migration:**
1. New features: Use dependency injection from day one
2. Bug fixes in old code: Leave module-level as-is (don't refactor during bug fix)
3. Major refactors: Migrate to dependency injection when touching the code significantly

#### Complete Example

```python
# smeme/feature/workflow.py
from starlette.templating import Jinja2Templates
from langgraph.types import RunnableConfig

async def render_viewer_node(state, config: RunnableConfig):
    """Render HTML using injected templates."""
    templates: Jinja2Templates = config["configurable"]["templates"]
    
    context = {
        "qnr_id": state["qnr_id"],
        "data": state["data"],
    }
    
    response = templates.TemplateResponse(
        "feature/output.html",
        context=context
    )
    
    return {"rendered_html": response.body.decode()}

# smeme/feature/routes.py
from starlette.templating import Jinja2Templates

templates = Jinja2Templates(directory="smeme/templates")

@router.get("/{id}/view")
async def view_route(id: UUID, user: CurrentUser, db: AsyncSessionDep):
    result = await workflow.ainvoke(
        {"id": id, "user_id": user.id},
        config={
            "configurable": {
                "db": db,
                "templates": templates,  # Inject here
            }
        }
    )
    return HTMLResponse(content=result["rendered_html"])
```

### 17. LLM Prompt Templating & Validator Alignment (Lessons Learned)

- Prompt templating with `.format(...)` requires escaping any literal braces in examples:
  - Use doubled braces to render JSON-like examples: `{{"source": "q1", "target": "q2"}}`
  - Only keep placeholders for intended variables (e.g., `{topic}`, `{goal}`)
- Align prompts and validators to runtime behavior:
  - If runtime navigation matches edge conditions via simple substring, instruct the prompt to produce simple literal conditions (no code-like expressions).
  - Make validator rules type-aware to reduce false negatives:
    - For radio questions, default edge is not required when every option label is covered by a conditional.
    - For checkbox/text/number, require a default edge when conditional edges exist.
  - Validate option presence for radio/checkbox and absence for text/number to prevent template/runtime mismatches.
- Prefer minimal viable validation that mirrors how the runtime actually routes, then iterate as behavior evolves.

---

## November 2025 Integration Updates

During the QNR Editor UI refactor we touched the LangGraph viewer/editor workflows and uncovered a few integration guidelines worth documenting:

1. **Separate Entry Points for Full-Page vs HTMX Swaps**  
   Provide a Boolean in `config["configurable"]` (e.g. `full_page`) so a single LangGraph workflow can emit either a full Jinja template or a partial, depending on caller context.

2. **Surface Size Metadata Early**  
   Expose `visualization.width/height` in the state after the layout node so downstream renderers and front-end containers can allocate scroll space before rendering SVG. This avoids cumulative layout shift.

3. **Always Return Deterministic Flags**  
   For conditional edges (`add_conditional_edges`) every upstream node must emit the Boolean flag it is tested on. Missing keys evaluate to the default `False` which may short-circuit unexpectedly.

4. **Prefer State Augmentation over Mutation**  
   Nodes should return a *delta* dict merged into state rather than mutating nested objects in place. This keeps LangGraph's immutable state model intact and eases debugging (just print the delta).

5. **Cache Invalidation Node Should Be Non-Blocking**  
   If invalidating Redis or in-memory cache fails, swallow the error and let the workflow succeed—DB is the source of truth. Mark the node `success=True` regardless to avoid rolling back already-committed changes.

6. **Prefer Pydantic Request Models over Ad-hoc Dict Mapping**  
   Manual `operation_data.get("field") or operation_data.get("alias")` logic quickly becomes brittle as routes evolve.  
   • Define a dedicated Pydantic model for each editor route's payload (e.g., `CreateEdgeRequest`, `UpdateNodeRequest`).  
   • Use `alias="text"` / `alias="question_text"` annotations (or the `model_config = {"populate_by_name": True}` flag) so both field names are accepted transparently.  
   • Convert the validated model to a dict once (`model.dict(exclude_unset=True)`) and pass that into LangGraph `operation_data`.  
   • This removes field-mapping code from `operations.py`, provides automatic validation / coercion, and keeps FastAPI docs accurate.

7. **HTMX Endpoint Audit Pattern**  
   When implementing HTMX-driven workflows, maintain a complete mapping of UI interactions to backend routes:
   • Search for all `hx-post` directives in templates and renderer functions
   • Create a checklist of expected routes vs implemented routes
   • Missing routes often indicate incomplete feature implementation
   • Two-step patterns (form generation + action) are common: `create_X_form` returns HTML form, `create_X` executes operation

These practices have been applied to `smeme/qnr/viewer/workflow.py` and `smeme/qnr/editor/workflow.py` and should serve as templates for future LangGraph integrations across the project.

---

## Pydantic Models with FastAPI Form Data (@as_form Pattern)

### The Problem

FastAPI doesn't natively support Pydantic models with HTML form data (`multipart/form-data`). Standard patterns require verbose `Form(...)` parameters:

```python
# ❌ Verbose and error-prone
@router.post("/create_edge")
async def create_edge(
    source: Annotated[str, Form()],
    target: Annotated[str, Form()],
    condition: Annotated[str | None, Form()] = None,
    user: CurrentUser,
    db: AsyncSessionDep,
):
    # Manual validation and dict construction
    operation_data = {
        "source": source,
        "target": target,
        "condition": condition
    }
```

### The @as_form Decorator Solution

Create a decorator that makes Pydantic models compatible with FastAPI Form data:

```python
# smeme/feature/models.py
import inspect
from typing import Type
from fastapi import Form
from pydantic import BaseModel, Field

def as_form(cls: type[BaseModel]) -> type[BaseModel]:
    """
    Decorator to make a Pydantic model compatible with FastAPI Form data.
    
    Dynamically generates __signature__ so FastAPI treats the model as a
    dependency with Form parameters.
    """
    new_params = []
    for field_name, field_info in cls.model_fields.items():
        # Get the default value or ... (required)
        if field_info.default is not None:
            default = Form(field_info.default)
        elif field_info.default_factory is not None:
            default = Form(field_info.default_factory())
        else:
            default = Form(...)
        
        new_params.append(
            inspect.Parameter(
                field_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=field_info.annotation,
            )
        )
    
    cls.__signature__ = inspect.Signature(new_params)
    return cls
```

### Applying the Decorator

```python
# smeme/feature/models.py
from pydantic import BaseModel, Field
from typing import Literal

@as_form
class CreateEdgeRequest(BaseModel):
    """Request to create a new edge."""
    
    source: str = Field(description="Source node ID")
    target: str = Field(description="Target node ID")
    condition: str | None = Field(default=None, description="Optional condition")

@as_form
class CreateNodeRequest(BaseModel):
    """Request with field aliases for backward compatibility."""
    
    node_id: str = Field(description="Node ID")
    question_text: str = Field(alias="text", description="Question text")
    question_type: Literal["text", "number", "radio", "checkbox"] = Field(
        alias="type", description="Question type"
    )
    
    model_config = {"populate_by_name": True}  # Accept both names and aliases
```

### Clean Route Implementation

```python
# smeme/feature/routes.py
from smeme.feature.models import CreateEdgeRequest

@router.post("/create_edge")
async def create_edge(
    qnr_id: Annotated[UUID, Form()],
    req: CreateEdgeRequest,  # ✅ Clean, self-documenting
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """Create edge using Pydantic model validation."""
    
    # Already validated by Pydantic
    operation_data = req.model_dump()
    
    # Pass to workflow
    result = await editor_workflow.ainvoke(
        {
            "qnr_id": qnr_id,
            "operation": "create_edge",
            "operation_data": operation_data,
        },
        config={"configurable": {"db": db}}
    )
    
    return HTMLResponse(content=result["rendered_html"])
```

### Benefits

1. **Type Safety**: Full Pydantic validation on form data
2. **No Manual Parsing**: Automatic field extraction and validation
3. **Better Errors**: Pydantic provides detailed validation error messages
4. **Self-Documenting**: Models serve as API documentation
5. **Alias Support**: Handle legacy field names gracefully
6. **Consistent**: Same pattern for all CRUD operations

### ⚠️ Critical Constraint: No Mixing with Separate Form() Parameters

**IMPORTANT**: When using `@as_form` decorated models, you CANNOT mix them with separate `Form()` parameters in the same route:

```python
# ❌ BROKEN - Causes 422 Unprocessable Content errors
@router.post("/delete_node")
async def delete_node(
    qnr_id: Annotated[UUID, Form()],  # DON'T DO THIS
    req: DeleteNodeRequest,            # @as_form model
    user: CurrentUser,
    db: AsyncSessionDep,
):
    ...
```

**Why It Fails**: The `@as_form` decorator modifies the function signature to consume form data. FastAPI's dependency injection cannot properly distinguish between the decorator-modified parameters and separate `Form()` parameters, leading to validation failures.

**Solution**: Include ALL form fields in your request model:

```python
# ✅ CORRECT - All form fields in the model
@as_form
class DeleteNodeRequest(BaseModel):
    qnr_id: UUID = Field(description="QNR ID")
    node_id: str = Field(description="Node ID to delete")

@router.post("/delete_node")
async def delete_node(
    req: DeleteNodeRequest = Depends(),  # MUST use Depends() with @as_form!
    user: CurrentUser,
    db: AsyncSessionDep,
):
    qnr_id = req.qnr_id  # Extract as needed
    ...
```

**Best Practice**: Always include context IDs (like `qnr_id`, `session_id`, etc.) as fields in your request models, and ensure HTML forms include them as hidden inputs:

```html
<form hx-post="/qnr/editor/delete_node" hx-target="#editor-container">
  <input type="hidden" name="qnr_id" value="{{ qnr_id }}">
  <input type="hidden" name="node_id" value="{{ node_id }}">
  <button type="submit">Delete</button>
</form>
```

### Handling Aliases for Backward Compatibility

When refactoring existing forms, use aliases to maintain compatibility:

```python
@as_form
class UpdateNodeRequest(BaseModel):
    node_id: str
    question_text: str = Field(alias="text")  # Accept both "question_text" and "text"
    question_type: str = Field(alias="type")  # Accept both "question_type" and "type"
    
    model_config = {"populate_by_name": True}

# HTML form can use either name:
# <input name="text"> or <input name="question_text"> both work
```

### Operations Integration

With canonical field names, operations become straightforward:

```python
# smeme/feature/operations.py
def apply_operation(graph: QNRGraph, operation: str, operation_data: dict) -> QNRGraph:
    """Apply operation with clean data from Pydantic models."""
    
    if operation == "create_edge":
        # No more field aliasing hacks needed!
        return create_edge(
            graph,
            source=operation_data["source"],  # Direct access
            target=operation_data["target"],
            condition=operation_data.get("condition"),
        )
```

### Complete Example: Editor CRUD Routes

```python
# models.py
@as_form
class CreateNodeRequest(BaseModel):
    node_id: str
    question_text: str = Field(alias="text")
    question_type: Literal["text", "number", "radio", "checkbox"] = Field(alias="type")
    options: list[str] | None = None
    help_text: str | None = None
    model_config = {"populate_by_name": True}

@as_form
class UpdateNodeRequest(BaseModel):
    node_id: str
    question_text: str = Field(alias="text")
    question_type: Literal["text", "number", "radio", "checkbox"] = Field(alias="type")
    options: list[str] | None = None
    help_text: str | None = None
    model_config = {"populate_by_name": True}

@as_form
class DeleteNodeRequest(BaseModel):
    node_id: str

# routes.py - Clean and consistent
@router.post("/create_node")
async def create_node(
    qnr_id: Annotated[UUID, Form()],
    req: CreateNodeRequest,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    operation_data = req.model_dump()
    result = await editor_workflow.ainvoke(...)
    return HTMLResponse(content=result["rendered_html"])

@router.post("/update_node")
async def update_node(
    qnr_id: Annotated[UUID, Form()],
    req: UpdateNodeRequest,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    operation_data = req.model_dump(exclude_none=True)  # Only changed fields
    result = await editor_workflow.ainvoke(...)
    return HTMLResponse(content=result["rendered_html"])

@router.post("/delete_node")
async def delete_node(
    qnr_id: Annotated[UUID, Form()],
    req: DeleteNodeRequest,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    operation_data = req.model_dump()
    result = await editor_workflow.ainvoke(...)
    return HTMLResponse(content=result["rendered_html"])
```

### When to Use This Pattern

✅ **Use @as_form when:**
- Building HTMX-driven CRUD operations
- Multiple form fields need validation
- Want type-safe route parameters
- Need to support field aliases
- Refactoring legacy forms

❌ **Don't use when:**
- Simple single-field forms (use `Form()` directly)
- JSON API endpoints (use regular Pydantic models)
- File uploads (use `UploadFile`)

### Testing @as_form Models

```python
# tests/test_models.py
def test_create_edge_request_validation():
    """Test Pydantic validation."""
    # Valid request
    req = CreateEdgeRequest(
        source="q1",
        target="q2",
        condition="answer == 'yes'"
    )
    assert req.source == "q1"
    
    # Invalid request
    with pytest.raises(ValidationError):
        CreateEdgeRequest(source="q1")  # Missing required field

def test_field_aliases():
    """Test alias support."""
    # Using alias
    req = CreateNodeRequest(
        node_id="q1",
        text="What is your name?",  # alias for question_text
        type="text"  # alias for question_type
    )
    assert req.question_text == "What is your name?"
    assert req.question_type == "text"
```

---

## HTMX Two-Step Form Pattern

### Pattern Overview

Many HTMX interactions follow a **two-step pattern**:
1. **Form Generation Route**: Returns HTML form based on current state
2. **Action Route**: Processes form submission and executes operation

This pattern enables:
- Dynamic forms that adapt to graph state
- Clean separation between UI generation and business logic
- Better user experience with inline editing

### Example: Creating Edges

**Step 1: Form Generation Route** (`/editor/create_edge_form`)

```python
@router.post("/create_edge_form", response_class=HTMLResponse)
async def create_edge_form(
    qnr_id: Annotated[UUID, Form()],
    source_node_id: Annotated[str, Form()],
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """
    Return HTML form for creating a new edge.
    
    Called when user clicks "Add Edge" button.
    Form includes dropdown of available target nodes.
    """
    # Load graph to enumerate available nodes
    qnr = await get_qnr_by_id(db, qnr_id)
    graph = parse_graph_data(qnr)
    
    # Build dropdown options (all nodes except source)
    node_options = "".join([
        f'<option value="{n.id}">{n.data.text or n.id}</option>'
        for n in graph.nodes
        if n.id != source_node_id
    ])
    
    # Return form HTML
    form_html = f"""
    <form hx-post="/qnr/editor/create_edge" 
          hx-target="#editor-content" 
          hx-swap="innerHTML">
        <input type="hidden" name="qnr_id" value="{qnr_id}">
        <input type="hidden" name="source" value="{source_node_id}">
        
        <div class="form-group">
            <label>Target Node:</label>
            <select name="target" class="form-control" required>
                <option value="">-- Select target node --</option>
                {node_options}
            </select>
        </div>
        
        <div class="form-group">
            <label>Condition (optional):</label>
            <input type="text" name="condition" class="form-control">
        </div>
        
        <button type="submit" class="btn btn-primary">Create Edge</button>
        <button type="button" class="btn btn-secondary"
                hx-get="/qnr/{qnr_id}/editor">Cancel</button>
    </form>
    """
    
    return HTMLResponse(content=form_html)
```

**Step 2: Action Route** (`/editor/create_edge`)

```python
@router.post("/create_edge", response_class=HTMLResponse)
async def create_edge(
    qnr_id: Annotated[UUID, Form()],
    req: CreateEdgeRequest,  # Validated by Pydantic
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """
    Execute edge creation and return updated view.
    
    Called when user submits the form from create_edge_form.
    """
    operation_data = req.model_dump()
    
    # Execute editor workflow
    result = await editor_workflow.ainvoke(
        {
            "qnr_id": qnr_id,
            "operation": "create_edge",
            "operation_data": operation_data,
        },
        config={"configurable": {"db": db}}
    )
    
    # Re-render entire view with new edge
    viewer_result = await viewer_workflow.ainvoke(...)
    return HTMLResponse(content=viewer_result["rendered_html"])
```

### UI Integration

```html
<!-- In side panel template -->
<div class="outgoing-edges">
    <h4>Outgoing Edges</h4>
    <!-- List existing edges here -->
    
    <!-- Add Edge Button triggers form generation -->
    <button hx-post="/qnr/editor/create_edge_form"
            hx-vals='{"source_node_id": "{{ selected_node_id }}", "qnr_id": "{{ qnr_id }}"}'
            hx-target="#new-edge-form"
            hx-swap="innerHTML">
        + Add Edge
    </button>
    
    <!-- Form will be injected here -->
    <div id="new-edge-form"></div>
</div>
```

### Pattern Benefits

1. **Dynamic Forms**: Dropdown options reflect current graph state
2. **Separation of Concerns**: Form rendering separate from business logic
3. **Progressive Enhancement**: Form appears inline without page reload
4. **Validation Before Submit**: Pydantic validates on action route
5. **Consistent UX**: Same pattern for all CRUD operations

### Auditing HTMX Endpoints

When implementing HTMX features, audit all UI interactions:

```bash
# Find all HTMX endpoints in templates and renderer code
grep -r "hx-post=" smeme/templates smeme/qnr/viewer/renderer.py

# Create checklist:
# /qnr/editor/create_edge_form ✅ Implemented
# /qnr/editor/create_edge ✅ Implemented
# /qnr/editor/update_edge_form ✅ Implemented
# /qnr/editor/update_edge ✅ Implemented
# /qnr/editor/delete_edge ✅ Implemented
# ... etc
```

**Missing routes are bugs** - if a UI element calls a route that doesn't exist, the feature is incomplete.

### Complete Two-Step Pattern Examples

**Node Editing:**
- `GET /editor/node/{node_id}/form` → Returns inline editor form
- `POST /editor/update_node` → Saves changes, returns updated view

**Edge Editing:**
- `POST /editor/update_edge_form` → Returns form pre-filled with current values
- `POST /editor/update_edge` → Saves changes, returns updated view

**Edge Creation:**
- `POST /editor/create_edge_form` → Returns form with available targets
- `POST /editor/create_edge` → Creates edge, returns updated view

This pattern is now the standard for all HTMX-driven CRUD operations in the QNR Editor and should be followed for future interactive features.

---

## November 2025 Advanced Patterns (Post-Editor Refactor)

During the QNR Editor UI enhancement work (November 21, 2025), we discovered several critical patterns for HTMX-driven workflows, validation systems, and relationship management. These patterns extend the November 2025 Integration Updates and should be considered standard practice going forward.

### 1. HTMX Out-of-Band (OOB) Swaps for Multi-Part Updates

**Problem**: When an operation affects multiple parts of the UI (e.g., updating an edge should refresh both the side panel AND the graph visualization), returning a single HTML fragment isn't sufficient.

**Solution**: Use HTMX's Out-of-Band swap feature to update multiple page regions simultaneously:

```python
# ❌ WRONG - Only updates one target
@router.post("/update_edge")
async def update_edge(...) -> HTMLResponse:
    result = await editor_workflow.ainvoke(...)
    
    # Only updates #side-panel-content
    return HTMLResponse(content=viewer_result["rendered_html"])

# ✅ RIGHT - Updates multiple targets with OOB swaps
@router.post("/update_edge")
async def update_edge(...) -> HTMLResponse:
    result = await editor_workflow.ainvoke(...)
    
    # Render side panel
    viewer_result = await viewer_workflow.ainvoke(...)
    
    # Render graph SVG
    graph_svg_html = templates.env.get_template("_graph_svg.html").render({
        "graph": result["graph"],
        "visualization": result.get("visualization"),
        "qnr_id": qnr_id,
    })
    
    # Render checklist view
    graph_checklist_html = templates.env.get_template("_graph_checklist.html").render({
        "graph": result["graph"],
        "qnr_id": qnr_id,
    })
    
    # Combine with OOB swaps
    combined_html = f"""
    {viewer_result["rendered_html"]}
    <div id="view-graph" hx-swap-oob="innerHTML">
        {graph_svg_html}
    </div>
    <div id="view-checklist" hx-swap-oob="innerHTML">
        {graph_checklist_html}
    </div>
    """
    
    return HTMLResponse(content=combined_html)
```

**Key Points:**
- Main content goes first (for the primary `hx-target`)
- OOB elements use `hx-swap-oob="innerHTML"` to target specific IDs
- All OOB target elements MUST exist in the DOM (add permanent placeholders if needed)
- This pattern enables "live updates" without full page reloads

**When to Use:**
- ✅ Updating a form + refreshing a visualization
- ✅ Saving data + updating multiple summary displays
- ✅ Any operation that affects multiple UI regions
- ❌ Simple single-target updates (use regular HTMX swap)

### 2. Persistent OOB Target Elements

**Problem**: OOB swaps fail silently if the target element doesn't exist in the DOM. When updating edges, error display divs were missing after HTMX swaps, causing errors to vanish.

**Solution**: Add permanent placeholder divs for all OOB targets in the base template:

```html
<!-- ❌ WRONG - Target only exists when form is shown -->
<form hx-post="/update_edge">
    <!-- Form fields -->
    <div id="edge-error-display"></div>  <!-- Disappears when form closes! -->
</form>

<!-- ✅ RIGHT - Permanent target always in DOM -->
<div id="side-panel-content">
    <!-- Error displays always present -->
    <div id="edge-error-display"></div>
    <div id="new-edge-error-display"></div>
    
    <!-- Dynamic content below -->
    {% if selected_node_id %}
        <!-- Node editor form, edge lists, etc. -->
    {% endif %}
</div>
```

**Best Practice:**
- Add error display divs at the top of containers that receive OOB swaps
- Keep them empty by default (`<div id="error-display"></div>`)
- OOB swaps populate them when needed
- They persist across HTMX content swaps

### 3. Error Display Pattern with HTMX (Status 200 + OOB)

**Problem**: HTMX by default doesn't swap 4xx/5xx responses, causing error messages to be ignored.

**Anti-Pattern (What We Tried):**
```python
# ❌ Doesn't work - HTMX ignores 400 responses
return HTMLResponse(content=error_html, status_code=400)

# ❌ Also doesn't work - clears the main target
return HTMLResponse(
    content='<div id="error-display" hx-swap-oob="true">Error</div>',
    status_code=200
)
```

**Correct Pattern:**
```python
# ✅ WORKS - Returns full side panel + OOB error
if validation_failed:
    # Re-render the side panel with current state
    viewer_result = await viewer_workflow.ainvoke(...)
    
    # Create error HTML
    error_html = f"""
    <div id="edge-error-display" class="alert alert-error">
        <h4>Edge Update Error</h4>
        <p>{error_message}</p>
    </div>
    """
    
    # Inject error into rendered HTML
    side_panel_html = viewer_result["rendered_html"]
    side_panel_html = side_panel_html.replace(
        '<div id="edge-error-display"></div>',
        f'<div id="edge-error-display"></div>\n{error_html}',
        1  # Only first occurrence
    )
    
    return HTMLResponse(content=side_panel_html, status_code=200)
```

**Why This Works:**
1. Returns **200 OK** so HTMX processes the response
2. Includes full side panel HTML for the main target
3. Error is injected into the permanent `#edge-error-display` placeholder
4. No content is cleared, error is visible, user can retry

### 4. Empty String Handling in Validation

**Problem**: HTML forms send empty strings for optional fields, but validation logic checked for `None`, treating `""` as a value requiring validation.

**Example Bug:**
```python
# ❌ WRONG - Empty string triggers validation
if edge.condition is None:
    continue  # Skip validation for default edges

# User submits form with empty condition field
# HTML sends: condition=""
# Validator sees: edge.condition = ""
# Result: Tries to validate "" as a condition → ERROR
```

**Solution**: Treat both `None` and empty strings as "no value":

```python
# ✅ RIGHT - Handle both None and empty strings
if edge.condition is None or not edge.condition.strip():
    continue  # Skip validation for default edges

# Also update has_default checks
has_default = any(
    e.condition is None or not e.condition.strip() 
    for e in edges_out
)

# And has_conditional checks  
has_conditional = any(
    e.condition and e.condition.strip() 
    for e in edges_out
)
```

**Apply Everywhere:**
- Validation rules (skip validation for empty values)
- Default edge detection (count both `None` and `""` as default)
- Conditional edge detection (ignore empty strings)

**Why This Matters:**
- HTML forms ALWAYS send empty strings for unfilled optional fields
- Pydantic can convert `""` to `None`, but database fields may store `""`
- Validation must handle both to work correctly

### 5. Auto-Save Pattern (Google Docs Style)

**Problem**: Explicit "Save Changes" buttons create confusion in multi-form UIs and require users to remember to save.

**Traditional Pattern:**
```html
<!-- ❌ OLD - Multiple save buttons, confusing UX -->
<form hx-post="/update_node">
    <input name="text" />
    <button type="submit">Save Changes</button>
</form>

<form hx-post="/update_edge">
    <input name="condition" />
    <button type="submit">Save</button>
</form>

<!-- User sees two "Save" buttons, unsure which does what -->
```

**Modern Auto-Save Pattern:**
```html
<!-- ✅ NEW - Auto-save with visual feedback -->
<div class="flex items-center justify-between mb-2">
    <div id="form-error-display"></div>
    <div id="save-status" class="text-xs font-medium"></div>
</div>

<form hx-post="/update_node" 
      hx-target="#side-panel-content"
      hx-trigger="change delay:500ms, input delay:2s changed"  <!-- Auto-save triggers -->
      id="node-editor-form">
    <input name="text" />
    <!-- No save button! -->
</form>

<script>
(function() {
    const form = document.getElementById('node-editor-form');
    const statusEl = document.getElementById('save-status');
    
    form.addEventListener('htmx:beforeRequest', function() {
        statusEl.innerHTML = '<span class="text-blue-600">● Saving...</span>';
    });
    
    form.addEventListener('htmx:afterSwap', function() {
        statusEl.innerHTML = '<span class="text-green-600">✓ Saved</span>';
        setTimeout(() => statusEl.innerHTML = '', 2000);
    });
    
    form.addEventListener('htmx:afterRequest', function(evt) {
        if (evt.detail.xhr.status >= 400) {
            statusEl.innerHTML = '<span class="text-red-600">⚠ Error</span>';
        }
    });
})();
</script>

<p class="text-xs text-gray-500 italic">💡 Changes save automatically</p>
```

**Benefits:**
- ✅ No button clutter
- ✅ Clear when changes are saved
- ✅ Modern UX (like Google Docs, Notion)
- ✅ Reduces cognitive load

**When to Use:**
- ✅ Frequently-edited forms (node properties)
- ✅ Single-user workflows (no conflicts)
- ⚠️ Keep explicit save for critical operations (edge creation/deletion)

### 6. Sequential vs Flow-Based Ordering

**Problem**: For the "Checklist View" we initially used BFS (breadth-first search) to traverse the graph from entry nodes. This created a "flow order" based on graph structure. Users wanted simple sequential order (q1, q2, q3...) instead.

**Flow-Based Order (BFS):**
```python
# ❌ Complex - Order depends on graph structure
def get_bfs_order(graph):
    visited = []
    queue = [entry_node_id]
    
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.append(current)
        
        # Add children
        outgoing = [e.target for e in graph.edges if e.source == current]
        queue.extend(outgoing)
    
    return visited  # Returns: ["q1", "q4", "q2", "q3"] (BFS order)
```

**Sequential Order:**
```python
# ✅ Simple - Alphabetical/numerical order
def get_sequential_order(graph):
    return sorted(graph.nodes, key=lambda n: n.id)
    # Returns: ["q1", "q2", "q3", "q4"] (sorted)
```

**In Jinja2:**
```html
{# ✅ Simple and predictable #}
{% set sorted_nodes = graph.nodes|sort(attribute='id') %}
{% for node in sorted_nodes %}
    <!-- Render question card -->
{% endfor %}
```

**When to Use Each:**
| View Type | Ordering | Reason |
|-----------|----------|--------|
| **Checklist/Preview** | Sequential | Users scan linearly, easy to find "Q5" |
| **Graph Visualization** | Flow-based | Shows actual execution flow |
| **Validation Messages** | Node-specific | Group by affected node |
| **Export/Print** | Sequential | Professional document format |

**Key Insight**: Don't conflate *graph execution order* with *human reading order*. They serve different purposes.

### 7. `lazy="raise"` as Default for SQLAlchemy Relationships

**Problem Discovered**: Using `lazy="selectin"` (eager loading) as default caused unintended side effects. When updating a parent object, SQLAlchemy would flush ALL loaded children, updating their `updated_at` timestamps even though they weren't modified.

**Example Bug:**
```python
# Relationships with lazy="selectin" (eager by default)
sessions: list["QNRSession"] = Relationship(
    back_populates="qnr",
    sa_relationship_kwargs={"lazy": "selectin"},  # Always loads!
)

# Later in code:
qnr = await get_qnr_by_id(db, qnr_id)  # Loads QNR + all 1000 sessions
qnr.is_current = False                  # Modify QNR
await db.commit()
# BUG: All 1000 sessions get updated_at refreshed! ❌
```

**Solution**: Use `lazy="raise"` by default, explicit `selectinload` when needed:

```python
# ✅ Relationships raise error if accessed without explicit load
sessions: list["QNRSession"] = Relationship(
    back_populates="qnr",
    sa_relationship_kwargs={"lazy": "raise"},  # Prevents accidents
)

# Explicit loading only when needed
qnr = await db.execute(
    select(QNR)
    .options(selectinload(QNR.sessions))  # Load only when needed
    .where(QNR.id == qnr_id)
)
qnr = result.scalar_one()

# Now sessions are loaded, but intentionally
```

**When to Use Each:**
```python
# lazy="raise" (DEFAULT) - Prevents accidental loads
children: list["QNR"] = Relationship(
    sa_relationship_kwargs={"lazy": "raise"}
)

# lazy="selectin" (ONLY for frequently-accessed, small relationships)
parent: Optional["QNR"] = Relationship(
    sa_relationship_kwargs={"lazy": "selectin"}  # Parent is always needed
)

# Explicit selectinload (WHEN YOU ACTUALLY NEED IT)
qnr = await db.execute(
    select(QNR)
    .options(selectinload(QNR.sessions))
    .where(...)
)
```

**Why This Matters:**
- Prevents "why did unrelated records get updated?" bugs
- Forces you to think about relationship access patterns
- Makes database queries explicit and traceable
- Avoids N+1 query performance issues

### 8. Chained `selectinload` for Nested Relationships

**Critical Pattern**: When accessing `session.qnr.parent` in templates or workflows, you MUST chain `selectinload` to load nested relationships. Otherwise: `MissingGreenlet` error.

```python
# ❌ WRONG - Only loads immediate relationship
result = await db.execute(
    select(QNRSession)
    .options(selectinload(QNRSession.qnr))  # Loads qnr
    .where(...)
)

# Later in template:
# {{ session.qnr.parent.title }}  ← MissingGreenlet! parent not loaded

# ✅ RIGHT - Chain selectinload for nested relationships
result = await db.execute(
    select(QNRSession)
    .options(
        selectinload(QNRSession.qnr).selectinload(QNR.parent),  # Chain!
        selectinload(QNRSession.qnr).selectinload(QNR.children),
    )
    .where(...)
)

# Now {{ session.qnr.parent.title }} works! ✓
```

**Rule of Thumb:**
> If you access `object.relationship.nested_relationship` anywhere (routes, templates, workflows), you MUST use chained `selectinload` when fetching `object`.

### 9. Validation System Architecture

Our validation system evolved to be type-aware and context-aware:

**Validation Categories:**
```python
def validate_graph_for_editing(graph: QNRGraph):
    """
    Two-tier validation:
    - ERRORS: Block publication (must fix)
    - WARNINGS: Suggest improvements (can publish)
    """
    errors = []
    warnings = []
    
    # Type-aware default edge requirements
    for node in question_nodes:
        edges_out = [e for e in graph.edges if e.source == node.id]
        has_conditional = any(e.condition and e.condition.strip() for e in edges_out)
        has_default = any(e.condition is None or not e.condition.strip() for e in edges_out)
        
        if node.data.type == "radio":
            # Radio: Default not required if all options covered
            conds = {e.condition.strip() for e in edges_out if e.condition}
            options_set = set(node.data.options or [])
            if conds != options_set and not has_default:
                warnings.append(f"Radio '{node.id}' missing default edge")
        
        elif node.data.type in ("checkbox", "text", "number"):
            # Checkbox/text/number: Always require default if conditional exists
            if has_conditional and not has_default:
                errors.append(f"Question '{node.id}' needs default edge")
```

**Key Principles:**
1. **Empty strings are defaults** - Treat `""` same as `None`
2. **Type-aware rules** - Radio vs checkbox have different requirements
3. **Two-tier severity** - Errors block publish, warnings don't
4. **Node-specific extraction** - Extract which nodes have issues for UI indicators
5. **Categorization** - Group by type (Structure, Edges, Content, etc.)

### 10. Edge Identification with Conditions

**Critical Bug We Fixed**: When updating edges, we initially identified them by `(source, target)` only. But graphs can have multiple edges between the same nodes with different conditions!

```python
# ❌ WRONG - Ambiguous when multiple conditions exist
edge_index = next(
    (i for i, e in enumerate(graph.edges) 
     if e.source == source and e.target == target),
    None
)

# With edges:
# q4 -> q5 (condition="Yes")
# q4 -> q5 (condition="No")
# 
# Updating "Yes" to "Maybe" creates a THIRD edge! Bug!

# ✅ RIGHT - Include old_condition for unique identification
edge_index = next(
    (i for i, e in enumerate(graph.edges) 
     if e.source == source 
     and e.target == target 
     and e.condition == old_condition),  # ← Critical!
    None
)
```

**Update Request Model:**
```python
@as_form
class UpdateEdgeRequest(BaseModel):
    qnr_id: UUID
    source: str
    old_target: str
    old_condition: str | None  # ← Include old value
    new_target: str
    new_condition: str | None
```

**Why This Matters:**
- Graphs can have parallel edges with different conditions
- `(source, target)` alone is NOT unique
- Must include `old_condition` to identify which edge to update
- This is a common graph database pattern (labeled edges)

### 11. LangGraph TypedDict as Silent Data Filter ⚠️

**Most Important Debugging Lesson**: When data disappears between LangGraph nodes, check the TypedDict state definition FIRST!

**The Problem:**
```python
# workflow.py - Node returns data
def generate_visualization_node(state: QNRViewerState, config: RunnableConfig):
    """Generate visualization and validation status"""
    validation_data = validate_graph(state["graph"])
    node_validation_status = get_node_validation_status(validation_data)
    
    return {
        "visualization": generate_svg(state["graph"]),
        "node_validation_status": node_validation_status,  # ← Returned!
    }

# models.py - TypedDict missing field
class QNRViewerState(TypedDict):
    qnr_id: UUID
    graph: QNRGraph
    visualization: NotRequired[str]
    # ❌ node_validation_status NOT defined
    # Result: DATA SILENTLY DROPPED!

# Template gets {} for node_validation_status
# Warnings don't display, hours wasted debugging templates
```

**The Fix:**
```python
# ✅ Add missing field to TypedDict
class QNRViewerState(TypedDict):
    qnr_id: UUID
    graph: QNRGraph
    visualization: NotRequired[str]
    node_validation_status: NotRequired[dict[str, dict[str, list[str]]]]  # ← Added!
    
# Now data flows through correctly! ✓
```

**Why This is Insidious:**
1. **Silent Failure** - No errors, warnings, or logs
2. **Data appears to exist** - Debugging shows it in node return
3. **Templates look correct** - Context passing syntax is fine
4. **Wrong debugging path** - Waste time on Jinja2, OOB swaps, etc.
5. **Hard to spot** - TypedDict is far from template rendering code

**Debugging Checklist (Always Start Here):**
```
When data is missing in templates/downstream nodes:

✅ 1. Check TypedDict state definition FIRST
✅ 2. Verify all node returns are declared in TypedDict
✅ 3. Match field names exactly between returns and TypedDict
✅ 4. Use NotRequired[] for optional fields
❌ 5. Template debugging (only if above checks pass)
❌ 6. Context passing (only if above checks pass)
```

**Real Example That Wasted 30 Minutes:**
```python
# Problem: Checklist warnings not appearing
# Wrong Path: Debug templates, add explicit context passing, check OOB swaps
# Right Path: Check QNRViewerState → missing node_validation_status → add it → fixed!
```

**Rule of Thumb:**
> **Follow the dataflow through the datastructures!** LangGraph TypedDict is a strict filter, not a documentation aid. Any field not declared is silently dropped at node boundaries.

**Additional TypedDict Gotchas:**
```python
# ❌ Typo in field name
return {"node_validations": data}  # TypedDict expects "node_validation_status"

# ❌ Wrong type
return {"count": "5"}  # TypedDict expects int

# ❌ Missing NotRequired for optional
class State(TypedDict):
    required_field: str
    optional_field: str  # ← Should be NotRequired[str]
    
# Result: Must return optional_field even when not needed
```

**Best Practice:**
- Add comprehensive type hints to TypedDict immediately
- When adding node returns, update TypedDict in same commit
- Use `NotRequired[]` liberally for optional data
- Consider TypedDict as contract between nodes, not just typing
- When debugging missing data, **always trace dataflow through TypedDict first**

---

## Summary of November 21, 2025 Patterns

These patterns emerged from real bugs and UX issues during the QNR Editor enhancement:

1. **HTMX OOB Swaps** - Update multiple UI regions simultaneously
2. **Persistent OOB Targets** - Always have placeholder divs in DOM
3. **Error Display (200 + OOB)** - Return full content + inject errors
4. **Empty String Handling** - Treat `""` same as `None` in validation
5. **Auto-Save Pattern** - Remove buttons, show save indicators
6. **Sequential vs Flow Order** - Choose based on user's mental model
7. **`lazy="raise"` Default** - Prevent accidental relationship loads
8. **Chained `selectinload`** - Load nested relationships explicitly
9. **Type-Aware Validation** - Different rules for radio vs checkbox
10. **Edge Identification** - Include `old_condition` for uniqueness
11. **TypedDict as Data Filter** ⚠️ - Always check state definitions first when debugging missing data

These are now considered **standard patterns** for LangGraph + HTMX + SQLAlchemy workflows in the project.

**Most Important Debugging Rule**: When data disappears between LangGraph nodes or doesn't reach templates, **always trace the dataflow through TypedDict definitions first** before debugging templates or context passing.

---

## Human-in-the-Loop with `interrupt()` (November 30, 2025)

### The Correct Pattern: `interrupt()` Inside Nodes

When implementing multi-step workflows with human editing (e.g., LLM generates content → user reviews/edits → workflow continues), use `interrupt()` inside nodes:

```python
from langgraph.types import interrupt

async def wait_for_factors_edit_node(state: AgenticState) -> dict:
    """Pause for user to review/edit factors."""
    factors_summary = state.get("factors_summary", "")
    
    # interrupt() pauses workflow and returns the edited value when resumed
    edited_factors = interrupt(factors_summary)
    
    # After resume, edited_factors contains what was passed to Command(resume=...)
    return {"factors_edited": edited_factors}
```

### Key Insight: `interrupt()` Return Value (NOT Exception!)

**⚠️ CRITICAL (LangGraph 2024+ behavior):** `interrupt()` does NOT raise `GraphInterrupt` anymore. Instead:

1. `ainvoke()` returns normally with `__interrupt__` key in the result
2. The interrupt value is in `result["__interrupt__"][0].value`
3. When resumed with `Command(resume=value)`, `interrupt()` **returns** that value

```python
# ❌ OLD PATTERN (doesn't work in modern LangGraph)
try:
    await workflow.ainvoke(state, config)
except GraphInterrupt as e:
    interrupt_value = e.value  # This exception is never raised!

# ✅ NEW PATTERN (correct)
result = await workflow.ainvoke(state, config)
if result.get("__interrupt__"):
    interrupt_value = result["__interrupt__"][0].value
```

### Why NOT `interrupt_before`?

We initially tried `interrupt_before` in graph compilation, but discovered issues:

1. **`Command(resume=dict)` doesn't merge into state** - The dict passed to `Command(resume={...})` isn't merged into workflow state
2. **Data loss** - The "receive" node doesn't see the edited values
3. **Confusing flow** - Unclear when nodes run vs when resume happens

```python
# ❌ DOESN'T WORK - interrupt_before + Command(resume=dict)
workflow.compile(
    checkpointer=memory,
    interrupt_before=["receive_human_edit"],
)

# Route tries to pass edited data:
await workflow.ainvoke(Command(resume={"edited_field": "user text"}), config)

# But receive_human_edit_node sees NOTHING:
async def receive_human_edit_node(state):
    print(state.get("edited_field"))  # None! Data was lost
```

### The Correct Pattern: `interrupt()` Inside Nodes

Instead, use `interrupt()` inside nodes. The value passed to `Command(resume=...)` is **returned** by `interrupt()`:

```python
from langgraph.types import interrupt

async def wait_for_edit_node(state: MyState) -> dict:
    """Pause and wait for user edit."""
    original_content = state.get("generated_content", "")
    
    # Pause workflow - original_content sent to route
    # When resumed, interrupt() returns the value from Command(resume=...)
    edited_content = interrupt(original_content)
    
    return {"edited_content": edited_content}
```

### HTMX Route Integration

The route handler orchestrates the interrupt/resume cycle:

```python
from langgraph.types import Command, Interrupt
from uuid import uuid4

# Step 1: Start workflow - runs until interrupt() is called
@router.post("/generate", response_class=HTMLResponse)
async def start_generation(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    openai_client: OpenAIClientDep,
    user_prompt: str = Form(...),
):
    thread_id = str(uuid4())
    
    config = {
        "configurable": {
            "thread_id": thread_id,
            "db": db,
            "openai_client": openai_client,
        }
    }
    
    initial_state = {"user_prompt": user_prompt}
    
    # Run workflow - returns when interrupt() is called
    result = await workflow.ainvoke(initial_state, config)
    
    # Check for interrupt (new LangGraph pattern)
    interrupts = result.get("__interrupt__", [])
    if interrupts:
        # Workflow paused - get the value passed to interrupt()
        interrupt_obj: Interrupt = interrupts[0]
        generated_content = interrupt_obj.value
        
        # Render edit form
        return templates.TemplateResponse(
            "edit_form.html",
            {
                "request": request,
                "thread_id": thread_id,
                "generated_content": generated_content,
            },
        )
    
    # Handle error or unexpected completion
    return templates.TemplateResponse("error.html", {...})


# Step 2: Resume workflow after user edit
@router.post("/submit_edit", response_class=HTMLResponse)
async def submit_edit(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    thread_id: str = Form(...),
    edited_content: str = Form(...),
):
    config = {
        "configurable": {
            "thread_id": thread_id,
            "db": db,
        }
    }
    
    # Resume workflow - pass edited value DIRECTLY (not dict!)
    # This value is RETURNED by interrupt() in the paused node
    result = await workflow.ainvoke(
        Command(resume=edited_content),  # ← String, not dict!
        config,
    )
    
    # Check for another interrupt or completion
    if result.get("__interrupt__"):
        # Another human-in-the-loop step...
        pass
    
    # Get final state
    state_snapshot = await workflow.aget_state(config)
    state = state_snapshot.values
    
    return templates.TemplateResponse(
        "result.html",
        {"request": request, "result": state.get("final_result")},
    )
```

### Flow Visualization

```
┌─────────────────────────────────────────────────────────────────┐
│                      HTMX Request Flow                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  POST /generate                                                 │
│    │                                                            │
│    ▼                                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ LangGraph Workflow                                       │   │
│  │  START                                                   │   │
│  │    │                                                     │   │
│  │    ▼                                                     │   │
│  │  generate_content (LLM call)                             │   │
│  │    │                                                     │   │
│  │    ▼                                                     │   │
│  │  wait_for_edit_node:                                     │   │
│  │    edited = interrupt(generated_content) ◄── PAUSE       │   │
│  │    │                                                     │   │
│  │    (workflow returns with __interrupt__)                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│    │                                                            │
│    ▼                                                            │
│  result["__interrupt__"][0].value → generated_content           │
│    │                                                            │
│    ▼                                                            │
│  Return HTML form with generated_content                        │
│                                                                 │
│  ════════════════════════════════════════════════════════════  │
│  ║               USER EDITS IN BROWSER                      ║  │
│  ════════════════════════════════════════════════════════════  │
│                                                                 │
│  POST /submit_edit (thread_id, edited_content)                  │
│    │                                                            │
│    ▼                                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ LangGraph Workflow (resumed)                             │   │
│  │                                                          │   │
│  │  Command(resume="edited content")                        │   │
│  │    │                                                     │   │
│  │    ▼                                                     │   │
│  │  wait_for_edit_node (continues):                         │   │
│  │    edited = interrupt(...) ← returns "edited content"    │   │
│  │    return {"edited_content": edited}                     │   │
│  │    │                                                     │   │
│  │    ▼                                                     │   │
│  │  process_result                                          │   │
│  │    │                                                     │   │
│  │    ▼                                                     │   │
│  │  END                                                     │   │
│  └─────────────────────────────────────────────────────────┘   │
│    │                                                            │
│    ▼                                                            │
│  aget_state() → {final_result: "..."}                           │
│    │                                                            │
│    ▼                                                            │
│  Return result HTML                                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Key Points

1. **Use `interrupt()` inside nodes** - Not `interrupt_before` in compilation
2. **Check `result["__interrupt__"]`** - NOT try/except GraphInterrupt
3. **`Command(resume=value)` is returned by `interrupt()`** - Pass value directly, not dict
4. **Thread ID is critical** - Must match between start and resume calls
5. **MemorySaver enables pause/resume** - For production, use persistent checkpointer
6. **`interrupt(original)` returns `edited`** - The resume value becomes the return value

### Multiple Interrupt Points

For workflows with multiple human-in-the-loop steps:

```python
workflow.compile(
    checkpointer=memory,
    interrupt_before=[
        "receive_factors_edit",    # First human input
        "receive_design_edit",     # Second human input
    ],
)
```

Each interrupt point follows the same pattern:
1. `ainvoke()` runs until hitting next `interrupt_before`
2. `aget_state()` gets current state
3. User edits in UI
4. `ainvoke(Command(resume=...))` continues to next interrupt or END

### Error Handling

```python
try:
    await workflow.ainvoke(initial_state, config)
    state_snapshot = await workflow.aget_state(config)
    state = state_snapshot.values
    
    # Check for workflow errors
    if state.get("error"):
        return templates.TemplateResponse(
            "error.html",
            {"error_message": state["error"]},
        )
    
    # Render success
    return templates.TemplateResponse(...)
    
except Exception as e:
    logger.error("Workflow failed", extra={"error": str(e)}, exc_info=True)
    return templates.TemplateResponse(
        "error.html",
        {"error_message": "An unexpected error occurred."},
    )
```

### When to Use This Pattern

✅ **Use `interrupt_before` when:**
- Building multi-step wizards with user review
- LLM generates content that users should verify/edit
- Implementing approval workflows
- Any human-in-the-loop scenario

❌ **Don't use when:**
- Simple request/response (no pause needed)
- Fully automated workflows
- Real-time streaming (use streaming instead)

### Testing Interrupted Workflows

```python
@pytest.mark.asyncio
async def test_workflow_interrupt_resume():
    """Test workflow pauses and resumes correctly."""
    workflow = build_workflow()
    
    config = {"configurable": {"thread_id": "test-123"}}
    initial_state = {"user_prompt": "Test prompt"}
    
    # Run until first interrupt
    await workflow.ainvoke(initial_state, config)
    state = (await workflow.aget_state(config)).values
    
    # Verify paused state
    assert "generated_content" in state
    assert state["generated_content"] != ""
    
    # Resume with edit
    await workflow.ainvoke(
        Command(resume={"edited_content": "User edited this"}),
        config,
    )
    final_state = (await workflow.aget_state(config)).values
    
    # Verify completion
    assert "final_result" in final_state
    assert final_state["edited_content"] == "User edited this"
```

### Summary

The `interrupt()` inside nodes pattern provides:
- **Clean data flow** - `interrupt(original)` returns the edited value
- **Predictable flow** - Workflow pauses at `interrupt()`, resumes when `Command(resume=...)` is called
- **Testability** - Easy to test each phase independently
- **Type safety** - Resume value is returned, not magically merged into state

**Critical Rules:**
1. `interrupt()` does NOT raise exceptions in modern LangGraph - check `result["__interrupt__"]`
2. `Command(resume=value)` makes `interrupt()` **return** that value
3. Pass the value directly to `Command(resume=...)`, NOT as a dict
4. The node continues executing after `interrupt()` returns

---

## 24. Explicit Phase Tracking (Sprint 6)

### Why Phase Tracking?

Without explicit phase tracking, you must infer the current phase from node names or state fields. This is fragile and makes debugging harder. Sprint 6 introduced explicit phase tracking for:

- **Always know current phase** - No inference needed
- **Phase transitions explicitly logged** - Clear audit trail
- **UI can reliably show progress** - Phase-based progress indicators
- **Analytics can track phase duration** - Performance insights
- **Debugging is clearer** - "Stuck in research phase" vs "stuck somewhere"

### Implementation Pattern

#### 1. Define Phase Enum

```python
# In models.py
from typing import Literal

QNRGenerationPhase = Literal[
    "research",      # Phase 1: Research + augmentation
    "conclusions",   # Phase 1.5: Conclusion extraction
    "design",        # Phase 2: Questionnaire design
    "build",         # Phase 3: Graph building + validation
    "complete",      # Phase 4: Successfully saved
    "error",         # Terminal error state
]
```

#### 2. Add Phase Fields to State

```python
class AgenticQNRGenerationState(TypedDict, total=False):
    # ... existing fields ...
    
    # Phase Tracking (Sprint 6)
    current_phase: NotRequired[QNRGenerationPhase]  # Explicit current phase
    phase_start_time: NotRequired[float]  # For duration tracking
    phase_history: Annotated[NotRequired[list[dict]], add]  # Full audit trail
```

#### 3. Create Phase Tracker Nodes

Phase tracker nodes are lightweight functions that explicitly update the current phase:

```python
import time

def set_research_phase(state: AgenticQNRGenerationState) -> dict:
    """Transition to research phase."""
    current_time = time.time()
    previous_phase = state.get("current_phase")
    
    phase_transition = {
        "from": previous_phase,
        "to": "research",
        "timestamp": current_time,
    }
    
    logger.info(
        "Phase transition: research",
        extra={
            "user_id": state.get("user_id"),
            "from_phase": previous_phase,
            "to_phase": "research",
        },
    )
    
    return {
        "current_phase": "research",
        "phase_start_time": current_time,
        "phase_history": [phase_transition],
    }

def set_conclusions_phase(state: AgenticQNRGenerationState) -> dict:
    """Transition to conclusions phase."""
    current_time = time.time()
    previous_phase = state.get("current_phase")
    phase_start = state.get("phase_start_time", current_time)
    phase_duration = current_time - phase_start
    
    phase_transition = {
        "from": previous_phase,
        "to": "conclusions",
        "timestamp": current_time,
        "previous_phase_duration_seconds": round(phase_duration, 2),
    }
    
    logger.info(
        "Phase transition: conclusions",
        extra={
            "user_id": state.get("user_id"),
            "from_phase": previous_phase,
            "to_phase": "conclusions",
            "previous_phase_duration": phase_duration,
        },
    )
    
    return {
        "current_phase": "conclusions",
        "phase_start_time": current_time,
        "phase_history": [phase_transition],
    }
```

#### 4. Wire Phase Trackers into Workflow

```python
def build_workflow():
    workflow = StateGraph(AgenticQNRGenerationState)
    
    # Add phase tracker nodes
    workflow.add_node("set_research_phase", set_research_phase)
    workflow.add_node("set_conclusions_phase", set_conclusions_phase)
    workflow.add_node("set_design_phase", set_design_phase)
    workflow.add_node("set_build_phase", set_build_phase)
    workflow.add_node("set_complete_phase", set_complete_phase)
    
    # Wire them before each major phase
    workflow.add_edge(START, "set_research_phase")
    workflow.add_edge("set_research_phase", "research_subgraph")
    
    workflow.add_edge("wait_for_research_edit", "set_conclusions_phase")
    workflow.add_edge("set_conclusions_phase", "conclusions_subgraph")
    
    # ... and so on
    
    return workflow
```

### Benefits

✅ **Explicit tracking** - `current_phase` always accurate  
✅ **Duration tracking** - Know how long each phase takes  
✅ **Audit trail** - `phase_history` records all transitions  
✅ **Better logging** - Phase context in all log messages  
✅ **UI progress** - Reliably show "Currently in: Design Phase"  

### Best Practices

1. **Always add phase tracker before major phase changes**
2. **Log phase transitions** - Makes debugging much easier
3. **Track phase duration** - Helps identify bottlenecks
4. **Don't skip phase trackers** - Even if phase seems obvious
5. **Use phase in interrupt payloads** - For routing verification

---

## 25. Standardized Interrupt Payloads (Sprint 6)

### Why Standardize Interrupts?

Before Sprint 6, interrupt payloads were ad-hoc dicts or strings. This made routing logic fragile and hard to maintain. Standardized interrupts provide:

- **Type safety** - Pydantic validation at interrupt boundaries
- **Consistent structure** - Same fields across all interrupts
- **Better routing** - Phase verification, error handling
- **Backward compatibility** - Old checkpoints continue to work

### InterruptPayload Model

```python
from pydantic import BaseModel, Field
from typing import Literal, Any

class InterruptPayload(BaseModel):
    """Standardized interrupt payload for all human-in-the-loop waits."""
    
    phase: Literal["research", "conclusions", "design", "build"] = Field(
        ...,
        description="Which phase is interrupting (for routing verification)",
    )
    user_id: str = Field(
        ...,
        description="User who owns this generation (for authorization checks)",
    )
    action_required: str = Field(
        ...,
        description="What user needs to do (e.g., 'Edit research factors')",
    )
    data_to_edit: dict[str, Any] = Field(
        default_factory=dict,
        description="Phase-specific data user can edit",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context (e.g., augmentation_count, token_usage)",
    )
```

### Using InterruptPayload in Wait Nodes

```python
async def wait_for_research_edit_node(state: AgenticQNRGenerationState) -> dict:
    """Pause for user to review/edit research factors."""
    research_context = state.get("research_context", "")
    augmentation_count = state.get("augmentation_count", 0)
    
    # Build standardized interrupt payload
    payload = InterruptPayload(
        phase="research",
        user_id=state["user_id"],
        action_required="Edit research factors and decide whether to continue or augment",
        data_to_edit={"research_context": research_context},
        metadata={
            "augmentation_count": augmentation_count,
            "search_skipped": state.get("search_skipped", False),
            "extraction_used": state.get("extraction_used", False),
        },
    )
    
    # Interrupt with payload (converts to dict automatically)
    result = interrupt(payload.model_dump())
    
    # Result is a dict from Command(resume=...) with user edits
    return result if isinstance(result, dict) else {}
```

### Handling InterruptPayload in Routes (with Backward Compatibility)

```python
@router.post("/generate", response_class=HTMLResponse)
async def start_generation(...):
    result = await workflow.ainvoke(initial_state, config)
    
    interrupts = result.get("__interrupt__", [])
    if interrupts:
        interrupt_obj: Interrupt = interrupts[0]
        
        # Try Sprint 6 format (InterruptPayload)
        if isinstance(interrupt_obj.value, dict):
            try:
                payload = InterruptPayload(**interrupt_obj.value)
                # Extract data from payload
                research_context = payload.data_to_edit.get("research_context", "")
                augmentation_count = payload.metadata.get("augmentation_count", 0)
                logger.info(f"Using InterruptPayload format: {payload.phase}")
            except Exception as e:
                # Fall back to legacy format
                logger.warning(f"InterruptPayload validation failed: {e}")
                research_context = state.get("research_context", "")
                augmentation_count = state.get("augmentation_count", 0)
        elif isinstance(interrupt_obj.value, str):
            # Legacy format: interrupt.value is the data directly
            research_context = interrupt_obj.value
            augmentation_count = state.get("augmentation_count", 0)
        
        # Render edit form with extracted data
        return templates.TemplateResponse(...)
```

### Benefits

✅ **Type safety** - Pydantic validates structure  
✅ **Consistent API** - Same fields across all interrupts  
✅ **Better errors** - Validation errors at interrupt boundaries  
✅ **Backward compat** - Old checkpoints still work  
✅ **Clear contracts** - Know exactly what data is available  

### Best Practices

1. **Always use InterruptPayload** - Don't pass raw strings/dicts
2. **Include phase in payload** - For routing verification
3. **Put editable data in `data_to_edit`** - Clear separation
4. **Put context in `metadata`** - For display, not editing
5. **Handle legacy format** - For backward compatibility during migrations

---

## 26. Workflow Versioning (Sprint 6)

### Why Version Workflows?

Workflows evolve over time (new nodes, new state fields, bug fixes). Version tracking enables:

- **Safe migrations** - Know which version generated each QNR
- **Debugging** - "This bug only affects v1.0.0"
- **Rollbacks** - Can identify workflows needing migration
- **Analytics** - Track adoption of new workflow versions

### Implementation Pattern

#### 1. Define Workflow Version Constant

```python
# In workflow.py

# Semantic version for workflow code
# Increment when making changes:
# - MAJOR: Breaking changes (state schema changes, node removals)
# - MINOR: New features (new nodes, new state fields with defaults)
# - PATCH: Bug fixes, performance improvements
WORKFLOW_VERSION = "1.0.0"
```

#### 2. Add Version Fields to Database Model

```python
# In models.py (InProgressQNRGeneration)

class InProgressQNRGeneration(BaseSQLModel, table=True):
    # ... existing fields ...
    
    # Workflow versioning (Sprint 6)
    workflow_version: str = SQLField(
        max_length=50,
        default="1.0.0",
        description="Semantic version of workflow code",
    )
    
    workflow_updated_at: datetime | None = SQLField(
        default=None,
        nullable=True,
        description="Timestamp when workflow was last updated/migrated",
        sa_type=DateTime(timezone=True),
    )
```

#### 3. Track Version When Creating Generation

```python
from smeme.qnr.generation.agentic.workflow import WORKFLOW_VERSION

async def start_new_generation(db, user_id, user_prompt):
    in_progress_gen = InProgressQNRGeneration(
        user_id=user_id,
        user_prompt_preview=user_prompt[:200],
        workflow_version=WORKFLOW_VERSION,  # Track current version
        # ... other fields ...
    )
    db.add(in_progress_gen)
    await db.commit()
    return in_progress_gen
```

#### 4. Version-Specific Logic (if needed)

```python
async def resume_workflow(thread_id: str):
    # Get workflow version from database
    in_progress_gen = await get_generation_by_thread_id(thread_id)
    
    if in_progress_gen.workflow_version == "0.9.0":
        # Old version - migrate or handle differently
        logger.warning(f"Old workflow version: {in_progress_gen.workflow_version}")
        # Could trigger migration, use compatibility shim, etc.
    
    # Continue with workflow
    workflow = await get_compiled_workflow()
    result = await workflow.ainvoke(Command(resume=...))
```

### When to Increment Version

| Change Type | Version Increment | Example |
|------------|-------------------|---------|
| **Breaking change** | MAJOR (1.0.0 → 2.0.0) | Remove state field, change state schema |
| **New feature** | MINOR (1.0.0 → 1.1.0) | Add new node, add state field (with default) |
| **Bug fix** | PATCH (1.0.0 → 1.0.1) | Fix validation logic, improve error handling |

### Benefits

✅ **Migration tracking** - Know which workflows need updates  
✅ **Debugging** - Filter logs by workflow version  
✅ **Analytics** - Track version adoption  
✅ **Safe rollbacks** - Can identify workflows on old versions  
✅ **Production confidence** - Clear version history  

### Best Practices

1. **Use semantic versioning** - MAJOR.MINOR.PATCH
2. **Track version in database** - For every generation
3. **Log version in all operations** - Makes debugging easier
4. **Plan migrations** - For breaking changes
5. **Document version changes** - Maintain a CHANGELOG

