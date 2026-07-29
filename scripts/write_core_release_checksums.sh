#!/usr/bin/env bash
set -euo pipefail

# Write SHA256SUMS.txt for durable GitHub Release assets only.
#
# Invariant:
#   1. Call only after every listed file is fully finalized.
#   2. Never checksum SHA256SUMS.txt itself.
#   3. Do not include workflow-only paths (e.g. legal-bundle/) unless those
#      paths are also attached to the GitHub Release.
#
# Keep this list aligned with the softprops/action-gh-release ``files:`` block
# in .github/workflows/ci-core.yml (release job).
#
# Usage:
#   scripts/write_core_release_checksums.sh <evidence-directory>

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <evidence-directory>" >&2
  exit 2
fi

EVIDENCE_DIR="$1"
if [[ "${EVIDENCE_DIR}" != /* ]]; then
  EVIDENCE_DIR="${PWD}/${EVIDENCE_DIR}"
fi

if [[ ! -d "${EVIDENCE_DIR}" ]]; then
  echo "error: evidence directory not found: ${EVIDENCE_DIR}" >&2
  exit 1
fi

# Durable release assets only (paths relative to the evidence directory).
RELEASE_ASSETS=(
  "sbom/smeme.cdx.json"
  "sbom/smeme.spdx.json"
  "sbom/smeme.source.txt"
  "EVIDENCE.txt"
  "COSIGN.md"
)

missing=0
for rel in "${RELEASE_ASSETS[@]}"; do
  if [[ ! -f "${EVIDENCE_DIR}/${rel}" ]]; then
    echo "error: missing durable release asset: ${rel}" >&2
    missing=1
  fi
done
if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

(
  cd "${EVIDENCE_DIR}"
  # Explicit list (not find) so legal-bundle and other workflow-only files are
  # excluded from the release checksum manifest.
  sha256sum "${RELEASE_ASSETS[@]}"
) >"${EVIDENCE_DIR}/SHA256SUMS.txt"

printf 'Wrote durable-asset checksums to %s\n' "${EVIDENCE_DIR}/SHA256SUMS.txt"
