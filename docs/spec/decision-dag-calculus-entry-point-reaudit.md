# Decision-DAG calculus — entry-point re-audit

**Spec:** [`decision-dag-calculus.md`](./decision-dag-calculus.md)  
**Core `main` tip at audit:** includes `C4` = `6ff0d455ec824ab553a649351467d8fb369f4bf5`  
**Rule:** Appendix B.1 — test evidence must exercise the path a caller actually reaches. Helper-only coverage is labeled as such and does not discharge a public/Deploy obligation.  
**Refresh:** After Part I / Appendix B changes, rewrite affected rows before cutting a theory citation tag — [maintenance discipline](../guides/decision-dag-calculus-maintenance.md).

**Verdict:** All Part I executable rows pass under B.1. No private Cloud paths or `docs/planning` cites in the spec. Naming revision (v1.1) does not change executable obligations. Ready for **public specification** status.

| Part I | Public / Deploy entry point | Evidence path (B.1) | Result |
|---|---|---|---|
| §§1–3, §4.2 | IR compile + `validate_ir` before solve (MCP/Deploy load compiled artifact; authoring → IR) | `validate_ir` / `compile_dt_graph_to_ir`; unit suites `test_dt_graph_to_ir`, `test_validate_ir` | Pass |
| §4.1 | `validate_graph` (authoring / publication stack calls it) | Exact-message tests in `test_graph_entry_validation.py` (`C4`) | Pass |
| §§5–6 | `compile_ir_to_z3` + `guards_radio` on evaluate / analysis paths | `test_compile_to_z3.py`; `test_i_guarded_exactly_one_only_applies_when_question_reachable` | Pass |
| §7 | MCP evaluate ingest → `validate_raw_answers_for_ir` → `raw_answers_to_canonical_facts` → projection; assumptions via tool params | Goldens + `test_assumptions.py`; remapping is Stage A on that path | Pass |
| §8 | `entails_target` / `possible_target` / evaluate consistency via MCP how-to-reach and evaluate | `test_vacuous_premise_gate.py` (A-φ, A-E, A-attrib, operational, …) | Pass |
| §9 | `decisive_support` + repair via MCP tools | Lit invariant + repair force-kill + Probe 4 tests | Pass |
| §10 | MCP: `smeme_reasoning_evaluate`, `_what_if`, `_how_to_reach`, `_decisive_support`, `_edit_affects_path` | Tool registration in `reasoning_fastmcp.py`; Compare always-delta test (`C4`); alternate-model in `evaluate.py` | Pass |
| §10.2 consumer guidance | N/A (explicitly not enforced) | Marked consumer guidance in spec; not a B.1 obligation | Pass (scope) |
| §11 | Deploy: `assess_publish_readiness_sync` | `test_theory_unsat_blocks_deploy_*`, `test_dead_conclusion_blocks_deploy_*` (`C4`); publication-boundary trust (no query identity lookup) matches code | Pass |
| §11 identity helpers | Not a Part I query obligation (§13.7) | Helper-only tests correctly excluded from query-path discharge | Pass (demoted) |
| §12 | Scope + publication boundary + unencoded preconditions | Spec prose; Deploy/source validation entry points as above | Pass |

**Post-audit note (MCP Apply rename):** the shipped Apply public surface is now `smeme_reasoning_evaluate_answers`; chat `smeme_reasoning_evaluate` is guided Inquire gather. This historical table is not a fresh B.1 reaudit.

**Link scrub:** no `docs/planning`, no Cloud-only audit URLs, no amendment paths in the spec file.

**Not re-audited as Part I:** §13 targets; §14 informative release-history; Appendix A non-obligations.
