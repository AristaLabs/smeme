# Public extract path lists (D023)

Normative for the clean public `AristaLabs/smeme` extract. Classification authority remains [D022](../DECISIONS.md#d022-product-surface-inventory--keep--saas-only--removed-core-distro-prep); distribution authority remains [D023](../DECISIONS.md#d023-public-core-repo--private-saas-overlay-distribution).

Use these lists when building the orphan public tree. Prefer an **allowlist copy** into a fresh repo over rewriting private history.

## Public allowlist (ship in `AristaLabs/smeme`)

### Product code

- `smeme/app_factory.py`
- `smeme/core_entrypoint.py`
- `smeme/api/`
- `smeme/auth/` (Clerk profile OK as first OIDC profile)
- `smeme/qnr/`
- `smeme/reasoning/`
- `smeme/mcp/`
- `smeme/docs/` (in-package docs that ship with Core)
- `smeme/billing/quota.py`
- `smeme/billing/usage.py`
- `smeme/billing/tiers.py`
- `smeme/billing/access_policy.py`
- `smeme/billing/providers.py`
- Core templates needed by KEEP surfaces (auth, qnr, layouts, shared partials) — **exclude** SaaS marketing/billing/legal hosted pages

### Skills and migrations

- `plugin/cowork-skills/`
- `alembic/` (and Core-safe `alembic/env.py` — optional SaaS imports only)

### Packaging / ops for Core

- `Dockerfile.core`
- `docker-compose.core.yml`
- `start-core.sh`
- `.env.core.example`
- `pyproject.toml` / `uv.lock` (Core extras; no requirement that SaaS extras exist in public tree)
- `scripts/check_core_no_saas_imports.py`
- `scripts/generate_core_sbom.sh`
- `scripts/bundle_core_notices.sh`
- `scripts/prepare_core_release_evidence.sh`
- `scripts/collect_python_licenses.py`
- `scripts/stage_core_public_extract.sh`

### Legal / community

- `LICENSE.md`
- `LICENSING.md`
- `SECURITY.md`
- `THIRD_PARTY_NOTICES.md`
- `legal/SOURCE_OFFER.md`
- `legal/third_party/`
- `CONTRIBUTOR_LICENSE_AGREEMENT.md`
- `CONTRIBUTING.md`
- `.github/ISSUE_TEMPLATE/`
- `.github/PULL_REQUEST_TEMPLATE.md`
- Core CI only: `.github/workflows/ci-core.yml` (never the private dual-stage Render pipeline)

### Docs (public-safe)

- `docs/ARCHITECTURE.md` and public architecture slices
- `docs/DECISIONS.md` (scrub or omit private business ADRs if any)
- `docs/ROADMAP.md` (public product roadmap only)
- `docs/guides/` needed for self-host / MCP / LangGraph (include `self-host-quickstart.md`)
- `docs/product/` (user-facing; no `docs/business/`)
- `docs/planning/` only if the doc is needed for contributors; otherwise omit sprint/internal planning

### Tests

- Tests for KEEP / FLAG-GATED paths only (no gallery / marketplace / SaaS-only route tests)

## Private denylist (stay in `smeme-cloud` / private tree)

### SaaS overlay code

- `smeme/saas_overlay.py`
- `smeme/main.py` (hosted SaaS entrypoint)
- `smeme/landing/`
- `smeme/legal/` (hosted Arista legal package)
- `smeme/billing/routes.py`
- `smeme/billing/stripe_sync.py`
- `smeme/billing/subscription_cancel.py`
- `smeme/billing/downgrade.py`
- `smeme/templates/landing/`
- `smeme/templates/legal/` (hosted Terms/Privacy/Principles for `smeme.ai`)
- `smeme/templates/billing/`
- Plausible / analytics partials used only by SaaS
- SaaS Dockerfile / Render / nginx deploy for `smeme.main:app`
- `docker-compose` / env files that presuppose Stripe/SendGrid/marketing waitlist

### Internal / non-product

- `docs/business/**`
- IP drafts, patent drafts, counsel work product
- Private strategy / COGS / pricing internal maps
- Production secrets, `.env`, credential dumps
- Agent transcripts, local IDE state, personal notes

## Extract procedure (engineering)

1. Create empty public repo `AristaLabs/smeme` (orphan history).
2. Copy allowlisted paths only; secret-scan the tree.
3. Confirm root `LICENSE.md` is the Core distribution text (already collapsed).
4. Build `Dockerfile.core` → push `ghcr.io/AristaLabs/smeme:<tag>` and record digest.
5. Point private `smeme-cloud` at that tag **and** digest.
6. Do **not** push this private monorepo’s full history to the public remote.
