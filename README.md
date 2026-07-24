# SMEme Core

SMEme Core is a source-available application for authoring inspectable
**decision-trees** and running them through a server-side **logical analysis
engine**.

Experts create decision-trees, **Deploy** a validated version, and connect MCP
clients that can (1) submit structured `raw_answers` for a **report**, and
(2) ask questions about the deployed tree itself — what-if, reachability, and
related analysis — without treating full evidence collection as the only path.
Agents gather evidence and pose questions; the server keeps the decision logic
and evaluation boundary under operator control.

**Agent bootstrap:** after OAuth, the client asks SMEme for the calling contract
via MCP (`smeme_reasoning_capabilities` → `smeme_reasoning_guidance_get`). There
is no installable zip — guidance is served over the wire. Humans edit
prose under [`agent-skills/`](agent-skills/README.md); CI builds what MCP returns.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Web Framework | FastAPI 0.115+ |
| Templates | Jinja2 + HTMX (no JS frameworks) |
| Database | PostgreSQL 16+ (JSONB) |
| ORM | SQLModel (SQLAlchemy 2.0 + Pydantic V2) |
| Reasoning | Deterministic IR compiler + Z3 theorem prover |
| AI-assisted authoring | LangGraph (optional; generation is off by default in Core) |
| LLM | OpenAI SDK (optional; off by default in Core image) |
| Auth | Clerk session JWT for browser identity; OAuth 2.1 Bearer tokens for remote MCP |
| MCP | Streamable HTTP MCP + RFC 9728 OAuth discovery |
| Package Manager | uv |

---

## Quick Start (Core / self-host)

```bash
cp .env.core.example .env.core
# edit secrets
docker compose --env-file .env.core -f docker-compose.core.yml up --build
```

- App: http://localhost:8000 → `/decision-trees/dashboard`
- Health: http://localhost:8000/api/v1/health
- Full guide: [self-host-quickstart.md](docs/guides/self-host-quickstart.md)

### Local Python (Core)

```bash
uv sync --extra dev
# Core entrypoint (no Stripe / landing overlay):
uv run uvicorn smeme.core_entrypoint:app --reload
```

## Configure environment

Create a `.env` / `.env.core` file (see `.env.core.example`):

```bash
ENVIRONMENT=development
DEBUG=true
DATABASE_URL=postgresql+asyncpg://smeme:smeme_dev_password@localhost:5432/smeme_dev

# Optional for Core boot (generation off by default in the Core image)
# SMEME_AI_GENERATION_ENABLED=true
# OPENAI_API_KEY=...
# TAVILY_API_KEY=...

# Clerk (required for browser login / MCP OAuth when exposing beyond localhost)
CLERK_SECRET_KEY=sk_test_...
CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SIGN_IN_URL=https://accounts.your-clerk-domain.com/sign-in
CLERK_SIGN_UP_URL=https://accounts.your-clerk-domain.com/sign-up
CLERK_SIGN_OUT_URL=https://accounts.your-clerk-domain.com/sign-out
CLERK_WEBHOOK_SECRET=whsec_...

MCP_ENABLED=false
```

## Product vocabulary

| Say | Avoid (legacy) |
|-----|----------------|
| **decision-tree** | questionnaire, retired pre-public names |
| **Deploy** / **Redeploy** | publish (when meaning reasoning artifact) |
| **Listed** / **Hidden** | MCP discoverability toggle |
| **report** | server engine output (not a downstream narrative or memo) |

---

## Documentation

- [Docs index](docs/README.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Authoring decision trees](docs/guides/authoring-decision-trees.md) — web wizard vs MCP chat; shared Deploy → Listed lifecycle
- [Engine promises](docs/guides/engine-promises.md)
- [Self-host quickstart](docs/guides/self-host-quickstart.md)
- [MCP / OAuth operator guide](docs/guides/dr3-mcp-oauth-authoritative-sources.md)
- [Contribution paths](docs/CONTRIBUTION_PATHS.md)
- [Contributing](CONTRIBUTING.md) · [CLA](CONTRIBUTOR_LICENSE_AGREEMENT.md) · [Security](SECURITY.md)

## License

SMEme Sustainable Use License 1.0 — see [LICENSE.md](LICENSE.md) and [LICENSING.md](LICENSING.md).
