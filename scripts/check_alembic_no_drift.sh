#!/usr/bin/env bash
# §9 — optional models-vs-migrations drift check (requires DB + RUN_ALEMBIC_DRIFT=1).
set -euo pipefail

if [[ "${RUN_ALEMBIC_DRIFT:-0}" != "1" ]]; then
  echo "WARNING: alembic drift check skipped (RUN_ALEMBIC_DRIFT != 1)." >&2
  echo "  Set RUN_ALEMBIC_DRIFT=1 with a reachable DATABASE_URL to enable." >&2
  exit 0
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

uv run alembic upgrade head

# Alembic 1.13+ requires --version-path to live under configured version_locations;
# a /tmp path aborts with "not represented in current version locations".
VERSION_DIR="$ROOT/alembic/versions"
REV_ID="$(python3 -c "import secrets; print(secrets.token_hex(6))")"

cleanup_drift_revision() {
  shopt -s nullglob
  for f in "$VERSION_DIR"/"${REV_ID}"_*.py; do
    rm -f "$f"
  done
  shopt -u nullglob
}
trap cleanup_drift_revision EXIT

uv run alembic revision --autogenerate -m drift_check --rev-id "$REV_ID" --version-path "$VERSION_DIR" >/dev/null

shopt -s nullglob
drift_files=("$VERSION_DIR"/"${REV_ID}"_*.py)
shopt -u nullglob
if ((${#drift_files[@]})); then
  for f in "${drift_files[@]}"; do
    if grep -E '^\s+op\.' "$f" >/dev/null 2>&1; then
      echo "ERROR: alembic autogenerate produced drift. Models and migrations are out of sync." >&2
      cat "$f" >&2
      exit 1
    fi
  done
fi

echo "Alembic drift check: clean."
