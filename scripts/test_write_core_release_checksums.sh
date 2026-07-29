#!/usr/bin/env bash
set -euo pipefail

# Local regression for the Core release checksum invariant:
# finalize evidence files first, then write SHA256SUMS for durable assets only.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/core-release-checksums.XXXXXX")"
cleanup() { rm -rf "${TMP}"; }
trap cleanup EXIT

mkdir -p "${TMP}/sbom"
printf 'cdx\n' >"${TMP}/sbom/smeme.cdx.json"
printf 'spdx\n' >"${TMP}/sbom/smeme.spdx.json"
printf 'source\n' >"${TMP}/sbom/smeme.source.txt"
printf 'cosign\n' >"${TMP}/COSIGN.md"
# Workflow-only path: must NOT appear in SHA256SUMS.txt
mkdir -p "${TMP}/legal-bundle"
printf 'notices\n' >"${TMP}/legal-bundle/NOTICE.txt"

{
  printf 'image=ghcr.io/aristalabs/smeme\n'
  printf 'digest=sha256:%s\n' "$(printf '0%.0s' {1..64})"
} >"${TMP}/EVIDENCE.txt"

# Finalize attestation metadata before checksums (the ordering bug).
{
  printf 'attested_by=github-oidc-actions-attest\n'
  printf 'generated_at_utc=2026-07-29T00:00:00Z\n'
} >>"${TMP}/EVIDENCE.txt"

bash "${ROOT}/scripts/write_core_release_checksums.sh" "${TMP}"

if ! grep -q 'EVIDENCE.txt$' "${TMP}/SHA256SUMS.txt"; then
  echo "FAIL: SHA256SUMS.txt missing EVIDENCE.txt" >&2
  exit 1
fi
if grep -q 'legal-bundle' "${TMP}/SHA256SUMS.txt"; then
  echo "FAIL: SHA256SUMS.txt must not include workflow-only legal-bundle" >&2
  exit 1
fi
if grep -q 'SHA256SUMS.txt' "${TMP}/SHA256SUMS.txt"; then
  echo "FAIL: SHA256SUMS.txt must not checksum itself" >&2
  exit 1
fi

(
  cd "${TMP}"
  sha256sum -c SHA256SUMS.txt
) >/dev/null

# Mutating a listed file after checksum generation must fail verification.
printf 'tampered\n' >>"${TMP}/EVIDENCE.txt"
if (
  cd "${TMP}"
  sha256sum -c SHA256SUMS.txt
) >/dev/null 2>&1; then
  echo "FAIL: expected checksum verification to fail after EVIDENCE.txt mutation" >&2
  exit 1
fi

echo "OK: write_core_release_checksums invariant holds"
