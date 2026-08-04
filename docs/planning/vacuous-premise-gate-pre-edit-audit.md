# Pre-edit audit — vacuous premise consistency gate

**Saved before any production edit.** Final report reconciles against this artifact.

- **Core HEAD:** `5e4a59218006ada2d684a92a7e6d8ab9a0bac681`
- **Tag:** `v0.9.10`
- **Date:** 2026-08-04
- **Policy parent:** `vacuous_entailment_hardening_18c5cada`
- **Core slice:** `vacuous_gate_core_slice_4f9b8ae4`

## SoT paths

| Role | Path |
|------|------|
| Entail / possible oracles | `smeme/reasoning/runtime/counterfactual.py` |
| Evaluate UNSAT attribution | `smeme/reasoning/runtime/evaluate.py` |
| Product result_kind | `smeme/reasoning/runtime/report_builder.py` |
| Decisive support | `smeme/reasoning/runtime/decisive_support.py` |
| Path under edit | `smeme/reasoning/runtime/path_under_edit.py` |
| Assumptions (φ) | `smeme/reasoning/runtime/assumptions.py` |
| Publish SAT(T) | `smeme/reasoning/publish_readiness.py`, `smeme/reasoning/runtime/analyze.py` |
| Deploy identity | `smeme/reasoning/artifact_identity.py`, `ReasoningCompiledArtifact` |
| Guarded ExactlyOne | `smeme/reasoning/theory/guards_radio.py` |

## Pytest targets (pre-fix)

```text
pytest tests/unit/reasoning/runtime/test_counterfactual.py \
       tests/unit/reasoning/runtime/test_decisive_support.py \
       tests/unit/reasoning/runtime/test_assumptions.py \
       tests/unit/reasoning/runtime/test_path_under_edit.py \
       tests/unit/reasoning/runtime/test_vacuous_premise_gate.py -q
```

## Three labeled defects

| Surface | Failure today | Layer | Direction |
|---------|---------------|-------|-----------|
| `entails_target` | yes ∀ targets when UNSAT \(B_\varphi\) | inherits incomplete classical `⊨` | vacuous false positive |
| `possible_target` | no ∀ targets when UNSAT \(B_\varphi\) | implementation collapse | confident false negative |
| `evaluate` / `_result_kind` | nonempty \(\varphi\) + UNSAT \(B_E\) → `assumptions_inconsistent` | coarse blame (`assumptions_unsat` if φ nonempty) | misattributed cause |

A-attrib is a **first-class** defect (wrong cause, not wrong status). φ is the production trigger, so this path is likely the most frequently exercised of the three.

## Spec corrections applied during implementation

- **CHANGE 1 / INTERRUPT 2:** witness-first for both helpers. `Cons(B)` is semantic, not a mandatory preliminary call. Affirmative `possible` ⇒ one call. Affirmative `not_entailed` ⇒ one call (countermodel). `entailed` / `impossible` require disambiguation after UNSAT.
- **Repair qualification:** one-call acceptance is **possible-mode only**. Entailment-mode accepted candidates still require `SAT(B')` after `UNSAT(B'∧¬q)`.
- **CHANGE 2:** status-code staging — ladder only on admitted E/φ; `sources_conflict` / `conflicting_assumptions` are pre-admission.

## Reconciliation matrix (in progress)

| Amendment claim | Normative or target | Core function/test | Actual behavior | Match? |
|---|---|---|---|---|
| Witness-first entailment | Normative | `entails_target` / A-φ | query `SAT(B∧¬q)` first; disambiguate on UNSAT | yes |
| Witness-first possibility | Normative | `possible_target` / A-φ, Test E | query `SAT(B∧q)` first; disambiguate on UNSAT | yes |
| Possible affirmative = 1 call | Normative | `test_possible_affirmative_one_solver_call` | `sat_calls==1` | yes |
| Entailment-mode repair ≠ always 1 call | Normative | `find_repairs` → `entails_target` | uses witness-first entailment (2 calls when accepting) | yes |
| Possible-mode repair accept = 1 call | Normative | `find_repairs` → `possible_target` | affirmative path one call | yes |
| Lit(S)⊆Lit(E) always-on | Normative | `assert_literal_subconjunction` | enforced in decisive shrink | yes |
| A-attrib answers cause | Normative | `test_a_attrib_*` | `z3_unsat` → `answers_inconsistent` with nonempty φ | yes |
| Ladder staging | Normative | `evaluate_with_canonical_facts` | E then φ checks | yes |
| Deploy identity triple | Normative | `SatValidationRecord` | helpers present; publish still uses existing SAT(T) | partial |
| Guarded ExactlyOne | Normative | `guards_radio` | preserved (no change) | yes |

Do not relabel a failed normative match as target behavior after implementation.

## Golden drift (assertion reorder)

Callers previously asserted φ before E; gate/helpers push E then φ. Compatibility check on 2026-08-04 after implementation:

- `test_evaluate_raw_answers_goldens.py` — **no golden shifts**
- `test_counterfactual.py`, `test_assumptions.py`, `test_decisive_support.py`, `test_path_under_edit.py` — **pass without golden updates**

If a future golden shifts, report it as a compatibility finding; do not silently update.

## Consequence-path inventory (pre-edit)

| Path | Calls oracle? | Consistency gate today? |
|------|---------------|-------------------------|
| `entails_target` | is the oracle | No — UNSAT(¬reach) → yes |
| `possible_target` | is the oracle | No — not SAT(reach) → no |
| `find_repairs_for_target` phase0 + per-plan | `_target_gate` → oracles | No |
| `find_minimal_decisive_supports` | `entails_target` | No |
| `run_edit_affects_path` | `entails_target` | No |
| `run_what_if` | evaluate sides | Evaluate UNSAT only; coarse attribution |
| `evaluate_with_canonical_facts` | direct `solver.check()` | Maps UNSAT → result_kind; **misattributes** when φ nonempty |

## Assertion order today

Callers: `compile_ir_to_z3` → `apply_assumptions_to_solver` (φ) → assert E in oracle push → query.
Target gate: establish SAT(T) → push E → push φ → query.
