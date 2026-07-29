#!/usr/bin/env bash
set -euo pipefail

# Local regression for the Core release checksum invariant:
# finalize evidence files first, then write SHA256SUMS for durable assets only.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/core-release-checksums.XXXXXX")"
cleanup() { rm -rf "${TMP}"; }
trap cleanup EXIT
EVIDENCE_DIR="${TMP}/evidence"
RELEASE_DIR="${TMP}/downloaded-release-assets"

mkdir -p "${EVIDENCE_DIR}/sbom"
printf 'cdx\n' >"${EVIDENCE_DIR}/sbom/smeme.cdx.json"
printf 'spdx\n' >"${EVIDENCE_DIR}/sbom/smeme.spdx.json"
printf 'source\n' >"${EVIDENCE_DIR}/sbom/smeme.source.txt"
printf 'cosign\n' >"${EVIDENCE_DIR}/COSIGN.md"
# Workflow-only path: must NOT appear in SHA256SUMS.txt
mkdir -p "${EVIDENCE_DIR}/legal-bundle"
printf 'notices\n' >"${EVIDENCE_DIR}/legal-bundle/NOTICE.txt"

{
  printf 'image=ghcr.io/aristalabs/smeme\n'
  printf 'digest=sha256:%s\n' "$(printf '0%.0s' {1..64})"
} >"${EVIDENCE_DIR}/EVIDENCE.txt"

# Finalize attestation metadata before checksums (the ordering bug).
{
  printf 'attested_by=github-oidc-actions-attest\n'
  printf 'generated_at_utc=2026-07-29T00:00:00Z\n'
} >>"${EVIDENCE_DIR}/EVIDENCE.txt"

bash "${ROOT}/scripts/write_core_release_checksums.sh" "${EVIDENCE_DIR}"

if ! grep -q 'EVIDENCE.txt$' "${EVIDENCE_DIR}/SHA256SUMS.txt"; then
  echo "FAIL: SHA256SUMS.txt missing EVIDENCE.txt" >&2
  exit 1
fi
if grep -q 'legal-bundle' "${EVIDENCE_DIR}/SHA256SUMS.txt"; then
  echo "FAIL: SHA256SUMS.txt must not include workflow-only legal-bundle" >&2
  exit 1
fi
if grep -q 'SHA256SUMS.txt' "${EVIDENCE_DIR}/SHA256SUMS.txt"; then
  echo "FAIL: SHA256SUMS.txt must not checksum itself" >&2
  exit 1
fi
if grep -q 'sbom/' "${EVIDENCE_DIR}/SHA256SUMS.txt"; then
  echo "FAIL: Release manifest must use flattened GitHub asset basenames" >&2
  exit 1
fi

# Emulate action-gh-release: every uploaded path becomes a basename in one
# downloaded Release-assets directory.
mkdir -p "${RELEASE_DIR}"
cp "${EVIDENCE_DIR}/sbom/smeme.cdx.json" "${RELEASE_DIR}/"
cp "${EVIDENCE_DIR}/sbom/smeme.spdx.json" "${RELEASE_DIR}/"
cp "${EVIDENCE_DIR}/sbom/smeme.source.txt" "${RELEASE_DIR}/"
cp "${EVIDENCE_DIR}/EVIDENCE.txt" "${RELEASE_DIR}/"
cp "${EVIDENCE_DIR}/COSIGN.md" "${RELEASE_DIR}/"
cp "${EVIDENCE_DIR}/SHA256SUMS.txt" "${RELEASE_DIR}/"
(
  cd "${RELEASE_DIR}"
  sha256sum -c SHA256SUMS.txt
) >/dev/null

# Mutating a listed file after checksum generation must fail verification.
printf 'tampered\n' >>"${RELEASE_DIR}/EVIDENCE.txt"
if (
  cd "${RELEASE_DIR}"
  sha256sum -c SHA256SUMS.txt
) >/dev/null 2>&1; then
  echo "FAIL: expected checksum verification to fail after EVIDENCE.txt mutation" >&2
  exit 1
fi

echo "OK: write_core_release_checksums invariant holds"
