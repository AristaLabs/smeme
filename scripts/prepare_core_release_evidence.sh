#!/usr/bin/env bash
set -euo pipefail

# Prepare release evidence for an immutable Core image: SBOM + legal bundle +
# optional cosign attestation commands (signing keys are operator-provided).
#
# Usage:
#   scripts/prepare_core_release_evidence.sh [image] [output-directory]
#
# Example:
#   docker build -f Dockerfile.core -t smeme:local .
#   scripts/prepare_core_release_evidence.sh smeme:local build/release-evidence

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
# Attesting the Core SBOM (operator step)

After pushing an immutable digest to GHCR:

```bash
# Resolve the registry digest for the tag you just pushed.
DIGEST="$(crane digest ghcr.io/AristaLabs/smeme:vX.Y.Z)"

# Attach the CycloneDX SBOM as a signed attestation (requires cosign key/OIDC).
cosign attest --yes \
  --predicate build/release-evidence/sbom/smeme.cdx.json \
  --type cyclonedx \
  "ghcr.io/AristaLabs/smeme@${DIGEST}"
```

Retain `build/release-evidence/` (or the CI artifact) for the retention period
described in `legal/SOURCE_OFFER.md`. Local `smeme:local` tags are not
registry-immutable; regenerate this pack from the pushed digest before treating
it as release evidence.
EOF

printf 'Release evidence written to %s\n' "${OUTPUT_DIR}"
printf 'Next: push an immutable GHCR digest, then follow %s/COSIGN.md\n' "${OUTPUT_DIR}"
