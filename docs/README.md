# SMEme v2 — Documentation Index

Quick navigation to guides, architecture, and reference docs.

> **Historical sprint docs and superseded plans** live in `docs/historical/` — treat them as archive, not current reference.

---

## Working-memory set (read these first)

| Doc | Purpose |
|-----|---------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Current system map — Clerk, MCP, reasoning IR, feature flags |
| [DECISIONS.md](DECISIONS.md) | ADRs — D016 (auth/MCP/Cowork), D017 (IR-first reasoning) |
| [LESSONS_LEARNED.md](LESSONS_LEARNED.md) | Gotchas, failures, non-obvious patterns |
| [ROADMAP.md](ROADMAP.md) | Engineering priorities and backlog |

---

## Guides

| Guide | Use when |
|-------|---------|
| [Self-host quickstart](guides/self-host-quickstart.md) | Docker `smeme` image / compose (D023) |
| [Public extract checklist](planning/core-public-extract-checklist.md) | Public `smeme` + `smeme-cloud` pin |
| [Sprint: public release](planning/sprint-core-public-release.md) | SUL + extract A→C |
| [Getting Started](guides/getting-started.md) | Local development setup |
| [Installation](guides/installation.md) | Dependency and environment setup |
| [Deployment](guides/deployment.md) | CI/CD, Docker, Render |
| [CI/CD Setup](guides/ci-cd-setup.md) | GitHub Actions dual-stage pipeline |
| [Go-Live Checklist](guides/go-live-checklist.md) | Pre-production env checklist |
| [Render Env Checklist](guides/render-env-checklist.md) | Render environment variables |
| [SendGrid Dependencies](guides/sendgrid-dependencies.md) | What SendGrid is still used for (post-Clerk cutover) |
| [LangGraph Integration](guides/langgraph-integration.md) | Workflow patterns, state design, HTMX integration |
| [MCP / OAuth (DR-3)](guides/dr3-mcp-oauth-authoritative-sources.md) | MCP endpoint, RFC 9728, Clerk Bearer, scopes |
| [Cowork Plugin Runbooks](guides/cowork-reasoning-plugin-runbooks.md) | Operator + end-user steps for the Cowork plugin |
| [Cowork Superuser Admin](guides/cowork-plugin-superuser-admin-guide.md) | IT/security overview for plugin deployment |
| [Data Migration](guides/data-migration.md) | Schema vs data migrations, safe backfill patterns |
| [Wizard Telemetry](guides/wizard-telemetry-drop-off.md) | Drop-off reporting, telemetry route |

---

## Architecture deep-dives (`docs/architecture/`)

Detailed topic files for database schema, workflow breakdowns, and QNR internals. Use after reading `ARCHITECTURE.md` for working context.

---

## Reference

| Doc | Notes |
|-----|-------|
| [Auth routes](reference/api/auth-routes.md) | Clerk-based auth routes (login, register, profile) |
| [QNR routes](reference/api/qnr-routes.md) | Dashboard, editor, agentic generation, sessions |
| [Memo routes](reference/api/memo-routes.md) | Memo generation endpoint |
| [Data schema notes](reference/data-schema.md) | Key models — spot-check against `smeme/core/models.py` for latest |

---

## Product

| Doc | Purpose |
|-----|---------|
| [User contract](product/user-contract.md) | Product narrative for stakeholders and user testing |

## Business & GTM

| Doc | Purpose |
|-----|---------|
| [Distribution & GEO GTM](business/distribution-and-geo-gtm.md) | Current distribution, GEO, monetization phasing |
| [Expert agency narrative & content plan](business/expert-agency-narrative-and-content-plan.md) | Arista Labs mission alignment + blog series |
| [Business marketplace access plan](planning/business-marketplace-access-plan.md) | Future **Business tier** engineering spec (sharing, grants — **not current GTM**; Free + Pro only today) |

---

## Planning

`docs/planning/` contains active specs and sprint plans. `docs/historical/` contains superseded plans, old sprint logs, and migration notes — **not promises**.

---

## Pre-deploy checklist

```bash
uv run ruff check smeme tests
uv run pytest
uv run alembic heads   # must be exactly one head
```

**Last Updated**: 2026-06-09
