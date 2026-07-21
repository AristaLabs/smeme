#!/usr/bin/env bash
set -euo pipefail

# Generate release-grade SBOMs from the built Core appliance, not from uv.lock.
#
# Usage:
#   scripts/generate_core_sbom.sh [image] [output-directory]
#
# The scanner is pinned by tag and digest for reproducibility. Override only
# deliberately, for example:
#   SYFT_IMAGE=anchore/syft:vX.Y.Z@sha256:... scripts/generate_core_sbom.sh

IMAGE="${1:-smeme:local}"
OUTPUT_DIR="${2:-build/sbom}"
SYFT_IMAGE="${SYFT_IMAGE:-anchore/syft:v1.48.0@sha256:b4f1df79f97b817682d8b5ff941eb6bfe74f6172553a5e312c75bbc2eabc405c}"
SBOM_BASENAME="${SBOM_BASENAME:-smeme}"

if [[ "${OUTPUT_DIR}" != /* ]]; then
  OUTPUT_DIR="${PWD}/${OUTPUT_DIR}"
fi

docker image inspect "${IMAGE}" >/dev/null
mkdir -p "${OUTPUT_DIR}"

docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "${OUTPUT_DIR}:/out" \
  "${SYFT_IMAGE}" \
  "${IMAGE}" \
  --scope all-layers \
  -o "cyclonedx-json=/out/${SBOM_BASENAME}.cdx.json" \
  -o "spdx-json=/out/${SBOM_BASENAME}.spdx.json"

{
  printf 'image=%s\n' "${IMAGE}"
  printf 'image_id=%s\n' "$(docker image inspect "${IMAGE}" --format '{{.Id}}')"
  printf 'repo_digests=%s\n' "$(docker image inspect "${IMAGE}" --format '{{json .RepoDigests}}')"
  printf 'generator=%s\n' "${SYFT_IMAGE}"
} >"${OUTPUT_DIR}/${SBOM_BASENAME}.source.txt"

printf 'Wrote %s, %s, and source metadata to %s\n' \
  "${SBOM_BASENAME}.cdx.json" \
  "${SBOM_BASENAME}.spdx.json" \
  "${OUTPUT_DIR}"
