# Self-host quickstart (SMEme Core)

Run the **Core** product (editor, Deploy/Listed, reasoning, MCP) with Docker.
Core excludes billing, marketing pages, analytics, and vendor-specific legal
pages.

## Requirements

- Docker + Docker Compose
- Postgres 16 (included in `docker-compose.core.yml`)
- Optional: Clerk (or later generic OIDC) for browser login and MCP OAuth
- Optional: OpenAI + Tavily when AI generation is enabled

## Quick start

```bash
cp .env.core.example .env.core
# edit secrets in .env.core
docker compose --env-file .env.core -f docker-compose.core.yml up --build
```

- App: http://localhost:8000 (redirects to `/decision-trees/dashboard`)
- Health: http://localhost:8000/api/v1/health

Default Core image settings:

- `SMEME_AI_GENERATION_ENABLED=false` — no `OPENAI_API_KEY` / `TAVILY_API_KEY` required to boot
- `MCP_ENABLED=false` — set `true` and configure Clerk/OAuth when you want remote MCP

**Network exposure:** do not publish port 8000 beyond localhost until Clerk (or a future OIDC profile) is configured and secrets are non-default. Product routes require auth (`/decision-trees/dashboard` → 401 without a session); `/api/docs` and `/api/v1/health` remain reachable. Compose ships placeholder secrets only as a local convenience — replace them for any shared host.

Full operator knob list: [`.env.core.example`](../../.env.core.example).

## Sovereignty / third-party egress

Self-host keeps **Deploy / evaluate / MCP report** on your infrastructure by default. Some optional flags send **decision-tree content, research text, or prompts** to third parties. Turn them on only if your policy allows that egress.

| Risk | Flag / dependency | What leaves your boundary | Default (Core image) |
|------|-------------------|---------------------------|----------------------|
| **High — generation wizard** | `SMEME_AI_GENERATION_ENABLED=true` + `OPENAI_API_KEY` | Brief, research corpus, design/build prompts, draft graph text → **OpenAI** | **Off** |
| **High — web research** | `TAVILY_API_KEY` (only while generation is on) | Search queries / URLs derived from the brief → **Tavily** | Unset (no calls) |
| **High if re-enabled** | LangSmith (`LANGCHAIN_*`) | Full LangGraph run I/O (prompts, state) → **LangSmith** | **Hard-disabled** at startup — keys have no effect |
| **Medium — identity** | `CLERK_*` | Auth sessions, user profile sync, OAuth for MCP → **Clerk** (not your trees, but PII/login) | Operator-chosen |
| **Low / none for trees** | `MCP_ENABLED` + evaluate tools | Answers + reports stay on **your** server; agents do not receive branch topology | Off until you enable |
| **Low for trees** | `MCP_AUTHORING_GRAPH_TOOLS_ENABLED` | Server-owned design guidance / validate / create draft — **no OpenAI** in the current MCP authoring path | On when `MCP_ENABLED` (set `false` to opt out) |
| **None (trees)** | Manual editor + Deploy + Z3 evaluate | Compiles and reasons locally (Postgres + Z3 in-process) | Always available |

**Sovereignty-preserving Core profile** (no decision-tree content to LLM/search vendors):

```bash
SMEME_AI_GENERATION_ENABLED=false
# leave OPENAI_API_KEY and TAVILY_API_KEY unset
MCP_ENABLED=true   # optional; still on your host
# configure Clerk (or future OIDC) only for login / MCP OAuth
```

Authors build trees in the **editor** (or via the web wizard / MCP chat authoring
path — see [Authoring decision trees](authoring-decision-trees.md)); agents call
MCP evaluate on your instance.

**LangSmith note:** the old `tracing.py` helpers were removed. Getting LangSmith working again is not “drop tracing.py back in” alone — you must stop (or gate) `disable_langsmith_tracing()`, set `LANGCHAIN_TRACING_V2` + API key, and accept that generation traces export workflow I/O. Optional metadata helpers can be re-added later; they are not the main switch.

## Operator options (Core)

