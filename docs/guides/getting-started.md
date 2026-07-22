# Getting Started

Local development setup for **SMEme Core** (public product tree).

For the Docker appliance path, prefer the
[self-host quickstart](self-host-quickstart.md).

## Prerequisites

- **Python 3.13+**
- **Docker & Docker Compose**
- **[uv](https://github.com/astral-sh/uv)**
- **Git**

---

## 1. Install dependencies

```bash
uv sync --extra dev
```

## 2. Start databases

```bash
docker compose up -d
```

Typical local containers:

- Postgres for development (port 5432)
- Postgres for tests (port 5433), if your compose file defines it

## 3. Configure environment

Copy `.env.core.example` (or `.env.example` if present) and set at least:

```bash
ENVIRONMENT=development
DEBUG=true
DATABASE_URL=postgresql+asyncpg://smeme:smeme_dev_password@localhost:5432/smeme_dev
BASE_URL=http://localhost:8000

# Clerk (required for browser login / MCP OAuth when exposing beyond localhost)
CLERK_SECRET_KEY=sk_test_...
CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SIGN_IN_URL=https://accounts.your-clerk-domain.com/sign-in
CLERK_SIGN_UP_URL=https://accounts.your-clerk-domain.com/sign-up
CLERK_SIGN_OUT_URL=https://accounts.your-clerk-domain.com/sign-out

# Optional AI generation (off by default in the Core image)
# SMEME_AI_GENERATION_ENABLED=true
# OPENAI_API_KEY=...
# TAVILY_API_KEY=...

MCP_ENABLED=false
```

## 4. Run database migrations

```bash
uv run alembic upgrade head
```

## 5. Start the development server

```bash
uv run uvicorn smeme.core_entrypoint:app --reload --port 8000
```

## 6. Verify

- App: http://localhost:8000
- Health: http://localhost:8000/api/v1/health

```bash
curl http://localhost:8000/api/v1/health
```

---

## Troubleshooting

### Database connection errors

```bash
docker compose down
docker compose up -d
sleep 5
uv run alembic upgrade head
```

### Port 8000 already in use

```bash
uv run uvicorn smeme.core_entrypoint:app --reload --port 8001
```

### Import errors

```bash
uv sync --extra dev
uv run python scripts/check_core_no_saas_imports.py
```

---

## Next steps

- [Architecture](../ARCHITECTURE.md)
- [Self-host quickstart](self-host-quickstart.md)
- [MCP / OAuth guide](dr3-mcp-oauth-authoritative-sources.md)
- [Contribution paths](../CONTRIBUTION_PATHS.md)
- Dashboard: http://localhost:8000/qnr/dashboard
