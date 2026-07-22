#!/usr/bin/env bash
# Finite HTTP checks for MCP + OAuth discovery (no hanging SSE).
# Usage:
#   bash scripts/smoke_mcp_url.sh https://your-smeme.example
#   bash scripts/smoke_mcp_url.sh http://127.0.0.1:8000 /api/v1/mcp
set -euo pipefail

ORIGIN="${1:?usage: $0 <origin> [mcp_path]}"
MCP_PATH="${2:-/api/v1/mcp}"
ORIGIN="${ORIGIN%/}"
MCP_PATH="/${MCP_PATH#/}"

echo "== RFC 9728 protected-resource metadata (should be 200, JSON) =="
curl -sS -o /dev/null -w "HTTP %{http_code}\n" --max-time 20 \
  "${ORIGIN}/.well-known/oauth-protected-resource${MCP_PATH}"

echo "== Sample body (first 240 bytes) =="
curl -sS --max-time 20 \
  "${ORIGIN}/.well-known/oauth-protected-resource${MCP_PATH}" | head -c 240
echo ""
echo "(done)"
