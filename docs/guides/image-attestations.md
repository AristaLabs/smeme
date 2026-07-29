# Core image attestations (SBOM + SLSA)

Publish jobs in [`.github/workflows/ci-core.yml`](../../.github/workflows/ci-core.yml)
sign every pushed Core digest with GitHub OIDC via `actions/attest`:

| Attestation | Predicate type |
|-------------|----------------|
| SLSA build provenance | `https://slsa.dev/provenance/v1` |
| CycloneDX SBOM (Syft all-layer) | `https://cyclonedx.org/bom` |

Buildx `provenance` / `sbom` stay off because empty BuildKit attestation blobs
previously 403'd on GHCR. Evidence is generated from the **exact published
digest** after push.

## Durable retention

| Store | Lifetime |
|-------|----------|
| GitHub Attestations API | Bound to the repository / digest |
| GitHub Release assets (`v*.*.*` tags) | Retained for the [source-offer](../../legal/SOURCE_OFFER.md) period |
| Workflow `upload-artifact` pack | 90 days (convenience only) |

Release tags attach SBOM + `EVIDENCE.txt` + `COSIGN.md` + `SHA256SUMS.txt`.
`SHA256SUMS.txt` is generated **after** those durable files are finalized and
lists only Release assets (not workflow-only paths such as `legal-bundle/`).
Download all Release assets into one directory, then verify with
`sha256sum -c SHA256SUMS.txt`. Manifest entries use asset basenames because
GitHub flattens uploaded source paths.

## Verify

```bash
scripts/verify_core_image_attestation.sh sha256:<digest>
# or
gh attestation verify \
  oci://ghcr.io/aristalabs/smeme@sha256:<digest> \
  --repo AristaLabs/smeme \
  --predicate-type https://slsa.dev/provenance/v1
```

Cloud must verify Core attestations before digest-pinning (see Cloud
`scripts/verify_core_attestation.sh`).
