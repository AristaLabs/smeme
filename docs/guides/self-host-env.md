# Self-host environment reference (Core)

Task-grouped knobs for the **public Core appliance** (`ghcr.io/aristalabs/smeme`).
Compose forwards these into the `web` service via `.env.core`.

**Not Core:** `STRIPE_*`, `PLAUSIBLE_*`, SendGrid waitlist mail, `MCP_COST_*`,
`RENDER_*`. Those belong to the hosted SaaS overlay only.

Bootstrap: [`scripts/init_core_env.sh`](../../scripts/init_core_env.sh) →
[`.env.core.example`](../../.env.core.example). Profiles below are copy-paste
snippets to merge into `.env.core` after init.

Restart policy: change any of these → recreate `web` (`docker compose … up -d
--force-recreate web`). DB password changes also require recreating `db` (data
volume keeps the old role password unless you `ALTER USER`).

---

## Profiles

### Health only {#profile-health}

<!-- profile-health -->

Minimal boot: secrets + image. No Clerk, no MCP, no wizard.

```bash
# After ./scripts/init_core_env.sh — defaults already match this profile.
SMEME_CORE_IMAGE=ghcr.io/aristalabs/smeme:v0.9.13
SMEME_AI_GENERATION_ENABLED=false
MCP_ENABLED=false
BASE_URL=http://127.0.0.1:8000
```

### MCP reasoning {#profile-mcp-reasoning}

<!-- profile-mcp-reasoning -->

Authenticate agents, list Listed trees, evaluate → report. No draft authoring
tools; no web wizard.

```bash
MCP_ENABLED=true
MCP_AUTHORING_GRAPH_TOOLS_ENABLED=false
SMEME_AI_GENERATION_ENABLED=false
BASE_URL=https://app.example.com
# + Clerk keys (see self-host-pilot.md)
# CLERK_OAUTH_DYNAMIC_REGISTRATION=false
# SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS=<static-clerk-oauth-app-id>
```

### MCP + authoring {#profile-mcp-authoring}

<!-- profile-mcp-authoring -->

Reasoning plus chat draft tools (`smeme_authoring_*`). Uses the **client** model;
no server `OPENAI_API_KEY`. Design guidance **2.5.0** (Quick encode + Research &
critique) ships in Core ≥ `v0.9.8`. Deploy stays human-in-editor.

```bash
MCP_ENABLED=true
MCP_AUTHORING_GRAPH_TOOLS_ENABLED=true
SMEME_AI_GENERATION_ENABLED=false
BASE_URL=https://app.example.com
# + Clerk as above
```

### Web wizard {#profile-wizard}

<!-- profile-wizard -->

Browser AI generation only. Independent of MCP authoring.

```bash
SMEME_AI_GENERATION_ENABLED=true
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...          # optional; full research
SHOW_DECISION_TREE_GENERATION_REGION_SELECTOR=true
MCP_ENABLED=false
```

**Egress:** brief / research / draft graph text leave your boundary → OpenAI
(+ Tavily queries when set).

### Full pilot {#profile-full-pilot}

<!-- profile-full-pilot -->

HTTPS origin + Clerk + MCP (reasoning + authoring) + optional wizard.

```bash
SMEME_CORE_IMAGE=ghcr.io/aristalabs/smeme:v0.9.13
BASE_URL=https://app.example.com
ALLOWED_ORIGINS=["https://app.example.com"]
SMEME_PUBLIC_HOST=app.example.com
MCP_ENABLED=true
MCP_AUTHORING_GRAPH_TOOLS_ENABLED=true
MCP_FIRST_PROVISIONING_ENABLED=true   # if you want MCP-first User rows
SMEME_LEGAL_TERMS_URL=https://www.smeme.ai/legal/terms
SMEME_LEGAL_PRIVACY_URL=https://www.smeme.ai/legal/privacy
SMEME_LEGAL_TERMS_VERSION=2026-07-20
SMEME_LEGAL_PRIVACY_VERSION=2026-07-20
# Clerk + static OAuth client allowlist
# Optional wizard:
# SMEME_AI_GENERATION_ENABLED=true
# OPENAI_API_KEY=...
# TAVILY_API_KEY=...
```

---

## Variable catalog

Legend: **R** = required to start compose (empty fails closed) · **S** = secret ·
**restart** = recreate `web` · **egress** = third-party network.

### Image & runtime

| Variable | Default | R/S | Profiles | Notes |
|----------|---------|-----|----------|--------|
| `SMEME_CORE_IMAGE` | (none) | R | all | `ghcr.io/aristalabs/smeme:<tag>` or `@sha256:…`. Prefer digest in production. |
| `ENVIRONMENT` | `development` | | all | Prod overlay forces `production`. |
| `DEBUG` | `false` | | | Keep false outside local debugging. |
| `LOG_LEVEL` | `INFO` | | | |
| `SQLALCHEMY_LOG_LEVEL` | `WARNING` | | | SQL text noise control. |
| `BASE_URL` | `http://127.0.0.1:8000` | | all | Public origin; MCP resource URL base. Must be `https://…` for real MCP clients. |
| `ALLOWED_ORIGINS` | loopback JSON | | | CORS; include `BASE_URL` origin. Prod overlay requires explicit value. |
| `SMEME_PUBLIC_HOST` | — | | full pilot / HTTPS | Hostname only for Caddy (`docker-compose.core.prod.yml`). |

### Secrets & database

