# Getting Started

Local development setup for SMEme Platform v2.

## Prerequisites

- **Python 3.13+**
- **Docker & Docker Compose**
- **[uv](https://github.com/astral-sh/uv)** (Python package manager)
- **Git**

---

## 1. Install dependencies

```bash
# This private monorepo defaults to smeme.main (the hosted overlay).
uv sync --extra dev --extra saas
```

## 2. Start databases

```bash
docker-compose up -d
```

Two containers will start:
- `smeme_postgres_dev` (port 5432)
- `smeme_postgres_test` (port 5433)

## 3. Configure environment

Create a `.env` file in the project root:

```bash
# Application
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=INFO

# Database
DATABASE_URL=postgresql+asyncpg://smeme:smeme_dev_password@localhost:5432/smeme_dev
TEST_DATABASE_URL=postgresql+asyncpg://smeme:smeme_test_password@localhost:5433/smeme_test

# Base URL
BASE_URL=http://localhost:8000

# OpenAI (required for QNR generation)
OPENAI_API_KEY=your-openai-api-key-here

# Tavily (optional, for agentic generation web search)
TAVILY_API_KEY=your-tavily-api-key-here

# Clerk (required for auth)
CLERK_SECRET_KEY=sk_test_...
CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SIGN_IN_URL=https://accounts.your-clerk-domain.com/sign-in
CLERK_SIGN_UP_URL=https://accounts.your-clerk-domain.com/sign-up
CLERK_SIGN_OUT_URL=https://accounts.your-clerk-domain.com/sign-out
CLERK_WEBHOOK_SECRET=whsec_...

# Stripe (optional, for Premium subscription)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PREMIUM_PRICE_ID=price_...
```

> **Note:** Without Clerk keys, sign-in/sign-up will not work. For local testing without Clerk, you can bypass auth using test utilities — see `tests/` for patterns.

## 4. Run database migrations

```bash
uv run alembic upgrade head
```

## 5. Start the development server

```bash
make dev
# or: uv run uvicorn smeme.main:app --reload --port 8000
```

## 6. Verify

- **App**: http://localhost:8000
- **API docs (Swagger)**: http://localhost:8000/api/docs
- **API docs (ReDoc)**: http://localhost:8000/api/redoc
- **Health check**: http://localhost:8000/api/v1/health

```bash
curl http://localhost:8000/api/v1/health
```

---

## Development workflow

```bash
make dev          # Start development server
make test         # Run tests
make test-cov     # Tests with coverage
make lint         # Ruff check
make format       # Ruff format
make type-check   # mypy
make migrate      # Create new migration (interactive)
make upgrade      # Apply migrations
make downgrade    # Rollback last migration
make db-up        # Start PostgreSQL containers
make db-down      # Stop PostgreSQL containers
```

---

## Troubleshooting

### Database connection errors

```bash
docker ps                    # check containers are running
docker-compose down
docker-compose up -d
sleep 5
uv run alembic upgrade head
```

### Port 8000 already in use

```bash
uv run uvicorn smeme.main:app --reload --port 8001
```

### Multiple Alembic heads

```bash
uv run alembic heads
uv run alembic merge heads -m "merge"
```

### Import errors

```bash
uv sync --extra dev --extra saas   # ensure private-overlay deps are installed
```

---

## Next steps

- [Architecture overview](../ARCHITECTURE.md)
- [LangGraph integration guide](langgraph-integration.md)
- [MCP / OAuth guide](dr3-mcp-oauth-authoritative-sources.md)
- [Deployment guide](deployment.md)
- Dashboard: http://localhost:8000/qnr/dashboard
