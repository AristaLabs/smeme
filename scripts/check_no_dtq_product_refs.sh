#!/usr/bin/env bash
# §10.2 — delegate to portable Python scanner (same rules as CI).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec uv run python "$ROOT/scripts/check_no_dtq_product_refs.py"