| Variable | Default | R/S | Notes |
|----------|---------|-----|--------|
| `SECRET_KEY` | (none) | R/S | Session / app crypto. Use `init_core_env.sh`. |
| `JWT_SECRET_KEY` | (none) | R/S | |
| `POSTGRES_PASSWORD` | (none) | R/S | Injected into `DATABASE_URL` for `web` and into `db`. |
| `DATABASE_URL` | (compose-built) | | Do not set by hand in compose path; Compose builds `postgresql+asyncpg://smeme:…@db:5432/smeme`. |

### AI generation wizard (web)

Independent of `MCP_AUTHORING_GRAPH_TOOLS_ENABLED`.

| Variable | Default | R/S | egress | Notes |
|----------|---------|-----|--------|--------|
| `SMEME_AI_GENERATION_ENABLED` | `false` | | OpenAI when true | Mounts wizard. |
| `OPENAI_API_KEY` | unset | S | OpenAI | Required when generation is on. |
| `TAVILY_API_KEY` | unset | S | Tavily | Optional research while generation is on. |
| `SHOW_DECISION_TREE_GENERATION_REGION_SELECTOR` | `true` | | | Brief-form region control. |

### Clerk (turnkey AS)

Do not claim generic OIDC. Enterprise AS = your problem.

| Variable | Default | R/S | egress | Notes |
|----------|---------|-----|--------|--------|
| `CLERK_SECRET_KEY` | unset | S | Clerk | Required with sign-in URL for browser auth. |
| `CLERK_PUBLISHABLE_KEY` | unset | | Clerk | Browser sync / issuer fallback. |
| `CLERK_SIGN_IN_URL` | unset | | | |
| `CLERK_SIGN_UP_URL` | unset | | | |
| `CLERK_SIGN_OUT_URL` | unset | | | Dedicated sign-out URL (not the sign-in URL). |
| `CLERK_WEBHOOK_SECRET` | unset | S | | `whsec_…` for `/auth/clerk/webhook`. |
| `CLERK_OAUTH_ISSUER` | unset | | | Override issuer (custom domain). |
| `CLERK_OAUTH_DYNAMIC_REGISTRATION` | `false` | | | **Static vs DCR:** `false` + allowlist for Cowork-style static client; `true` only if Clerk DCR is on (some clients require it). |

### MCP

| Variable | Default | Notes |
|----------|---------|--------|
| `MCP_ENABLED` | `false` | Streamable HTTP + OAuth discovery. |
| `MCP_HTTP_PATH` | `/api/v1/mcp` | Resource path suffix. |
| `MCP_AUTHORING_GRAPH_TOOLS_ENABLED` | `true` | Chat draft tools; **no** server OpenAI. Set `false` for reasoning-only. |
| `MCP_INQUIRE_TOOLS_ENABLED` | `false` | Mounts Inquire **orchestrator** MCP at `{MCP_HTTP_PATH}/orchestrator` with explicit `smeme_inquire_*` (+ inquire guidance). Default off. Chat guided gather (`evaluate` / `evaluate_continue`) is always available when MCP is on (requires Phase 6 migration). See [inquire-mcp-contract](inquire-mcp-contract.md). |
| `SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS` | empty | Comma-separated Clerk OAuth app IDs when DCR is off. Empty = no client_id binding. |
| `SMEME_MCP_OAUTH_ACCESS_TOKEN_AUDIENCE` | unset | Optional `aud` bind. |
| `SMEME_MCP_TRANSPORT_RATE_LIMIT_PER_IP_PER_MINUTE` | `120` | `0` disables IP dimension. |
| `SMEME_MCP_TRANSPORT_RATE_LIMIT_PER_SUB_PER_MINUTE` | `240` | |
| `MCP_INVOCATION_TELEMETRY_ENABLED` | `true` | |
| `MCP_INVOCATION_TELEMETRY_PERSIST` | `true` | |

### First-user / legal (web + MCP-first)

| Variable | Default | Notes |
|----------|---------|--------|
| `MCP_FIRST_PROVISIONING_ENABLED` | `false` | MCP Bearer may create local `User` after Clerk + legal gates. |
| `SMEME_MCP_FIRST_PROVISION_RATE_LIMIT_PER_IP_PER_MINUTE` | `10` | |
| `SMEME_MCP_FIRST_PROVISION_RATE_LIMIT_PER_SUB_PER_MINUTE` | `5` | |
| `SMEME_LEGAL_TERMS_URL` | unset | Required (all four) when MCP-first provision is on. |
| `SMEME_LEGAL_PRIVACY_URL` | unset | |
| `SMEME_LEGAL_TERMS_VERSION` | unset | Operator label, e.g. `2026-07-20`. |
| `SMEME_LEGAL_PRIVACY_VERSION` | unset | |

### Web-first vs MCP-first

- **Web-first:** users sign in via Clerk in the browser; webhook / session creates the local `User`.
- **MCP-first:** enable `MCP_FIRST_PROVISIONING_ENABLED` and complete legal URL/version constants so a valid MCP Bearer can provision without a prior browser session.

### Capability matrix

| Capability | Flags |
|------------|--------|
| Health / editor (no login product) | secrets only |
| Browser login | `CLERK_*` |
| MCP evaluate / guidance | `MCP_ENABLED` + Clerk OAuth |
| MCP draft authoring | + `MCP_AUTHORING_GRAPH_TOOLS_ENABLED=true` |
| Web wizard | `SMEME_AI_GENERATION_ENABLED` + `OPENAI_API_KEY` |
| Full research in wizard | + `TAVILY_API_KEY` |

---

## Drift check

```bash
uv run python scripts/check_core_operator_env_drift.py
```

CI runs the same gate. When you add a compose-forwarded key, update
`.env.core.example`, this guide, and (if applicable) Settings `alias=`.

See also: [self-host-quickstart.md](self-host-quickstart.md),
[self-host-pilot.md](self-host-pilot.md).
