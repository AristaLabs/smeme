# Curated third-party notices

These files supplement licenses missing from or conflicting in installed
distribution metadata. They ship in the Core image under `/app/legal/third_party/`.

| File | Component | Why curated |
|------|-----------|-------------|
| `z3-solver-4.16.0.0-MIT.txt` | Microsoft Z3 | Wheel omits embedded LICENSE.txt; upstream MIT text required |
| `standardwebhooks-1.0.1-Apache-2.0.txt` | standardwebhooks (via Svix) | PyPI metadata says MIT; upstream tag `v1.0.1` is Apache-2.0 — **we ship Apache-2.0** |
| `psycopg-binary-3.2.10-LGPL-3.0.txt` | psycopg-binary | LGPL-3.0 native wheel; keep explicit text beside Debian copyrights |

Refresh these files when the locked versions change. The harvest under
`/app/legal/python/` is generated at image build time from installed
`*.dist-info` license files.
