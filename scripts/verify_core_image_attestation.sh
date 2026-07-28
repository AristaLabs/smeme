#!/usr/bin/env bash
set -euo pipefail

# Verify GitHub OIDC-signed attestations for an immutable Core image digest.
#
# Usage:
#   scripts/verify_core_image_attestation.sh <digest|oci-ref> [repo]
#
# Examples:
#   scripts/verify_core_image_attestation.sh sha256:abc…
#   scripts/verify_core_image_attestation.sh \
#     oci://ghcr.io/aristalabs/smeme@sha256:abc… AristaLabs/smeme
#
# Requires: gh (authenticated for private packages), docker login to GHCR when
# verifying by digest-only form.

IMAGE_NAME="${SMEME_CORE_IMAGE:-ghcr.io/aristalabs/smeme}"
REPO="${2:-AristaLabs/smeme}"
SUBJECT="${1:-}"

if [[ -z "${SUBJECT}" ]]; then
  echo "usage: $0 <sha256:digest|oci://…@sha256:digest> [owner/repo]" >&2
  exit 2
fi

if [[ "${SUBJECT}" == oci://* ]]; then
  OCI_REF="${SUBJECT}"
elif [[ "${SUBJECT}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  OCI_REF="oci://${IMAGE_NAME}@${SUBJECT}"
elif [[ "${SUBJECT}" == *"@sha256:"* ]]; then
  OCI_REF="oci://${SUBJECT#oci://}"
else
  echo "error: subject must be sha256:… or oci://image@sha256:…" >&2
  exit 2
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh CLI is required" >&2
  exit 1
fi

echo "Verifying SLSA provenance for ${OCI_REF} (repo ${REPO})"
gh attestation verify "${OCI_REF}" \
  --repo "${REPO}" \
  --predicate-type https://slsa.dev/provenance/v1

echo "Verifying SBOM attestation for ${OCI_REF} (repo ${REPO})"
# actions/attest selects the predicate from the SBOM format. Core publishes
# CycloneDX; fall back to SPDX if a future generator switches formats.
if ! gh attestation verify "${OCI_REF}" \
  --repo "${REPO}" \
  --predicate-type https://cyclonedx.org/bom; then
  gh attestation verify "${OCI_REF}" \
    --repo "${REPO}" \
    --predicate-type https://spdx.dev/Document
fi

echo "Core image attestation verified: ${OCI_REF}"
