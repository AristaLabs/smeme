# Post-merge reconciliation probes — coverage audit (`4fd308e`)

**Date:** 2026-08-04  
**Core commit:** `4fd308e` (PR #66 merge)  
**Rule:** permanent tests only where coverage was missing; no temporary probe scripts.

## Probe 1 — unpublished / in-memory `SAT(T)` hatch

**Claim:** Unpublished/in-memory IR performs request-local `SAT(T)` validation;
any cached result dies with the request and cannot become persistent artifact
trust without the D025 identity triple.

| Status | Evidence |
|--------|----------|
| Partial before | `test_deploy_identity_mismatch_refuses` — mismatch raises with `in_process_unpublished=False` |
| Missing | hatch → `recompute`; hatch cannot override mismatch; no record/no hatch raises; identity hit → `use_record` |
| Added | `test_unpublished_hatch_recomputes_without_persistent_trust`, `test_hatch_cannot_override_identity_mismatch`, `test_missing_sat_t_without_hatch_or_identity_raises`, `test_identity_hit_uses_deploy_record` |
| Impl | `assert_sat_t_established` in `smeme/reasoning/runtime/consistency_gate.py` |
| Against `4fd308e` | pass (no production change) |

Note: there is no durable in-process cache object; hatch policy returns
`recompute` (never `use_record`) without the identity triple, which is the
trust boundary the claim requires.

## Probe 2 — repair mode asymmetry

**Claim:** Possible-mode SAT acceptance may take one call; entailment-mode
acceptance requires consistency disambiguation after `UNSAT(B′∧¬q)`; rejected
candidates receive an attribution call only when diagnostics request it.

| Status | Evidence |
|--------|----------|
| Partial before | `test_possible_affirmative_one_solver_call` (helper, not repair accept); `test_entailment_repair_force_kills_inconsistent_candidate` (discard inconsistent) |
| Missing | repair possible-mode accept without `entails_target`; repair entailed accept via `entails_target`; no attribution surface on reject |
| Added | `test_possible_mode_repair_accept_does_not_call_entails_target`, `test_entailment_repair_acceptance_requires_entails_target`, `test_rejected_inconsistent_repair_candidate_has_no_attribution_surface` |
| Impl | `find_repairs_for_target` in `smeme/reasoning/runtime/counterfactual.py` |
| Against `4fd308e` | pass (no production change) |

Note: `find_repairs_for_target` has no diagnostics opt-in API at `4fd308e`.
Rejected inconsistent candidates are discarded with empty `plans[]` and no
cause field — attribution is not surfaced unless a future diagnostics path is
added.

## Probe 3 — operational status after UNSAT disambiguation

**Claim:** If the first consequence query returns UNSAT but consistency
disambiguation returns timeout, unknown, or budget exhaustion, the helper
returns that operational status — never `entailed`, `impossible`, or
`inconsistent`.

| Status | Evidence |
|--------|----------|
| Partial before | `test_l_budget_precedes_any_solver_call` — budget before any Cons call on `check_premise_consistency` alone |
| Missing | first-query UNSAT then Cons operational → helper status for both helpers |
| Added | `test_disambiguation_operational_never_logical` (param: timeout/unknown/budget × entails/possible) |
| Impl | `_disambiguate_unsat_query` in `smeme/reasoning/runtime/counterfactual.py` |
| Against `4fd308e` | pass (no production change) |

## Verdict

Follow-up PR **required** for permanent missing coverage only. Production code
on `4fd308e` already matches all three claims; no fix commit.
