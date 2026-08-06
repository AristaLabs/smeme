# Decision-DAG algebra — maintenance discipline

**Audience:** Core maintainers changing reasoning, Deploy, or MCP evaluate surfaces.

**Canonical artifacts** (public Core only):

| Artifact | Path |
|----------|------|
| Normative theory | [`docs/spec/decision-dag-algebra.md`](../spec/decision-dag-algebra.md) |
| Entry-point re-audit (Appendix B.1) | [`docs/spec/decision-dag-algebra-entry-point-reaudit.md`](../spec/decision-dag-algebra-entry-point-reaudit.md) |

Cite the theory at an **immutable Git tag or commit**, never floating `main`. Record path / tag / commit / content SHA-256 **outside** the file (citing work or release notes).

---

## Two pins (do not conflate)

| Pin | What it freezes | Example |
|-----|-----------------|---------|
| **Theory citation** | Spec prose + Appendix B baseline as of a commit | annotated tag `decision-dag-algebra-v1.0` → commit SHA |
| **Runtime image** | Code + deps Cloud/self-host run | GHCR digest on `v*.*.*` release (`channel=release`) |

Same commit may carry both. Updating one does not update the other. Image digest pins never rewrite theory URLs; a new theory tag never replaces a digest pin.

See [ARCHITECTURE — GHCR publish tracks](../ARCHITECTURE.md#ghcr-publish-tracks) and [image attestations](image-attestations.md).

---

## When this checklist is mandatory

Run it when a change touches any of:

- Source / IR validation (`validate_graph`, `compile_dt_graph_to_ir`, `validate_ir`)
- Theory compile (`compile_ir_to_z3`, `guards_radio`, reachability encoding)
- Evidence / assumptions ingest (`raw_answers`, fact projection, assumption admission)
- Query runtime (evaluate, what-if, how-to-reach, decisive support, path-under-edit)
- Deploy readiness (`assess_publish_readiness*`, `THEORY_UNSAT` / `DEAD_CONCLUSION`)
- Public MCP tool contracts for the above
- Tests that Appendix B cites as conformance evidence

**Skip** for pure UI copy, auth/transport, billing, or docs that do not change executable Part I obligations.

If unsure whether Part I still matches the caller path: run the re-audit — do not demote a Part I claim silently.

---

## Maintainer checklist

### 1. Classify the change

| Kind | Spec action |
|------|-------------|
| Behavior already claimed in Part I; code/tests fix a defect | Keep Part I; add/adjust Appendix B evidence (`C*`); refresh re-audit rows |
| New shipped guarantee | Add/extend Part I; add Appendix B row + B.1 entry-point evidence |
| Intentionally not shipping yet | Part II only — **no** Appendix B row that pretends it ships |
| Removes or weakens a Part I guarantee | Treat as a **theory revision** (see §3), not a quiet edit |

### 2. Evidence rule (Appendix B.1)

Test evidence must exercise the **path a caller actually reaches** (MCP tool, Deploy gate, authoring validation stack). Helper-only unit tests do **not** discharge a public/Deploy obligation — label them helper-only in Appendix B / the re-audit.

### 3. Update the artifacts on the same PR when practical

1. Edit `docs/spec/decision-dag-algebra.md` (Part I / II / Appendix B as required).
2. Rewrite or extend `docs/spec/decision-dag-algebra-entry-point-reaudit.md` for every affected Part I row.
3. Land tests that the new Appendix B rows cite **before** or **with** the doc update.
4. Merge to `main` (staging image builds from that commit; that is not a theory citation).

### 4. Theory citation tag (when publishing a citeable revision)

Use when external cites, GTM, or conformance claims must freeze a new public theory snapshot (not for every bugfix).

```bash
# After the revision is on main:
git tag -a decision-dag-algebra-vX.Y <merge-commit-sha> -m "Decision-DAG algebra vX.Y"
git push origin decision-dag-algebra-vX.Y
```

External record (example):

```text
path:     docs/spec/decision-dag-algebra.md
tag:      decision-dag-algebra-vX.Y
commit:   <full sha>
SHA-256:  <shasum -a 256 docs/spec/decision-dag-algebra.md at that commit>
```

Bump the document **Version** metadata when cutting a new theory tag. Do **not** rename the file for versioning.

Theory tags (`decision-dag-algebra-v*`) are **orthogonal** to Core release tags (`v*.*.*`). Cutting `v*.*.*` for an image does not create a theory pin; cutting a theory tag does not publish a release image.

### 5. Before a Core `v*.*.*` release that includes reasoning changes

- [ ] Part I + Appendix B match the release tip (or an ancestor that still holds).
- [ ] Entry-point re-audit current for that tip.
- [ ] If public cites must move with this release, cut/update `decision-dag-algebra-v*` on the intended commit **before** or **with** the release cut.
- [ ] Cloud production pin uses the **release** digest ([Cloud production runbook](https://github.com/AristaLabs/smeme-cloud) — operators: Phase 3.1a Core pin).

---

## Anti-patterns

| Do not | Why |
|--------|-----|
| Cite `…/blob/main/docs/spec/decision-dag-algebra.md` in papers, GTM, or contracts | `main` moves |
| Put Cloud-only drafts or amendment archaeology in Core | Public Core is the only theory home |
| Claim Part I from helper-only tests | Fails B.1 |
| Quietly move a broken Part I claim into Part II | Status is by location; demotion needs an explicit revision |
| Treat image digest as the algebra citation | Different pin |

---

## Related

- [Engine promises](engine-promises.md) — product-facing Deploy/evaluate guarantees
- [Image attestations](image-attestations.md) — verify release digests
- [Contributing](../../CONTRIBUTING.md) — PR / local checks
