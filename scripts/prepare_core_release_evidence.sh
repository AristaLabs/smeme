#!/usr/bin/env bash
set -euo pipefail

# Prepare release evidence for an immutable Core image: SBOM + legal bundle +
# verification instructions for GitHub OIDC attestations (publish CI signs).
#
# Usage:
#   scripts/prepare_core_release_evidence.sh [image] [output-directory]
#
# Example:
#   docker build -f Dockerfile.core -t smeme:local .
#   scripts/prepare_core_release_evidence.sh smeme:local build/release-evidence
#
# Release publishes also run this against the exact GHCR digest and attach
# signed attestations via actions/attest.

IMAGE="${1:-smeme:local}"
OUTPUT_DIR="${2:-build/release-evidence}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${OUTPUT_DIR}" != /* ]]; then
  OUTPUT_DIR="${PWD}/${OUTPUT_DIR}"
fi

mkdir -p "${OUTPUT_DIR}"

"${ROOT}/scripts/generate_core_sbom.sh" "${IMAGE}" "${OUTPUT_DIR}/sbom"
"${ROOT}/scripts/bundle_core_notices.sh" "${IMAGE}" "${OUTPUT_DIR}/legal-bundle"

IMAGE_ID="$(docker image inspect "${IMAGE}" --format '{{.Id}}')"
{
  printf 'image=%s\n' "${IMAGE}"
  printf 'image_id=%s\n' "${IMAGE_ID}"
  printf 'repo_digests=%s\n' "$(docker image inspect "${IMAGE}" --format '{{json .RepoDigests}}')"
  printf 'generated_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"${OUTPUT_DIR}/EVIDENCE.txt"

cat >"${OUTPUT_DIR}/COSIGN.md" <<'EOF'
# Verifying Core image attestations

Publish CI attaches GitHub OIDC–signed attestations to every pushed Core digest:

- SLSA build provenance (`https://slsa.dev/provenance/v1`)
- CycloneDX SBOM (`https://cyclonedx.org/bom`)

Durable stores (not the 90-day workflow artifact):

1. **GitHub Attestations API** — bound to `AristaLabs/smeme` for the digest
2. **GitHub Release assets** — for each `vMAJOR.MINOR.PATCH` tag (SBOM + checksums)

## Verify (preferred)

```bash
DIGEST=sha256:…   # from the publish job notice
gh attestation verify \
  "oci://ghcr.io/aristalabs/smeme@${DIGEST}" \
  --repo AristaLabs/smeme \
  --predicate-type https://slsa.dev/provenance/v1

gh attestation verify \
  "oci://ghcr.io/aristalabs/smeme@${DIGEST}" \
  --repo AristaLabs/smeme \
  --predicate-type https://cyclonedx.org/bom
```

Or use `scripts/verify_core_image_attestation.sh "${DIGEST}"`.

## Optional Cosign

Attestations are also pushed as OCI referrers when registry push succeeds.
Cosign remains optional for operators who prefer Sigstore tooling:

```bash
cosign verify-attestation \
  --type cyclonedx \
  --certificate-identity-regexp 'https://github.com/AristaLabs/smeme/.github/workflows/ci-core.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  "ghcr.io/aristalabs/smeme@${DIGEST}"
```

Retain this evidence pack (or the matching GitHub Release assets) for the
period described in `legal/SOURCE_OFFER.md`.

## Release checksums

On `vMAJOR.MINOR.PATCH` tags, `SHA256SUMS.txt` covers only durable Release
assets (SBOM files, `EVIDENCE.txt`, `COSIGN.md`). It is written after those
files are finalized and does not checksum itself. Workflow-only paths such as
`legal-bundle/` remain in the 90-day artifact and are intentionally omitted
from the release checksum manifest.

```bash
sha256sum -c SHA256SUMS.txt
```
EOF

printf 'Release evidence written to %s\n' "${OUTPUT_DIR}"
printf 'Next: CI attests the pushed digest; operators verify with scripts/verify_core_image_attestation.sh\n'
