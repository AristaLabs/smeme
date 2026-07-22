#!/usr/bin/env bash
# Stage a clean public-Core tree for AristaLabs/smeme extract (D023).
#
# Does NOT create a git repo or push. Copies the documented allowlist into an
# orphan-ready directory and prunes SAAS-ONLY paths (same set as Dockerfile.core).
#
# Usage:
#   scripts/stage_core_public_extract.sh [output_dir]
#
# Default output: build/public-smeme-extract/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-${ROOT}/build/public-smeme-extract}"

echo "Staging public Core extract → ${OUT}"
rm -rf "${OUT}"
mkdir -p "${OUT}"

copy_path() {
  local rel="$1"
  local src="${ROOT}/${rel}"
  if [[ ! -e "${src}" ]]; then
    echo "skip (missing): ${rel}"
    return 0
  fi
  mkdir -p "$(dirname "${OUT}/${rel}")"
  if [[ -d "${src}" ]]; then
    rsync -a \
      --exclude '.git/' \
      --exclude '__pycache__/' \
      --exclude '*.pyc' \
      --exclude '.pytest_cache/' \
      --exclude '.mypy_cache/' \
      --exclude '.ruff_cache/' \
      "${src}/" "${OUT}/${rel}/"
  else
    cp "${src}" "${OUT}/${rel}"
  fi
}

# ---------------------------------------------------------------------------
# Root legal / community / packaging
# ---------------------------------------------------------------------------
for rel in \
  LICENSE.md \
  LICENSING.md \
  THIRD_PARTY_NOTICES.md \
  CONTRIBUTING.md \
  CONTRIBUTOR_LICENSE_AGREEMENT.md \
  SECURITY.md \
  pyproject.toml \
  uv.lock \
  alembic.ini \
  Dockerfile.core \
  docker-compose.core.yml \
  start-core.sh \
  tailwind.config.js \
  tailwind.input.css \
  .dockerignore \
  .gitignore \
  .gitleaks.toml \
  .env.core.example
do
  copy_path "${rel}"
done

cp "${ROOT}/README.core.md" "${OUT}/README.md"

# ---------------------------------------------------------------------------
# Product + migrations + skills + legal notices
# ---------------------------------------------------------------------------
copy_path "smeme"
copy_path "alembic"
copy_path "plugin/agent-skills"
copy_path "legal"

# ---------------------------------------------------------------------------
# Scripts (Core CI / legal / boundary — not private SaaS helpers)
# ---------------------------------------------------------------------------
for rel in \
  scripts/check_core_no_saas_imports.py \
  scripts/generate_core_sbom.sh \
  scripts/bundle_core_notices.sh \
  scripts/prepare_core_release_evidence.sh \
  scripts/collect_python_licenses.py \
  scripts/stage_core_public_extract.sh \
  scripts/build_css.sh \
  scripts/validate_agent_skills.py \
  scripts/build_guidance_artifact.py \
  scripts/build_design_guidance_artifact.py \
  scripts/check_no_dtq_product_refs.py \
  scripts/check_no_dtq_product_refs.sh \
  scripts/check_alembic_no_drift.sh \
  scripts/check_raw_callout_classes.py \
  scripts/eval_branching_fixtures.py \
  scripts/qnr_reasoning_inspect.py \
  scripts/smoke_mcp_url.sh
do
  copy_path "${rel}"
done

# ---------------------------------------------------------------------------
# Tests (KEEP / FLAG-GATED only — drop SaaS-only suites below)
# ---------------------------------------------------------------------------
copy_path "tests"

# ---------------------------------------------------------------------------
# Docs (public-safe; omit business / historical / internal planning / SaaS ops)
# ---------------------------------------------------------------------------
for rel in \
  docs/README.md \
  docs/ARCHITECTURE.md \
  docs/guides/self-host-quickstart.md \
  docs/guides/getting-started.md \
  docs/guides/installation.md \
  docs/guides/dr3-mcp-oauth-authoritative-sources.md \
  docs/guides/frontend-css-build.md \
  docs/guides/cowork-reasoning-plugin-runbooks.md \
  docs/guides/data-migration.md \
  docs/guides/engine-promises.md
do
  copy_path "${rel}"
done

# ---------------------------------------------------------------------------
# GitHub community + Core-only CI (never the private dual-stage Render pipeline)
# ---------------------------------------------------------------------------
copy_path ".github/ISSUE_TEMPLATE"
copy_path ".github/PULL_REQUEST_TEMPLATE.md"
copy_path ".github/workflows/ci-core.yml"

# ---------------------------------------------------------------------------
# Prune SAAS-ONLY (must match Dockerfile.core core-source stage)
# ---------------------------------------------------------------------------
rm -rf \
  "${OUT}/smeme/main.py" \
  "${OUT}/smeme/saas_overlay.py" \
  "${OUT}/smeme/landing" \
  "${OUT}/smeme/legal" \
  "${OUT}/smeme/billing/routes.py" \
  "${OUT}/smeme/billing/stripe_sync.py" \
  "${OUT}/smeme/billing/subscription_cancel.py" \
  "${OUT}/smeme/billing/downgrade.py" \
  "${OUT}/smeme/templates/billing" \
  "${OUT}/smeme/templates/landing" \
  "${OUT}/smeme/templates/legal" \
  "${OUT}/smeme/templates/layouts/_analytics.html" \
  "${OUT}/smeme/gallery" \
  "${OUT}/smeme/memo"

# SaaS-only / Stripe / landing tests (stay in private overlay tree)
rm -rf \
  "${OUT}/tests/unit/test_landing.py" \
  "${OUT}/tests/unit/test_legal.py" \
  "${OUT}/tests/unit/test_teams_waitlist.py" \
  "${OUT}/tests/unit/test_billing_subscription.py" \
  "${OUT}/tests/unit/test_sprint7_billing.py" \
  "${OUT}/tests/unit/test_saas_app_composition.py" \
  "${OUT}/tests/unit/billing/test_stripe_sync.py" \
  "${OUT}/tests/unit/billing/test_downgrade_lifecycle.py"

# Never ship SaaS Docker / compose / dual-stage CI
rm -f \
  "${OUT}/Dockerfile" \
  "${OUT}/docker-compose.yml" \
  "${OUT}/start.sh" \
  "${OUT}/.github/workflows/ci-cd-dual-stage.yml"

# Defensive: no business / historical / internal ops docs if copied somehow
rm -rf \
  "${OUT}/docs/business" \
  "${OUT}/docs/historical" \
  "${OUT}/docs/ip" \
  "${OUT}/docs/guides/internal" \
  "${OUT}/docs/operations" \
  "${OUT}/docs/planning/sprint-core-public-release.md"

cat >"${OUT}/EXTRACT_README.txt" <<EOF
Staged $(date -u +%Y-%m-%dT%H:%MZ) from private monorepo.

Next:
  1. Review tree against docs/planning/core-public-extract-paths.md
  2. Secret-scan this directory
  3. cd ${OUT} && git init && git checkout --orphan main && git add -A && git commit
  4. Create empty AristaLabs/smeme on GitHub; push orphan history only
  5. Build Dockerfile.core → ghcr.io/AristaLabs/smeme:<tag> (+ digest)
  6. Pin smeme-cloud FROM that tag and digest

Do not push the private monorepo history.
EOF

echo "Done. Review ${OUT}/EXTRACT_README.txt"
echo "Suggested checks (from extract after uv sync --extra dev):"
echo "  (cd \"${OUT}\" && uv sync --extra dev && uv run python scripts/check_core_no_saas_imports.py)"
echo "  # secret-scan before first push"
