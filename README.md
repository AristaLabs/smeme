# SMEme Core

SMEme Core is a source-available application for authoring inspectable
**decision-trees** and running them through a server-side **logical analysis
engine**.

Experts create decision-trees, **Deploy** a validated version, and connect MCP
clients that can (1) run the default **guided gather** loop, where
`smeme_reasoning_evaluate` returns one blind question or a terminal outcome and
`smeme_reasoning_evaluate_continue` takes an answer with provenance—or an
abstention—until the loop returns a **report** or
`isolated_evaluations_required`, (2) submit a full worksheet of structured
`raw_answers`
in a single `smeme_reasoning_evaluate_answers` call for batch, integration, and
audit use, and (3) ask questions about the deployed tree itself — what-if,
reachability, and related analysis — without treating full evidence collection
as the only path. Agents gather evidence and pose questions; the server keeps
the decision logic and evaluation boundary under operator control.

**Agent bootstrap:** after OAuth, the client asks SMEme for the calling contract
via MCP (`smeme_reasoning_capabilities` → `smeme_reasoning_guidance_get`). There
is no installable zip — guidance is served over the wire. Humans edit
prose under [`agent-skills/`](agent-skills/README.md); CI builds what MCP returns.

### Need help?

| Need | Where |
|------|--------|
| How-to, MCP clients, integrations, example trees, self-host tips | **[GitHub Discussions](https://github.com/AristaLabs/smeme/discussions)** (Sign in with GitHub — free) |
| Reproducible bug or Core feature request | [Issues](https://github.com/AristaLabs/smeme/issues) |
| Account / billing on [smeme.ai](https://www.smeme.ai) | Email **contact@aristalabs.ai** |
| Security vulnerability | [SECURITY.md](SECURITY.md) — **not** Discussions or public Issues |

Start with the pinned **Start here** post in Discussions. Do not post secrets, `.env` files, or tokens.

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
git clone https://github.com/AristaLabs/smeme.git && cd smeme
git checkout "$(git describe --tags --abbrev=0 --match 'v*.*.*')"   # latest release
./scripts/init_core_env.sh
docker compose --env-file .env.core -f docker-compose.core.yml pull
docker compose --env-file .env.core -f docker-compose.core.yml up -d --no-build --wait
curl -fsS http://127.0.0.1:8000/api/v1/health
```

- App: http://127.0.0.1:8000 → `/decision-trees/dashboard`
- Health: http://127.0.0.1:8000/api/v1/health
- **Healthy ≠ usable product** (Clerk / MCP / Deploy need more config)
- Guides: [quickstart](docs/guides/self-host-quickstart.md) · [env](docs/guides/self-host-env.md) · [pilot](docs/guides/self-host-pilot.md)

### Local Python (Core)

```bash
uv sync --extra dev
# Core entrypoint (no Stripe / landing overlay):
uv run uvicorn smeme.core_entrypoint:app --reload
```

## Configure environment

Use `./scripts/init_core_env.sh` (writes `.env.core` from `.env.core.example`).
Task-grouped knobs and profiles: [self-host-env.md](docs/guides/self-host-env.md).
Clerk + MCP pilot: [self-host-pilot.md](docs/guides/self-host-pilot.md).

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
- [Self-host quickstart](docs/guides/self-host-quickstart.md) · [env reference](docs/guides/self-host-env.md) · [pilot](docs/guides/self-host-pilot.md)
- [MCP / OAuth operator guide](docs/guides/dr3-mcp-oauth-authoritative-sources.md)
- [Contribution paths](docs/CONTRIBUTION_PATHS.md)
- [Contributing](CONTRIBUTING.md) · [CLA](CONTRIBUTOR_LICENSE_AGREEMENT.md) · [Security](SECURITY.md)

## License

SMEme Sustainable Use License 1.0 — see [LICENSE.md](LICENSE.md) and [LICENSING.md](LICENSING.md).
