# Architecture Decisions

Why things are the way they are. This document captures key decisions, alternatives considered, and rationale. Prevents AI assistants from suggesting approaches we already tried and rejected.

**Doc stack:** With [ARCHITECTURE.md](ARCHITECTURE.md) (*what exists now*) and [LESSONS_LEARNED.md](LESSONS_LEARNED.md) (*what went wrong*), this file forms the usual **assistant working-memory trio**; see the “How this file fits” section at the top of `ARCHITECTURE.md`.

**Product narrative** (business owners, user testing, roadmap in user terms — not legal terms): [docs/product/user-contract.md](product/user-contract.md).

**Last Updated**: 2026-07-21 (D023: AristaLabs names locked; counsel waived; public LICENSE collapsed)

---

## Decision Format

Each decision follows this structure:
- **Context**: Why did this decision need to be made?
- **Decision**: What did we choose?
- **Alternatives**: What else was considered?
- **Rationale**: Why this choice over alternatives?
- **Consequences**: What trade-offs did we accept?

---

## Core Framework Decisions

### D001: LangGraph for Workflow Orchestration

**Context**: Need to orchestrate multi-step AI workflows with validation, retries, and human-in-the-loop.

**Decision**: Use LangGraph.

**Alternatives Considered**:
1. **Raw async functions** - Simple but no state persistence, hard to debug
2. **Celery** - Overkill, designed for distributed task queues
3. **Prefect/Dagster** - Data pipeline focused, not AI-native
4. **Custom state machine** - Reinventing the wheel

**Rationale**:
- Native TypedDict state management
- Conditional routing for validation retries
- LangSmith integration for observability
- Checkpoint persistence to PostgreSQL
- Human-in-the-loop via interrupts

**Consequences**:
- ✅ Clean workflow definitions
- ✅ Full visibility into every step
- ⚠️ TypedDict gotchas (silent field drops)
- ⚠️ Learning curve for conditional edges

---

### D002: OpenAI SDK Over LangChain

**Context**: Need to call LLMs with structured output.

**Decision**: Use OpenAI SDK directly with `response_format` for structured outputs.

**Alternatives Considered**:
1. **LangChain** - Verbose, abstractions add complexity
2. **LiteLLM** - Good for multi-provider, but we're OpenAI-only for now
3. **PydanticAI** - Considered but OpenAI SDK is simpler

**Rationale**:
- Direct API = fewer abstractions to debug
- Native Pydantic `response_format` support
- Simple singleton client pattern
- Model selection at call time (not client creation)

**Consequences**:
- ✅ Minimal dependencies
- ✅ Easy to understand
- ⚠️ Locked to OpenAI (acceptable for MVP)

---

### D003: HTMX Over React/Vue

**Context**: Need dynamic UI interactions.

**Decision**: HTMX + Jinja2 server-side rendering.

**Alternatives Considered**:
1. **React** - Adds build step, npm complexity, large bundle
2. **Vue** - Same issues as React
3. **Alpine.js** - Considered, but HTMX is simpler for server-driven UI

**Rationale**:
- No build step required
- Server renders HTML (natural for Python)
- Progressive enhancement
- Smaller learning curve
- Works without JavaScript

**Consequences**:
- ✅ Simple deployment
- ✅ SEO-friendly
- ✅ Fast initial load
- ⚠️ Limited client-side interactivity
- ⚠️ More server round-trips

---

### D004: SQLModel Over Pure SQLAlchemy

**Context**: Need ORM with good Pydantic integration.

**Decision**: SQLModel (SQLAlchemy 2.0 + Pydantic).

**Alternatives Considered**:
1. **Pure SQLAlchemy** - No automatic Pydantic validation
2. **Tortoise ORM** - Less mature, Django-influenced
3. **SQLAlchemy + Pydantic manually** - More boilerplate

**Rationale**:
- Single model definition for DB and API
- Automatic validation
- Familiar SQLAlchemy patterns
- Good async support

**Consequences**:
- ✅ DRY model definitions
- ✅ Type safety throughout
- ⚠️ Some Pydantic V2 warnings with fastapi-users

---

## Workflow Design Decisions

### D005: Separate Viewer and Editor Workflows

**Context**: QNR operations mix reads and writes.

**Decision**: Two separate workflows - Viewer (read-only, cached) and Editor (write, fresh data).

**Alternatives Considered**:
1. **Single workflow with mode flag** - Complicated caching logic
2. **No workflow for viewer** - Inconsistent patterns

**Rationale**:
- Clear cache boundaries
- Viewer can cache aggressively
- Editor always gets fresh data
- Independent scaling

**Consequences**:
- ✅ Simple caching strategy
- ✅ Clear mental model
- ⚠️ Some code duplication

---

### D006: Freeform Design Before Structured Output

**Context**: LLM generates complex questionnaire branching logic.

**Decision**: Phase 1 generates freeform markdown, Phase 2 converts to structured JSON.

**Alternatives Considered**:
1. **Direct JSON generation** - LLM fights constraints, poor reasoning
2. **XML intermediate** - No advantage over markdown
3. **Multiple JSON refinement rounds** - Expensive, still constrained

**Rationale**:
- LLM reasons better without JSON constraints
- Human-readable intermediate format
- Easier for humans to edit before commitment
- Mechanical conversion step is simple

**Consequences**:
- ✅ Better reasoning quality
- ✅ Human review before build
- ⚠️ Extra processing step

---

### D007: Deterministic Auto-Fix Over LLM Tool-Calling

**Context**: Generated graphs often have validation errors.

**Decision**: Code-driven deterministic fixes using regex patterns.

**Alternatives Considered**:
1. **LLM tool-calling agent** - Tried and failed (see below)
2. **Regenerate entire graph** - Expensive, loses good parts
3. **Human fixes only** - Poor UX

**Rationale for rejecting tool-calling**:
- Hallucinated node IDs
- Unpredictable sequencing (added edge before target node existed)
- Created new errors while fixing old ones
- Got stuck in loops
- Expensive (multiple LLM calls per fix)
- Hard to debug "Why did it do that?"

**Deterministic approach**:
```python
if match := re.search(r"Self-loop detected on node '(\w+)'", error):
    graph = delete_edge(graph, source=match.group(1), target=match.group(1))
```

**Consequences**:
- ✅ Predictable, debuggable
- ✅ Cheap (no LLM calls)
- ✅ Bounded (finite fix patterns)
- ⚠️ Can't fix all errors (complex ones need human)

---

## Database Decisions

### D008: JSONB for Graph Storage

**Context**: Questionnaire graphs have variable structure.

**Decision**: Store `graph_data` as JSONB column.

**Alternatives Considered**:
1. **Separate nodes/edges tables** - Complex joins, rigid schema
2. **Document DB (MongoDB)** - Different tech stack
3. **Graph DB (Neo4j)** - Overkill, operational complexity

**Rationale**:
- PostgreSQL JSONB is fast and indexed
- Flexible schema evolution
- Single query loads entire graph
- Easy to version (lazy migration on read)

**Consequences**:
- ✅ Simple queries
- ✅ Schema flexibility
- ⚠️ Must version JSON schema carefully
- ⚠️ No referential integrity for node relationships

---

### D009: Advisory Locks for Migration Safety

**Context**: Render free tier has no pre-deploy commands. Multiple containers start concurrently.

**Decision**: PostgreSQL advisory locks in `alembic/env.py`.

**Alternatives Considered**:
1. **Render paid tier pre-deploy** - Not available on free tier
2. **File-based locking** - Doesn't work across containers
3. **External lock service (Redis)** - Additional dependency

**Rationale**:
- Uses PostgreSQL features only
- No additional dependencies
- Works on any tier
- Automatic cleanup on crash

**Consequences**:
- ✅ Works on free tier
- ✅ No external dependencies
- ⚠️ Adds ~2-5 seconds to container startup (lock wait)

---

### D010: Neon Over Self-Managed PostgreSQL

**Context**: Need PostgreSQL in cloud.

**Decision**: Neon serverless PostgreSQL.

**Alternatives Considered**:
1. **RDS/Cloud SQL** - More expensive, always-on
2. **Supabase** - Good but Neon's branching is better for our workflow
3. **Self-managed Docker** - Operational burden

**Rationale**:
- Serverless (pay per use)
- Database branching for dev/staging
- Connection pooling built-in
- Good free tier

**Consequences**:
- ✅ Low cost for low traffic
- ✅ Easy branch management
- ⚠️ Cold start latency (~1-2s after suspend)
- ⚠️ Must use pooler endpoint

---

## API & Integration Decisions

### D011: Graceful Degradation for Tavily

**Context**: External API may fail (rate limits, network issues).

**Decision**: Graceful degradation - continue with LLM-only if Tavily fails.

**Alternatives Considered**:
1. **Hard fail** - Blocks users unnecessarily
2. **Retry indefinitely** - Poor UX, may never succeed
3. **Queue for later** - Complex, unnecessary

**Rationale**:
- LLM can generate reasonable output without web search
- User is informed via warning banner
- Workflow continues normally
- Better UX than failure

**Consequences**:
- ✅ More resilient
- ✅ Good UX
- ⚠️ Quality degradation (training data only)

---

### D012: Cookie Sessions Over JWT-Only

**Context**: Need authentication for web app.

**Decision**: Cookie-based sessions (primary) with JWT support (API).

**Alternatives Considered**:
1. **JWT only** - Doesn't work well with HTMX
2. **Session DB table** - More complexity
3. **Cookie + JWT hybrid** - What we chose

**Rationale**:
- Cookies work naturally with browser
- httponly cookies = XSS protection
- JWT available for API clients if needed
- FastAPI-Users supports both

