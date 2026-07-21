# Public SMEme repository extract checklist (D023)

Goal: publish public product repo **`AristaLabs/smeme`** that builds **`ghcr.io/AristaLabs/smeme`**, while this private tree (or renamed **`smeme-cloud`**) keeps SAAS-ONLY as an overlay that pins the public image by tag **and digest**.

Path lists: [core-public-extract-paths.md](core-public-extract-paths.md).

**Counsel:** Outside counsel is **not** in budget. Legal pack is engineering best-effort + self-review. Residual risk is accepted by Arista Labs for first public release. See [`LICENSING.md`](../../LICENSING.md) self-review note.

## Locked decisions

| Item | Value |
|------|--------|
| License | SMEme Sustainable Use License 1.0 (n8n-derived text; n8n permits reuse; renamed) — [`LICENSE.md`](../../LICENSE.md) |
| Licensor | Arista Labs, LLC |
| Public repo | `AristaLabs/smeme` |
| Public image | `ghcr.io/AristaLabs/smeme` |
| Private overlay | `AristaLabs/smeme-cloud` → `ghcr.io/AristaLabs/smeme-cloud` |
| Boundary | `FROM ghcr.io/AristaLabs/smeme:<tag>` (+ digest); not pip/git |
| Marketing | “source-available” / “fair-code,” never “open source” |
| EE in public tree | **No** `.ee` files — commercial code stays private |

## Order (see [sprint](sprint-core-public-release.md))

1. Appliance proof → 2. Legal pack (SBOM from **final image**) → 3. Clean extract → 4. Pin `smeme-cloud` last

## Before first public push

### A — Appliance proof (critical path)

- [x] `scripts/check_core_no_saas_imports.py` passes (tree scan of KEEP packages)
- [x] `scripts/check_core_no_saas_imports.py --image smeme:local` passes (forbidden files absent from every runtime-image layer; SaaS/dev packages absent)
- [x] `docker build -f Dockerfile.core -t smeme:local .` succeeds after boundary fixes
- [x] Compose boots with generation off; health/routes OK; SaaS main/adapters/middleware absent
- [x] Stripe, SendGrid, and pytest packages absent from the Core image
- [x] Plausible analytics partial absent (SaaS overlay supplies the optional include)
- [x] Network-accessible posture: documented (do not expose without Clerk; `/api/docs` + health open) — see self-host quickstart

### B — Legal pack

- [x] `LICENSE.md` — public-distro-ready SMEme SUL 1.0 (collapsed preamble; Core applies to whole Core distribution; SaaS overlay called out as proprietary without ADR path lists)
- [x] `LICENSING.md` — allowed/prohibited examples, network + customer-controlled infra notes, output / model-provider statement, n8n reuse note, self-review note
- [x] `CONTRIBUTOR_LICENSE_AGREEMENT.md`, CONTRIBUTING CLA pointer
- [x] Hosted Terms / Privacy carve out self-host; SUL governs Core software copies; hosted docs govern `smeme.ai` only
- [x] Outside counsel **waived** (budget) — residual risk accepted; do not claim “attorney reviewed”
- [x] Reproducible all-layer CycloneDX + SPDX generation from `smeme:local`; curate initial [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md)
- [x] Core image pins Python base digest and embeds `/app/legal/` (LICENSE, notices, SOURCE_OFFER, curated third_party, harvested python licenses, debian inventories)
- [x] `scripts/prepare_core_release_evidence.sh` produces SBOM + legal bundle (+ cosign instructions)
- [x] SOURCE_OFFER engineering language landed; attach signed SBOM to immutable public digest **per tag at release time** (operator step)

### C — Clean extract (prefer over history rewrite)

- [ ] Audited KEEP/FLAG-GATED snapshot with **fresh orphan history**
- [x] Explicit **public allowlist** + **private denylist** — [core-public-extract-paths.md](core-public-extract-paths.md)
- [x] Staging helper: `scripts/stage_core_public_extract.sh` → `build/public-smeme-extract/` (prune matches `Dockerfile.core`)
- [x] Public `LICENSE.md` collapsed for Core distribution (SaaS carve-out remains as proprietary notice; no ADR incorporation)
- [x] Org/repo names locked to `AristaLabs/smeme` and `ghcr.io/AristaLabs/smeme` in shipped legal docs
- [x] Secret-scan tooling note: `.dockerignore` excludes `.env` / `.env.*` (keeps `*.example`); still secret-scan the public tree before first push
- [ ] Secret-scan staged/public tree before first push
- [ ] Immutable version tags + reproducible GHCR image (`smeme`)
- [ ] Rewrite private history only if you intentionally need to preserve private commits

### D — Pin cloud last

- [ ] Private overlay Dockerfile pins `FROM …/smeme:<tag>` **and** digest

## Paths that stay in public `smeme` (KEEP + FLAG-GATED)

See [core-public-extract-paths.md](core-public-extract-paths.md) and [D022](../DECISIONS.md#d022-product-surface-inventory--keep--saas-only--removed-core-distro-prep).

## Paths that move to private `smeme-cloud` only

See [core-public-extract-paths.md](core-public-extract-paths.md) denylist.

## Private overlay pin (after public image exists)

```dockerfile
ARG SMEME_IMAGE=ghcr.io/AristaLabs/smeme
ARG SMEME_VERSION=1.0.0
FROM ${SMEME_IMAGE}:${SMEME_VERSION}
# Prefer also pinning by digest in production deploy config.
```

1. Public `smeme` tags `vX.Y.Z` and publishes `ghcr.io/AristaLabs/smeme:vX.Y.Z`.
2. `smeme-cloud` depends on that tag (+ digest), then copies overlay.
3. Contributors open PRs only against the public `smeme` repo.

## History strategy

**Prefer clean extract:** audited KEEP/FLAG-GATED tree + fresh history + secret-scan. Do not push the private monorepo history. Only rewrite private history if you intentionally want to preserve commits there.

## Sprint

See [sprint-core-public-release.md](sprint-core-public-release.md).
