# Lessons Learned

Hard-won insights from building the SMEme Platform. This document is optimized for AI coding assistants - consolidating gotchas, patterns that worked, and mistakes to avoid.

**Doc stack:** Use with [ARCHITECTURE.md](ARCHITECTURE.md) (*system map*) and [DECISIONS.md](DECISIONS.md) (*ADRs*) as the **working-memory set** for task and harness context; deeper topic files live under `docs/architecture/` and `docs/guides/`.

**Last Updated**: 2026-07-06 (§12: CSS is pre-built Tailwind, not the CDN — see D020)

---

## Table of Contents

1. [LangGraph Patterns](#langgraph-patterns)
2. [Database & Migrations](#database--migrations)
3. [Dependency Stack Gotchas](#dependency-stack-gotchas)
4. [LLM Integration](#llm-integration)
5. [Authentication](#authentication)
6. [Deployment & CI/CD](#deployment--cicd)
7. [Code Organization](#code-organization)
8. [What Didn't Work](#what-didnt-work)
9. [Testing with pytest-asyncio](#testing-with-pytest-asyncio)
10. [Public Gallery & HTMX Patterns](#public-gallery--htmx-patterns)
11. [Email Verification & Password Reset](#email-verification--password-reset)
12. [Design System & Component Library](#design-system--component-library)
13. [Stripe & Payments](#stripe--payments)
14. [Considerations](#considerations)
15. [Deterministic Reasoning (Z3)](#deterministic-reasoning-z3)
16. [MCP OAuth 2.1 Discovery and Bearer Auth (DR-3)](#mcp-oauth-21-discovery-and-bearer-auth-dr-3)
17. [MCP: DCR (`registration_endpoint`) and Cursor](#mcp-dcr-registration-endpoint-and-cursor)
17b. [CIMD research (Client ID Metadata Documents) — July 2026](#cimd-research-client-id-metadata-documents--july-2026)
18. [Modal Navigation & HTMX UX](#modal-navigation--htmx-ux)
19. [MCP Hardening: Auth, Transport & Misconfiguration (security review)](#mcp-hardening-auth-transport--misconfiguration-security-review)
20. [Cowork Plugin Delivery: Hosts, Versions & Drift](#cowork-plugin-delivery-hosts-versions--drift)
21. [Cowork-Facing Copy & MCP Error Design](#cowork-facing-copy--mcp-error-design)
22. [Cowork Harness Discovery: Deferred Tool Loading](#cowork-may-defer-loading-smeme_reasoning_evaluate--reasoningtools-is-the-authoritative-catalog)

---

## LangGraph Patterns

### TypedDict is a Silent Data Filter

**Problem**: Any field not declared in your TypedDict state will be **silently dropped** between nodes.

```python
# If state declares only these fields:
class MyState(TypedDict):
    input: str
    output: str

# And a node returns:
return {"input": "x", "output": "y", "debug_info": "z"}

# The next node will NOT see debug_info - it's gone!
```

**Solution**: Declare ALL fields your workflow needs in the state TypedDict, even optional ones with `NotRequired`.

---

### Never Put Database Sessions in State

**Problem**: `AsyncSession` objects are not serializable. If you put them in state, workflow persistence/checkpointing breaks.

```python
# WRONG - will break checkpointing
class State(TypedDict):
    db: AsyncSession  # NO!

# RIGHT - pass via RunnableConfig
async def my_node(state: State, config: RunnableConfig) -> dict:
    db: AsyncSession = config["configurable"]["db"]
```

**Rule**: State = serializable data only. Config = dependencies (db, clients, user_id).

---

### Dependency Injection via RunnableConfig

**Pattern**: Create dependencies at route level, pass via `config["configurable"]`.

```python
# In route
@router.post("/generate")
async def generate(
    db: AsyncSession = Depends(get_async_session),
    openai_client: AsyncOpenAI = Depends(get_openai_client),
    user: User = Depends(current_active_user),
):
    result = await workflow.ainvoke(
        initial_state,
        config={
            "configurable": {
                "db": db,
                "openai_client": openai_client,
                "user_id": user.id,
            }
        }
    )

# In node - extract from config
async def my_node(state: MyState, config: RunnableConfig) -> dict:
    db = config["configurable"]["db"]
    openai_client = config["configurable"]["openai_client"]
```

---

### Separate Workflows for Read vs Write

**Pattern**: Don't mix read-only operations with write operations in one workflow.

| Workflow | Purpose | Characteristics |
|----------|---------|-----------------|
| **Viewer** | Read-only display | Fast, cacheable, no writes |
| **Editor** | Modifications | Fresh data, validation, saves |

**Benefits**:
- Clear boundaries
- Better caching (viewer can cache aggressively)
- Simpler state management
- Independent scaling

---

### Validation Retry with Conditional Edges

**Pattern**: Use LangGraph's conditional edges for LLM validation retry loops.

```python
workflow.add_conditional_edges(
    "validate_node",
    should_retry,  # Returns "retry" | "continue" | "fail"
    {
        "retry": "llm_node",      # Loop back with error feedback
        "continue": "save_node",
        "fail": END
    }
)

def should_retry(state: State) -> Literal["retry", "continue", "fail"]:
    if state.get("validation_errors"):
        if state.get("retry_count", 0) < 3:
            return "retry"
        return "fail"
    return "continue"
```

**Key**: Pass validation errors back to LLM via state so it can self-correct.

---

## Database & Migrations

### The Two-Phase Migration Rule

> **Never do breaking changes in one step.**

**Phase 1 (Additive)**: Add new things, keep old things working
**Phase 2 (Destructive)**: Remove old things after code is updated

**Why**: Code and database are deployed at different times. Old code must work with new DB, new code must work with old DB (temporarily).

---

### Pattern: Adding a NOT NULL Column

```python
# WRONG - breaks immediately if rows exist
op.add_column("users", sa.Column("timezone", sa.String(), nullable=False))

# RIGHT - two-phase
# Migration 1: Add nullable
op.add_column("users", sa.Column("timezone", sa.String(), nullable=True))

# Deploy code that writes timezone for new users, tolerates NULL for existing

# Migration 2 (later): Backfill and tighten
op.execute("UPDATE users SET timezone = 'UTC' WHERE timezone IS NULL")
op.alter_column("users", "timezone", nullable=False)
```

---

### Pattern: Renaming a Column

**Never do this in one step**:
```python
op.alter_column("users", "email", new_column_name="login_email")  # BREAKS INSTANTLY
```

**Multi-phase approach**:
1. Add new column (nullable)
2. Deploy code that writes to BOTH columns
3. Backfill old data
4. Deploy code that reads from new column
5. Drop old column

---

### JSONB Schema Evolution

Treat JSONB columns like a **public API**:

**Safe Changes**:
- Add optional keys
- Add new nested objects
- Expand value types (string → string|null)

**Dangerous Changes**:
- Rename keys (old code breaks)
- Remove keys (old code breaks)
- Change value semantics

**Best Practice**: Version your JSON schema:
```python
graph_data = {"schema_version": 1, "nodes": [], "edges": []}
```

Then do lazy migration on read if version < current.

---

### Advisory Locks for Free-Tier Migration Safety

**Problem**: Render free tier has no pre-deploy commands. Multiple containers may start concurrently and race on migrations.

**Solution**: PostgreSQL advisory locks in `alembic/env.py`:

```python
def do_run_migrations(connection: Connection) -> None:
    # Acquire lock (blocks if another process holds it)
    connection.execute(text("SELECT pg_advisory_lock(hashtext('smeme_migrations'))"))

    try:
        context.run_migrations()
    finally:
        connection.execute(text("SELECT pg_advisory_unlock(hashtext('smeme_migrations'))"))
```

**Critical for async**: Must explicitly commit after migrations!
```python
async with connectable.connect() as connection:
    await connection.run_sync(do_run_migrations)
    await connection.commit()  # Without this, migrations silently rollback!
```

---

### Autogenerate Drops Tables Not in SQLModel Metadata

**Problem**: `alembic revision --autogenerate` compares the DB to SQLModel's metadata. Tables that exist in the DB but **are not** defined as SQLModel models get flagged for removal. Autogenerate emits `op.drop_table(...)` for them.

**Example**: `stripe_events` is created in a migration (bb8be63) for webhook idempotency; it is not a SQLModel table. A later autogenerate for unrelated changes (e.g. adding `local_sources`) saw `stripe_events` in the DB but not in metadata → added `op.drop_table("stripe_events")` to the upgrade. Running that migration would have broken billing.

**Solution**:
1. **Always review autogenerate output** — remove any `op.drop_table` or `op.alter_column` you did not intend. Autogenerate often picks up schema drift.
2. **Exclude raw tables** — add them to `include_object` in `alembic/env.py` so autogenerate ignores them. We already exclude LangGraph checkpoint tables (see [SPRINT_OVERVIEW](../historical/sprints/SPRINT_OVERVIEW.md)); `stripe_events` is now excluded there too. Alternative: create a minimal SQLModel table (not used in app logic) just so metadata includes them.
3. **When downgrade fails** — PostgreSQL aborts the transaction on the first error; the "current transaction is aborted" message hides the real failure. Fix the migration (remove bad ops), then re-run downgrade.

---

### Naming Conventions for Constraints

**Why**: Alembic can't reliably reference constraints without predictable names.

```python
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
```

---

### Async SQLAlchemy: Lazy Relationships and `MissingGreenlet` {#async-sqlalchemy-lazy-relationships-and-missinggreenlet}

**Problem:** With `AsyncSession`, loading a row via `await db.execute(select(Model).where(...))` and then reading a **lazy** relationship (e.g. `session.qnr` on `QNRSession`) triggers an implicit IO path that is not `await`-driven. SQLAlchemy raises **`sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called`**. The HTTP response is often **500**; the traceback points at the first attribute access (`if not session.qnr`, template use of `session.qnr`, etc.).

**Concrete case:** `GET /qnr/version-modal/{session_id}` in `smeme/qnr/routes.py` used `select(QNRSession).where(...)` without eager-loading **`qnr`**. The dashboard path was fine because **`list_user_sessions`** in `smeme/qnr/helpers/db_queries.py` already applies **`selectinload(QNRSession.qnr)`** (and parent/children where needed).

**Fix:** Eager-load relationships you will touch in the same `execute`:

```python
from sqlalchemy.orm import selectinload

result = await db.execute(
    select(QNRSession)
    .options(selectinload(QNRSession.qnr))
    .where(QNRSession.id == session_id, QNRSession.user_id == user_id)
)
session = result.scalar_one_or_none()
```

**Rule of thumb:** After any `await db.execute(...)`, if the handler or Jinja template reads a relationship, that relationship should have been **eager-loaded** (`selectinload` / `joinedload`) on that query, or loaded explicitly with a second awaited query. Do not rely on lazy load in async request code.

---

## Dependency Stack Gotchas

### Neon Connection Pooling

**Problem**: Direct connections bypass Neon's pooler, leading to connection exhaustion.

**Solution**: Always use `-pooler` endpoint:
```
# Good
postgresql://...@ep-name-pooler.us-east-1.aws.neon.tech/...

# Bad - will exhaust connections
postgresql://...@ep-name.us-east-1.aws.neon.tech/...
```

---

### Connection Pool Configuration

```python
# Development
pool_size=5, max_overflow=10, pool_recycle=1800

# Production
pool_size=20, max_overflow=40, pool_recycle=3600

# Critical settings
pool_pre_ping=True     # Detect stale connections (Neon auto-suspend)
pool_recycle=3600      # Force reconnect hourly
```

---

### LangGraph UUID Serialization

**Problem**: LangGraph checkpoints to JSONB. UUIDs and datetimes don't serialize.

```python
# WRONG - will fail
state["qnr_id"] = uuid4()
state["created_at"] = datetime.now()

# RIGHT - convert to strings
state["qnr_id"] = str(uuid4())
state["created_at"] = datetime.now(UTC).isoformat()
```

---

### Pydantic V2 + FastAPI-Users Warnings

**Symptom**: `UserWarning: 'orm_mode' has been renamed to 'from_attributes'`

**Impact**: Cosmetic only, no functional impact.

**Action**: Monitor for `fastapi-users-db-sqlmodel` updates. Warnings are harmless.

---

### Python 3.13 Async Edge Cases

**Watch for**:
- `RuntimeError: Event loop is closed`
- Slow async performance
- Context manager issues with async generators

**Known**: asyncpg had performance regression in 3.13.0-3.13.4 (fixed in 3.13.5+)

**If weird async issues**: Try Python 3.12 to isolate.

---

## LLM Integration

### Singleton OpenAI Client

**Pattern**: Use `@lru_cache` for singleton, configure model at call time.

```python
@lru_cache(maxsize=1)
def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=30.0,
        max_retries=3,
    )

# In node - decide model based on context
async def call_llm_node(state, config):
    client = config["configurable"]["openai_client"]

    # Escalate model on retries
    if state.get("retry_count", 0) >= 2:
        model = "gpt-4o"
    else:
        model = "gpt-4o-mini"

    response = await client.beta.chat.completions.parse(
        model=model,
        messages=[...],
        response_format=MyPydanticModel,
    )
```

---

### Structured Output vs Freeform

**For complex reasoning**: Let LLM think in freeform first, then convert to structured.

```
Phase 1: LLM generates markdown design (freeform thinking)
Phase 2: Human reviews and edits
Phase 3: LLM converts markdown → structured JSON (mechanical conversion)
```

**Why**: LLM fights JSON constraints during complex reasoning. Better results with freeform → structured pipeline.

---

### Deterministic Auto-Fix Over Tool-Calling Agents

**Problem with tool-calling agents for graph fixes**:
- Unpredictable sequencing
- Parameter hallucination
- Loop risk
- Partial fixes create new errors
- Expensive (multiple LLM calls)
- Hard to debug

**Better**: Deterministic code-driven fixes with regex pattern matching:

```python
# Fix self-loops
if match := re.search(r"Self-loop detected on node '(\w+)'", error):
    node_id = match.group(1)
    graph = delete_edge(graph, source=node_id, target=node_id)
```

---

### Graceful Degradation for External APIs

| API | Failure Response | Rationale |
|-----|------------------|-----------|
| **Tavily** | Graceful degradation | User can proceed with LLM-only |
| **OpenAI** | Hard fail | Cannot proceed without LLM |

```python
try:
    result = await tavily_client.search(...)
except Exception:
    logger.warning("Tavily failed, proceeding with LLM knowledge only")
    return {"research_degraded": True, "research_context": llm_only_analysis}
```

---

## Authentication

### FastAPI-Users + Cookie Sessions

**Pattern**: Cookie-based sessions (httponly, samesite=lax), not JWT in headers.

**Inheritance order matters**:
```python
class User(BaseSQLModel, SQLModelBaseUserDB, table=True):
    # BaseSQLModel first = our naming conventions take precedence
```

---

## Deployment & CI/CD

### Dual-Stage Pipeline

```
dev branch → auto-deploy to staging → Neon dev branch
main + tag → manual deploy to production → Neon main branch
```

**Key Principles**:
1. Never run Alembic in build stage (DB-less build)
2. Exactly one migration runner (concurrency groups)
3. Fail fast if migrations fail (`set -e`)
4. Same image for migrate + run
5. No migrations on preview branches

---

### GitHub Actions Concurrency

```yaml
concurrency:
  group: staging-deploy
  cancel-in-progress: false  # Wait for first to finish
```

Prevents race conditions on simultaneous deploys.

---

### Render Rollback Trap: DB-Ahead-of-Image Loop

**Symptom**: Every container restart fails with `Can't locate revision identified by '<hash>'`.

**What happened**:
1. New image deployed → Alembic migrations ran successfully → DB advanced to new HEAD
2. App crashed on startup (for any reason) → Render health check failed
3. Render rolled back to the **previous stable image** — which predates the new migration files
4. Old image starts → Alembic checks `alembic_version`, finds unknown revision → crashes
5. Infinite restart loop. The service is fully broken until a new working image is deployed.

**Key insight**: Render's rollback does NOT revert the database. The DB stays at the new HEAD. Only a new successful deploy (not a restart) escapes the loop.

**Diagnosis clue**: The error `Can't locate revision identified by 'f8a9b0c1d2e3'` in repeated restart logs means the DB is ahead of the running image. Look for a *different* error in the **first** deploy attempt's logs — that's the actual root cause.

**Fix**: Push any commit to trigger a fresh CI/CD cycle. The new image will have the migration files, `alembic upgrade head` will be a no-op (already at head), and the real startup error becomes visible.

---

### pydantic-settings Crashes on Non-JSON List Env Vars

**Symptom**:
```
pydantic_settings.exceptions.SettingsError:
  error parsing value for field "allowed_origins" from source "EnvSettingsSource"
Caused by: JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

**Root cause**: For `list[str]` fields, pydantic-settings calls `json.loads(value)` inside `EnvSettingsSource.decode_complex_value()` — before any pydantic `field_validator` or `model_validator` can run. This crashes on:
- Blank string `ALLOWED_ORIGINS=""` (env var declared but empty on Render)
- Bare URL `ALLOWED_ORIGINS=https://smeme.com` (human-readable but not JSON)
- Comma-separated `ALLOWED_ORIGINS=https://a.com,https://b.com`

**What doesn't work**:
- `env_ignore_empty=True` in `model_config` — only handles exact `""`, not bare URLs
- `@field_validator("allowed_origins", mode="before")` — never reached because the source crashes first

**Fix**: Override `settings_customise_sources` to substitute a lenient `EnvSettingsSource` subclass:

```python
class _LenientEnvSource(EnvSettingsSource):
    def decode_complex_value(self, field_name, field, value):
        if not isinstance(value, str):
            return super().decode_complex_value(field_name, field, value)
        stripped = value.strip()
        if not stripped:
            return None                        # → field uses its default
        if stripped.startswith(("[", "{")):
            return json.loads(stripped)        # → normal JSON path
        return [v.strip() for v in stripped.split(",") if v.strip()]  # → comma-sep

class Settings(BaseSettings):
    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings,
                                    env_settings, dotenv_settings, file_secret_settings) -> tuple:
        return (init_settings, _LenientEnvSource(settings_cls), dotenv_settings, file_secret_settings)
```

**Prevention**: On Render, set list env vars as proper JSON arrays (`'["https://smeme.com"]'`) or delete them entirely. Never leave them as blank strings.

---

### z3-solver Requires libstdc++6 in python:3.13-slim Docker Runtime

**Symptom**: App fails silently on startup with no Python traceback — `uvicorn` starts then immediately exits (health check timeout).

**Root cause**: `z3-solver` bundles `libz3.so` (a C++ library) in its manylinux wheel. Even though the wheel is self-contained, `python:3.13-slim` strips out `libstdc++6` and `libgomp1`. The OS dynamic linker can't load the `.so` on startup.

**Affected path**: `main.py` → `smeme/api/reasoning_evaluate.py` → `smeme/reasoning/runtime/evaluate.py` → `from z3 import ...` (imported unconditionally at module level, runs at every uvicorn start).

**Fix**: Add to the **runtime** stage in Dockerfile:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libstdc++6 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*
```

The **builder** stage already has `build-essential` (which includes these), so the issue only surfaces in the slim runtime stage.

---

## Code Organization

### Separation of Concerns

```
Routes     → HTTP concerns (requests, responses, auth)
Workflows  → Business logic (state transitions, decisions)
Helpers    → Pure utilities (db queries, validation)
Models     → Data structures (SQLModel for DB, Pydantic for API)
```

---

### Structured Logging

```python
logger.info(
    "Operation performed",
    extra={
        "user_id": str(user_id),
        "node": "my_node",
        "elapsed_ms": round(elapsed_ms, 2),
        "result_count": len(results),
    },
)
```

**Always include**: user_id, node name, elapsed_ms for performance tracking.

---

### Immutable Graph Operations

**Pattern**: Never mutate graphs in place. Return new copies.

```python
def create_node(graph: QNRGraph, ...) -> QNRGraph:
    new_graph = deepcopy(graph)
    new_graph.nodes.append(new_node)
    return new_graph
```

---

## What Didn't Work

### Tool-Calling Agents for Graph Fixes

We tried using LLM tool-calling agents to fix validation errors. Problems:
- Hallucinated node IDs
- Created new errors while fixing old ones
- Got stuck in loops
- Expensive and slow

**Switched to**: Deterministic regex-based fixes. Predictable, cheap, debuggable.

---

### Direct JSON Generation for Complex Questionnaires

Asking LLM to generate complex branching logic directly as JSON led to:
- Missing edges
- Incorrect conditions
- Poor reasoning quality

**Switched to**: Freeform markdown design → human review → mechanical JSON conversion.

---

### Single Workflow for Read and Write

Mixing viewer and editor logic in one workflow caused:
- Cache invalidation nightmares
- Unclear state boundaries
- Hard to test

**Switched to**: Separate viewer (read-only, cached) and editor (write, fresh data) workflows.

---

### Relying on LLM Retry for Validation

Simple retry loops for LLM validation errors were:
- Expensive (full regeneration each time)
- Often repeated same mistakes
- No visibility into retry attempts

**Switched to**: Conditional edges with error feedback. LLM sees its mistakes and can self-correct. All attempts visible in LangSmith.

---

## Testing with pytest-asyncio

### Event Loop Scope Mismatches

**Problem**: pytest-asyncio creates a new event loop per test by default. asyncpg connections bind to their creation event loop. Running multiple async tests causes "attached to different loop" errors.

**Solution**: Use session-scoped event loops for all async tests:

```python
# pytest.ini
asyncio_mode = strict
asyncio_default_fixture_loop_scope = session

# In test file
pytestmark = pytest.mark.asyncio(loop_scope="session")
```

---

### Isolating Sync Tests from Async Fixtures

**Problem**: Session-scoped async fixtures in `tests/conftest.py` break sync tests in child directories because pytest tries to apply scope to everything.

**Solution**: Use `--confcutdir` to prevent conftest inheritance:

```bash
# Run pure unit tests (no async)
pytest tests/unit/ -v --confcutdir=tests/unit

# Run async integration tests
pytest tests/test_auth_flows.py -v
```

---

### asyncio_mode: auto vs strict

| Mode | Behavior | Problem |
|------|----------|---------|
| `auto` | All tests auto-wrapped as async | Sync tests get scope mismatches |
| `strict` | Explicit `@pytest.mark.asyncio` required | Predictable, explicit control |

**Recommendation**: Use `strict` mode. Add `pytestmark` at module level for async test files.

---

### Mocking Import-Time Functions

**Problem**: Mocking at the wrong path fails when functions are imported inside methods.

```python
# In smeme/auth/manager.py
async def on_after_request_verify(self, ...):
    from smeme.core.email import send_verification_email  # Imported here!
    await send_verification_email(...)

# WRONG - function doesn't exist at this path
patch("smeme.auth.manager.send_verification_email")

# RIGHT - mock at definition site
patch("smeme.core.email.send_verification_email")
```

---

### FastAPI Dependency Overrides for Tests

**Pattern**: Don't modify production code for tests. Use dependency overrides:

```python
@pytest_asyncio.fixture
async def app(test_session_factory):
    from smeme.core.database import get_db

    application = create_app()

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_get_db
    yield application
    application.dependency_overrides.clear()
```

---

### Pure Unit Tests vs Integration Tests

| Type | Characteristics | Speed | Reliability |
|------|-----------------|-------|-------------|
| **Pure Unit** | No DB, no async, no network | 0.2s for 57 tests | 100% |
| **Integration** | Real DB, async fixtures | 14s for 8 tests | Event loop dependent |

**Rule**: If you can test it as a pure function, do so. Integration tests are for HTTP/auth flows only.

---

## Public Gallery & HTMX Patterns

### HTMX Partial vs Full Page Rendering

**Pattern**: Check the `HX-Request` header to decide whether to return a full page or an HTML fragment.

```python
if request.headers.get("HX-Request"):
    return templates.TemplateResponse("gallery/_items.html", context)
return templates.TemplateResponse("gallery/gallery.html", context)
```

The full page template `{% include %}`s the partial, so both paths render the same content - the partial just skips the layout wrapper. This means:
- Direct navigation (`GET /gallery`) gets the full page with nav, filters, etc.
- HTMX requests (search, filter, sort, pagination) get only the results fragment.
- `hx-push-url="true"` keeps URLs bookmarkable and back-button friendly.

### Global `#modal-container`: direct swap, not OOB-only

**Problem:** A trigger uses `hx-get="…" hx-target="#modal-container"` (often with `hx-swap="innerHTML"`). The response is a **single** root node with `hx-swap-oob="innerHTML:#modal-container"`. The request succeeds (**200**) but the overlay never appears or stays empty.

**Cause:** Out-of-band swaps are meant **alongside** a normal response body. When the **entire** response is only an OOB node, HTMX can mishandle the interaction between the primary target swap and OOB processing (order and stripping differ by version).

**Fix:** For “load this modal into `#modal-container`,” return **plain HTML** (no `hx-swap-oob` on the fragment root). Keep `hx-target="#modal-container"` and `hx-swap="innerHTML"` on the button. To clear the modal, return an **empty** body (same pattern as `GET /auth/profile/close-modal`), not a synthetic `<div hx-swap-oob="innerHTML:#modal-container"></div>`.

**Still use OOB** when one response must update **multiple** targets (e.g. editor graph + checklist); that is the intended pattern.

### JSONB Metadata Access in Templates

**Problem**: `qnr.metadata` in Jinja2 templates resolves to the SQLAlchemy `MetaData` class attribute (from `BaseSQLModel.metadata`), not the JSONB metadata. Accessing `qnr.metadata.description` silently returns `Undefined` in Jinja2 (not an error), so templates appear to work but never render the metadata.

**Fix**: Extract metadata from `graph_data` in the route handler and pass it as a separate template variable.

```python
def _extract_metadata(qnr: QNR) -> dict:
    graph_data = qnr.graph_data or {}
    meta = graph_data.get("metadata", {}) or {}
    return {
        "description": meta.get("description", ""),
        "category": meta.get("category", ""),
        "estimated_time": meta.get("estimated_time"),
        "tags": meta.get("tags", []),
    }
```

Then in templates use `{{ meta.description }}` instead of `{{ qnr.metadata.description }}`.

### UUID Path Parameters for Public Routes

**Problem**: FastAPI's `UUID` path parameter type returns a 422 JSON validation error for malformed UUIDs. For public-facing HTML pages, this is terrible UX.

**Fix**: Accept `str` and parse manually, returning a styled 404 template for invalid input.

```python
@router.get("/{qnr_id}")
async def gallery_detail(qnr_id: str, ...):
    try:
        parsed_id = UUID(qnr_id)
    except (ValueError, AttributeError):
        return templates.TemplateResponse("gallery/not_found.html", ..., status_code=404)
```

### HTMX Skips Swap on 4xx by Default

**Problem**: When a form submits via HTMX and the server returns 422 (validation error), the response is not swapped in. User sees spinner flash, then nothing changes — no error message, no preserved form data.

**Cause**: HTMX does not swap content on 4xx/5xx responses by default (treats them as errors).

**Fix**: Return **200** for validation errors when you're returning a valid form with error messages. The "error" is semantic (validation failed), but the response body is usable HTML. Alternative: use `htmx:beforeSwap` to allow 422 to swap:

```javascript
document.body.addEventListener('htmx:beforeSwap', function(evt){
  if (evt.detail.xhr.status === 422) {
    evt.detail.shouldSwap = true;
    evt.detail.isError = false;
  }
});
```

**Recommendation**: Return 200 for validation-error responses that re-render the form with preserved values and error messages. Simpler than global event handlers.

### Form Validation: Preserve Values on Error

**Problem**: When validation fails, the default error handler returns only an error div. HTMX swaps that into the target, replacing the entire form — user loses title, goal, and all other input.

**Fix**: Parse the form manually in the route (before Pydantic validation), catch `ValidationError`, and re-render the full form with `form_values` and `validation_errors` in the template context. Return 200 so HTMX swaps the form. User can fix errors and resubmit without re-entering data.

### Form JS: Progressive Enhancement Only

**What the JS does** in the generation brief form:

| Feature | Purpose | Could remove? |
|---------|---------|---------------|
| **Tab switching** | Show/hide Expert Context panels (URLs, Pasted text, Exclude) | Could use `<details>` or CSS-only, but tabs are cleaner |
| **Char counters** | Live "0/200" (title) and "0/400" (goal) as user types; yellow/red when near/over limit | Yes — server validates; purely cosmetic |

**Rule**: Server validation is authoritative. Form JS is progressive enhancement.

### Jinja2 selectattr/rejectattr for Template-Level Filtering

**Pattern**: Split a single list into multiple sections without modifying the route handler.

```jinja2
{% set published_qnrs = my_qnrs|selectattr('is_public')|list %}
{% set private_qnrs = my_qnrs|rejectattr('is_public')|list %}
```

Useful for dashboard sections where you want published, private, and archived QNRs in separate visual groups without additional database queries.

### PostgreSQL Full-Text Search at Query Time

For small datasets (<1000 rows), query-time `to_tsvector` is fast enough without a GIN index:

```python
search_query = func.plainto_tsquery("english", q)
stmt = stmt.where(func.to_tsvector("english", QNR.title).op("@@")(search_query))
```

`plainto_tsquery` handles user input safely (no special syntax needed). Add a GIN index via Alembic migration when dataset grows.

---

## Modal Navigation & HTMX UX

### Same-URL Modal Links Can Be a No-Op

**Problem**: A modal action like "Go to dashboard" is implemented as a plain `<a href="/qnr/dashboard">`.  
When the user is already on `/qnr/dashboard`, browsers may not visibly navigate, so the modal remains open and users think the button is broken.

**Fix**: For same-page targets, handle it as an explicit UI action:
- Clear `#modal-container`
- Force refresh (`window.location.reload()`) only when `href` resolves to current location
- Keep normal navigation for different targets (e.g. `/billing/choose-workflow`)

**Rule**: Treat modal "go back" actions as state transitions, not just URL links.

### Keep Modal Close Behavior Deterministic

**Pattern**:
- Use one global close path (`/auth/profile/close-modal` or equivalent empty response swap)
- Ensure every modal close affordance (X, backdrop action, secondary button) uses the same clear mechanism
- Avoid relying on incidental page navigation to close overlays

This prevents "stuck overlay" regressions when navigation is prevented, intercepted, or same-route.

### Dashboard Anchors Are Useful But Not a Refresh Mechanism

Anchors like `/qnr/dashboard#in-progress` are correct for deep-linking sections, but they do not guarantee a rerender or state refresh.  
If your intent is "close modal and refresh current dashboard state," do that explicitly.

### Prefer Explicit HTMX/JS Intent Over Ambiguous Anchors in Modal CTAs

For modal CTA buttons:
- If intent is **open another modal**: use HTMX (`hx-get`, `hx-target="#modal-container"`)
- If intent is **navigate to a different page**: plain navigation is fine
- If intent is **stay on page but refresh UI**: explicit reload/HTMX refresh + close modal

Mixing these intents behind plain anchors makes behavior route-dependent and easy to regress.

---

## Email Verification & Password Reset

### FastAPI-Users Verify Router is POST-Only

**Problem**: FastAPI-Users `get_verify_router()` only provides a `POST /` endpoint that expects `{"token": "..."}` as JSON body. But email verification links are `GET` requests with `?token=...` query params. Clicking the email link returns 404.

**Fix**: Add a custom `GET /auth/verify` route that reads the token from query params and calls `user_manager.verify(token)`:

```python
@auth_router.get("/verify")
async def verify_email(request: Request, user_manager: UserManagerDep, token: str = ""):
    try:
        await user_manager.verify(token, request)
        return templates.TemplateResponse("auth/verify_result.html", {"success": True, ...})
    except Exception:
        return templates.TemplateResponse("auth/verify_result.html", {"success": False, ...})
```

Register this **before** the FastAPI-Users verify router include to avoid route conflicts.

### BASE_URL and RENDER_EXTERNAL_URL

**Problem**: Email links, Stripe redirects, and other absolute URLs use a base URL. If it's wrong, links point to the wrong host (e.g. verification emails go to production when testing locally).

**Fix**: The app uses `settings.effective_base_url`, which prefers `RENDER_EXTERNAL_URL` when set (Render sets it automatically), else `BASE_URL`:

- **Local dev**: Set `BASE_URL=http://localhost:8000` in `.env`
- **Render**: No action needed — `RENDER_EXTERNAL_URL` is set automatically
- **Custom domain on Render**: Set `BASE_URL=https://yourdomain.com` to override (Render keeps `RENDER_EXTERNAL_URL` as the onrender.com URL)

### Inline HTMX for Contextual Actions

**Pattern**: Instead of redirecting to a separate "resend verification" page, embed an HTMX button directly in the login error message:

```python
if not user.is_verified:
    return HTMLResponse(
        '...Please verify your email... '
        '<button hx-post="/auth/resend-verification" '
        f'hx-vals=\'{{"email": "{user.email}"}}\' '
        'hx-target="closest div" hx-swap="outerHTML" '
        'class="underline">Resend verification email</button>'
    )
```

The button replaces the warning div with a success message in-place. No page navigation needed.

### Anti-Enumeration Pattern for Email Operations

**Rule**: Always return success for operations that reveal user existence (forgot password, resend verification). Use the same response whether the email exists or not:

```python
# Always return success to avoid leaking user existence
try:
    user = await find_user(email)
    if user:
        await send_email(user)
except Exception:
    pass
return HTMLResponse("If an account exists, you'll receive an email.")
```

---

## Design System & Component Library

### CSS is Pre-built Tailwind, Not the CDN

**Pattern**: Tailwind is compiled ahead of time to a purged static stylesheet
(`smeme/static/css/app.css`, ~13 KB gz), linked once from `base.html`. The Play CDN
(`cdn.tailwindcss.com`) was removed — it shipped a large JS runtime and compiled in the browser,
hurting LCP/CLS. Build with **`make css`** (standalone CLI binary, no npm/Node); Docker rebuilds
it automatically.

**Gotcha**: After changing template classes, **rebuild** (`make css`) — the committed `app.css`
can otherwise drift. Purge only detects **complete class-name literals** (macros/inline JS are
fine; never concatenate like `"bg-" + color`). JS-only toggles are also in `safelist` in
`tailwind.config.js`. Full guide: [frontend-css-build.md](guides/frontend-css-build.md);
decision: [D020](DECISIONS.md#d020-pre-built-tailwind-css-over-the-play-cdn).

### Jinja2 Macros as a Component System

**Pattern**: Use `{% from "components/macros.html" import btn, card, badge %}` for reusable UI components. Jinja2's `{% call %}` block pattern creates container components (cards, modals) that accept arbitrary content.

```jinja2
{# Container component with caller() #}
{% call card(title="Account Info") %}
  <p>Content goes here</p>
{% endcall %}

{# Self-closing component #}
{{ btn("Save", variant="primary", type="submit") }}
```

**Key insight**: The `attrs` parameter is essential for HTMX compatibility. It allows macros to pass through arbitrary HTML attributes without the macro needing to know about `hx-*` attributes:

```jinja2
{{ btn("Edit", variant="primary",
       attrs='hx-get="/edit" hx-target="#modal" hx-swap="innerHTML"') }}
```

### Additive Tailwind Config for Gradual Migration

**Pattern**: When introducing a design system to an existing Tailwind codebase, make all token changes **additive**. Old classes (`purple-600`, `green-100`) keep working alongside new semantic tokens (`brand-600`, `success-100`).

```javascript
tailwind.config = {
  theme: {
    extend: {  // extend, not replace
      colors: {
        brand: { 50: '...', 600: '...' },  // New tokens
        // purple-600 etc. still work
      }
    }
  }
}
```

This allows incremental migration — pages can be refactored one at a time without breaking unreactored pages.

### Modal Macro with ARIA

**Pattern**: Encapsulate accessibility requirements in the macro so every modal gets them automatically:

```jinja2
{% macro modal(id, title) %}
<div id="{{ id }}" role="dialog" aria-modal="true" aria-labelledby="{{ id }}-title">
  <h3 id="{{ id }}-title">{{ title }}</h3>
  <button aria-label="Close">...</button>
  {{ caller() }}
</div>
{% endmacro %}
```

Every use of `{% call modal(...) %}` gets correct ARIA for free.

### FastAPI-Users Login Form Name Mismatch

**Gotcha**: FastAPI-Users uses `OAuth2PasswordRequestForm` which expects a form field named `username` — even if you're authenticating by email. The login form must use `name="username"` even when the label says "Email". Use the macro's `attrs` parameter to override the generated `id` for label association:

```jinja2
{{ form_input("username", "Email", type="email", attrs='id="email"') }}
```

---

## Stripe & Payments

### Price ID vs Product ID

**Problem**: Stripe Checkout `line_items[].price` expects a **Price ID** (`price_xxx`), not a Product ID (`prod_xxx`). Using a Product ID returns `No such price: 'prod_xxx'`.

**Fix**: In Stripe Dashboard → Products → select product → Pricing tab → copy the **Price ID** (starts with `price_`). Set `STRIPE_PREMIUM_PRICE_ID` to that value.

### Webhook Raw Body Required

**Problem**: Stripe webhook signature verification requires the **raw request body**. If FastAPI or middleware parses JSON first, the body is consumed and verification fails.

**Fix**: Use `payload = await request.body()` in the webhook route. Do not use `request.json()`. Ensure the webhook route is excluded from any JSON body parsing middleware.

### Env Vars Per Environment

**Problem**: Billing features (Upgrade banner, subscribe, session-pay) only appear when `stripe_configured` is True. If `STRIPE_SECRET_KEY` or `STRIPE_PREMIUM_PRICE_ID` are missing in Render/staging/production, the banner is hidden and endpoints return 503.

**Fix**: Add Stripe env vars to each deployment environment (Render Environment Variables). Test mode uses `sk_test_` and `whsec_` (test webhook secret); live uses `sk_live_` and live webhook secret.

**Base URL**: On Render, `RENDER_EXTERNAL_URL` is set automatically — used for Stripe success/cancel redirects and email links. For custom domains, set `BASE_URL` to override.

### Idempotency for Webhooks

**Pattern**: Stripe may deliver the same webhook event multiple times. Store `event.id` in a `stripe_events` table before processing. If the event ID already exists, return 200 immediately without reprocessing.

### Session-Complete Race with Webhook

**Problem**: User lands on `/billing/session-complete?checkout_session_id=cs_xxx` before the webhook has created the session. Query returns nothing.

**Fix**: Show "Processing your payment..." with auto-refresh (e.g. every 2 seconds). When the webhook runs and creates the session, the next refresh finds it and redirects to the session viewer.

---

## Considerations

Tradeoff analyses and design decisions that don't fit as hard rules but are worth documenting for future implementation choices.

### Ephemeral Upload Storage: Temp Disk vs PostgreSQL bytea

When storing file upload bytes temporarily (before parsing and discarding), two options exist. Both can be implemented securely; the choice depends on deployment topology and operational preferences.

**Temp Disk (`/tmp` or dedicated dir)**

| Pros | Cons |
|------|------|
| No DB bloat — uploads don't inflate table sizes or backups | Single-instance only — upload and parse must be on the same host |
| No large binary traffic across the wire | Orphan files on crash (until cleanup job runs) |
| Simple lifecycle — `unlink()` after parse | Container disk is limited and shared with app |
| Easy to enforce quotas / size caps | Risk of disk exhaustion under spike traffic |
| DB connection pool not used for big reads/writes | |

**PostgreSQL bytea**

| Pros | Cons |
|------|------|
| Multi-instance safe — any worker can read by `file_id` | Bloats DB size and backups |
| Survives restarts — no orphan blobs | Large I/O uses connections and memory |
| Same transactional semantics as rest of app | More schema and cleanup logic |
| Can enforce quotas via row size and policies | Requires explicit `DELETE` after parse (or TTL job) |

**Security comparison**: Both are fine when implemented correctly. Temp disk: use `tempfile.mkstemp` with random names, never user-controlled paths; avoid symlink issues with `O_NOFOLLOW`. bytea: enforce `user_id`/`thread_id` in queries to prevent cross-tenant leaks. Neither inherently safer; security comes from implementation (path handling, size caps, access checks).

**Recommendation for SMEme (single-instance, Render)**: **Temp disk** — fewer moving parts, no DB bloat, straightforward cleanup (startup job deletes stale files). Add: size caps before write (per-file and per-run), dedicated dir (e.g. `/tmp/smeme_uploads`) with random filenames, startup cleanup for files older than N minutes.

**Consider bytea later if**: You move to multi-instance or background workers where upload and parse run on different processes; you need cross-instance access by `file_id`.

### Checkpoint Cleanup – `cleanup_expired_generations`

LangGraph checkpoints for QNR generation workflows accumulate over time. **`cleanup_expired_generations` is wired in app lifespan** (`smeme/main.py` → `smeme/qnr/generation/agentic/maintenance.py`): startup backstop, daily periodic cleanup, and weekly orphan checkpoint + wizard telemetry retention. See [checkpoint-maintenance-plan.md](planning/checkpoint-maintenance-plan.md). Without this hygiene, checkpoint tables can grow unbounded and impact DB size, backups, and query performance.

### MCP Streamable HTTP: `Last-Event-ID`, Python SDK, and `StripLastEventIdMiddleware`

**Context:** SMEme mounts **FastMCP** Streamable HTTP in **stateless** mode (`stateless_http=True` in `smeme/mcp/reasoning_fastmcp.py`). The **MCP Python SDK** (`mcp` on PyPI) creates per-request transports with **`event_store=None`** in that mode (hardcoded in `StreamableHTTPSessionManager._handle_stateless_request`).

**Trigger:** SSE clients that **reconnect** send a **`Last-Event-ID`** header (standard for resumable SSE). **MCP Inspector** does this after stream teardown.

**Failure:** When `Last-Event-ID` is present and `event_store` is missing, the SDK’s `_replay_events` path **returns without sending any HTTP response**. Starlette then raises **`RuntimeError: No response returned.`**, which surfaces as **HTTP 500** and Inspector errors such as “SSE error: Non-200 status code (500)”. This is an SDK gap, not an application logic bug in SMEme. Track upstream: [python-sdk#1648](https://github.com/modelcontextprotocol/python-sdk/issues/1648), [python-sdk#423](https://github.com/modelcontextprotocol/python-sdk/issues/423).

**Mitigation in repo:** `StripLastEventIdMiddleware` wraps the mounted MCP Starlette app and **removes** the `Last-Event-ID` header (case-insensitive match on the ASGI header **list**—do not convert headers to a `dict`, which drops duplicate names and breaks case handling). That forces the normal GET SSE path instead of the broken replay branch.

| Aspect | Implication |
|--------|-------------|
| **Resumability** | Stripping the header **disables** SSE replay for this mount; acceptable for dev, Inspector, and current stateless MCP until a real `EventStore` exists. |
| **When to remove** | Prefer removing or narrowing the middleware when upstream fixes the no-`event_store` replay path **or** stateless mode passes through a configured `EventStore`. |
| **Alternative** | **Stateful** MCP sessions plus a proper **`EventStore`** implementation would make replay legitimate; then **do not** strip `Last-Event-ID`—implement storage/replay instead. |

**Related (Inspector UX, not SMEme):**

- **Default URL** in the Inspector UI is often `http://localhost:3001/sse` (SSE samples / `localStorage`); switch transport to **Streamable HTTP** and set the SMEme URL (e.g. `http://127.0.0.1:8000/api/v1/mcp`).
- **`npx @modelcontextprotocol/inspector` alone** starts proxy + UI; the URL is configured **in the browser**, not as a first positional argument (that mode is **stdio** and tries to `spawn` the string as a command → `ENOENT`).
- **Optional Authorization header:** if enabled with an **empty** value, Inspector rejects the connection; leave custom headers **off** until Bearer auth is required on the MCP route (DR-3 P2).

Operational detail: [docs/guides/dr3-mcp-oauth-authoritative-sources.md](guides/dr3-mcp-oauth-authoritative-sources.md) (Try locally + Inspector).

### MCP mount path: 307 trailing-slash redirect and POST 406 (Starlette `Mount`)

**Context:** FastMCP is mounted with Starlette `Mount` at `settings.mcp_http_path` (default `/api/v1/mcp`). The mount’s path regex matches **`/api/v1/mcp/`** plus a remainder segment (including empty). An HTTP path of exactly **`/api/v1/mcp`** (no trailing slash) **does not** match the mount.

**What happens:** The app router’s `redirect_slashes` logic issues **307 Temporary Redirect** to **`/api/v1/mcp/`**. That is normal Starlette behavior, not a broken deploy.

**Failure mode:** Some remote MCP clients (e.g. Claude Desktop during connector / OAuth setup) **re-issue the POST** after the redirect **without** preserving `Accept: application/json, text/event-stream`. The Streamable HTTP transport then responds **406 Not Acceptable**. Render logs can show `POST /api/v1/mcp` → 307, then `POST /api/v1/mcp/` → 406, while the same server works from Inspector or curl with correct headers.

**Mitigation in repo:** `McpMountPathNormalizeMiddleware` (registered in `smeme/main.py` when `MCP_ENABLED`) runs **outermost** on the FastAPI stack and rewrites an exact-path request from bare `{mcp_http_path}` to `{mcp_http_path}/` **before** routing, avoiding the redirect entirely for that URL shape. See `smeme/mcp/reasoning_fastmcp.py`.

| Aspect | Implication |
|--------|-------------|
| **Operator workaround** | Paste the connector URL **with** a trailing slash (`.../api/v1/mcp/`) if a client still misbehaves. |
| **curl** | A streaming 200 may **hang** until `--max-time`; timeout with 0 body bytes can still mean the mount is OK. |

### `curl` GET to MCP endpoint times out (exit 28)

**Symptom:** `curl --max-time 15 -H "Accept: application/json, text/event-stream" … https://host/api/v1/mcp/` prints **`curl: (28) Operation timed out`** and **`0 bytes received`**, while **`-w "%{http_code}"` may still show `200`**.

**Cause:** Streamable HTTP uses a **long-lived GET** (SSE) on the MCP path. **`curl` waits for the response body to finish**; the server intentionally does not close the stream, so curl hits **`--max-time`** and exits **28**. **`http_code` 200** reflects that the HTTP response **started** (status line / headers), not that the transfer “completed.”

**What to use instead:** **`GET /.well-known/oauth-protected-resource{MCP_HTTP_PATH}`** — normal JSON, completes quickly. Example: `curl -sS -o /dev/null -w "%{http_code}\n" --max-time 20 "https://host/.well-known/oauth-protected-resource/api/v1/mcp"`. Repo: `bash scripts/smoke_mcp_url.sh https://host`.

**Shell pitfall:** In `curl … \` newline continuations, **any character (including a space) after the backslash** breaks line continuation; the next line may run as a **separate shell command**, so `-H` flags never reach `curl`.

**Claude Desktop “Couldn’t reach the MCP server”:** That message is **Anthropic-client** wording; it is **not** proved by MCP-URL curl timing out. Confirm reachability with well-known + Inspector; then check OAuth redirects, Desktop-specific callback URIs in Clerk, and connector advanced settings.

---

## Deterministic Reasoning (Z3)

**Historical:** The pre-cutover DTQ stack (`smeme/qnr/dtq/`) is documented in
git history and in `docs/planning/dtq-to-reasoning-cutover.md`. Current
production behavior lives under `smeme/reasoning/README.md` and
`smeme/reasoning/IR_validator.md`.

**Invariants carried forward (still true):**
- Do not block the event loop on Z3 — run `evaluate_reasoning` /
  `solve_reachability_witness` via `asyncio.to_thread` at HTTP boundaries.
- One publish gate for web, API, and MCP —
  `smeme/reasoning/publish_readiness.py::assess_publish_readiness` is the
  single orchestrator.
- Publish-failure policy: on structural/compile failure, no
  `ReasoningCompiledArtifact` row and no `is_public` flip.
- Trace gate: `SMEME_REASONING_Z3_TRACE`, logger `smeme.reasoning.z3`.

## Quick Reference

### Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `TooManyConnectionsError` | Pool exhausted | Reduce `pool_size`, use `-pooler` URL |
| `Event loop is closed` | Leaked async context | Check cleanup in `lifespan` |
| `Object not JSON serializable` | UUID/datetime in state | Convert to strings |
| `Connection reset` | Stale Neon connection | Add `pool_pre_ping=True` |
| `Can't locate revision identified by 'xxx'` | Render rolled back to old image after new image failed health check; DB is ahead of image | Push a new commit to force fresh deploy — do NOT restart; see [Render Rollback Trap](#render-rollback-trap-db-ahead-of-image-loop) |
| `SettingsError: error parsing value for field "allowed_origins"` | `ALLOWED_ORIGINS` env var on Render set to blank or non-JSON string | Delete the env var or set to JSON array `'["https://host"]'`; code-side fix via `_LenientEnvSource` |
| `sqlmodel not defined` | Missing import in migration | Check `render_item` in env.py |
| `attached to different loop` | Event loop scope mismatch | Use `loop_scope="session"` |
| **`MissingGreenlet`** / `greenlet_spawn has not been called` | Lazy-loaded relationship on `AsyncSession` (e.g. `session.qnr` after `select(QNRSession)` only) | Use `.options(selectinload(Model.rel))` on the query (see [Async SQLAlchemy lazy relationships](#async-sqlalchemy-lazy-relationships-and-missinggreenlet)) |
| `ScopeMismatch` | Async fixtures with sync tests | Use `--confcutdir` or separate dirs |
| `fixture not found` | confcutdir too restrictive | Remove confcutdir for integration tests |
| `qnr.metadata` is empty in Jinja2 | Resolves to SQLAlchemy MetaData | Extract from `graph_data` in route handler |
| 422 JSON on invalid UUID path | FastAPI UUID validation | Use `str` param + manual `UUID()` parse |
| 404 on email verify link click | FastAPI-Users verify is POST-only | Add custom `GET /auth/verify` route |
| Email links point to wrong host | `BASE_URL` env mismatch | Local: `BASE_URL=http://localhost:8000`. Render: uses `RENDER_EXTERNAL_URL` automatically |
| Login form `name` vs label mismatch | FastAPI-Users OAuth2PasswordRequestForm | Use `name="username"` with `attrs='id="email"'` |
| New Tailwind tokens not working | Missing `extend` in config | Use `theme.extend.colors`, not `theme.colors` |
| `No such price: 'prod_xxx'` | Product ID used instead of Price ID | Use Price ID (`price_xxx`) in `STRIPE_PREMIUM_PRICE_ID` |
| Upgrade banner not showing on Render | Stripe env vars not set | Add `STRIPE_SECRET_KEY`, `STRIPE_PREMIUM_PRICE_ID` to env |
| Modal "Go to dashboard" does nothing | CTA points to current URL; navigation becomes no-op and overlay stays mounted | For same-page destinations, clear `#modal-container` and explicitly refresh (reload or HTMX partial refresh) |
| Autogenerate drops raw tables (e.g. stripe_events) | Tables not in SQLModel metadata | Review autogenerate; remove spurious `op.drop_table`; use `include_object` for raw tables |
| `InFailedSQLTransactionError` on alembic downgrade | Migration step failed; transaction aborted | Fix migration (remove bad ops), re-run downgrade; real error is earlier in traceback |
| FastAPI `Invalid args for response field` on route | Return type is `Union[Response, RedirectResponse, HTMLResponse]` | Add `response_model=None` on the route decorator |
| MCP Inspector **500** / SSE error on reconnect; Uvicorn may show no body | Python `mcp` SDK + `Last-Event-ID` + `event_store=None` in stateless mode | `StripLastEventIdMiddleware` on mount (see [Considerations](#mcp-streamable-http-last-event-id-python-sdk-and-striplasteventidmiddleware)); upgrade SDK or add `EventStore` when available |
| **`POST …/mcp` → 307** then **`POST …/mcp/` → 406** | Starlette `Mount` only matches trailing-slash path; redirect drops `Accept` on some clients | `McpMountPathNormalizeMiddleware` when `MCP_ENABLED` ([Considerations](#mcp-mount-path-307-trailing-slash-redirect-and-post-406-starlette-mount)); or use connector URL `.../mcp/` |
| **`curl` (28) on `GET …/mcp/`**, `http_code` 200 | SSE stream never ends; curl times out on body | Not a down server — use [well-known GET](#curl-get-to-mcp-endpoint-times-out-exit-28) or `scripts/smoke_mcp_url.sh` |

---

---

## MCP OAuth 2.1 Discovery and Bearer Auth (DR-3)

End-to-end learnings from wiring **Clerk** as the OAuth AS, serving **RFC 9728** / **RFC 8414** / OIDC discovery from SMEme (inline, no redirect to Clerk for well-known), **transport-layer** **401** + **`WWW-Authenticate`** (`resource_metadata`), and Bearer JWT verification (JWKS, shared decode for verifier + tools).

**Confirmed working (2026-03 — 2026-04):** MCP Inspector (Quick + Guided), **Anthropic Cowork** (hosted MCP URL + `https://claude.ai/api/mcp/auth_callback`), and **Cursor** IDE remote MCP (**Tools & MCP**, same MCP URL and Clerk OAuth app as long as **every** client redirect URI is allowlisted). Same **`BASE_URL` / `resource`** rules apply to all hosts; **web login once** still required so **`sub` → `users.clerk_user_id`**.

---

### `Pydantic AnyHttpUrl` Adds a Trailing Slash to Bare Origins

**Problem:** `AnyHttpUrl("https://host.example.com")` normalises to `"https://host.example.com/"` (trailing slash). When MCP Inspector constructs the RFC 8414 AS metadata URL by appending `/.well-known/oauth-authorization-server`, it produces a **double slash**: `https://host.example.com//.well-known/oauth-authorization-server`. Clerk (and most OAuth AS implementations) return 404 on that malformed path.

**Symptom:** MCP Inspector Guided OAuth flow reports "Failed to discover OAuth metadata" immediately after metadata fetch returns 200. The actual GET succeeds, but Inspector then uses the `authorization_servers[0]` value to construct discovery URLs and gets 404.

**Fix:** Strip trailing slash after `meta.model_dump()`:

```python
payload = meta.model_dump(mode="json", exclude_none=True)
payload["authorization_servers"] = [
    str(u).rstrip("/") for u in payload["authorization_servers"]
]
```

**Location:** `smeme/mcp/discovery_routes.py` → `_protected_resource_payload`.

---

### 302 Redirect for AS Metadata Fails CORS in Browser-Based MCP Clients

**Problem:** If `/.well-known/oauth-authorization-server` returns `302 → Clerk`, the browser follows the redirect to `https://your-instance.clerk.accounts.dev/.well-known/oauth-authorization-server`. Clerk does not emit `Access-Control-Allow-Origin` headers for arbitrary `localhost:*` origins. The browser blocks the response with a CORS error, and Inspector reports discovery failure even though the redirect target is reachable from `curl` or Node.

**Why it's subtle:** The discovery GET to SMEme's endpoint succeeds (simple cross-origin GET, no preflight needed). The redirect *destination* — Clerk — is where the CORS failure occurs. Server logs show your endpoint returning 302 but no follow-on error; the failure happens silently in the browser.

**Fix:** Serve the AS metadata **inline** from SMEme, derived from the Clerk issuer URL. No network call is needed — Clerk's endpoints follow the standard OAuth 2.0 structure:

```python
def _clerk_as_metadata(issuer: str) -> dict:
    base = issuer.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "jwks_uri": f"{base}/.well-known/jwks.json",
        ...
    }
```

The browser now only talks to `localhost:8000`, which our CORS config allows.

**Location:** `smeme/mcp/discovery_routes.py` → `authorization_server_metadata`.

---

### MCP Inspector Also Fetches `/.well-known/openid-configuration`

**Problem:** MCP Inspector's Guided OAuth flow fetches **three** well-known documents from the resource server, not two. After `oauth-protected-resource` and `oauth-authorization-server` both return 200, Inspector also tries `/.well-known/openid-configuration`. A 404 on that endpoint causes Guided flow to report "Failed to discover OAuth metadata" even though the RFC 8414 document succeeded.

**Why:** Inspector supports both RFC 8414 (OAuth 2.0) and OpenID Connect Discovery as valid AS metadata sources. It checks all known paths and fails hard if none respond.

**Fix:** Register a `/.well-known/openid-configuration` route that serves Clerk's OIDC config inline (same pattern as AS metadata):

```python
app.add_api_route(
    "/.well-known/openid-configuration",
    openid_configuration,
    methods=["GET"],
    include_in_schema=False,
)
```

**Note:** Clerk's actual `/openid-configuration` response includes additional fields (`service_documentation`, `revocation_endpoint`, `op_tos_uri`) that we don't derive locally. This is fine for Inspector — it only needs the core endpoint URLs.

**Location:** `smeme/mcp/discovery_routes.py`.

---

### CORS Preflight (`OPTIONS`) 400 vs Actual GET 200

**Observation:** Server logs will show:
```
OPTIONS /.well-known/oauth-protected-resource → 400
GET    /.well-known/oauth-protected-resource → 200
```

This looks alarming but is **partially expected**. FastAPI's CORSMiddleware returns 400 for preflights from disallowed origins. However, simple cross-origin GET requests (no custom headers, standard `Accept`) don't require a preflight — the browser sends them directly. The GET therefore succeeds without the preflight.

**When it becomes a hard failure:** If the MCP client sends a GET with custom headers (e.g. `Authorization` on a well-known probe) or makes a POST (token exchange), the browser **requires** the preflight to succeed. A 400 preflight will block those.

**Fix for dev:** Add Inspector's origin to `ALLOWED_ORIGINS` in `.env`:
```
ALLOWED_ORIGINS=["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:6274"]
```

Restart the server (`.env` changes are not hot-reloaded).

**Do not** add arbitrary origins in production; `ALLOWED_ORIGINS` is read from env and should be deployment-specific.

---

### MCP Inspector Has Two Different OAuth Callback URLs

**Problem:** Inspector has two OAuth flow modes with **different redirect URIs**:

| Mode | Redirect URI |
|------|-------------|
| Quick flow | `http://localhost:6274/oauth/callback` |
| Guided flow | `http://localhost:6274/oauth/callback/debug` |

Register **both** in your Clerk OAuth app's Redirect URI list. If you only add `/oauth/callback`, Guided flow fails with Clerk's `redirect_uri does not match` error. The mismatch is visible in the browser URL bar — decode the `redirect_uri=` query param to see exactly what Inspector sent.

**For Cowork production:** `https://claude.ai/api/mcp/auth_callback` — register this once. It's shared across all Cowork users; Anthropic's infrastructure handles the callback.

---

### Cursor IDE: remote MCP OAuth redirect {#cursor-ide-mcp-oauth}

**For Cursor (Tools & MCP):**

1. **Dynamic registration:** Many Cursor builds follow the MCP/OAuth bootstrap in [Clerk’s guide](https://clerk.com/docs/guides/ai/mcp/connect-mcp-client) and expect **RFC 7591** client registration. With **`CLERK_OAUTH_DYNAMIC_REGISTRATION` unset/false**, SMEme’s mirrored AS metadata **omits** `registration_endpoint`, so Cursor never reaches a successful **POST** to **`{issuer}/oauth/register`** and OAuth stalls (connection errors, failed login, or no tools) **even though** well-known GETs return 200. **Fix:** turn on **Dynamic OAuth Client Registration** for the Clerk **instance**, set **`CLERK_OAUTH_DYNAMIC_REGISTRATION=true`** on SMEme, restart — see [DCR and Cursor](#mcp-dcr-registration-endpoint-and-cursor) below.
2. **Redirect URI:** Still distinct from Cowork’s `https://claude.ai/...`. On **`redirect_uri does not match`**, decode `redirect_uri=` from Clerk’s error URL and allowlist that exact URI on the same Clerk OAuth application.

---

### Redirect URI Is Per-Client-Type, Not Per-User

The OAuth redirect URI is a **per-MCP-client allowlist**, not per-user. Each MCP client application (Inspector, Cowork, Cursor, etc.) has one registered redirect URI. All users of that client share it — Anthropic's callback endpoint handles Cowork for all users; SMEme only sees the Bearer token on subsequent tool calls, never the callback.

---

### Cowork + Clerk: DCR Off, Static `clientId`, Public (PKCE) {#cowork-clerk-dcr-off-static-clientid-public-pkce}

**Symptoms:** Cowork shows "Couldn't reach the MCP server" after reconnect; `smeme_reasoning_list` returns `auth_error` with `Authorization: Bearer <token> required` (no token attached).

**Cause chain:** With **Clerk instance-level Dynamic Client Registration disabled** (recommended default — Clerk warns that DCR exposes a public `/oauth/register` API), MCP clients cannot self-register. They need a **pre-registered** Clerk OAuth application **Client ID**. Without it, the OAuth start step never obtains tokens.

**Fix:** In **`plugin/smeme-cowork/.mcp.json`**, set `"oauth": { "clientId": "<your Clerk OAuth app Client ID>" }` next to `"url"`. In the Clerk Dashboard, the same OAuth app must have **Public** enabled so **PKCE** (no client secret in the plugin) works.

**SMEme metadata:** While DCR is off, `/.well-known/oauth-authorization-server` and `/.well-known/openid-configuration` served from SMEme **omit** `registration_endpoint` so Cowork-style clients use a **static** `clientId` instead of self-registration. When you **intentionally** enable Clerk DCR (e.g. for Cursor), set **`CLERK_OAUTH_DYNAMIC_REGISTRATION=true`** so those documents **include** `registration_endpoint` → `{issuer}/oauth/register` (implemented in `smeme/mcp/discovery_routes.py`). See [DCR and Cursor](#mcp-dcr-registration-endpoint-and-cursor).

**Deep link noise:** A `claude://` redirect after browser OAuth can surface errors in **Claude Desktop** even when the real failure is missing `clientId` / token on the **Cowork** connector — fix OAuth first, then re-test.

---

### Dynamic Client Registration (`registration_endpoint`) and Cursor {#mcp-dcr-registration-endpoint-and-cursor}

**Problem (April 2026):** **Cursor** remote MCP against SMEme showed **connectivity / OAuth failures** while **MCP Inspector** and (with static `clientId`) **Cowork** worked. RFC 9728 + inline AS + OIDC discovery all returned **200**; transport **401** + `WWW-Authenticate` behaved correctly. The gap was **client registration**: Cursor’s flow matches Clerk’s documentation — it expects to **discover** a **`registration_endpoint`** and **POST** [RFC 7591](https://www.rfc-editor.org/rfc/rfc7591.html) **`{issuer}/oauth/register`** at **Clerk** to obtain a **`client_id`** (and sometimes **`client_secret`**) before starting the authorization code + PKCE dance. With **`CLERK_OAUTH_DYNAMIC_REGISTRATION` at default `false`**, SMEme mirrored **no** `registration_endpoint`; conforming clients had **nowhere valid to register** and never obtained credentials, so the pipe never reached “Allow” + token exchange.

**Fix (two steps, both required):**

1. **Clerk Dashboard** — Enable **Dynamic OAuth Client Registration** for the **Clerk instance** (OAuth / Advanced / instance-level toggle — exact location varies by Clerk UI revision). Clerk exposes **`POST https://{frontend-api-host}/oauth/register`** publicly; read Clerk’s security notice (spam / phishing) before turning this on.
2. **SMEme** — Set **`CLERK_OAUTH_DYNAMIC_REGISTRATION=true`** in the app environment and **restart**. Then `GET /.well-known/oauth-authorization-server` and `GET /.well-known/openid-configuration` on the SMEme origin include **`"registration_endpoint": "{issuer}/oauth/register"`** (same issuer as JWT `iss`). Implementation: `Settings.clerk_oauth_dynamic_registration` → `_clerk_as_metadata` / `_clerk_oidc_config` in `smeme/mcp/discovery_routes.py`. Tests: `test_well_known_routes_clerk_dcr_advertises_registration_endpoint` in `tests/unit/mcp/test_dr3_discovery.py`.

**Why this fixes Cursor:** The client completes **DCR** against Clerk, receives a **client_id**, then opens the browser for **`/oauth/authorize`**, exchanges the code at **`/oauth/token`**, and finally sends **`Authorization: Bearer`** on MCP **POST**s — the same Bearer path **`bearer_auth.py`** already validates.

**Coexistence with Cowork:** **Cowork** can keep **`oauth.clientId`** in **`plugin/smeme-cowork/.mcp.json`** (static public client). Advertising **`registration_endpoint`** does not remove static clients; it only **adds** the registration option for DCR-first apps. If a deployment must stay **DCR-off** for policy reasons, operators cannot rely on Cursor’s default Clerk-aligned flow — use a client that supports static Client ID only, or accept enabling DCR for development/staging only.

**Do not** set **`CLERK_OAUTH_DYNAMIC_REGISTRATION=true`** unless Clerk’s instance actually serves **`/oauth/register`**; otherwise clients will follow a dead `registration_endpoint`.

---

### Bearer Token Auth in FastMCP Tools: Use `ctx.request_context.request`

**Problem:** FastMCP tool functions are not FastAPI route handlers — you cannot use `Depends()` for authentication. The usual `current_active_user` dependency is unavailable.

**Solution:** FastMCP's `Context` object exposes the Starlette `Request` via `ctx.request_context.request`. For Streamable HTTP (stateless mode), the request object is fully populated, including headers:

```python
@mcp.tool()
async def my_tool(ctx: Context) -> str:
    request = ctx.request_context.request
    auth = request.headers.get("authorization", "")
    # ... validate Bearer token
```

This is confirmed for `mcp` SDK with `stateless_http=True`. For non-HTTP transports (stdio), `request` will be `None` — always check.

**Location:** `smeme/mcp/bearer_auth.py` → `get_mcp_user`, `smeme/mcp/reasoning_fastmcp.py` → tool handlers.

---

### DB Sessions in FastMCP Tools: Use `AsyncSessionLocal` Directly {#db-sessions-in-fastmcp-tools-use-asyncsessionlocal-directly}

**Problem:** FastMCP tools cannot use `Depends(get_db)`. You need a database session inside an async tool function.

**Pattern:** Use the session factory directly as an async context manager:

```python
from smeme.core.database import AsyncSessionLocal

@mcp.tool()
async def my_tool(ctx: Context) -> str:
    async with AsyncSessionLocal() as db:
        result = await db.execute(...)
        ...
    # session is committed and closed on exit
```

Each tool call opens and closes its own session. This is correct for stateless MCP (every request is independent). Do not share sessions across tool calls or store them as module-level state.

---

### JWKS Caching: Kid Rotation and Cache Invalidation

**Pattern in `_JwksCache`:**
1. Cache RSA keys in process memory with a 5-minute TTL.
2. If the JWT `kid` is not in the cached key set, **re-fetch once** before failing. This handles Clerk key rotation without requiring a server restart.
3. Call `cache.invalidate()` in tests to force a re-fetch.

**Why `kid`-aware retry matters:** Clerk rotates its signing keys periodically. A long-lived process might have a stale cache when a new key is introduced. The re-fetch-on-cache-miss pattern means the first request after rotation takes one extra JWKS round-trip, and all subsequent requests use the new key without any downtime.

**Do not** cache the `jwt.decode` result — only cache the raw public key objects. Token validation (expiry, issuer) must run on every call.

---

### Bearer Token `sub` Must Match `users.clerk_user_id` {#bearer-token-sub-must-match-usersclerk_user_id}

**Problem:** Clerk issues two different kinds of JWTs:
- **Session JWT** (used by the web app via `__session` cookie) — `sub` is the Clerk user ID
- **OAuth access token** (issued by the OAuth app to MCP clients) — `sub` is also the Clerk user ID

Both use the same `sub` value, **but** the `users.clerk_user_id` column is only populated when the user first logs into SMEme's web app (via `get_or_create_user_for_clerk` in `clerk_auth.py`). If a user authenticates a Cowork connector without ever having logged into the SMEme web UI, the `sub` in their Bearer token will not match any row in `users`.

**Fix for dev/testing:** Log into `http://localhost:8000/auth/login` at least once before testing MCP tool calls. This creates the `users` row and sets `clerk_user_id`. In production, this will be a natural step (users create an account before connecting Cowork).

**Error message:** `get_mcp_user` raises `MCPAuthError("No local SMEme account linked to Clerk id ...")` which tools return as `{"error": {"code": "auth_error", ...}}`.

---

### MCP transport 401 + `WWW-Authenticate` vs tool-level `auth_error` (DR-3 challenge retrofit)

**Context:** Some connectors bootstrap OAuth from the **first** POST to the MCP URL. They expect **HTTP 401** with **`WWW-Authenticate: Bearer …`** including **`resource_metadata="…"`** (RFC 9728 URL derived from the MCP resource URL via `mcp.server.auth.routes.build_resource_metadata_url`).

**Implementation:** When `clerk_oauth_issuer` is set, FastMCP is constructed with **`AuthSettings`** (`issuer_url`, `resource_server_url` = full MCP endpoint URL) and **`ClerkMcpTokenVerifier`** (`mcp.server.auth.provider.TokenVerifier`). The MCP Python SDK wraps Streamable HTTP in **`RequireAuthMiddleware`**, which emits that challenge for missing or invalid Bearer tokens. **`ClerkMcpTokenVerifier`** only checks JWT + JWKS (signature, `iss`, `exp`, `sub`); it does **not** query the database.

**Tool layer:** `get_mcp_user` still maps **`sub` → `users.clerk_user_id`** and returns in-band **`auth_error`** when the JWT is valid but there is no local row (or the account is inactive). Missing **`Authorization`** should no longer produce HTTP 200 + tool **`auth_error`** for list/evaluate/capabilities — the transport rejects the request first.

**`resource_metadata` URL:** Must match the FastAPI discovery route: `{effective_base_url}/.well-known/oauth-protected-resource{MCP_HTTP_PATH}` (see `smeme/mcp/urls.py` and `discovery_routes.py`). The SDK builds this from **`AuthSettings.resource_server_url`** (the **resource** URL, not the metadata URL).

**Inner Starlette app:** Enabling FastMCP `auth` also registers RFC 9728 routes on the **mounted** sub-app; clients should keep using the parent app’s well-known handlers.

**`HTMXLoginRedirectMiddleware` vs MCP:** For other routes, **401** may become **302** → `/auth/login` when **`Accept`** includes **`text/html`** or **`HX-Request`** is set — fine for HTMX, fatal for OAuth if applied to the MCP mount. **Mitigation in repo:** `_is_mcp_http_path()` in `smeme/core/middleware.py` skips that redirect when the request path is under **`MCP_HTTP_PATH`**, so MCP **401** + **`WWW-Authenticate`** reach the client even if **`Accept`** lists both JSON/SSE and **`text/html`** (some connectors do). See [DR-3 guide — Transport-layer auth and HTMX middleware](../guides/dr3-mcp-oauth-authoritative-sources.md#transport-layer-auth-and-htmx-middleware).

**Clerk unset:** If `clerk_oauth_issuer` is missing, transport auth is not enabled on FastMCP; behavior falls back to the pre-challenge model (tools still enforce Bearer where implemented).

---

### Clerk OAuth Access Tokens Do Not Carry Custom Scopes (P2 Limitation)

**Finding (Spike S3):** Clerk's OAuth applications (as of March 2026) do not support custom OAuth scopes in access tokens. Forward-looking **`reasoning:list`** / **`reasoning:evaluate`** style scopes were discussed for SMEme's RFC 9728 / RFC 8414 documents, but Clerk will **not** include custom resource scopes in issued access tokens — only standard OIDC scopes (`profile`, `email`, `offline_access`) are present.

**Impact:** P2 authorization is sub-based ownership only (`user.id == qnr.author_id`). Custom reasoning scopes are not enforced at the token level until Clerk (or an embedded AS) can issue them.

**Consequence for P3:** Before enforcing `reasoning:*` scopes at the RS layer, either (a) Clerk adds custom scope support, or (b) we implement an embedded AS (Authlib) that can issue scopes. Document in D016 and DECISIONS.md — do not surprise future implementors with a scope check that always passes.

---

### MCP Inspector `resource` Field Must Match Connection URL Exactly

**Problem:** If `BASE_URL` is `http://localhost:8000`, the RFC 9728 `resource` field is `http://localhost:8000/api/v1/mcp`. If you connect Inspector to `http://127.0.0.1:8000/api/v1/mcp`, Inspector validates that the connection URL matches the `resource` value and fails with "Protected resource X does not match expected Y".

**Fix:** Use the exact same hostname in Inspector's URL field as in `BASE_URL`. `localhost` and `127.0.0.1` are not interchangeable for this check even though they resolve to the same address.

---

### Clerk OAuth Client Secret Is Between MCP Client and Clerk, Not SMEme

**Conceptual clarity:** The Client ID + Secret are credentials for the **MCP client application** (Inspector, Cowork) to authenticate with **Clerk** during token exchange. SMEme never sees or needs the client secret. SMEme's role is the Resource Server — it only validates the issued Bearer token using Clerk's public JWKS. 

The security model: PKCE prevents code interception; the client secret proves the token exchange came from the legitimate application; JWKS signature validation proves the token was issued by Clerk. SMEme verifies the last step only.

---

---

### Clerk Web Auth UX: Three Patterns Working Together

The SMEme Clerk web integration has three distinct sign-in paths, each requiring a different fix. They coexist in `smeme/templates/partials/_clerk_browser_sync.html`.

**Path 1 — Email / verification-code (modal)**

`Clerk.openSignIn()` keeps everything on the SMEme page. After the user enters the code Clerk calls `addListener`, which fires when `resources.session` becomes truthy. At that point `showSigningInOverlay()` shows a loading spinner and `forceRedirectUrl` carries the user to `/auth/clerk-callback`. On localhost this path is fast enough that the overlay flashes; on Render free tier (~300–600 ms latency) it is clearly visible.

**Path 2 — Google / social OAuth (full-page redirect)**

The modal disappears on the Google redirect. The `addListener` callback registered by `withSigningInOverlay` is destroyed with the JS context. Additionally, Clerk may silently drop `forceRedirectUrl` for social logins on development instances and fall back to the Dashboard "After Sign-In URL", which may point to `/auth/login` instead of `/auth/clerk-callback`.

**Fix:** After `Clerk.load()`, check `Clerk.session` synchronously. `clerk-js` processes `__clerk_db_jwt` from the URL during `load()` so the session object is populated on the first load. If on `/auth/login` with an active session and no logout flag, immediately call `showSigningInOverlay()` and `window.location.assign(callbackUrl)`. This bypasses the ~2-second server-side JWT validation that the `login_page` pre-check would otherwise do.

```javascript
if (
  window.location.pathname === "/auth/login" &&
  !u.searchParams.get("smeme_clerk_logout") &&
  Clerk.session
) {
  showSigningInOverlay();
  window.location.assign(callbackUrl);  // callbackUrl = origin + "/auth/clerk-callback"
  return;
}
```

The `__clerk_db_jwt` cleanup block that follows is kept as a fallback for clerk-js builds where `Clerk.session` is not set synchronously after `load()` — it forces a reload, after which the session check above catches the session.

**Path 3 — Logout**

Server-side cookie deletion (`clear_clerk_browser_cookies`) is not sufficient. `clerk-js` stores session state in IndexedDB / localStorage and rehydrates it on `Clerk.load()`, making the user appear still signed in on the next page load. The fix is a two-step handshake:

1. `GET /auth/logout` clears cookies and redirects to `/auth/login?smeme_clerk_logout=1`.
2. The browser-sync script sees `smeme_clerk_logout=1`, calls `await Clerk.signOut({ redirectUrl: origin + "/auth/login" })`, and strips the parameter from the URL.

**Critical**: The `login_page` route has a server-side pre-check that redirects authenticated users straight to the dashboard. This pre-check must be skipped when `smeme_clerk_logout=1` is present — otherwise the page reloads to the dashboard before `Clerk.signOut()` can run client-side. See `smeme/auth/routes.py` `login_page`.

```python
if settings.clerk_enabled and not request.query_params.get("smeme_clerk_logout"):
    user = await clerk_authenticated_user(request, db, user_manager)
    if user is not None:
        return RedirectResponse(url="/qnr/dashboard", status_code=302)
```

---

### `/auth/clerk-callback` as Canonical Clerk Return Route

Configuring Clerk Dashboard → Paths → "After Sign-In URL" / "After Sign-Up URL" to relative path `/auth/clerk-callback` is more reliable than depending on the `redirect_url` query parameter. Clerk ignores `redirect_url` for already-signed-in users and for some social login flows, falling back to the Dashboard URL instead.

The callback route (`GET /auth/clerk-callback` in `smeme/auth/routes.py`):
1. Calls `clerk_authenticated_user` which validates the JWT and runs `get_or_create_user_for_clerk` (creating the local `User` row on first visit).
2. On success, redirects to `/qnr/dashboard`.
3. On failure (clock skew, session not yet propagated), redirects to `/auth/login` — the pre-check there picks up a valid session on the next request.

This route is the single re-entry point for all Clerk-hosted flows. Every sign-in and sign-up path (modal, hosted page, social OAuth) should point here via `forceRedirectUrl`, `afterSignInUrl`, `afterSignUpUrl`, or the Dashboard URL.

---

### Clerk `azp` Claim: Account Portal vs App Origin

Clerk's `azp` (authorized party) claim in session JWTs is the frontend origin that *initiated* the session. When a user signs in via Clerk's Account Portal (`https://<instance>.accounts.dev`), the `azp` value is the Account Portal domain — not the SMEme origin. If `clerk_authorized_parties()` only includes SMEme's base URL, these sessions are rejected.

**Fix in `smeme/core/config.py` → `clerk_authorized_parties()`**: parse the scheme+host from `CLERK_SIGN_IN_URL` and from the publishable key's frontend API host, and add both to the authorized parties set. This ensures sessions created via the Account Portal (common in development) are accepted.

```python
# From CLERK_SIGN_IN_URL = https://valued-civet-29.accounts.dev/sign-in
# → adds https://valued-civet-29.accounts.dev
if self.clerk_sign_in_url:
    parsed = urlparse(self.clerk_sign_in_url.strip())
    if parsed.scheme and parsed.netloc:
        parties.add(f"{parsed.scheme}://{parsed.netloc}")
```

Without this, newly registered users are not created in the local `users` table because `clerk_authenticated_user` rejects their JWT before `get_or_create_user_for_clerk` is ever called.

---

### Adding to Quick Reference Table

| Error | Cause | Fix |
|-------|-------|-----|
| `Failed to discover OAuth metadata` (Inspector) | Trailing slash on `authorization_servers[0]` causing double-slash URL, or `/.well-known/openid-configuration` returns 404 | Strip trailing slash after `model_dump`; add OIDC config endpoint |
| `OPTIONS /.well-known/* → 400` | Inspector's origin not in `ALLOWED_ORIGINS` | Add `http://localhost:6274` to `ALLOWED_ORIGINS` in `.env`; restart server |
| `redirect_uri does not match` (Clerk) | Inspector Guided vs Quick use different paths; **Cursor** uses its own URI (not Cowork’s `claude.ai` callback) | Register **all** URIs: Inspector **both** callbacks; Cowork **`https://claude.ai/api/mcp/auth_callback`**; **Cursor** per browser error URL / client docs |
| **Cursor** MCP: discovery **200** but OAuth never finishes | No **`registration_endpoint`** — client cannot **RFC 7591** register | Clerk: enable **Dynamic OAuth Client Registration**; SMEme: **`CLERK_OAUTH_DYNAMIC_REGISTRATION=true`**; restart ([§ DCR](#mcp-dcr-registration-endpoint-and-cursor)) |
| `Protected resource X does not match expected Y` | `BASE_URL` uses `localhost` but Inspector connected to `127.0.0.1` (or vice versa) | Use identical hostname in Inspector URL and `BASE_URL` |
| MCP tool `auth_error: No local SMEme account` | User authenticated with Clerk but never logged into SMEme web | Log into SMEme web once to create `users` row with `clerk_user_id` |
| MCP **401** + `WWW-Authenticate` / missing `resource_metadata` | Clerk not configured on server, or wrong `resource_server_url` in FastMCP `AuthSettings` | Set `clerk_oauth_issuer`; ensure `BASE_URL` matches the public MCP origin; compare header URL to `/.well-known/oauth-protected-resource{MCP_HTTP_PATH}` |
| MCP tool `auth_error: Bearer token required` (HTTP 200) | Rare after transport auth: token present at transport but tool path lost header | Complete OAuth; if this persists, check for a client that strips `Authorization` only on tool POSTs |
| Logout bounces back to dashboard | `smeme_clerk_logout=1` missing or server pre-check runs before `Clerk.signOut()` | Ensure `/auth/logout` → `/auth/login?smeme_clerk_logout=1` and `login_page` skips pre-check on that param |
| New Clerk user missing from `users` table | `azp` mismatch — Account Portal domain not in `clerk_authorized_parties()` | Add Account Portal host (from `CLERK_SIGN_IN_URL`) and frontend API host to authorized parties in `config.py` |
| 2-second wait on `/auth/login` after Google OAuth | Server pre-check validating JWT; `forceRedirectUrl` ignored for social flow | Client-side `Clerk.session` check after `Clerk.load()` redirects to `/auth/clerk-callback` immediately |

---

## MCP Hardening: Auth, Transport & Misconfiguration (security review)

These came out of a focused security review of `smeme/mcp/*`, the MCP mount in `smeme/main.py`, and related middleware/config. The architecture is sound for the intended **`MCP_ENABLED=true` + Clerk configured** path; the lessons below are about **defaults and misconfiguration**, not broken happy paths. Tracking + planned fixes: [`sprint-mcp-quota-enforcement-hardening.md`](planning/sprint-mcp-quota-enforcement-hardening.md) (Workstream B).

### `MCP_ENABLED=true` without Clerk silently disables transport auth

**Problem:** `_fastmcp_clerk_auth` returns `(None, None)` when `clerk_oauth_issuer` is empty, so FastMCP mounts **without** the SDK `RequireAuthMiddleware`. Unauthenticated clients can reach the JSON-RPC surface. Tools still fail in-band with `auth_error` (because `get_mcp_user` runs), but there is **no HTTP 401** — the endpoint is open for probing, log noise, and protocol-level interaction.

**Lesson:** "Tools return `auth_error`" is **not** the same as "the transport is protected." In production, treat MCP-without-Clerk as a fail-closed condition: refuse to mount (or fail startup) when `mcp_enabled and not clerk_oauth_issuer and is_production`. Add a test for `MCP_ENABLED=true` + no Clerk → unauthenticated `POST /api/v1/mcp/` returns **401** (or no mount). The existing test only asserts `fm.settings.auth is None`, which documents the gap rather than closing it.

### Transport auth and local-user auth are two different gates

**Insight:** `ClerkMcpTokenVerifier.verify_token` is **JWT/JWKS only** (signature, `iss`, `exp`, `sub`) — it does **not** touch the DB. The DB check (`sub` → `users.clerk_user_id`) lives in `get_mcp_user` at the tool layer. Consequence: a **valid Clerk OAuth token for an account that never logged into SMEme web** passes the transport (HTTP 200 on tool calls) and only fails **in-band** with `auth_error`. Authenticated-but-unlinked callers can still consume MCP/DB/JWKS work.

**Lesson:** Don't conflate "reached the tool body" with "fully authorized." Existing transport-401 tests cover **missing** bearer, not **valid JWT + no local user**. If this path matters for abuse, map `sub` → user inside the verifier (with caching) so unlinked accounts get a transport **401**; at minimum rate-limit and monitor it.

### OAuth client binding and `aud` are opt-in (code retained)

**Problem:** `mcp_allowed_oauth_client_ids` defaults to `[]`, and an empty allowlist **skips** client enforcement — any Clerk OAuth app that obtains user consent can mint tokens MCP accepts. Separately, `jwt.decode(..., options={"verify_aud": False})` unless `SMEME_MCP_OAUTH_ACCESS_TOKEN_AUDIENCE` is set.

**SaaS prod decision (2026-06-18):** **Clerk instance DCR on** + **`CLERK_OAUTH_DYNAMIC_REGISTRATION=true`**; **`SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS` intentionally blank** — DCR registers a new `client_id` per connector; static allowlist is impractical. Residual registration risk accepted on **Clerk** (SMEme is not the AS). SMEme still enforces JWKS, transport rate limits, linked-user checks, and quotas. Startup log **`mcp_oauth_client_allowlist_empty`** is **expected** on SaaS, not a misconfig.

**Self-hosted:** Set **`SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS`** to static Clerk OAuth app client ID(s) when DCR is off. Set **`SMEME_MCP_OAUTH_ACCESS_TOKEN_AUDIENCE`** when Clerk emits stable `aud` (benched on SaaS).

### Anthropic plugin import drops `oauth.clientId` {#anthropic-plugin-import-drops-oauthclientid}

**Problem (June 2026):** Plugin zip includes correct `.mcp.json` with **`oauth.clientId`**, but Anthropic **plugin-import** paths (Chat web, Cowork, Desktop) may **strip the `oauth` block** — synced connector shows only `type` + `url`, **greys out** Client ID in Advanced settings, and fails with **`oauth_error=registration_endpoint_missing`** until DCR is advertised or a **custom connector** is added manually. Matches [anthropics/claude-ai-mcp#359](https://github.com/anthropics/claude-ai-mcp/issues/359).

**Workarounds:**

1. **SaaS (DCR on):** Enable Clerk DCR + **`CLERK_OAUTH_DYNAMIC_REGISTRATION=true`**; leave allowlist blank.
2. **Custom connector:** Settings → Connectors → Add custom connector — URL `https://www.smeme.ai/api/v1/mcp`, Client ID `NRdsdBvrio0DW9yo`, secret blank. Install plugin zip separately for **skills**.
3. **Prime/cache quirk:** Adding custom connector once may let a subsequent plugin connector connect (client state reuse) — do not document as the primary path.

**Distribution shift:** Plugin zip = **skills + version**; MCP OAuth is often a **separate connector step** on Anthropic clients until Anthropic preserves bundled `oauth.clientId` or **Anthropic-held credentials** (`mcp-review@anthropic.com`) are configured.

### CIMD research (Client ID Metadata Documents) — July 2026 {#cimd-research-client-id-metadata-documents--july-2026}

**Status:** Research only — **no SMEme implementation** as of 2026-07-04. Full snapshot: [cimd-mcp-client-registration-research-2026-07.md](planning/cimd-mcp-client-registration-research-2026-07.md).

**Context:** GTM moved to **connector-first** onboarding (`guidance_get` + manual URL + static OAuth Client ID). Team evaluated **CIMD** as a spec-preferred way to publish first-party client metadata **without** DCR's public registration surface.

**Findings:**

1. **SMEme does not implement CIMD** — no `client_id_metadata_document` in mirrored AS metadata, no hosted metadata document route.
2. **Clerk (current AS)** — no visible CIMD support in docs or `/.well-known/oauth-authorization-server` as of July 2026; Clerk MCP guidance still centers on the **DCR instance toggle**.
3. **Interim GTM path** — **DCR off** + static Client ID `NRdsdBvrio0DW9yo` in custom connector UI + `smeme_reasoning_guidance_get` for agent bootstrap. Documented in `/docs/mcp`, `/mcp`, dashboard **Connect MCP**.
4. **Authlete** — strong native CIMD + MCP AS features; headless AS model; ~$999/mo+ managed cloud; high migration cost from Clerk.

**Trade-off accepted for July 2026 GTM:** Manual connector setup is acceptable because guidance tools remove the zip prerequisite; Cursor users must enter Client ID manually when DCR is off.

**When to revisit:** Clerk ships CIMD; a major host requires it; DCR risk becomes unacceptable; or Authlete-tier AS is justified. See planning doc §When to revisit.

### Transport security defaults can quietly weaken (DNS rebinding + CORS union)

**Problem:** In `_build_transport_security`, if `effective_base_url` yields an empty `netloc`, the code returns `TransportSecuritySettings(enable_dns_rebinding_protection=False)` — protection **off** entirely in non-dev/test envs. It also unions `settings.allowed_origins` into the MCP transport `allowed_origins`, so a loose global `ALLOWED_ORIGINS` weakens host/origin validation for Streamable HTTP.

**Lesson:** Make `BASE_URL` a full HTTPS origin a precondition for enabling MCP, and **fail startup** in production if rebinding protection would be disabled. Derive MCP transport origins **only** from `BASE_URL`/`effective_base_url`; do not union the global CORS list.

### The MCP mount bypasses FastAPI rate limiting; quota is post-auth only

**Insight:** `slowapi`'s `@limiter` decorators sit on auth/landing routes, not on the mounted MCP app. The monthly weighted **quota** only applies *after* auth on *billable* tools (`capabilities`/`list` have weight 0). So `initialize`/`tools/call`, JWKS fetches, and Z3 evaluate paths have **no transport-level backpressure** — and on the no-Clerk path, no auth either.

**Lesson:** Quota ≠ rate limiting. Add per-IP and/or per-`sub` limits on the MCP mount (ASGI middleware or nginx/Cloudflare edge). Originally a non-goal of the quota sprint; the security review moved it into scope.

### Middleware reads process-global `settings`, not the per-app registration

**Gotcha:** `main.py` can mount MCP with a per-call `reg` (`create_app(_register_settings=s)`), but `_is_mcp_http_path` / the MCP middleware read process-global `settings.mcp_enabled` / `settings.mcp_http_path`. In tests this can desync the HTMX-401 bypass or inbound telemetry; in a normal single-settings production process it's fine.

**Lesson:** Pass MCP path/enabled into middleware at registration, or read from `request.app.state`, if you ever run multiple app configs in one process.

---

## Cowork Plugin Delivery: Hosts, Versions & Drift

From a delivery review of `plugin/smeme-cowork`, `plugin/cowork-skills`, packaging scripts, download routes, and manifests. Tracking: [`sprint-mcp-quota-enforcement-hardening.md`](planning/sprint-mcp-quota-enforcement-hardening.md) (Workstream C).

### The connector host must match `BASE_URL` exactly — pick one and enforce it

**Problem:** The shipped `plugin/smeme-cowork/.mcp.json` used `https://www.smeme.ai/api/v1/mcp` while several operator/user docs said `https://app.smeme.ai/api/v1/mcp`. OAuth RFC 9728 requires the `resource` to match the connector URL **exactly**, so a `www` vs `app` mismatch breaks auth/metadata for anyone following the docs (this is the same class of failure as [MCP Inspector `resource` Field Must Match Connection URL Exactly](#mcp-inspector-resource-field-must-match-connection-url-exactly), but across the *artifact vs docs* this time).

**Lesson:** Treat the canonical SaaS host as a single source of truth used by `.mcp.json`, README, runbooks, and go-live — and add a `validate_cowork_plugin.py` check that the Tier A URL matches it. Don't let the host live in prose in five places.

### Capabilities-version coupling forces full rebuilds for config-only edits

**Gotcha:** CI enforces `plugin.json == REASONING_CAPABILITIES_VERSION` (`validate_cowork_plugin.py`). So a **plugin-only** change (e.g. fixing the `.mcp.json` env) still requires bumping `REASONING_CAPABILITIES_VERSION`, which means a full image rebuild, the operator "triple update," and a new immutable-cache filename — even though no MCP wire/tool behavior changed (this happened at 2.6.1).

**Lesson:** Either accept and **document** "any shipped-zip byte change ⇒ coupled bump," or split a *plugin bundle version* from the *capabilities contract version* with explicit rules for when each moves. Don't leave the coupling implicit.

### Manifest can disagree with the baked zip and the served filename

**Problem:** `_semver_ok` only checks that `semver` is a non-empty string. `PLUGIN_BUNDLE_VERSION` / DB `semver` can disagree with `REASONING_CAPABILITIES_VERSION` and the filename actually served (the download route uses the code constant, not the manifest). The UI can then show the wrong version/SHA for a different URL. Tests pass with `9.9.9`.

**Lesson:** Validate the manifest at resolution/startup: semver format, filename segment (`smeme-cowork-plugin-{semver}.zip`), and equality with `REASONING_CAPABILITIES_VERSION`.

### `cowork-skills/` → installable `skills/` is a manual copy (drift waiting to happen)

**Gotcha:** The source of truth is `plugin/cowork-skills/`; the installable `plugin/smeme-cowork/skills/` tree is a **hand copy**. The validator only checks that required files **exist**, not that they're **identical**. They were byte-identical at review time, but nothing prevents silent drift on the next skill edit. (Confirmed in practice: editing the skills required copying into **both** trees and `diff -rq` to verify.)

**Lesson:** Add a `diff`/`hash` compare of the `SKILL.md` pairs to the validator, or a `scripts/sync_cowork_skills.sh` run in CI before validate. Until then, **always edit both trees** and diff them.

### Other delivery foot-guns

- **`.sha256` sidecar is web-exposed:** the Dockerfile copies all of `dist/` into the download dir, and `StaticFiles` can serve `…zip.sha256` publicly. Low sensitivity, but COPY the zip only.
- **Download UI is gated on `mcp_enabled`:** the zip route is always registered, but the in-app download/email UX is wrapped in `{% if mcp_enabled %}`. Creators on an MCP-disabled env can't discover the download. Gate the UI on the plugin bundle gate + manifest instead, or document the dependency.
- **`dist/` is gitignored:** planning docs imply `dist/*.sha256` is in-repo provenance, but it isn't tracked — provenance is image-build output + the local package script. Fix the docs or commit sidecars only.

---

## Cowork-Facing Copy & MCP Error Design

The MCP surface is the product as far as a Cowork/LLM agent is concerned. Two non-obvious things follow from that.

### Tool docstrings and FastMCP `name`/`instructions` are LLM-facing copy, not dev comments

**Insight:** FastMCP exposes each tool's **docstring** as its description and the server `instructions` as system context for tool selection. So `reasoning_fastmcp.py` docstrings and the `FastMCP(name=..., instructions=...)` block are **customer-facing copy** that steers the agent — they are not just developer notes.

**Lesson:** Keep them in product voice and vocabulary. When the brand/term conventions change, update the docstrings and `instructions`, not only the SKILL files.

### Brand and product vocabulary: `SMEme` and `workflow`

**Convention:** use the brand **`SMEme`** (not `sMeMe`) in user-facing copy, docs, and agent-readable strings: web templates, Cowork SKILL files, manifest template, returned `error.message` strings, tool docstrings, and `FastMCP` `name`/`instructions`. Use the user-facing noun **`workflow`** (not "QNR", not "questionnaire") wherever end users or agents read product text.

**Keep unchanged:** literal API identifiers and contract surface — payload keys (`qnr_id`, `reasoning_qnrs`), error **codes** (`invalid_qnr_id`, `not_discoverable`, …), skill `name:` slugs (`smeme-reasoning-plugin`), Python package paths (`smeme/`), and wire symbols/tables.

### An empty list is a result, not an error — and the agent must say why

**Pattern:** `smeme_reasoning_list` returns `{"reasoning_qnrs": [], "count": 0, "hint": "..."}`. The `hint` is only present when the list is empty and explains the two owner-side preconditions (published for reasoning **and** set to **Listed** on the dashboard). The skills instruct the agent to surface the hint and **never fabricate a `qnr_id`** to work around an empty list.

**Lesson:** When a "nothing here" result has a common, fixable cause, return a machine-readable **hint** alongside the empty payload rather than relying on the agent to guess. This avoids the failure mode where an LLM invents an id and then hits `not_found`.

### Cowork may defer loading `smeme_reasoning_evaluate` — `reasoning.tools` is the authoritative catalog

**Problem (June 2026):** Cowork (and other MCP clients) can **lazily load** tool schemas. In practice this meant only the lightweight discovery/read tools (`smeme_reasoning_list`, `smeme_reasoning_template_*`, `smeme_reasoning_validate_answers`) appeared in `tool_search` and the visible tool list at session start. `smeme_reasoning_evaluate` — billable, only needed after validate — was deferred and absent. The agent correctly reported "evaluate not on this surface" but incorrectly concluded "not exposed by the server." Three things in the skill text enabled this:

1. **`capabilities` was labeled optional** ("optional sanity check") so agents skipped it when answering "what tools exist?" from already-loaded context.
2. **The capability-gated section only mentioned future tools** (what-if, how-to), implying `evaluate` was always visible — it didn't say the inverse: core tools can be deferred by the client.
3. **No mention of deferred MCP loading** anywhere in the skills.

**Fix:** Skills updated (2026-06-19):

- `smeme_reasoning_capabilities` promoted from "optional sanity check" → **session bootstrap** (step 1 of workflow).
- `reasoning.tools` from capabilities is now declared the **authoritative tool inventory**; `tool_search` / client tool list are explicitly unreliable.
- New **"Authoritative tool catalog"** section with table of rules (don't infer from `tool_search`; call by name if in `reasoning.tools`; never say evaluate isn't exposed based on a deferred listing).
- **"More reasoning tools" section split** into core (always present, call by name even if deferred) vs opt-in/future (check `reasoning.tools` before calling).
- New anti-pattern tip: **"When the user asks what MCP tools exist"** — call capabilities first, report `reasoning.tools`, don't conclude unavailability from a prior tool list.
- `smeme-reasoning-slot-fill` adds one-liner cross-reference at step 6 (evaluate).
- Description frontmatter updated so the skill routes correctly when the user asks about tool discovery.

**Lesson:** When an MCP client defers tool schemas, the agent's session-start tool inventory is incomplete. Skills must explicitly name `capabilities` as the authoritative catalog and prohibit reasoning about tool availability from client-side listings alone. Distinguish "not in my current tool list" from "not exposed by the server."

### Make error messages name the fix, and have skills branch on `error.code`

**Pattern:** Every reasoning tool returns success **XOR** `{"error": {"code", "message", ...}}`. The `code` is the stable contract (`REASONING_TOOL_ERROR_CODES`); the `message` is written to tell the user the **exact** action in the SMEme web app ("publish it from the SMEme editor," "set the workflow to **Listed**," "re-publish, then retry the same answers"). The SKILL error tables map each `code` → what it means → what to do, and tell the agent to **read `error.message` to the user**.

**Lesson:** Keep the `code` ↔ SKILL table ↔ tool docstring error list in sync (they drift easily across three files). Codes are for branching; messages are for humans — invest in both. Distinguish connector/transport hiccups (reconnect) from tool errors (fix the input or the workflow) so agents don't "fix" answers in response to an auth/connection problem.

---

## Resources

- [Neon Connection Pooling](https://neon.tech/docs/connect/connection-pooling)
- [LangGraph Concepts](https://langchain-ai.github.io/langgraph/concepts/)
- [Alembic Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [FastAPI-Users](https://fastapi-users.github.io/fastapi-users/)
- [Stripe Zero-Downtime Migrations](https://stripe.com/blog/online-migrations)