**Consequences**:
- ✅ Secure by default
- ✅ Works with HTMX
- ⚠️ Cookie config varies by environment

---

## Code Organization Decisions

### D013: Immutable Graph Operations

**Context**: Graph editing could mutate or copy.

**Decision**: All graph operations return new copies, never mutate.

**Alternatives Considered**:
1. **In-place mutation** - Harder to reason about, side effects
2. **Copy-on-write with change tracking** - Complex

**Rationale**:
- Easier to test
- No side effects
- Clear data flow
- Can compare before/after

**Consequences**:
- ✅ Predictable behavior
- ✅ Easy testing
- ⚠️ Memory overhead (acceptable for graph sizes)

---

### D014: Centralized Dependencies Hub

**Context**: Many routes need same dependencies.

**Decision**: `smeme/core/dependencies.py` as central hub.

```python
AsyncSessionDep = Annotated[AsyncSession, Depends(_get_db)]
CurrentUser = Annotated[User, Depends(_current_active_user)]
OpenAIClientDep = Annotated[AsyncOpenAI, Depends(_get_openai_client)]
```

**Alternatives Considered**:
1. **Import Depends everywhere** - Inconsistent, repetitive
2. **Middleware injection** - Less explicit

**Rationale**:
- Single source of truth
- Type hints included
- Easy to test (override in one place)
- Consistent across all routes

**Consequences**:
- ✅ DRY
- ✅ Easy testing
- ✅ Clear dependency tree

---

## Validation Decisions

### D015: Two-Tier Validation (Lenient/Strict)

**Context**: When should validation block saves?

**Decision**: Lenient during editing (save anyway), strict on publish.

**Alternatives Considered**:
1. **Always strict** - Frustrating during development
2. **Never validate** - Users publish broken QNRs
3. **Validate but only warn** - Unclear what's actually broken

**Rationale**:
- Let users save work-in-progress
- Block publishing of broken QNRs
- Clear separation of concerns
- Matches user mental model

**Consequences**:
- ✅ Good UX during editing
- ✅ Quality gate before publish
- ⚠️ Two validation code paths

---

## Integration Auth (DTQ / MCP / Cowork)

### D016: Authentication & Permissions — Final Plan (Cowork Launch, Remote MCP, SSO)

**Context**

