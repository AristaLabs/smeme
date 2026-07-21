#!/bin/sh
# Startup script for SMEme Core Docker image (self-host / public product).
# See Dockerfile.core and docs/guides/self-host-quickstart.md

set -e

echo "Starting SMEme Core container..."
echo "PORT: ${PORT:-8000}"
echo "SMEME_AI_GENERATION_ENABLED: ${SMEME_AI_GENERATION_ENABLED:-false}"
echo "DATABASE_URL is set: $(if [ -n "$DATABASE_URL" ]; then echo 'YES'; else echo 'NO'; fi)"
echo ""

echo "=== Running Database Migrations ==="
alembic upgrade head

echo ""
echo "=== Migrations Complete - Starting Core Application ==="
echo ""

exec uvicorn smeme.core_entrypoint:app --host 0.0.0.0 --port ${PORT:-8000}