| Area | Env | Notes |
|------|-----|--------|
| **Runtime** | `DEBUG`, `LOG_LEVEL`, `ALLOWED_ORIGINS` | CORS must include your public origin when not localhost |
| **AI generation** | `SMEME_AI_GENERATION_ENABLED` | Mounts wizard + checkpointer; requires `OPENAI_API_KEY` when `true` |
| | `OPENAI_API_KEY` | Required only when generation is on |
| | `TAVILY_API_KEY` | Optional web research for agentic generation; ignored if generation is off |
| | `SHOW_DECISION_TREE_GENERATION_REGION_SELECTOR` | Tavily country control on the brief form (default on) |
| **Auth** | `CLERK_*` | Sign-in/up/out, publishable/secret keys, webhook secret, optional `CLERK_OAUTH_ISSUER` |
| | `CLERK_OAUTH_DYNAMIC_REGISTRATION` | Usually `false` for self-host with a static OAuth client |
| **MCP** | `MCP_ENABLED` | Streamable HTTP MCP + discovery |
| | `MCP_HTTP_PATH` | Default `/api/v1/mcp` |
| | `MCP_AUTHORING_GRAPH_TOOLS_ENABLED` | Chat authoring tools (`smeme_authoring_*`); on when MCP is enabled; set `false` to opt out |
| | `SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS` | Static client allowlist when DCR is off |
| | `SMEME_MCP_OAUTH_ACCESS_TOKEN_AUDIENCE` | Optional `aud` binding |
| | Transport rate limits / invocation telemetry | See `.env.core.example` |
| **Quotas** | Self-host metering | **Enforcement off** by default; MCP/wizard **metering stays on**. Core does not register plan-based caps. |

**LangSmith:** hard-disabled (see [sovereignty](#sovereignty--third-party-egress)). Not an operator toggle today.

Vendor billing, analytics, waitlist, and cost-accounting settings are not part
of Core compose.

Full authoring comparison (wizard vs MCP chat, DTGraph shape, egress): [Authoring decision trees](authoring-decision-trees.md).

## Enable AI generation (with optional Tavily)

```bash
# in .env.core
SMEME_AI_GENERATION_ENABLED=true
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...          # optional; improves agentic research
SHOW_DECISION_TREE_GENERATION_REGION_SELECTOR=true

docker compose --env-file .env.core -f docker-compose.core.yml up --build
```

Or one-shot:

```bash
SMEME_AI_GENERATION_ENABLED=true \
OPENAI_API_KEY=sk-... \
TAVILY_API_KEY=tvly-... \
docker compose -f docker-compose.core.yml up --build
```

## Enable MCP

1. Configure Clerk (or your OIDC AS) per [DR-3 guide](dr3-mcp-oauth-authoritative-sources.md).
2. In `.env.core`: `MCP_ENABLED=true`, set `BASE_URL` to your public HTTPS origin, fill `CLERK_*`.
3. For DCR-off + a static OAuth client: set `SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS` to that client id; keep `CLERK_OAUTH_DYNAMIC_REGISTRATION=false`.
4. Authoring tools (`smeme_authoring_*`) are registered when MCP is enabled. Set `MCP_AUTHORING_GRAPH_TOOLS_ENABLED=false` only if you want to disable them.
5. Restart the `web` service.

**How agents get guidance:** there is no installable zip to download. After OAuth, the
client calls **`smeme_reasoning_guidance_get`** (usually after
`smeme_reasoning_capabilities`) and caches the returned markdown calling
contract. The repo folder [`agent-skills/`](../../agent-skills/README.md) is
the authoring source used to build that content. In-app detail: `/docs/mcp`.

## Build the image alone

```bash
docker build -f Dockerfile.core -t smeme:local .
```

Notices and corresponding-source materials live in the image under `/app/legal/` (see [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md) and [`legal/SOURCE_OFFER.md`](../../legal/SOURCE_OFFER.md)). For a release evidence pack (SBOM + legal bundle):

```bash
scripts/prepare_core_release_evidence.sh smeme:local build/release-evidence
```

## Stuck?

Ask in [GitHub Discussions → Self-host / operators](https://github.com/AristaLabs/smeme/discussions/categories/self-host-operators)
(or **Get started** for MCP connect questions). Include the image tag/digest if you
can; never paste a full `.env` or secrets. Confirmed Core defects →
[Issues](https://github.com/AristaLabs/smeme/issues).

## Contributor checks

```bash
uv run python scripts/check_core_no_saas_imports.py
```

See [CONTRIBUTING.md](../../CONTRIBUTING.md).