1. **MCP + OAuth (normative)** — [MCP Authorization (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization): HTTP MCP servers act as **OAuth 2.1 resource servers**; clients discover the **authorization server** using **Protected Resource Metadata** ([RFC 9728](https://www.rfc-editor.org/rfc/rfc9728.html)), `WWW-Authenticate` (including `resource_metadata` and `scope`), and well-known fallbacks. Optional: **Dynamic Client Registration** ([RFC 7591](https://www.rfc-editor.org/rfc/rfc7591)), OIDC/AS discovery. **STDIO** MCP remains **out of band** (env vars), not this flow.

2. **Anthropic Cowork / Claude Code / Desktop (March 2026 practice)** — **Remote MCP** connectors use a **hosted MCP URL** with **OAuth 2.1**; setup can include **connector name, URL**, and **advanced OAuth Client ID + Secret**. Capabilities and tiers **evolve** (beta / plan limits). **Operational reports**: **access tokens expiring** and connectors showing auth errors until **re-authentication** (roughly **30 minutes to ~24 hours** in user reports). **Transport**: ecosystem favors **Streamable HTTP** over legacy SSE for remote MCP performance.

3. **Security architecture** — Prefer **token issuance and consent** in a **logical authorization server** separable from the MCP **resource** worker for security and portability. **Enterprise** may later add an **MCP gateway** (policy, allowlists); first-party SMEme assumes **direct** resource server until required.

4. **SMEme today** ([D012](#d012-cookie-sessions-over-jwt-only)) — **FastAPI-Users**: **cookie** + **JWT** (`/auth/jwt/login`). **No** federated SSO yet. **REST** `POST …/reasoning/evaluate` is **off by default** (**`REASONING_REST_EVALUATE_ENABLED`**); when enabled for tests/operators it uses **session** + **`is_public`** for non-owners — **interim** only. **Planned pre–GA:** migrate **web** auth to **Clerk** (layer **B**); the **permission layers** table below marks **today vs target** for web (A, B).

5. **Journeys** — **Cowork-first** and **SMEme-first**; after **one-time connect**, **web publish** must **not** require Cowork changes (**account-scoped** server rules).

**Decision — permission layers (coexist)**

| Layer | Mechanism | Use |
|-------|-----------|-----|
| **A. Web** | **Cookie session** — today **FastAPI-Users**; **target** **Clerk**-backed web session mapped to `User` | HTMX app, publish, dashboard. |
| **B. SSO / web IdP (pre–full deployment)** | **Clerk** (or equivalent) → mapped `User` | **Planned before GA:** managed signup/login/SSO; **not** a substitute for MCP tokens without an explicit OAuth/token exchange (see below). |
| **C. Remote MCP / Cowork** | **OAuth 2.1** — **RS** = SMEme MCP; **AS** = **Clerk** (MVP target) *or* SMEme-embedded (fallback) | **`smeme_reasoning_*`** MCP tools; **scopes** = least privilege; Cowork uses **client id/secret** + browser consent. |
| **D. Automation (deferred)** | **Hashed API keys** (internal automation keys, etc.) | **Not** a planned first-class external surface—product integration is **MCP + OAuth**. Revisit only if a concrete automation use case appears. |
| **E. Interim** | FastAPI-Users **JWT** | Curl, internal tools until C is live. |

**Decision — rules**

1. **Resource server** — Implement **RFC 9728** metadata and **401** challenges. Prefer **Streamable HTTP** for remote MCP when built.

2. **Authorization server** — OAuth **2.1** with **short-lived access tokens**, **`reasoning:*` scopes** (forward-looking naming), **refresh tokens** with **explicit expiry** and rotation so hosts can **refresh** reliably (mitigates connector **de-auth** when tokens lack proper lifecycle). **MVP preference:** delegate AS to **Clerk** (hosted authorize/token/consent) so SMEme implements **RS** + **JWT verification** only; **fallback:** embedded **Authlib** (or similar) on SMEme if Clerk scopes/audiences do not fit.

3. **Reasoning access** — Token **subject** = `users.id`. **List / evaluate** only **author-owned** QNRs with a persisted **`reasoning_compiled_artifacts`** row (**`graph_hash`** match). **No per-QNR secret** in Cowork after connect. **`is_public`** = gallery/web visibility, **not** “any logged-in user may call integrate evaluate”; **narrow** cookie+public **REST** evaluate when **C** is primary.

4. **Scopes (v1)** — `reasoning:list`, `reasoning:evaluate`; later repair/counterfactual scopes (DR-4). **Structural verify** stays **owner-only** unless explicitly scoped.

5. **Cowork connector** — Document **MCP URL**, **first-party OAuth client**: **static Clerk OAuth app Client ID** in plugin `.mcp.json` when **Clerk DCR is off** (default — avoids public `/oauth/register` risk per Clerk’s dashboard warning). Optional **client secret** only if a client uses confidential flow; **Public + PKCE** covers Cowork without a secret in the plugin. **DCR** remains an explicit opt-in at Clerk instance level; if enabled, SMEme should advertise `registration_endpoint` in AS metadata. Call out **plan/beta** limits and **re-auth** UX; our side minimizes via **refresh** + clear **exp**.

6. **API keys** — **Deprioritized** as a public integration path; **MCP + OAuth** is the external agent surface (see [P3 sprint — RS binding + metering](planning/sprint-dr3-p3-mcp-rs-binding-metering.md)). Optional internal keys remain a backlog idea only if demand materializes.

**Alternatives considered** — Cookie-only MCP (rejected); API-keys-only primary (rejected); **passing a third-party web-session or IdP access token straight to MCP as a bearer** without **`reasoning:*` binding, audience, and refresh lifecycle** (rejected). **Managed IdP for the web app** (e.g. **Clerk**) is **planned**, not rejected—see pre–full deployment below.

**Rationale** — Spec + Anthropic remote MCP alignment; SSO vs delegation separated; account-scoped reasoning access matches publish-without-Cowork-work; refresh-first AS addresses real connector churn.

**Consequences** — DR-3+ AS/RS/metadata/MCP/slug/list + tighten REST; **spike** Anthropic OAuth/token shape each release; optional gateway later.

**Implementation sequence** — **P0** metadata + discovery stubs (**shipped:** `MCP_ENABLED`, Streamable HTTP MCP endpoint, RFC 9728 + AS metadata JSON, OAuth endpoint **501** stubs — see `docs/guides/dr3-mcp-oauth-authoritative-sources.md`).

**P1 — Authorization server (pick one path for Cowork; can add the other later)**

| Track | What to build | When it fits |
|-------|----------------|--------------|
| **P1-Clerk (MVP-friendly)** ✅ **SHIPPED 2026-03-27** | **Clerk** OAuth application ("SMEme MCP") created; client id/secret in password manager. **RFC 9728** `authorization_servers` = Clerk issuer (auto-derived from `CLERK_PUBLISHABLE_KEY`; overridable with `CLERK_OAUTH_ISSUER`). **`/.well-known/oauth-authorization-server`** returns **inline JSON** derived from issuer URL — no 302 redirect (CORS fails in browser-based MCP clients; see [LESSONS_LEARNED §Discovery](LESSONS_LEARNED.md#302-redirect-for-as-metadata-fails-cors-in-browser-based-mcp-clients)). **`/.well-known/openid-configuration`** also served inline (required by MCP Inspector Guided flow). Trailing slash stripped from `authorization_servers` after Pydantic `AnyHttpUrl` serialization (see [LESSONS_LEARNED §AnyHttpUrl](LESSONS_LEARNED.md#pydantic-anyhttpurl-adds-a-trailing-slash-to-bare-origins)). SMEme `/oauth/authorize` + `/oauth/token` stubs removed. **Scope spike result (Clerk limitation):** Clerk does not issue custom resource scopes in OAuth access tokens as of March 2026 — P2 uses sub-based ownership only; `reasoning:*` enforcement deferred to P3. | Shipped on Clerk + Render free tier. |
| **P1-Embedded (fallback)** | **Authlib** (or equivalent) **authorization_code** + **refresh** on SMEme; tokens bound to `User` + scopes. | Only needed if Clerk custom scopes become required before P3, or if Clerk constraints block custom audiences. Estimated 7–9 days. |

**P1-Web (parallel or first)** ✅ **SHIPPED** — **Clerk** for **HTMX web** sessions (Backend SDK, webhooks → `users`, profile refactor with Clerk ownership split, `smeme_clerk_logout` contract). **Browser auth ownership (2026-06):** Clerk owns sign-in, sign-up, password reset, and email verification UX. SMEme retains **`users`** row sync (Clerk callback + webhooks), cookie/JWT helpers for in-app routes, and profile fields Clerk does not manage. **Removed** legacy FastAPI-Users HTML routes (`/auth/forgot-password`, `/auth/reset-password`, `/auth/verify`, resend/request-verify-token) — no stubs or redirects. **UX polish shipped 2026-03-28:** `Clerk.openSignIn()` modal (no Account Portal redirect), `withSigningInOverlay` + `showSigningInOverlay` (loading spinner for email/code flow), client-side `Clerk.session` check after `Clerk.load()` (fast redirect for Google/social OAuth landing), `/auth/clerk-callback` canonical callback route (eliminates `redirect_url` reliability issues), logout race fix (`smeme_clerk_logout=1` skips server pre-check so `Clerk.signOut()` can run), `azp` Account Portal fix (`clerk_authorized_parties()` includes Account Portal + frontend API hosts). See [LESSONS_LEARNED §Clerk Web Auth UX](LESSONS_LEARNED.md#clerk-web-auth-ux-three-patterns-working-together).

**P2** ✅ **SHIPPED 2026-03-28** — **`TokenVerifier`** on MCP: `smeme/mcp/bearer_auth.py` validates Bearer JWTs against Clerk JWKS (`_JwksCache` with 5-min TTL + kid-rotation re-fetch). Maps `sub` → `User.clerk_user_id`. Raises `MCPAuthError` for all failure paths (no header, wrong scheme, expired, wrong issuer, no sub, user not found, deactivated). **`smeme_reasoning_list`** and **`smeme_reasoning_evaluate`** tools wired with auth. DB sessions via `AsyncSessionLocal` (no FastAPI `Depends`). Z3 in `asyncio.to_thread`. 16 unit tests in `tests/unit/mcp/test_p2_bearer_auth.py`. **End-to-end confirmed with MCP Inspector** Quick + Guided OAuth flows; Google SSO via Clerk; real reasoning evaluation returning `SAT_UNIQUE` / `UNSAT`. Auth contract: sub-based ownership only (`reasoning:*` scope enforcement deferred to P3).

**Post-P2 retrofit (2026-04):** FastMCP **`AuthSettings`** + **`ClerkMcpTokenVerifier`** (`mcp` SDK `RequireAuthMiddleware`) when `clerk_oauth_issuer` is set — unauthenticated MCP Streamable HTTP requests return **401** with **`WWW-Authenticate`** including **`resource_metadata`** (RFC 9728 challenge). Shared JWT decode: `decode_clerk_oauth_access_token`. **`smeme_reasoning_capabilities`** requires the same Bearer + user row (checkpoint A in [DR-3 guide — Transport-layer auth and HTMX middleware](guides/dr3-mcp-oauth-authoritative-sources.md#transport-layer-auth-and-htmx-middleware)). Tests: `tests/unit/mcp/test_dr3_mcp_transport_oauth.py`.

**Validated connectors:** **MCP Inspector**; **Anthropic** clients (Chat, Cowork, Desktop) with **Clerk DCR** and/or **custom connector** + static Client ID; **Cursor** with DCR. Plugin zip = skills; see [LESSONS_LEARNED — Anthropic plugin import](LESSONS_LEARNED.md#anthropic-plugin-import-drops-oauthclientid).

**P3** — **[MCP resource-server binding + usage metering](planning/sprint-dr3-p3-mcp-rs-binding-metering.md):** **Invocation telemetry + quotas shipped.** **OAuth client allowlist** code retained; **SaaS prod (2026-06-18):** **Clerk DCR on**, **`CLERK_OAUTH_DYNAMIC_REGISTRATION=true`**, **`SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS` blank** (DCR client ids not allowlistable). Self-hosted DCR-off may set static allowlist. **`aud`** benched when Clerk lacks stable audience. **OAuth refresh UX** (connector de-auth). **`reasoning:*` scope enforcement** once Clerk supports custom scopes. **Narrow public REST evaluate** remains hygiene when MCP is primary.

**P4** — Web SSO polish — largely **Clerk** dashboard config if P1-Web done.

**P5 (before full deployment / GA)** — **Render topology**: separate MCP **RS** service when traffic or blast-radius warrants it; **Clerk** remains AS (or migrate AS only if product changes).

**Pre–full deployment — Clerk (or equivalent managed IdP)**

- **Goal:** Move **web** authentication (registration, login, passwordless/SSO, session UX) to **Clerk** **before** treating SMEme as fully deployed to a broad market, reducing auth maintenance and aligning with connector-era expectations.
- **MVP acceleration:** If **Clerk** + **Render** free tiers are sufficient, **implementing Clerk during MVP** is reasonable: one product for **web sessions** and (when confirmed by spike) **OAuth AS for remote MCP**, avoiding a throwaway **Authlib** AS. **Python stack:** use **Clerk Backend SDK** + **JWKS JWT verification** on MCP; **do not** depend on **`@clerk/mcp-tools`** (Node-only); mirror **AS metadata** in FastAPI per RFC 8414 / Clerk docs.
- **User model:** Keep a stable **`users`** row (or successor table); **map** Clerk `sub` (and org metadata if used) to that record on first login and on each request (webhooks or JWT claims).
- **MCP OAuth:** Remote MCP stays **OAuth 2.1** with **`reasoning:*` scopes** and refresh-friendly tokens. **Preferred (P1-Clerk):** Clerk issues access/refresh tokens for the **OAuth app** used by Cowork; SMEme **only validates** tokens and enforces scopes. **Fallback:** **token exchange** or **P1-Embedded** AS if Clerk cannot express required scopes/audiences. **Do not** treat the browser Clerk session cookie as proof of identity for MCP JSON-RPC.
- **Same container (MVP):** Running **MCP Streamable HTTP** on the **same FastAPI app** as HTMX + REST is **acceptable** (matches common Clerk + FastAPI guidance); separation is **logical** (bearer-only MCP) and **deploy** (P5) when scaling requires it.
- **Migration:** Overlap **FastAPI-Users** only as long as needed for cutover; document rollback and dual-read. **P1-Web** and **P1-Clerk** may be **ordered either way** depending on whether Cowork or dashboard login is higher urgency.
- **Profile / identity split (Clerk vs SMEme):** **Clerk** owns sign-in: **email** + **verification codes** (default); optional **password** and **first/last name** via Account Portal (optional 2FA when enabled in Clerk). **SMEme** does **not** mirror Clerk usernames; the app handle shown in UI is the **sign-in email**. The legacy **`users.username`** column remains a **unique internal slug** derived from the email local-part at first Clerk sync (`get_or_create_user_for_clerk`) for DB/FastAPI-Users compatibility and provisional `/creator/{slug}` routes when marketplace UI is on. **Editable public creator aliases** are deferred to **Business** author profiles (Coming Soon)—not Clerk Account Portal. **`PUT /auth/profile/me`** rejects email changes (Clerk) and handle changes (Business tier not shipped). Creator bio/links/credentials are SMEme-owned when marketplace UI is enabled.
- **Profile refactor — explicit note (Clerk logout / session; do not regress):** Server-side cookie clearing on **`GET /auth/logout`** (`clear_clerk_browser_cookies` in `smeme/auth/clerk_auth.py`) is **not sufficient** by itself: **`Clerk.load()`** in **`smeme/templates/partials/_clerk_browser_sync.html`** runs on **`/auth/login`** and can **rehydrate** Clerk session cookies from **client** state (IndexedDB / sync), so users looked “still logged in” after logout. The working contract is: when **`CLERK_SIGN_OUT_URL`** is **not** set, redirect to **`/auth/login?smeme_clerk_logout=1`**; the partial, after **`Clerk.load()`**, calls **`Clerk.signOut({ redirectUrl: origin + "/auth/login" })`** (and strips the query param). **Any future Profile or auth UX refactor** that moves login, embeds Clerk differently, adds alternate logout entrypoints, or changes where **`_clerk_browser_sync.html`** runs must **preserve this end-to-end sign-out** or **replace it with an equivalent** (e.g. always hitting Clerk-hosted sign-out + same client cleanup); otherwise logout will silently break again.

**Render / container — MCP vs app API (what is split today vs target)**

- **Today (one Render Web Service, one process):** The HTTP app is a **single FastAPI** instance. **MCP is not mixed into HTMX or QNR routers:** Streamable HTTP is a **mounted Starlette sub-app** at **`MCP_HTTP_PATH`** (default **`/api/v1/mcp`** in `smeme/mcp/reasoning_fastmcp.py`), wrapped by **`StripLastEventIdMiddleware`** to avoid Python SDK **500**s when clients send **`Last-Event-ID`** without an **`EventStore`** in stateless mode ([LESSONS_LEARNED](LESSONS_LEARNED.md#mcp-streamable-http-last-event-id-python-sdk-and-striplasteventidmiddleware)), while the **app API** lives under **`/api/v1/...`** routers and **`/auth/...`**, **`/qnr/...`**, etc. **RFC 9728** metadata is exposed under **`/.well-known/oauth-protected-resource/...`**. So **URL paths and the MCP stack are already separate** from page and REST route handlers; **discovery and OAuth stub routes** register on the same app.
- **Shared concerns (still one container):** Same **process**, **DB pool**, **env**, and **global ASGI middleware** (e.g. CORS, logging) run **before** routing—MCP requests are not a second container yet.
- **Target before full deployment:** **Two Render Web Services** (or two processes behind a gateway if we outgrow the simple model): (**1**) **Web + app API** — cookies, HTMX, billing, QNR, internal REST; (**2**) **MCP resource server only** — **bearer-only** validation, minimal surface, **independent** deploy and scale, **no** reliance on session cookies for MCP. Both talk to the **same Postgres**; tokens verified via **JWKS** or **introspection** from whichever component is the **AS** (Clerk and/or SMEme). Until then, **staging / closed beta** may stay on **one** service if MCP never authenticates via cookies and **RFC 9728** `resource` URLs remain correct for the public MCP base URL.

**Canonical doc note** — Third-party blog/support links in research memos may drift; treat **MCP spec** + **Anthropic official docs** as source of truth for integration spikes. Deployment detail for MCP/OAuth also summarized in `docs/guides/dr3-mcp-oauth-authoritative-sources.md`.

---

## Deterministic Reasoning (DTQ)

### D017: DTQ Proof-of-Concept vs Production Symbolic Reasoning Pipeline

**Context**

1. **`smeme/qnr/dtq/` (DR-1)** delivered a working **proof of concept**: compile a minimal theory artifact, structural Z3 checks, publish gate, and evaluation paths sufficient to validate the **product shape** (QNR → deterministic reasoning → MCP tools).

2. The **platform around it** — QNR authoring, graph storage, sessions, billing surfaces, **remote MCP** ([D016](#d016-authentication--permissions--final-plan-cowork-launch-remote-mcp-sso)), OAuth, and HTTP boundaries — was built so that a **real** symbolic reasoning stack could plug in later. The PoC was not intended as the final theory encoding or long-term maintenance burden.

3. A **replacement architecture** is in progress: **lossless IR** from QNR, **IR validation**, **theory compilation**, and **runtime execution** (see `smeme/reasoning/SPRINT_PLAN.md`, `smeme/reasoning/workflow_design.md`). That pipeline is what we intend to **ship to production** and put in front of users.

4. There is **no requirement** to preserve PoC-era DTQ semantics for an external “installed base”: the earlier work was **internal / exploratory**, not a committed production contract we optimize for backward compatibility.

**Decision**

1. **Production reasoning** = the **IR-first pipeline** under **`smeme/reasoning/`** (compiler spine, validator, theory layer, runtime). The former PoC package under **`qnr`** has been **removed**; it is not the long-term core.

2. **Do not** invest in deep fixes or feature expansion in deleted PoC modules **as if** they were the final architecture. Prefer **greenfield** theory/IR code in **`smeme/reasoning/`** over reviving the old encoding.

3. **Reuse deliberately**: keep **MCP**, **OAuth/bearer auth** ([D016](#d016-authentication--permissions--final-plan-cowork-launch-remote-mcp-sso)), **`QNRGraph` / graph JSON** as authoring truth, DB and routing patterns where they still fit. The **theory builder and publish gate** now live in **`smeme/reasoning/`**.

**Alternatives considered**

1. **Evolve `smeme/qnr/dtq/` in place** — incrementally fix Z3 guards, reachability, and compiler output until it matches the spec. **Rejected** as the primary path: wrong abstraction, high merge cost with the IR/validator design, and it perpetuates technical debt we already named disposable.

2. **Maintain two parallel “production” implementations** — old DTQ for “stability,” new for “future.” **Rejected**: duplicates effort and blurs ownership; the PoC is explicitly **not** a stability anchor.

**Rationale**

- Aligns engineering with **intent**: the rest of the codebase exists to support **capability**, not to freeze the first Z3 sketch.
- Frees the team to **delete or thin** PoC code at cutover instead of endlessly patching it.
- Keeps **integration surfaces** (MCP tools, auth, QNR data) stable while swapping the **reasoning engine** underneath.

**Consequences**

- ✅ Clear **single direction** for new work: IR, validation, theory, runtime.
- ✅ **MCP and platform** investment remain valid; only the **DTQ implementation folder** is superseded.
- ⚠️ Docs and tests that still describe the PoC stack as “the” system should be **updated** to point at **`smeme/reasoning/`**. **MCP** tool contracts ([D016](#d016-authentication--permissions--final-plan-cowork-launch-remote-mcp-sso)) remain; **implementation** is IR-first.

---

### D018: MCP Harness Evidence Envelope and Two-Phase Evaluate (M0)

**Context**

Cowork and other MCP clients treat the server as the **source of policy** for reasoning ingest, but the shipping path was **list → worksheet → evaluate** with incomplete Phase 1 (evidence **`E`**) representation, no first-class **provenance**, and **warnings** vs hard errors under-specified for LLM harnesses. Agents need **machine-stable** payloads, optional **orchestration hints**, and **one canonical registry** for `code` values so skills and runbooks do not drift.

**Decision**

1. **Normative M0 design lock** — [`docs/planning/mcp-harness-evidence-evaluate-m0-design-lock.md`](planning/mcp-harness-evidence-evaluate-m0-design-lock.md): **shape C** ingest (`evidence_items[]` + per-question refs + `answers`), **`warnings[]`** for non-blocking hygiene (e.g. `missing_evidence_ref`), hard rejects via existing **`error.code`** patterns, **Phase 1** **`smeme_reasoning_validate_*`** without Z3, **Phase 2** **`smeme_reasoning_evaluate`** **gated** on the same validation kernel before Z3. **REST** `POST …/reasoning/evaluate` uses the **same kernel** when **`REASONING_REST_EVALUATE_ENABLED=true`** (default **`false`** — MCP-first surface; enable for tests/operators).

2. **Persistence** — On `persist=true` completed runs, store ingest warnings in a **dedicated** JSONB column on **`reasoning_evaluation_runs`** (e.g. `ingest_warnings`); **never** overload `conflict_report` / `explanation` for ingest hygiene.

3. **Telemetry** — Hard rejects without a completed row **must** emit structured **logs + metrics** (same `code` vocabulary).

4. **Canonical codes + ordering** — Single **`smeme/`** module for wire codes; deterministic sort for `warnings[]` (see design lock §5).

5. **Orchestration hint** — **`harness_next` / `phase_result`**-style enum on validate/evaluate success is **recommended** but **explicitly chosen per M0 PR** (ship in v1 vs defer); capabilities advertise if present.

6. **Blob evaluate** — Remains **lab / operator-only**; not part of the product harness path ([sprint plan §2.4](planning/sprint-mcp-two-phase-evidence-and-evaluate.md#24-engineering-only-blob-mcp-tool-not-in-deployment-plan)).

**Alternatives considered**

1. **Inline-only provenance (shape A)** per answer — rejected for this sprint; shape **C** supports multi-cite and shared timestamps ([sprint plan §2.5](planning/sprint-mcp-two-phase-evidence-and-evaluate.md#25-normative--provenance-envelope-shape-c-ships-this-sprint)).

2. **Blocking evaluate when evidence refs missing** — rejected; **warnings** only ([sprint plan §2.6](planning/sprint-mcp-two-phase-evidence-and-evaluate.md#26-normative--warnings-vs-hard-rejects-persistence-and-telemetry)).

3. **Skills-first routing without server hints** — acceptable only if (5) defers; risks harness drift ([sprint plan §2.7](planning/sprint-mcp-two-phase-evidence-and-evaluate.md#27-m0-design-lock--llm-harness-reliability)).

**Rationale**

- Aligns MCP (and **opt-in** REST JSON evaluate) with the **two-phase** product story; keeps Z3 behind a **validate gate**.
- Gives operators **auditable** warnings and **observable** failure rates without fake evaluation rows.

**Consequences**

- Requires **migration**, MCP semver / **`REASONING_CAPABILITIES_VERSION`** bump, and **implementation backlog** ([mcp-harness-evidence-evaluate-tickets.md](planning/mcp-harness-evidence-evaluate-tickets.md) — items **T1–T5**).
- Agent Skills and runbooks **after** satisfactory implementation ([sprint plan §8](planning/sprint-mcp-two-phase-evidence-and-evaluate.md#8-exit-criteria-sprint-plan-complete)).

---

### D019: MCP Evaluate Product Report and Mandatory Provenance (Shape C.1)

**Context**

Harness agents need **provenance** for each answered slot, a **canonical server-generated memo** (not LLM-paraphrased Z3 vocabulary), and **user-facing outcome language** without `SAT_*` / `triggered_edges` on the MCP wire. There are no legacy MCP consumers requiring the old evaluate JSON.

**Decision**

1. **Shape C.1 ingest** — Extend `evidence_items` with required harness fields: **`title`**, **`locator`**, **`locator_kind`** (`file` | `url` | `mcp_resource` | `workspace_path` | `other`), plus existing **`excerpt`**, **`retrieved_at`**, **`source_id`**, **`id`**. Skills treat **every answered question** as requiring **`evidence_refs`**; on **`missing_evidence_ref`** warnings from **`smeme_reasoning_validate_answers`**, the agent **asks the user** for a source before evaluate.

2. **Evaluate response** — **`smeme_reasoning_evaluate`** returns **`report`** only on success (`result_kind`, `headline`, `brief_memo`, `reasoning_path`, `candidates`, `answer_sheet`). **No** top-level `outcome`, `technical`, or Z3 trace fields on MCP. Internal `EvaluationResult.status` remains for DB indexing.

3. **Report builder** — Server builds **`report`** from graph text + ingest envelope + evaluation result (`smeme/reasoning/runtime/report_builder.py`). **`reasoning_path`** uses witness order without exposing edge ids or guard logic to the harness.

4. **Validate** — **`smeme_reasoning_validate_answers`** returns **`status`**, **`warnings`**, **`harness_next`** only (no **`report`**).

5. **Persistence** — Store full **`report`** JSONB and **`ingest_envelope`** snapshot on **`reasoning_evaluation_runs`** when `persist=true`.

6. **Capabilities** — Bump **`REASONING_CAPABILITIES_VERSION`** / plugin semver to **2.6.0**; advertise **`evaluate_response.report_v1`** and **`evidence_locator_v1`**.

**Consequences**

- Cowork skills and runbooks must branch on **`report.result_kind`**, not `SAT_*`.
- REST evaluate (opt-in) mirrors **`artifacts.report`**; summary drops Z3 field names.

---

### D020: Pre-built Tailwind CSS Over the Play CDN

**Context**

`layouts/base.html` loaded Tailwind via the **Play CDN** (`cdn.tailwindcss.com`) with an inline `tailwind.config` and a hand-written "critical CSS" `<style>` block. The Play CDN ships a large JS runtime and **compiles CSS in the browser on every page load** — it is explicitly *not for production*. This hurts LCP/CLS (a Core Web Vitals ranking + conversion signal) and was the biggest technical SEO risk before driving launch/paid traffic. See [PRE_GTM_CHECKLIST §12](PRE_GTM_CHECKLIST.md) and the SEO/GEO review.

**Decision**

Pre-build a **purged static stylesheet** and serve it as a single `<link>`:
- Source: `tailwind.input.css` (@tailwind directives + `--ui-*` tokens + custom base/component CSS moved out of `base.html`) and `tailwind.config.js` (theme moved verbatim from the old inline config; `content: ["./smeme/templates/**/*.html"]`; `darkMode: "class"`; a small `safelist` for classes toggled only in inline JS).
- Build: `scripts/build_css.sh` / `make css` downloads the **Tailwind standalone CLI binary** (pinned `v3.4.17`, cached in `.cache/`) and emits `smeme/static/css/app.css --minify`. **No npm/Node in the app or runtime image.**
- Docker: the builder stage runs the build; the runtime stage copies the fresh `app.css` over the committed one, so prod is always freshly purged.
- `smeme/static/css/app.css` is **committed** so local dev, tests, and non-Docker runs work without a build.

**Alternatives Considered**
1. **Keep the Play CDN** — simplest, but the production performance/CWV cost is exactly what launch traffic can't afford.
2. **Defer/async the CDN script** — still downloads + runtime-compiles; causes FOUC because styles apply after JS.
3. **npm + PostCSS build pipeline** — the conventional Tailwind setup, but violates the repo's "no npm/Node" constraint and adds toolchain weight.

**Rationale**
- The standalone CLI is a single binary → keeps the "no npm/Node in the app" constraint intact while removing the runtime JS + in-browser compile.
- Output is ~13 KB gzipped vs the CDN's ~400 KB+ JS; render-blocking `<link>` avoids FOUC/CLS.
- Content scanning is safe here: macros/JS use complete class-name string literals (no `"bg-" + x` concatenation), and dynamic toggles are also safelisted.

**Consequences**
- ✅ Faster LCP/FCP, no in-browser compile, no third-party JS on every page.
- ⚠️ A build step now exists (the one sanctioned exception to "no build step"): **rebuild `app.css` after changing template classes** (`make css`); Docker rebuilds it automatically. Drift between the committed CSS and templates is possible locally until rebuilt — a CI `--check` guard is a candidate follow-up.
- ⚠️ Pinned to Tailwind v3 config format; a v4 upgrade would change config/input conventions.
- Related: [D003 (HTMX over React/Vue)](#d003-htmx-over-reactvue) — htmx is still CDN-loaded (small); self-hosting is a possible later step. Full how-to: [guides/frontend-css-build.md](guides/frontend-css-build.md).

---

### D021: Blind Protocol Retained for Agent Reliability (Not License-Dependent)

**Context**

Product is moving toward a **source-available / non-commercial use** license. That weakens one historical rationale for the MCP **blind evaluation protocol** — protecting SMEme’s *engine* IP by never shipping graph internals to third-party LLM contexts. Creators still care about playbook confidentiality, but the open question was whether to **relax the wire contract** (expose branching rules / IR topology on evaluate-path tools) once engine source is available.

**Decision**

**Keep the blind protocol on the default agent evaluate path.** Assistants may see question text, valid answer options, and report-vocabulary outcomes; they must **not** receive edge guards, branch topology, conclusion wiring, `reach` atoms, or solver internals via product MCP tools (`evaluate`, `what_if`, and non-target fields of `how_to_reach`).

Primary rationale is **agent reliability and division of labor**, not engine IP:

1. The harness must **gather and slot-fill**, not re-derive judgment along the tree.
2. Seeing branches tempts the model to skip tools, invent repairs, or steer answers toward a hoped-for conclusion — contaminating evidence and breaking attributable reports.
3. Dumping the playbook into context burns tokens and fights the compiled-\(T\) product story ([ALGEBRA.md](../ALGEBRA.md) §17 query modes).

**IP / creator confidentiality remains a secondary benefit** (especially for shared workflows), but a source-available engine license **does not** authorize relaxing the default MCP wire contract.

Optional **owner/debug** surfaces that expose more structure may ship later as **explicit opt-in** — not as the default Cowork/evaluate path. Authoring aids already allowed under the protocol (`template_get`, `list_conclusions` for target ids) stay as today.

**Alternatives Considered**
1. **Relax blind on all MCP tools because source is available** — confuses the LLM and collapses the gatherer vs reasoner split.
2. **Keep blind only for grantee/shared workflows; open for owners** — owners still run agents that will misuse topology; keep default blind, add opt-in debug if needed.
3. **Drop blind entirely; rely on skill prompting alone** — aspirational; not enforceable when tools return the graph.

**Rationale**

Source-available means third parties can *read the codebase*; it does not mean every agent session should load each workflow’s decision graph into the model. Blind evaluation is a **runtime product contract** that keeps reasoning server-side and agents honest. See settled constraint [CWP §2.2](planning/cowork-plugin-delivery-sprints.md#22-blind-evaluation-protocol-settled-design-constraint) and product narrative [user-contract — Blind evaluation](product/user-contract.md#blind-evaluation-plain-language).

**Consequences**
- ✅ License change and marketing can emphasize openness of the *engine* without changing evaluate-path blindness.
- ✅ Skills / guidance continue to forbid mental-modeling \(T\) / anticipating conclusions.
- ⚠️ Do not treat “source available” as permission to return `triggered_edges`, guard text, or full IR on product tools.
- ⚠️ A future owner-debug mode needs a separate ADR/sprint if product wants deeper inspection without breaking the default agent path.

---

### D022: Product Surface Inventory — Keep / SaaS-Only / Removed (Core Distro Prep)

**Status:** Accepted (2026-07-18); **distribution wording amended 2026-07-20**. Inventory remains normative for *classification* (what is Core vs SaaS-only vs removed). **Where code lives and how it is packaged** is locked in **[D023](#d023-public-core-repo--private-saas-overlay-distribution)** (public Core product repo + private SaaS overlay; n8n-shaped). Composition / extract may still be in progress in this tree.

**Related:** [D016](#d016-authentication--permissions--final-plan-cowork-launch-remote-mcp-sso) (auth / MCP), [D017](#d017-dtq-proof-of-concept-vs-production-symbolic-reasoning-pipeline) (IR reasoning), [D021](#d021-blind-protocol-retained-for-agent-reliability-not-license-dependent) (blind evaluate), [D023](#d023-public-core-repo--private-saas-overlay-distribution) (distribution), [ROADMAP — Gated surfaces](ROADMAP.md#gated-surfaces), [user-contract](product/user-contract.md), [CIMD research](planning/cimd-mcp-client-registration-research-2026-07.md).

#### Context

SMEme is evolving toward two deployable shapes:

1. **SaaS** — `smeme.ai` (Render today): Clerk, Stripe, marketing landing, Business waitlist, Plausible, Arista-branded legal pages — commercial hosted layer on top of Core ([D023](#d023-public-core-repo--private-saas-overlay-distribution)).
2. **Core (self-host)** — product app + Postgres; humans author/Deploy/List; agents call MCP. No Stripe requirement; BYO OAuth AS (generic OIDC target; Clerk as first profile). Exact license text deferred to first public release ([D023](#d023-public-core-repo--private-saas-overlay-distribution)).

**Today** this repository may still be a single private tree that contains both Core and SaaS-only code. **Target** is a **public product repo** `<org>/smeme` (forks/PRs, `ghcr.io/<org>/smeme` image) plus a **private overlay** `smeme-cloud` — not a divergent secret product fork. See [D023](#d023-public-core-repo--private-saas-overlay-distribution).

Before packaging Core, the tree accumulated **lab / dogfood / GTM-experiment** surfaces (flagged off or “on in prod for dogfood”) that expanded attack surface, confused the product narrative, and would leak into any “full codebase” distro. A 2026-07-18 strip deleted those lab surfaces from the monorepo (both SaaS and future Core). Separately, operators asked what belongs in Core vs what stays SaaS-only when a stripped distro ships.

This ADR answers: **what is product**, **what is SaaS-only**, **what was removed on purpose**, and **what remains optional at runtime** (flag-gated Core). It does **not** by itself lock repo topology — that is [D023](#d023-public-core-repo--private-saas-overlay-distribution).

#### Decision

Classify every user- or agent-facing surface. **KEEP** and **REMOVED** are distribution buckets for the public Core tree. **SAAS-ONLY** must not appear in public Core or the `smeme` image. **FLAG-GATED** is **not** a fourth distribution bucket — it marks **Core** code that is optional at runtime (`required` vs `optional` under KEEP).

| Bucket | Meaning |
|--------|---------|
| **KEEP (Core)** | Required or first-class product surface. Lives in the **public** `smeme` tree (and thus in cloud via image pin). Public distro / `smeme` image **must** include. |
| **SAAS-ONLY** | Legitimate for `smeme.ai` (or Arista-operated cloud). Lives in the **private `smeme-cloud` overlay** — **must not** appear in the public tree or `smeme` image. Do not rely on “empty env ⇒ soft disable.” |
| **FLAG-GATED** | Optional **Core** capability (same public tree); may default off. Flags are for **real options**, not a graveyard of experiments. |
| **REMOVED** | Deleted from the product tree (2026-07-18). Do not reintroduce without a new ADR/sprint. Planning docs may still mention them historically. |

**Packaging rule (normative):** Core enforcement is **artifact and tree shape** (SaaS routers not mounted in Core entrypoint, SAAS-ONLY packages not in public Core / not in `smeme` image), not “operators forgot to set `STRIPE_*`.” Empty Stripe keys still leave routes and upgrade CTAs if billing code ships in the Core artifact. See [D023](#d023-public-core-repo--private-saas-overlay-distribution).

**Auth posture (forward-looking, not fully implemented):** SMEme remains an MCP **resource server (MRS)**. Do **not** embed an OAuth authorization server in SMEme. Target: generic OIDC/OAuth JWT verify + `sub` → local user; Clerk is the first **profile**. CIMD and [Enterprise-Managed Authorization](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization) are **MAS/IdP** concerns — selection criteria for the customer’s AS, not reasons to grow an in-process AS. See Future Decision Areas §6 and [D023](#d023-public-core-repo--private-saas-overlay-distribution).

---

#### KEEP (Core) — public Core tree (and SaaS via Core dependency)

These define the product: experts encode workflows; agents evaluate structured answers; reasoning stays on the server ([D021](#d021-blind-protocol-retained-for-agent-reliability-not-license-dependent)).

##### Web application

| Surface | Location / notes |
|---------|------------------|
| Auth entry + session (Clerk today) | `smeme/auth/*` — Core will need a **generic OIDC adapter**; until then SaaS and Core-preview may still use Clerk |
| Profile (non-marketplace) | `smeme/auth/routes.py` profile dashboard; no public `/creator/{username}` |
| Dashboard | `smeme/qnr/routes.py` — workflows list, permanent delete (not archive) |
| Graph editor + Deploy / publish readiness | `smeme/qnr/editor/*`, `smeme/reasoning/publish_readiness.py` |
| Listed / Hidden (MCP discoverability) | Per-user `mcp_discoverable` — owner-scoped |
| Live / Stale vs deployed artifact | Dashboard / Tools panel semantics |
| Session viewer (consumer path) | `smeme/qnr/viewer/*`, `smeme/qnr/workflow.py` |
| In-app creator docs (non-pricing) | `smeme/docs/routes.py` — intro, MCP connect, changelog; **strip `/docs/plans` upsell from Core** when packaging |
| Health | `smeme/api/health.py` |
| Reasoning preflight (owner) | `smeme/api/reasoning_preflight.py` |

##### Reasoning spine

| Surface | Location / notes |
|---------|------------------|
| QNR → IR compile, validate, Z3 theory | `smeme/reasoning/ir/*`, `theory/*` |
| Publish SAT gate | `enumerate_conclusion_sat_queries` via publish readiness |
| Persisted `ReasoningCompiledArtifact` (`ir_json`) | Deploy artifact |
| Deterministic publish-time evidence contract induction | `smeme/reasoning/cevi/induction.py`, `deterministic_induction.py`, `atom_catalog.py`, corpus helpers — **keep writers**; do not resurrect Lexicon UI / legal ontology / LLM bridge |
| Structured evaluate | `evaluate_reasoning` + `fact_projection.py` ← **product evaluate path** |
| Blind MCP report vocabulary | [D019](#d019-mcp-evaluate-product-report-and-mandatory-provenance-shape-c1) / [D021](#d021-blind-protocol-retained-for-agent-reliability-not-license-dependent) |

##### MCP (when `MCP_ENABLED=true`)

Always-on product tools (when MCP is mounted):

| Tool | Role |
|------|------|
| `smeme_reasoning_capabilities` | Versioned catalog |
| `smeme_reasoning_list` | Owner Listed + deployed workflows |
| `smeme_reasoning_validate_answers` | Phase-1 ingest gate |
| `smeme_reasoning_evaluate` | Structured `raw_answers` → `report` |
| `smeme_reasoning_what_if` | Counterfactual compare |
| `smeme_reasoning_how_to_reach` | Target conclusion repair / entail / possible |
| `smeme_reasoning_decisive_support` | Minimal sufficient evidence |
| `smeme_reasoning_edit_affects_path` | Path-under-edit |
| `smeme_reasoning_list_conclusions` | Conclusion catalog |
| `smeme_reasoning_template_check` / `_get` | Worksheet / manifest for owners |
| `smeme_reasoning_guidance_check` / `_get` | Connector-only bootstrap contract |

**Skills authoring source (not the retired installable zip):** `plugin/cowork-skills/` — `smeme-reasoning-plugin`, `smeme-reasoning-outcomes`, `smeme-reasoning-slot-fill`, `smeme-workflow-author` (+ `DESIGN.md`). Connector + `guidance_get` is the primary install path; skills are optional host-side context.

##### Quota **engine** (logic kept; control plane changes for Core)

| Piece | Notes |
|-------|-------|
| `smeme/billing/quota.py`, `usage.py`, `tiers.py`, `access_policy.py`, `providers.py` | Cap checks / MCP reserve / wizard completion counting; provider-neutral lifecycle (no Stripe) |
| `mcp_tool_invocations` telemetry | Supports quotas and ops |

**Core intent (locked 2026-07-21):** **enforcement off by default**, **metering on**. Hosted Free/Pro Mode B caps are **registered explicitly** by the SaaS overlay (`register_hosted_quota_enforcement` in `saas_overlay`); SaaS boots **fail closed** if unregistered. There is **no** self-host env switch that reuses SaaS Free/Pro tiers. Stretch: operator-managed `defaults` / `per_user` (admin DB; env only seeds install). Do not confuse “keep quota engine” with “keep Stripe Checkout.”

##### Optional authoring (see FLAG-GATED)

AI generation wizard and MCP chat-authoring are **product options**, not lab scrap — classified under FLAG-GATED below, but the **code paths stay in Core** when the operator enables them.

---

#### SAAS-ONLY — private SaaS overlay (omit from public Core)

Lives in the **private `smeme-cloud` overlay** for `smeme.ai` ([D023](#d023-public-core-repo--private-saas-overlay-distribution)). Public builds and the `smeme` image must **not** include these packages/routes/templates (or must replace with operator-owned equivalents).

| Surface | Why SaaS-only | Primary locations |
|---------|---------------|-------------------|
| **Stripe Checkout / Portal / webhook** | Monetization; webhook fraud surface if shipped unused | `smeme/billing/routes.py` (payment paths), `stripe_sync.py`, `subscription_cancel.py`; templates `smeme/templates/billing/` |
| **SaaS downgrade / “pick a workflow”** | Free-after-cancel product | `smeme/billing/downgrade.py`, `WorkflowPickRequiredMiddleware`, choose-workflow routes |
| **Upgrade CTAs / `/docs/plans`** | Stripe upsell copy | docs plans page; dashboard upgrade chrome |
| **Marketing landing + SEO crawlers** | GTM / GEO for smeme.ai | `smeme/landing/routes.py` (`/`, how-it-works, robots, sitemap, `llms.txt`, …) — **except** waitlist routes below |
| **Plausible** | Phones home when configured | `_analytics.html`, `PLAUSIBLE_*` |
| **Arista legal / subprocessors pages** | AristaLabs contracts, not the customer’s | `smeme/legal/*` — Core needs **operator-supplied** policy or none |
| **Hardcoded SaaS MCP URL copy** | Points operators at production | e.g. `MCP_SAAS_PUBLIC_MCP_URL` in help surfaces — Core must use `BASE_URL` |
| **SaaS COGS / margin telemetry knobs** | Internal unit economics | `MCP_COST_*`, internal cost maps — optional to strip from Core |
| **Clerk as the only IdP story** | SaaS identity; Core → generic OIDC | Clerk webhook hard-delete, Account Portal sync assumptions — replace for Core |

##### SaaS-only but **explicitly retained** (lead-gen)

| Surface | Notes |
|---------|-------|
| **Business waitlist** | `/marketplace/business`, `POST /teams-waitlist`, `smeme/landing/waitlist.py`, SendGrid waitlist mail — **kept** by product decision (2026-07-18). Not for Core; still SaaS. Do not delete when packaging Core — **omit** from Core artifact. |

##### SaaS product still planned (not Core)

| Surface | Notes |
|---------|-------|
| **Business-tier sharing / grants / Connect** | [business-marketplace-access-plan.md](planning/business-marketplace-access-plan.md) — Coming Soon; not shipped. When built, classify again (likely SaaS-only or paid Core SKU). |
| **Public marketplace gallery** | **Removed** from monorepo (see REMOVED); plan docs remain historical. Do not resurrect into Core. |

---

#### FLAG-GATED — optional Core runtime (not a separate distro bucket)

These surfaces live in the **public Core** tree. Flags control whether they are on at runtime; defaults in `smeme/core/config.py`.

| Flag | Default | What it gates | Distro note |
|------|---------|---------------|-------------|
| `MCP_ENABLED` | off | Streamable HTTP MCP + OAuth discovery | Core almost always **on** in production appliances |
| `SMEME_AI_GENERATION_ENABLED` | on (SaaS) | AI generation wizard + checkpointer; requires `OPENAI_API_KEY` | Core appliances may default **off** |
| `MCP_AUTHORING_GRAPH_TOOLS_ENABLED` | off | `smeme_authoring_design_guidance`, `validate_graph`, `create_draft`; skill `smeme-workflow-author` | Deliberate chat authoring; **not** proactive scout |
| `SHOW_QNR_GENERATION_REGION_SELECTOR` | on | Tavily country on agentic brief | Harmless; Core may leave on |

**AI generation wizard** (`smeme/qnr/generation/agentic/*`): gated by **`SMEME_AI_GENERATION_ENABLED`** (default **on** for SaaS backward compatibility). When off, Core boots without OpenAI and does not mount generation routes or initialize the generation checkpointer. **Tavily** is an optional add-on when generation is on. **LangSmith is not optional today** — startup always runs `disable_langsmith_tracing()` (no third-party LangGraph I/O export); restoring it needs an explicit product opt-in, not env alone. See [self-host quickstart — sovereignty](guides/self-host-quickstart.md#sovereignty--third-party-egress).

**Authoring posture (product):**

- **Deliberate** path: user/agent chooses to build → wizard and/or MCP authoring tools + `smeme-workflow-author`.
- **Proactive scout** (removed): was intrusive; deliberate tools replace the *build* path, not unsolicited nudges.

---

#### REMOVED (2026-07-18) — both SaaS and Core

Deleted from the monorepo so they cannot be “accidentally flipped on.” Do not restore without a new decision.

| Surface | Former flags / homes | Why removed |
|---------|----------------------|-------------|
| Marketplace / gallery / public creator profiles | `SHOW_MARKETPLACE_MONETIZATION_UI`, `smeme/gallery/`, `profile_public.py` | Public discovery + monetization UI; leak risk; not GTM Free/Pro path |
| Archive / Restore UI | `SHOW_QNR_ARCHIVE_UI` | Unfinished edge; permanent delete is the product path |
| Web memo pipeline | `smeme/memo/` | Legacy vs agent-owned MCP `report`; attack/ops surface |
| NL blob evaluate | `MCP_REASONING_BLOB_TOOL_ENABLED`, `evaluate_reasoning_with_blob`, CEVI bridge runtime | Explicitly **not** the user-contract path; structured `raw_answers` only |
| Legal ontology enrichment | `CEVI_LEGAL_VALIDATION_*` (stub) | Stub theater at publish; not a real service |
| LLM bridge induction at publish | `CEVI_LLM_BRIDGE_*` | Experimental OpenAI bridge proposals |
| Lexicon editor + CEVI metadata settings UI | `SHOW_QNR_EDITOR_LEXICON_TAB`, `SHOW_QNR_EDITOR_METADATA_SETTINGS` | Dogfood editor for CEVI; not GTM |
| Workflow scout | `MCP_WORKFLOW_SCOUT_ENABLED`, `smeme_authoring_candidate_guidance`, `smeme-workflow-scout` skill | Proactive top-of-funnel; intrusive; deliberate authoring tools supersede the *build* funnel |
| REST evaluate | `REASONING_REST_EVALUATE_ENABLED`, `smeme/api/reasoning_evaluate.py` | Extra HTTP attack surface; MCP is the product evaluate path |
| Z3 trace env knobs | `SMEME_REASONING_Z3_TRACE*` | Lab observability, not product |
| Wizard telemetry **report** UI | `/telemetry/report` | Funnel ops page; **`wizard.complete` event writes kept** for quota |

**Still in DB / models (dead columns — no drop migration yet):** e.g. `memos`, `qnr_lexicon_drafts`, `cevi_legal*`, creator-profile fields, `is_archived` (still filtered in places). Cascade deletes may still reference `Memo`. Cleanup migrations are optional follow-up.

**CEVI package retained slices:** `fact_projection`, `induction` / corpus / `atom_catalog` — required for publish + structured evaluate. Removed: bridge_runtime, legal_validation, llm_bridge_*, lexicon_draft, editor_lexicon_availability.

---

#### Alternatives considered

1. **Flag-gate forever (soft disable)** — Rejected for lab surfaces: flags flipped in prod for dogfood; Core operators could re-enable attack surface. Delete lab code.
2. **Strip SaaS billing from the product tree now** — Rejected while SaaS still needs Stripe in the same working tree; move SAAS-ONLY into the private overlay at extract time ([D023](#d023-public-core-repo--private-saas-overlay-distribution)), not delete billing from SaaS.
3. **Keep scout “off by default”** — Rejected: deliberate MCP authoring + `smeme-workflow-author` cover build-when-asked; proactive scout was product-noise.
4. **Embed OAuth AS in SMEme for Core** — Rejected: MRS-only; BYO AS (Clerk profile → generic OIDC). Aligns with enterprise-managed auth extension (IdP + MAS external).
5. **Single “full” image for SaaS and Core** — Rejected as long-term posture: Stripe routes with empty keys are still a fraud/confusion surface ([packaging rule](#decision) above).
6. **Public Docker binary only; entire smeme.ai application closed** — Rejected: weak trust for self-host buyers; fights contributor gravity. Prefer n8n-shaped **public Core product** + commercial hosted layer ([D023](#d023-public-core-repo--private-saas-overlay-distribution)).
7. **Two divergent product codebases** (full private SaaS fork of the app) — Rejected: duplicates CI and contributor tax. SaaS is a thin overlay on Core, not a second product tree.

#### Rationale

- **Product clarity:** Structured evaluate + Deploy/Listed + deliberate authoring is the story; blob/legal ontology/scout/gallery were diluting it.
- **Security:** Fewer public forms, webhooks, and experimental MCP tools in every deploy.
- **Distro readiness:** A written keep/SaaS-only inventory is the prerequisite for public Core vs private overlay without rediscovering classification in every sprint ([D023](#d023-public-core-repo--private-saas-overlay-distribution)).
- **Activation without intrusion:** Chat/wizard authoring when the user opts in; no passive scout skill interrupting sessions.

#### Consequences

- ✅ Product tree after 2026-07-18 matches the REMOVED table; assistants must not suggest restoring those surfaces casually.
- ✅ SaaS continues to run Stripe, landing, waitlist, Plausible, legal (via overlay once extracted).
- ⚠️ Public extract remains: appliance proof, counsel on legal pack, GHCR `smeme` + `smeme-cloud` pin — see [D023](#d023-public-core-repo--private-saas-overlay-distribution) and [sprint-core-public-release](planning/sprint-core-public-release.md). Admin quota modes and generic OIDC MRS may follow extract.
- ⚠️ Planning/runbook docs may still mention blob/scout/REST evaluate — treat as historical until scrubbed; **this ADR + ROADMAP gated table win** for inventory; **D023 wins** for distribution.
- ⚠️ `is_public` / creator fields / lexicon tables may linger in Postgres; do not re-expose UI.
- ⚠️ Business sharing / marketplace plans are **not** authorization to put gallery back without a new decision.

#### Implementation checklist (when building Core distro)

1. Public Core / `smeme` image omits: billing payment routers, landing marketing (waitlist **out** of Core), Plausible, Arista legal, gallery (already gone), upgrade CTAs — SAAS-ONLY stays in private `smeme-cloud` overlay ([D023](#d023-public-core-repo--private-saas-overlay-distribution)).
2. Root `/` → auth or dashboard, not marketing hero.
3. `BASE_URL`-relative MCP connect docs only.
4. Quota: **enforcement off** / metering on in Core; hosted Free/Pro registered by SaaS overlay only; stretch admin org defaults / `per_user` — no Stripe writers in Core.
5. Auth: generic issuer + JWKS + subject mapping; Clerk as documented Core profile (optional module OK for self-host).
6. Optional: `SMEME_AI_GENERATION_ENABLED`; OpenAI required only when on.
7. Artifact / tree separation so Core cannot “flip on Stripe” by setting env alone — public Core must boot and document without SaaS packages ([D023](#d023-public-core-repo--private-saas-overlay-distribution)). SUL 1.0 + counsel review gate first public release.

---

### D023: Public Core Repo + Private SaaS Overlay (Distribution)

**Status:** Accepted (2026-07-20); **naming + license locked 2026-07-20**.

**Related:** [D022](#d022-product-surface-inventory--keep--saas-only--removed-core-distro-prep) (surface inventory), [D016](#d016-authentication--permissions--final-plan-cowork-launch-remote-mcp-sso), [D021](#d021-blind-protocol-retained-for-agent-reliability-not-license-dependent), [ROADMAP](ROADMAP.md), [messaging](product/messaging.md), [LICENSING.md](../LICENSING.md).

#### Context

Self-host buyers and contributors need a **visible product codebase** and a clear appliance image. Hosting `smeme.ai` needs Stripe, marketing, waitlist, legal, analytics, and ops that must not ship in that artifact. n8n’s fair-code pattern — public self-hostable product, commercial hosted service, optional paid proprietary later — matches SMEme better than “closed SaaS app + public Docker binary only” or “two full product forks.” Adjustment vs n8n: **no `.ee` files in the public tree**; commercial code stays in a private overlay.

#### Decision

1. **Primary boundary:** public **product** vs commercial **hosted / overlay** — not “open source vs entirely secret SaaS application.” Marketing language: **source-available** or **fair-code**, never “open source.”

2. **License:** [SMEme Sustainable Use License 1.0](../LICENSE.md) for public SMEme (text adapted from n8n’s Sustainable Use License 1.0; n8n’s docs encourage other projects to use that license; **renamed** here; a professional-services provision was added to the Limitations to match n8n’s own FAQ). Licensor: **Arista Labs, LLC**. Public names locked: **`AristaLabs/smeme`**, **`ghcr.io/AristaLabs/smeme`**. Plain-language FAQ: [LICENSING.md](../LICENSING.md). Contributions: [CONTRIBUTOR_LICENSE_AGREEMENT.md](../CONTRIBUTOR_LICENSE_AGREEMENT.md). Outside counsel waived for first public release (budget); residual risk accepted — do not claim attorney review.

3. **Public repo + image** (product owns the name — not an “incomplete core SDK”):
   - Repo: `AristaLabs/smeme`
   - Image: `ghcr.io/AristaLabs/smeme:<tag>` (record digest on production pins)
   - Contents: KEEP + FLAG-GATED per [D022](#d022-product-surface-inventory--keep--saas-only--removed-core-distro-prep), skills under `plugin/cowork-skills/`, tests for those paths, compose, `Dockerfile.core`. Contributors fork and open PRs here only.

4. **Private overlay:** `AristaLabs/smeme-cloud` (prefer over `smeme-enterprise` until a licensed self-host SKU exists). SAAS-ONLY packages/routes (Stripe, landing/SEO, Business waitlist, Plausible, Arista legal, SaaS COGS knobs, Render deploy secrets). Commercial image: `ghcr.io/AristaLabs/smeme-cloud` built as:

   ```dockerfile
   ARG SMEME_IMAGE=ghcr.io/AristaLabs/smeme
   ARG SMEME_VERSION=1.0.0
   FROM ${SMEME_IMAGE}:${SMEME_VERSION}
   ```

   Pin **tag + digest** in production. **Do not** use a pip/git Core package boundary unless SMEme is genuinely published as a library — the container is the appliance boundary.

5. **No public `.ee` split:** Do not mix enterprise-only files into the public repo under filename conventions (n8n `LICENSE_EE.md` pattern deferred). Commercial code lives only in `smeme-cloud`. License-key infrastructure waits until there is a real self-hosted paid tier.

6. **Composition roots:** `create_core_app()` in public product; SaaS `create_saas_app()` imports the Core factory and mounts SAAS-ONLY routers/middleware. Core entrypoint must not import SAAS-ONLY modules.

7. **Auth:** Product remains an MCP **MRS** with generic OIDC/JWT verify as the target. **Clerk** is the first documented profile *and* the SaaS default. Basic safe authentication if the container is network-accessible is a **public-release gate**; full generic OIDC may land post-extract. Clerk-only hard-delete / Account Portal assumptions that are SaaS-specific may stay in the overlay when they cannot be generalized.

8. **EE / community extensions:** Not in v1. When Business sharing / Connect / marketplace ship, classify again (private overlay vs separate packages). Community skills/guidance packs as separate public artifacts are later.

9. **Never public:** secrets, prod runbooks with credentials, sensitive COGS maps, SendGrid waitlist ops config, Arista legal copy if redistribution is undesired (legal pages stay overlay).

#### Alternatives considered

1. **Entire smeme.ai application closed; only a Docker binary public** — Rejected: weak audit story; no fork/PR gravity.
2. **Two divergent full app trees** — Rejected: double CI, merge pain, contributor confusion.
3. **Single public monorepo including Stripe/landing** — Rejected long-term: SAAS-ONLY attack surface and Arista contracts in every self-host clone; use overlay instead.
4. **Embed OAuth AS in Core** — Rejected ([D022](#d022-product-surface-inventory--keep--saas-only--removed-core-distro-prep) / Future §6).
5. **Public image named `smeme-core`** — Rejected: sounds like an SDK / incomplete dependency; public appliance owns the product name `smeme`.
6. **pip/git pin of Core as the commercial boundary** — Rejected for now: container `FROM` pin is the cleanest appliance boundary.
7. **n8n-style `.ee` files in the public tree** — Rejected for v1: complicates CI, extract, and contributor expectations; keep commercial code private.

#### Rationale

- Trust and ecosystem around a **readable product tree**; monetize convenience, multi-tenant ops, and (later) EE.
- Inventory ([D022](#d022-product-surface-inventory--keep--saas-only--removed-core-distro-prep)) stays stable while repo topology changes.
- Same product commit builds the public image; `smeme-cloud` pins that image — contributors never need the private overlay.
- The SMEme SUL 1.0 permits internal commercial use and paid consulting/services while restricting paid hosting / white-label competition (see [LICENSING.md](../LICENSING.md)).

#### Consequences

- ✅ Clear contributor path: fork public `smeme` → PR → CI → tag → GHCR `smeme`; `smeme-cloud` bumps pin + digest.
- ✅ `smeme` image must boot without Stripe/landing/waitlist/legal/Plausible packages; generation off by default.
- ⚠️ Extract phases: composition split in one tree → scrub history → public repo → overlay `FROM` pin.
- ⚠️ Counsel review of LICENSING FAQ, CLA, and embedding language before first public push.
- ⚠️ Until extract completes, this private monorepo may still contain SAAS-ONLY code beside Core — assistants follow D022 classification and Core entrypoint import guards.

#### Implementation checklist

1. ~~`create_core_app` / SaaS mounts; Core CI import graph fails on SAAS-ONLY imports from Core entrypoint.~~ (landed in-tree: `smeme/app_factory.py`, `smeme/saas_overlay.py`, `scripts/check_core_no_saas_imports.py`)
2. ~~`SMEME_AI_GENERATION_ENABLED`; `OPENAI_API_KEY` required only when generation is on.~~
3. ~~License + naming locked: SUL 1.0, `<org>/smeme`, `ghcr.io/<org>/smeme`, overlay `smeme-cloud`; legal pack scaffolds (`LICENSE.md`, `LICENSING.md`, CLA, `THIRD_PARTY_NOTICES.md`).~~
4. Prove Core appliance (compose / `Dockerfile.core`); counsel pass; public extract + GHCR tags/digests; `smeme-cloud` `FROM` pin — see [extract checklist](planning/core-public-extract-checklist.md) and [sprint](planning/sprint-core-public-release.md).
5. Generic OIDC MRS + operator-managed quota modes without Stripe (may slip; Clerk-first documented). Core enforcement-off default is locked; hosted Free/Pro stay overlay-registered.

---

## Rejected Approaches

### R001: PydanticAI for LLM Orchestration

**Tried**: Using PydanticAI as wrapper for OpenAI calls.

**Rejected Because**: Added abstraction without significant benefit. OpenAI SDK's native `response_format` with Pydantic is simpler.

---

### R002: LangChain for LLM Calls

**Tried**: LangChain for LLM abstraction.

**Rejected Because**: Too many abstractions, verbose, hard to debug. Direct OpenAI SDK is cleaner for our use case.

---

### R003: Single Unified QNR Workflow

**Tried**: One workflow handling view, edit, and generate.

**Rejected Because**: Cache invalidation nightmares, unclear state boundaries, hard to test.

---

### R004: LLM Agent for Graph Fixes

**Tried**: Tool-calling agent to fix validation errors.

**Rejected Because**:
- Hallucinated node IDs
- Unpredictable sequencing
- Created new errors
- Expensive and slow
- Hard to debug

---

### R005: Direct JSON Generation for Complex Questionnaires

**Tried**: Asking LLM to generate questionnaire directly as JSON.

**Rejected Because**:
- Poor reasoning quality (constrained by format)
- Missing edges
- Incorrect conditions
- No human review before commitment

---

## Future Decision Areas

Areas where decisions may need revisiting:

1. **Multi-provider LLM support** - Currently OpenAI-only
2. **Real-time collaboration** - May need WebSockets
3. **Mobile app** - May need different architecture
4. **Horizontal scaling** - May need to revisit state management
5. **Paid features / Core entitlements** - SaaS Stripe remains in the private `smeme-cloud` overlay; public packaging under SUL 1.0 and entitlement gating per [D022](#d022-product-surface-inventory--keep--saas-only--removed-core-distro-prep) / [D023](#d023-public-core-repo--private-saas-overlay-distribution)
6. **OAuth authorization server (external)** - SMEme stays MRS ([D022](#d022-product-surface-inventory--keep--saas-only--removed-core-distro-prep), [D023](#d023-public-core-repo--private-saas-overlay-distribution)); BYO AS — Clerk profile first, then generic OIDC. DCR / static Client ID / CIMD / enterprise-managed authorization are MAS/IdP choices ([D016](#d016-authentication--permissions--final-plan-cowork-launch-remote-mcp-sso), [CIMD research](planning/cimd-mcp-client-registration-research-2026-07.md)). **Do not embed AS in SMEme.**
7. **EE / community extensions** - Business sharing, Connect, marketplace, and community skills packs: classify when built (private overlay vs in-repo EE license vs separate public packages) per [D023](#d023-public-core-repo--private-saas-overlay-distribution).
