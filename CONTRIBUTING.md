# Contributing to SMEme

Thanks for helping improve SMEme. This repository is the **public product** (decision-tree authoring, Deploy/Listed, IR/Z3 reasoning, MCP). Hosted `smeme.ai` commercial surfaces (Stripe, marketing landing, waitlist, Arista legal) live in a **private `smeme-cloud` overlay** and are out of scope for public PRs.

Architecture decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md) — especially **D022** (surface inventory) and **D023** (public `smeme` + private overlay).

**License:** source-available under the [SMEme Sustainable Use License 1.0](LICENSE.md) (Arista Labs, LLC). See [LICENSING.md](LICENSING.md). Do not describe SMEme as “open source.”

## Contributor License Agreement

By opening a pull request, you agree to the [Contributor License Agreement](CONTRIBUTOR_LICENSE_AGREEMENT.md), which lets Arista Labs, LLC relicense contributions (including under commercial terms for hosted / proprietary offerings).

## How to contribute

1. **Fork** the public `smeme` repo (once published; until then this private tree is the working product + overlay monorepo).
2. Create a branch from `main` / `dev` as directed in the PR template.
3. Make changes that belong in the **public product** only. Do not add Stripe Checkout, marketing landing, waitlist, or Arista legal pages here.
4. Run checks locally (see below).
5. Open a PR. Maintainers review; CI must pass.

## Local setup

```bash
# Python 3.13+, uv, Docker (optional for Postgres)
cp .env.example .env   # or .env.core.example for product-only compose
uv sync --extra dev

# Core import guard (must stay green)
uv run python scripts/check_core_no_saas_imports.py
# After building the appliance: also
# uv run python scripts/check_core_no_saas_imports.py --image smeme:local

uv run ruff check smeme
uv run ruff format --check smeme
uv run pytest tests/unit/test_app_composition.py -q
```

Self-host with Docker:

```bash
cp .env.core.example .env.core
docker compose --env-file .env.core -f docker-compose.core.yml up --build
```

Optional knobs (OpenAI, Tavily, MCP authoring, Clerk) are listed in `.env.core.example` and [`docs/guides/self-host-quickstart.md`](docs/guides/self-host-quickstart.md).

## What belongs in public `smeme` vs `smeme-cloud`

| In public product (PRs welcome) | Private overlay (not here) |
|---------------------------------|----------------------------|
| Editor, dashboard, Deploy / Listed | Stripe Checkout / Portal / webhooks |
| Reasoning + MCP tools | Marketing landing, SEO, Business waitlist |
| Quota *engine* | Upgrade CTAs, downgrade pick-flow |
| Skills under `plugin/cowork-skills/` | Arista legal / subprocessors pages |
| `create_core_app` / `core_entrypoint` | `saas_overlay` / `create_saas_app` |

## Code style

- Match existing patterns; prefer small, focused diffs.
- Product vocabulary: **workflow** in wire IDs is fine; UI/docs prefer decision-tree / Deploy / Listed per `CLAUDE.md`.
- Do not reintroduce surfaces listed as **REMOVED** in D022.

## License

- Software: [`LICENSE.md`](LICENSE.md) · FAQ: [`LICENSING.md`](LICENSING.md)
