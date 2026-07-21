#!/usr/bin/env bash
set -euo pipefail

# Build a release notice/source-evidence pack from a Core image.
#
# Usage:
#   scripts/bundle_core_notices.sh [image] [output-directory]
#
# Writes under the output directory:
#   SOURCE_OFFER.md
#   LICENSE.md
#   THIRD_PARTY_NOTICES.md
#   third_party/          curated overrides
#   python/               harvested from the image venv
#   debian-packages.txt
#   debian-copyright-index.txt
#   image-identity.txt
#   README.md

IMAGE="${1:-smeme:local}"
OUTPUT_DIR="${2:-build/legal-bundle}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${OUTPUT_DIR}" != /* ]]; then
  OUTPUT_DIR="${PWD}/${OUTPUT_DIR}"
fi

docker image inspect "${IMAGE}" >/dev/null
rm -rf "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"

cp "${ROOT}/LICENSE.md" "${OUTPUT_DIR}/LICENSE.md"
cp "${ROOT}/THIRD_PARTY_NOTICES.md" "${OUTPUT_DIR}/THIRD_PARTY_NOTICES.md"
cp "${ROOT}/legal/SOURCE_OFFER.md" "${OUTPUT_DIR}/SOURCE_OFFER.md"
cp -R "${ROOT}/legal/third_party" "${OUTPUT_DIR}/third_party"

{
  printf 'image=%s\n' "${IMAGE}"
  printf 'image_id=%s\n' "$(docker image inspect "${IMAGE}" --format '{{.Id}}')"
  printf 'repo_digests=%s\n' "$(docker image inspect "${IMAGE}" --format '{{json .RepoDigests}}')"
  printf 'created=%s\n' "$(docker image inspect "${IMAGE}" --format '{{.Created}}')"
} >"${OUTPUT_DIR}/image-identity.txt"

# Extract the notice tree already embedded in the image (preferred), falling
# back to harvesting the image venv if an older image lacks /app/legal/python.
cid="$(docker create "${IMAGE}")"
cleanup() { docker rm -f "${cid}" >/dev/null 2>&1 || true; }
trap cleanup EXIT

if docker cp "${cid}:/app/legal/python" "${OUTPUT_DIR}/python" 2>/dev/null; then
  :
else
  mkdir -p "${OUTPUT_DIR}/_venv"
  docker cp "${cid}:/app/.venv" "${OUTPUT_DIR}/_venv/venv"
  python3 "${ROOT}/scripts/collect_python_licenses.py" \
    "${OUTPUT_DIR}/_venv/venv" \
    "${OUTPUT_DIR}/python"
  rm -rf "${OUTPUT_DIR}/_venv"
fi

docker cp "${cid}:/app/legal/debian-packages.txt" "${OUTPUT_DIR}/debian-packages.txt" 2>/dev/null \
  || docker run --rm --entrypoint "" "${IMAGE}" \
       dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' \
       >"${OUTPUT_DIR}/debian-packages.txt"

docker cp "${cid}:/app/legal/debian-copyright-index.txt" \
  "${OUTPUT_DIR}/debian-copyright-index.txt" 2>/dev/null \
  || docker run --rm --entrypoint "" "${IMAGE}" \
       sh -c 'find /usr/share/doc -name copyright | sort' \
       >"${OUTPUT_DIR}/debian-copyright-index.txt"

cat >"${OUTPUT_DIR}/README.md" <<EOF
# SMEme Core legal bundle

Generated from \`${IMAGE}\`.

Contents:

- \`LICENSE.md\` — SMEme Sustainable Use License (SMEme Core)
- \`THIRD_PARTY_NOTICES.md\` — curated inventory and redistribution notes
- \`SOURCE_OFFER.md\` — corresponding-source written offer
- \`third_party/\` — curated notices for metadata gaps/conflicts
- \`python/\` — license files harvested from the image virtualenv
- \`debian-packages.txt\` / \`debian-copyright-index.txt\` — OS package inventory
- \`image-identity.txt\` — image id / digests for this pack

Publish this directory beside the immutable GHCR digest for each release tag.
EOF

printf 'Wrote legal bundle to %s\n' "${OUTPUT_DIR}"
