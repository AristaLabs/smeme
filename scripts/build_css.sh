#!/usr/bin/env bash
# Build the pre-built, purged Tailwind stylesheet without npm/node.
#
# Downloads the pinned Tailwind standalone CLI (a single self-contained binary)
# and compiles tailwind.input.css -> smeme/static/css/app.css (minified).
# Release assets are verified against hardcoded SHA-256 digests (H-06).
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

# SHA-256 digests from https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/sha256sums.txt
expected=""
case "${TAILWIND_VERSION}:${asset}" in
  v3.4.17:tailwindcss-linux-x64) expected="7d24f7fa191d2193b78cd5f5a42a6093e14409521908529f42d80b11fde1f1d4" ;;
  v3.4.17:tailwindcss-linux-arm64) expected="69b1378b8133192d7d2feb12a116fa12d035594f58db3eff215879e4ad8cf39b" ;;
  v3.4.17:tailwindcss-macos-x64) expected="6cbdad74be776c087ffa5e9a057512c54898f9fe8828d3362212dfe32fc933a3" ;;
  v3.4.17:tailwindcss-macos-arm64) expected="a1d0c7985759accca0bf12e51ac1dcbf0f6cf2fffb62e6e0f62d091c477a10a3" ;;
  *)
    echo "No SHA-256 mapped for Tailwind ${TAILWIND_VERSION} asset ${asset}" >&2
    exit 1
    ;;
esac

verify_sha256() {
  local file="$1" want="$2" got
  if command -v sha256sum >/dev/null 2>&1; then
    echo "${want}  ${file}" | sha256sum -c -
  else
    got="$(shasum -a 256 "$file" | awk '{print $1}')"
    if [ "$got" != "$want" ]; then
      echo "SHA-256 mismatch for ${file}: expected ${want}, got ${got}" >&2
      exit 1
    fi
  fi
}

if [ ! -x "$BIN" ]; then
  echo "Downloading Tailwind standalone CLI ${TAILWIND_VERSION} (${asset})..."
  mkdir -p "$CACHE_DIR"
  url="https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/${asset}"
  curl -sSL --fail -o "$BIN" "$url"
  chmod +x "$BIN"
fi

verify_sha256 "$BIN" "$expected"

mkdir -p "$(dirname "$OUTPUT")"

if [ "${1:-}" = "--watch" ]; then
  exec "$BIN" -c "${ROOT}/tailwind.config.js" -i "$INPUT" -o "$OUTPUT" --watch
fi

"$BIN" -c "${ROOT}/tailwind.config.js" -i "$INPUT" -o "$OUTPUT" --minify
echo "Built $OUTPUT"
