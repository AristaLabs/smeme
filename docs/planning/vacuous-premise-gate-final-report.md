# Vacuous-premise consistency gate — final Core report

**Date:** 2026-08-04  
**Scope:** Core runtime, tests, contracts, and Cloud amendment reconciliation  
**Branch base:** `5e4a592` (`v0.9.10` lineage)

## Findings

1. **Vacuous entailment.** Spec incompleteness in classical consequence
   (`ALGEBRA.md` §17) lacked a consistency condition, so `entails_target`
   could report `entailed` for inconsistent premises.
2. **Possibility collapsing inconsistency into impossibility.**
   `possible_target` mapped inconsistent premises to `impossible`, a
   confident false negative not required by classical Possible.
3. **Evidence inconsistency misattributed to assumptions.** Nonempty φ was
   used to choose the assumptions cause even when admitted evidence was
   already inconsistent (`UNSAT(T ∧ E)` labeled `assumptions_inconsistent`).

These are soundness/correctness findings; this report deliberately does not
use “security” terminology.

## Implemented behavior

- `entails_target` and `possible_target` are witness-first over the exact
  `B = T ∧ E ∧ φ`. A SAT witness returns `not_entailed` or `possible` and
  proves consistency for that exact base. An UNSAT query is disambiguated
  before `entailed` or `impossible` is reported.
- The E-then-φ cause ladder reports the first failing admitted prefix:
  `answers_inconsistent` for `T ∧ E`, `assumptions_inconsistent` for
  `T ∧ E ∧ φ`. Pre-admission source and assumption conflicts remain outside
  the ladder.
- Decisive support keeps inherited consistency only under the always-on
  `Lit(S) ⊆ Lit(E)` invariant. Violations raise loudly.
- Repair uses independent witness-first bases. Possible-mode acceptance may
  take one call; entailment-mode acceptance requires consistency
  disambiguation after `UNSAT(B' ∧ ¬q)`. Inconsistent candidates are excluded
  from `plans[]`.
- Successful Deploy plus the D025 identity triple
  `(artifact_hash, IR format version, compiler/semantics version)` remains the
  `SAT(T)` record. A partial or mismatched identity refuses stale trust; no
  ceremony table was added.
- Guarded radio ExactlyOne remains
  `Implies(reach(q), PbEq(...))`. Incomplete evidence remains legitimate.
  Budget precedes solver calls; timeout/unknown are operational outcomes, not
  cached logical results.

## Evidence and tests

The pre-edit audit and red-before-green evidence are in
`docs/planning/vacuous-premise-gate-pre-edit-audit.md`. Regression coverage is
in `tests/unit/reasoning/runtime/test_vacuous_premise_gate.py`:
A-φ, A-E, A-attrib, E, F, J, Collapse-φ, Collapse-E, possible one-call,
guarded ExactlyOne, operational budget precedence, Deploy identity mismatch,
decisive Lit invariant failure, and repair force-kill.

Focused reasoning coverage for this change is green. No golden was updated.

### Full-suite baseline vs final (placeholder-database environment)

Both runs used Python **3.13.5**, the same dependency lock via `uv sync --extra
dev`, identical secrets (`SECRET_KEY`, `JWT_SECRET_KEY`, placeholder
`OPENAI_API_KEY`), and

`DATABASE_URL=postgresql+asyncpg://smeme:smeme@localhost:5432/smeme_ci`.

| Run | Tree | Aggregate |
|-----|------|-----------|
| Baseline | isolated worktree at `5e4a592` | 11 failed, 827 passed, 2 skipped, 5 errors |
| Final | dirty working tree on `fix/vacuous-premise-consistency-gate` | 11 failed, 842 passed, 2 skipped, 5 errors |

The **+15 passed** delta is new vacuous-premise coverage on the final tree; those
tests are not in the blocked set.

**Identical blocked set** (exact pytest node IDs):

Failed:

