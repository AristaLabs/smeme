#!/usr/bin/env bash
# Create .env.core from .env.core.example with generated secrets.
# Refuses to overwrite an existing .env.core. Does not print secret values.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

EXAMPLE=".env.core.example"
TARGET=".env.core"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: required command not found: $1" >&2
    exit 1
  fi
}

need_cmd docker
need_cmd openssl
need_cmd curl
need_cmd git

if ! docker compose version >/dev/null 2>&1; then
  echo "error: docker compose v2 is required" >&2
  exit 1
fi

COMPOSE_VER="$(docker compose version --short 2>/dev/null || docker compose version | head -1)"
echo "docker compose: ${COMPOSE_VER}"

# Require Compose 2.24+ for prod overlay (!reset); warn only for local init.
MAJOR="$(echo "$COMPOSE_VER" | sed -n 's/^[^0-9]*\([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\1/p')"
MINOR="$(echo "$COMPOSE_VER" | sed -n 's/^[^0-9]*\([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\2/p')"
if [[ -n "${MAJOR}" && -n "${MINOR}" ]]; then
  if (( MAJOR < 2 || (MAJOR == 2 && MINOR < 24) )); then
    echo "warning: Compose ${COMPOSE_VER} < 2.24 — production overlay (docker-compose.core.prod.yml) needs !reset" >&2
  fi
fi

if [[ ! -f "$EXAMPLE" ]]; then
  echo "error: missing ${EXAMPLE}" >&2
  exit 1
fi

if [[ -e "$TARGET" ]]; then
  echo "error: ${TARGET} already exists — refuse to overwrite. Remove or rename it first." >&2
  exit 1
fi

SECRET_KEY="$(openssl rand -hex 32)"
JWT_SECRET_KEY="$(openssl rand -hex 32)"
POSTGRES_PASSWORD="$(openssl rand -hex 24)"

cp "$EXAMPLE" "$TARGET"

# Portable in-place replace (macOS/BSD and GNU sed).
tmp="$(mktemp)"
awk -v sk="$SECRET_KEY" -v jk="$JWT_SECRET_KEY" -v pp="$POSTGRES_PASSWORD" '
  /^SECRET_KEY=/ { print "SECRET_KEY=" sk; next }
  /^JWT_SECRET_KEY=/ { print "JWT_SECRET_KEY=" jk; next }
  /^POSTGRES_PASSWORD=/ { print "POSTGRES_PASSWORD=" pp; next }
  { print }
' "$TARGET" >"$tmp"
mv "$tmp" "$TARGET"
chmod 600 "$TARGET"

echo "Wrote ${TARGET} (mode 600) with generated SECRET_KEY, JWT_SECRET_KEY, POSTGRES_PASSWORD."
echo "Next:"
echo "  docker compose --env-file .env.core -f docker-compose.core.yml pull"
echo "  docker compose --env-file .env.core -f docker-compose.core.yml up -d --no-build --wait"
