#!/usr/bin/env bash
# Build the pre-built, purged Tailwind stylesheet without npm/node.
#
# Downloads the pinned Tailwind standalone CLI (a single self-contained binary)
# and compiles tailwind.input.css -> smeme/static/css/app.css (minified).
#
# Usage:  bash scripts/build_css.sh            # build once
#         bash scripts/build_css.sh --watch    # rebuild on change (local dev)
#
# The binary is cached in .cache/tailwind/ (git-ignored) so repeat builds are fast.
set -euo pipefail

TAILWIND_VERSION="${TAILWIND_VERSION:-v3.4.17}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CACHE_DIR="${ROOT}/.cache/tailwind"
BIN="${CACHE_DIR}/tailwindcss-${TAILWIND_VERSION}"
INPUT="${ROOT}/tailwind.input.css"
OUTPUT="${ROOT}/smeme/static/css/app.css"

# Resolve the standalone release asset name for this OS/arch.
os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m)"
case "$os" in
  linux) os="linux" ;;
  darwin) os="macos" ;;
  *) echo "Unsupported OS: $os" >&2; exit 1 ;;
esac
case "$arch" in
  x86_64 | amd64) arch="x64" ;;
  aarch64 | arm64) arch="arm64" ;;
  *) echo "Unsupported arch: $arch" >&2; exit 1 ;;
esac
asset="tailwindcss-${os}-${arch}"

if [ ! -x "$BIN" ]; then
  echo "Downloading Tailwind standalone CLI ${TAILWIND_VERSION} (${asset})..."
  mkdir -p "$CACHE_DIR"
  url="https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/${asset}"
  curl -sSL --fail -o "$BIN" "$url"
  chmod +x "$BIN"
fi

mkdir -p "$(dirname "$OUTPUT")"

if [ "${1:-}" = "--watch" ]; then
  exec "$BIN" -c "${ROOT}/tailwind.config.js" -i "$INPUT" -o "$OUTPUT" --watch
fi

"$BIN" -c "${ROOT}/tailwind.config.js" -i "$INPUT" -o "$OUTPUT" --minify
echo "Built $OUTPUT"