- `tests/integration/test_reasoning_publish_transaction.py::test_publish_happy_path_persists_contract_and_hash`
- `tests/integration/test_reasoning_publish_transaction.py::test_publish_idempotent_redeploy_same_version`
- `tests/integration/test_reasoning_publish_transaction.py::test_publish_contract_validates_and_round_trips`
- `tests/integration/test_reasoning_publish_transaction.py::test_publish_persists_research_corpus_hash_when_corpus_saved`
- `tests/integration/test_reasoning_publish_transaction.py::test_publish_commit_failure_no_durable_publish`
- `tests/unit/mcp/test_authoring_graph_tools.py::TestAuthoringUpdateDraftTool::test_update_deployed_becomes_stale_without_touching_artifact`
- `tests/unit/test_editor_publish_share.py::test_publish_sets_reasoning_status_compiled`
- `tests/unit/test_editor_publish_share.py::test_publish_redirects_to_dashboard_when_return_next_dashboard`
- `tests/unit/test_editor_publish_share.py::test_publish_redirects_to_editor_success_when_no_return_next`
- `tests/unit/test_editor_publish_share.py::test_publish_redirects_to_tools_tab_when_return_next_tools`
- `tests/unit/test_editor_publish_share.py::test_publish_allows_free_user`

Errors:

- `tests/unit/decision_tree/test_workflow_delete.py::test_dashboard_shows_delete_ui_by_default`
- `tests/unit/decision_tree/test_workflow_delete.py::test_delete_wrong_phrase_returns_400`
- `tests/unit/decision_tree/test_workflow_delete.py::test_delete_non_author_returns_403`
- `tests/unit/decision_tree/test_workflow_delete.py::test_delete_non_current_version_returns_400`
- `tests/unit/decision_tree/test_workflow_delete.py::test_delete_removes_entire_family_and_related_rows`

**Root cause (all 16, both runs):** local Postgres schema drift —
`NotNullViolationError` on
`reasoning_compiled_artifacts.cevi_legal_validation_status` while Core at
`5e4a592` no longer writes that column. These are database-dependent paths.

**Classification:** identical blocked set → local environment parity
established for this change. Database-dependent paths did not execute
successfully in either run and remain unverified locally; configured Postgres
CI is required before merge.

> The final working tree matches the baseline under the same
> placeholder-database environment. Database-dependent paths did not execute
> successfully in either run and remain unverified locally; configured
> Postgres CI is required before merge.

## Performance

`docs/planning/vacuous-premise-gate-perf-notes.md` records 20-run local
measurements: affirmative possible 1 call / 0.340 ms mean, not entailed 1 /
0.293 ms, entailed 2 / 0.369 ms, and impossible 2 / 0.353 ms.

## Reconciliation and release

The Cloud amendment draft
`docs/algebra/ALGEBRA-AMD-2026-08-consistency-v1.md` now has Actual behavior
and Match? values for witness-first queries, repair mode split, attribution,
ladder staging, Deploy identity, guarded ExactlyOne, operational precedence,
and repair force-kill. All listed normative claims match merged Core.

Final contract/release artifacts include:

- `docs/guides/engine-promises.md`
- `smeme/reasoning/evaluate_semantics.md`
- `agent-skills/smeme-reasoning/SKILL.md`
- `agent-skills/smeme-reasoning-outcomes/SKILL.md`
- generated MCP guidance and capabilities at 3.5.0
- `docs/planning/vacuous-premise-gate-release-note-draft.md`

The release note names all three findings (vacuous entailment; possibility
collapsing inconsistency into impossibility; evidence inconsistency
misattributed to assumptions) and describes this as a correctness/soundness
fix. Version and digest exposure remain release-time verification items.

## Parked and acceptance gates

Option-feasibility plus determinacy remain parked for a separate project.
The pre-edit audit, red-before-green tests, focused suite, reconciliation
matrix, no-golden-drift comparison, and baseline/final blocked-set parity are
complete. Real CI on the PR is the merge gate for database-dependent paths.
The ALGEBRA amendment publish remains an external human gate requiring an
immutable commit/tag permalink and SHA-256; it blocks only the annex, not Core
completion.
