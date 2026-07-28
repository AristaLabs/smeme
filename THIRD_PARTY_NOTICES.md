# Third-party notices

SMEme incorporates open-source and other third-party components. Those components remain under their original licenses; the SMEme Sustainable Use License applies only to SMEme-authored Core software (see [`LICENSE.md`](LICENSE.md)).

The Core appliance embeds under `/app/legal/`:

| Path | Contents |
|------|----------|
| `LICENSE.md` | SMEme Sustainable Use License 1.0 |
| `THIRD_PARTY_NOTICES.md` | This file |
| `SOURCE_OFFER.md` | Corresponding-source written offer |
| `third_party/` | Curated notices for metadata gaps/conflicts |
| `python/` | License files harvested from the image virtualenv at build time |
| `debian-packages.txt` | `dpkg` package list |
| `debian-copyright-index.txt` | Paths to `/usr/share/doc/*/copyright` |

## Generate release evidence

```bash
docker build -f Dockerfile.core -t smeme:local .
scripts/prepare_core_release_evidence.sh smeme:local build/release-evidence
```

That runs:

- `scripts/generate_core_sbom.sh` → CycloneDX + SPDX (Syft all-layer, pinned digest)
- `scripts/bundle_core_notices.sh` → legal bundle bound to the scanned image id

`build/` is gitignored. Publish CI generates this pack from the **exact GHCR
digest**, signs SLSA provenance + CycloneDX SBOM with GitHub OIDC
(`actions/attest`), and for `v*.*.*` tags attaches SBOM/checksums to the GitHub
Release (durable retention for the source-offer period). Workflow artifacts are
a 90-day convenience copy only. Treat SBOMs as an **inventory aid**, not a
substitute for the embedded notices and source offer.

### Current pre-release baseline (2026-07-20)

- Base: `python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91`
- Generator: Syft 1.48.0 (container pinned by digest in `scripts/generate_core_sbom.sh`)
- Core boundary check: Stripe, SendGrid, and pytest packages are absent
- Rebuild + `prepare_core_release_evidence.sh` after notice-bundle changes; the GHCR digest pack is authoritative for a release

## Redistribution obligations (containers)

Publishing `ghcr.io/AristaLabs/smeme` redistributes:

1. **SMEme Core** under [`LICENSE.md`](LICENSE.md) (SMEme Sustainable Use License 1.0).
2. **Python packages** under their upstream licenses (see `/app/legal/python/` + table below).
3. **Debian packages** from the pinned base plus `curl`, `libstdc++6`, and `libgomp1`. Copyright files under `/usr/share/doc/*/copyright` remain in the image; see `debian-copyright-index.txt`.
4. **Copyleft / LGPL components** — covered by the written offer in [`legal/SOURCE_OFFER.md`](legal/SOURCE_OFFER.md). Retain the release-evidence pack (SBOM + legal bundle + digest) for the offer period.

Publish CI attests each Core digest with GitHub OIDC (SLSA provenance + CycloneDX SBOM). Verify with [`scripts/verify_core_image_attestation.sh`](scripts/verify_core_image_attestation.sh) or the commands in `build/release-evidence/COSIGN.md`. Durable stores are the GitHub Attestations API and (for release tags) GitHub Release assets — not the 90-day workflow artifact alone.

## Direct Python dependencies

| Component | Version in baseline | License |
|-----------|---------------------|---------|
| aiocache | 0.12.3 | BSD-3-Clause |
| Alembic | 1.16.5 | MIT |
| asyncpg | 0.30.0 | Apache-2.0 |
| Clerk Backend API | 5.0.6 | MIT |
| FastAPI | 0.118.0 | MIT |
| FastAPI Users | 14.0.1 | MIT |
| FastAPI Users DB SQLModel | 0.3.0 | MIT |
| HTTPX | 0.28.1 | BSD-3-Clause |
| Jinja2 | 3.1.6 | BSD-3-Clause |
| LangGraph | 0.6.8 | MIT |
| LangGraph Checkpoint Postgres | 2.0.24 | MIT |
| MCP Python SDK | 1.26.0 | MIT |
| OpenAI Python SDK | 2.3.0 | Apache-2.0 |
| Passlib | 1.7.4 | BSD |
| Psycopg | 3.2.10 | LGPL-3.0 |
| Pydantic | 2.11.10 | MIT |
| Pydantic Settings | 2.11.0 | MIT |
| PyJWT | 2.10.1 | MIT |
| pypdf | 6.8.0 | BSD-3-Clause |
| python-docx | 1.2.0 | MIT |
| python-jose | 3.5.0 | MIT |
| python-multipart | 0.0.20 | Apache-2.0 |
| SlowAPI | 0.1.9 | MIT |
| SQLModel | 0.0.25 | MIT |
| Svix | 1.89.0 | MIT |
| Tavily Python | 0.7.13 | MIT |
| Uvicorn | 0.37.0 | BSD-3-Clause |
| Z3 Solver | 4.16.0.0 | MIT (Microsoft) |

Versions above document the current pre-release image only. The per-tag SBOM records all direct, transitive, and operating-system components.

## Known metadata gaps and conflicts

Syft did not emit a license for these installed Python distributions. Their package classifiers or upstream license files identify:

- MIT: `annotated-types`, `clerk-backend-api`, `fastapi`, `fastapi-users`, `fastapi-users-db-sqlalchemy`, `fastapi-users-db-sqlmodel`, `pwdlib`, `sqlmodel`, `tavily-python`
- BSD-3-Clause: `Jinja2`
- Apache-2.0 **OR** BSD-2-Clause: `packaging`

**standardwebhooks 1.0.1:** PyPI metadata declares MIT; upstream git tag `v1.0.1` is Apache-2.0. **Resolution for redistribution:** ship and rely on the upstream Apache-2.0 text in [`legal/third_party/standardwebhooks-1.0.1-Apache-2.0.txt`](legal/third_party/standardwebhooks-1.0.1-Apache-2.0.txt) until the publisher aligns metadata.

**Z3:** Wheel omits embedded `LICENSE.txt`. Microsoft MIT text is shipped at [`legal/third_party/z3-solver-4.16.0.0-MIT.txt`](legal/third_party/z3-solver-4.16.0.0-MIT.txt).

**psycopg-binary:** LGPL-3.0 text shipped at [`legal/third_party/psycopg-binary-3.2.10-LGPL-3.0.txt`](legal/third_party/psycopg-binary-3.2.10-LGPL-3.0.txt). Native libraries inside the wheel remain subject to the LGPL corresponding-source offer.

## Operating-system components

The appliance inherits Debian components from the pinned `python:3.13-slim` digest and installs `curl`, `libstdc++6`, and `libgomp1`. Exact versions are in each image SBOM and `debian-packages.txt`. Do not remove or obscure `/usr/share/doc/*/copyright`.
