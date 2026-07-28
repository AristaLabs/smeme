# Corresponding-source offer (SMEme Core container)

Arista Labs, LLC redistributes the SMEme Core appliance image together with
third-party components whose licenses may require availability of corresponding
source (including Debian GPL/LGPL packages inherited from the base image and
LGPL components such as Psycopg).

## Written offer

For as long as Arista Labs offers the relevant SMEme Core image for download, and
for at least three (3) years after the last date on which that exact image digest
was distributed by Arista Labs, Arista Labs will, on written request, provide the
corresponding source for GPL/LGPL (and similarly obligated) object code included
in that image, on a medium customarily used for software interchange, at no more
than Arista Labs’ reasonable cost of physically performing source distribution
(or free of charge via electronic transfer when that is the ordinary method).

## How to request

Email **contact@aristalabs.ai** with subject line:

`SMEme Core corresponding source request`

Include:

1. The **image reference** and **digest** (for example
   `ghcr.io/AristaLabs/smeme:vX.Y.Z@sha256:…`).
2. The **component(s)** you need source for, if known (or “all GPL/LGPL
   components in this image”).
3. A contact address for delivery.

## What we retain per public release

For each immutable public Core tag, Arista Labs retains:

- The image digest and multi-arch manifests
- CycloneDX + SPDX SBOMs generated with all-layer scope
- GitHub OIDC–signed SLSA provenance and SBOM attestations for that digest
  (GitHub Attestations API; also attached as OCI referrers when registry push
  succeeds)
- GitHub Release assets for the matching `vMAJOR.MINOR.PATCH` tag (SBOM +
  `SHA256SUMS.txt` + evidence metadata) for the offer period
- The `/app/legal/` notice bundle embedded in the image
- This source offer
- Build inputs needed to reconstruct Debian package source for the pinned base
  digest and installed packages listed in `debian-packages.txt`

Debian package source is ordinarily obtained from the Debian project mirrors for
the exact package versions recorded in the image. Python package source is
ordinarily obtained from the locked upstream sdist/wheel URLs in `uv.lock` and
the curated notices under `legal/third_party/`.

## Scope note

This offer covers **third-party** copyleft obligations for redistributed object
code in the Core image. SMEme-authored Core software is licensed separately under
the SMEme Sustainable Use License 1.0 (`LICENSE.md` in the repository root and in this
image under `/app/legal/LICENSE.md`). This document is not legal advice. Arista Labs
ships it as an engineering best-effort corresponding-source offer for Core image
redistribution.
