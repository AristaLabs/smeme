# SMEme

**Source-available** decision-workflow platform (fair-code). SMEs **author** interactive **workflows** → users or agents supply structured answers → server-side deterministic reasoning → structured **report**.

- **Self-host Core:** [`docs/guides/self-host-quickstart.md`](docs/guides/self-host-quickstart.md) · image `ghcr.io/AristaLabs/smeme`
- **License:** [SMEme Sustainable Use License 1.0](LICENSE.md) — see [LICENSING.md](LICENSING.md). Not open source.
- **Hosted product:** [smeme.ai](https://smeme.ai) is the commercial layer (`smeme-cloud`) on top of the same Core image.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Web Framework | FastAPI 0.115+ |
| Templates | Jinja2 + HTMX (no JS frameworks) |
| Database | PostgreSQL 16+ (JSONB) |
| ORM | SQLModel (SQLAlchemy 2.0 + Pydantic V2) |
| AI Workflows | LangGraph (optional generation) |
| LLM | OpenAI SDK (optional; off by default in Core image) |
| Auth | Clerk profile (first OIDC); FastAPI-Users cookie/JWT for session |
| MCP | Streamable HTTP MCP + RFC 9728 OAuth discovery |
| Package Manager | uv |

---

## Quick Start (Core / self-host)

```bash
cp .env.core.example .env.core
# edit secrets
docker compose --env-file .env.core -f docker-compose.core.yml up --build
```

- App: http://localhost:8000 → `/qnr/dashboard`
- Health: http://localhost:8000/api/v1/health
- Full guide: [self-host-quickstart.md](docs/guides/self-host-quickstart.md)

### Local Python (Core)

```bash
uv sync --extra dev
# Core entrypoint (no Stripe / landing overlay):
uv run uvicorn smeme.core_entrypoint:app --reload
```

### Private monorepo / hosted SaaS overlay

This checkout may also contain the proprietary `smeme-cloud` overlay (`smeme.main:app`, Stripe, marketing). That surface is **not** part of the public Core distribution:

```bash
uv sync --extra saas
docker compose up -d
uv run uvicorn smeme.main:app --reload
```

---

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

Hosted SaaS overlay additionally uses Stripe / SendGrid — those packages and routes are omitted from Core.

---

## Product vocabulary

| Say | Avoid (legacy) |
|-----|----------------|
| **workflow** | questionnaire, QNR |
| **Deploy** / **Redeploy** | publish (when meaning reasoning artifact) |
| **Listed** / **Hidden** | MCP discoverability toggle |
| **report** | memo (downstream agent work) |

---

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Decisions (ADRs)](docs/DECISIONS.md)
- [User contract](docs/product/user-contract.md)
- [Messaging](docs/product/messaging.md)
- [Self-host quickstart](docs/guides/self-host-quickstart.md)
- [Contributing](CONTRIBUTING.md) · [CLA](CONTRIBUTOR_LICENSE_AGREEMENT.md) · [Security](SECURITY.md)

## License

SMEme Sustainable Use License 1.0 — see [LICENSE.md](LICENSE.md) and [LICENSING.md](LICENSING.md).
