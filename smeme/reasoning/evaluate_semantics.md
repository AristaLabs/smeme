# Reasoning evaluate semantics (explainer)

This document fixes the **logical contract** for how user answers interact with the compiled Z3 theory at evaluate time: what \(T(\mathrm{IR})\) asserts, what evidence \(E\) adds, why answers are **not** tied to `reach(q)`, and why MCP callers pass **structured** `raw_answers` rather than free-form canonical facts.

**Audience:** engineers extending `evaluate_reasoning`, MCP tools, or the theory layer.

**Code anchors:** `theory/compile_to_z3.py`, `theory/guards_radio.py`, `runtime/canonical_facts.py`, `cevi/fact_projection.py`, `runtime/input_validation.py`, `runtime/ingest_codes.py`, `runtime/ingest_envelope.py`, `runtime/evaluate.py`, `mcp/reasoning_fastmcp.py`, `mcp/tool_contract.py`.

---

## 1. Two layers: theory vs evidence

Evaluate solves:

```text
SAT( T(IR) ∧ E )
```

| Layer | What it is | When built |
| ----- | ---------- | ---------- |
| **\(T(\mathrm{IR})\)** | Reachability recurrence + guard wiring + radio semantics | `compile_ir_to_z3(ir)` on every evaluate |
| **\(E\)** | Unit literals on option atoms (`ir_radioopt_*`) from user answers | Stage A → Stage B (`raw_answers_to_canonical_facts` → `apply_canonical_facts_to_solver`) |

\(T(\mathrm{IR})\) is **fixed per published artifact**. \(E\) changes per request (session answers, hypotheticals, counterfactuals).

---

## 2. What \(T(\mathrm{IR})\) says (minimal)

### Reachability

Each node `n` has a boolean `reach[n]`. Non-entry nodes satisfy:

```text
reach[n]  ==  ⋁  ( reach[parent] ∧ guard_on_edge )
```

Entry nodes are asserted `reach[entry] = true`. See `compile_to_z3.py`.

### Radio guards

For each radio question `q`:

1. One boolean per option label (`ir_radioopt_{q}_{label}`).
2. **Conditional exactly-one:** `reach[q] → PbEq(options, 1)` — if the question is on the path, exactly one option is true (`guards_radio.py`). `PbEq` = pseudo-Boolean equality in Z3 (weighted sum of literals equals 1).
3. Each **labeled** edge guard is **materially equivalent** to its option atom: `guard == option_atom[expr]`. **Default** guards (`expr == ""`) are asserted **always true** (separate from options).

**Important:** The radio axiom is an **implication**, not a biconditional. When `reach[q]` is false, `reach[q] → PbEq(...)` is **vacuously true** for any assignment to option atoms. The theory does **not** globally assert “at most one option true” or “answered questions must be reachable.”

---

## 3. Design commitments

### 3.1 Assert all **answered** questions into the solver

**Policy:** For every question the caller supplies an answer for, emit unit literals on that question’s option atoms and assert them on the solver. **Do not** pre-filter answers by a simulated “currently reachable” set before Z3.

**Why:**

1. **Hypotheticals / counterfactuals** — Future solver calls may change earlier answers or assumptions. A branch that was dead under one assignment can become live under another. Option literals should remain **stable evidence** in the formula; `reach` is what the graph derives per model.
2. **Single theory, many queries** — The same compiled \(T(\mathrm{IR})\) supports publish preflight (`enumerate_conclusion_sat_queries`), full evaluate, and scoped `push`/`pop` checks without re-ingesting answers differently per scenario.
3. **Dead-branch answers are benign** — See §4.

**What we do not do:** Add axioms such as `option_true → reach(q)` (“if the user answered, the node must be on the path”). That would break valid cases where the payload contains answers for questions on paths cut off by other answers.

### 3.2 MCP / REST: structured answers only

**Policy:** Product evaluate entry points (`smeme_reasoning_evaluate_answers`, opt-in REST evaluate) accept **structured** ingest, not arbitrary canonical-fact lists.

```text
raw_answers_json  →  prepare_evaluate_ingest  →  flat answers map  →  evaluate_reasoning
```

The `answers` map has **at most one value per `question_id`** (JSON object keys). Values are **string or null** per radio question (`validate_raw_answers_for_ir`). A question is **answered** only when the value is a **non-empty** string after strip; missing keys, `null`, and whitespace-only strings are **unanswered** (see §7). Stage A turns each answered string into **exactly one** `value=true` option row (case-insensitive match) with `confidence=EXPLICIT`; non-chosen options for that question are explicit `false`.

**Why force structured ingest:**

| Concern | Structured `raw_answers` | Caller-supplied canonical facts |
| ------- | ------------------------ | -------------------------------- |
| Two options true for same `q` | Prevented by shape (one value per key) + single match | Must be validated explicitly |
| Unknown question ids | Rejected at ingest | Must be validated explicitly |
| Audit / envelope | Provenance envelope (`ingest_envelope.py`) + persistence | Caller-defined |
| Agent ergonomics | One answer per question, matches session UX | Error-prone for connectors |

`evaluate_with_canonical_facts` remains the **internal** tail after Stage A; direct canonical-fact callers (tests) are not the MCP contract.

**Product path only:** **`evaluate_reasoning(raw_answers)`**. There is no blob-evaluate tool or bridge-runtime ingest in this tree.

---

## 4. Dead-branch answers (proof sketch)

**Claim:** If `reach[q] = false` in a model, facts pinned on `q`’s options do not change `reach[t]` for nodes `t` whose **only** incoming paths go through `q`.

For a single edge `q → t`:

```text
reach[t]  ==  reach[q] ∧ guard_{q→t}
```

If `reach[q] = false`, then `false ∧ guard = false` for any `guard`, regardless of option atoms (guards only affect the term via `guard`, which is multiplied by `false`).

Option literals are **not deleted** from \(T(\mathrm{IR}) \land E\); they are **inactive for reach propagation** in that model. If a later hypothetical makes `reach[q] = true`, the same pinned options constrain guards and PbEq.

**DAG caveat:** If `t` has another incoming edge from a reachable predecessor, `t` may still be reachable when `reach[q] = false`.

---

## 5. When conflicts become UNSAT

| Situation | Result |
| --------- | ------ |
| Two `value=true` for same `q` in one **MCP structured** payload | **Prevented at ingest** (one string per `qid`) |
| Non-empty answer string not matching any option label | **`ingest_invalid_answer_option`** (MCP/REST via `prepare_evaluate_ingest`) |
| Two options true for same `q` in caller-built canonical facts | May reach Z3 (tests/internals); MCP structured path prevents this |
| `reach[q] = true` and exactly-one violated (e.g. two options pinned true) | **UNSAT** — PbEq antecedent is active |
| `reach[q] = false` and two options pinned true | PbEq vacuous; **not** a violation of the radio implication (may be unsatisfiable for other reasons) |
| Labeled guard + **default** guard on same question | **Both guards can be true** — default is always true; this is encoding semantics, not duplicate options |

Do **not** rely on Z3 UNSAT alone as ingest validation for “two options true”; unreachable `q` can hide the conflict. MCP structured ingest avoids that for the main path.

### Premise consistency before consequence (vacuous-entailment hardening)

Working bases: \(B_E = T \land E\), \(B_\varphi = T \land E \land \varphi\).
Let \(B = B_\varphi\).

`Cons(B)` is a semantic condition on reporting a consequence, not a requirement to
perform a separate preliminary solver call. A satisfying query witness may
establish consistency of the **exact same** base; an UNSAT query result must be
disambiguated before it is reported as entailment, refutation, or impossibility.

| Query | Witness-first shape |
| ----- | ------------------- |
| Entailment | First \(SAT(B \land \neg q)\): SAT → `not_entailed`; UNSAT → \(SAT(B)\) → `entailed` or ladder |
| Possibility | First \(SAT(B \land q)\): SAT → `possible` (one call); UNSAT → \(SAT(B)\) → `impossible` or ladder |

Never report `entailed` / `impossible` from the first UNSAT alone. Witnesses do not transfer across different \(E\), \(\varphi\), theory versions, repair candidates, or assertion stacks.

Repair (replaced base): possible-mode acceptance may be one call; entailment-mode acceptance still requires \(SAT(B')\) after \(UNSAT(B' \land \neg q)\).

Cause codes on **admitted** \(E\)/\(\varphi\):

| Code | Stage |
| ---- | ----- |
| `sources_conflict` | Before admitted \(E\) (blob; `reason == "blob_conflict"`) |
| `conflicting_assumptions` | During φ validation (syntactic force∩forbid), before φ admitted |
| `answers_inconsistent` | Ladder step 2: UNSAT(\(B_E\)) |
| `assumptions_inconsistent` | Ladder step 3: SAT(\(B_E\)) but UNSAT(\(B_\varphi\)) |

When evidence alone is unsatisfiable, the cause is `answers_inconsistent` even if assumptions are present.

---

## 6. Enforcement map

| Check | Where | MCP evaluate |
| ----- | ----- | ------------ |
| IR valid (DAG, single entry, guard labels ∈ options) | `validate_ir` at publish / evaluate | Indirect (artifact from publish) |
| One answer per question in payload | `ingest_envelope` + `validate_raw_answers_for_ir` | **Yes** |
| ≤1 explicit true per question in canonical facts | `raw_answers_to_canonical_facts` | **Yes** (structural) |
| Answer string matches an option label | `validate_raw_answers_for_ir` → `ingest_invalid_answer_option` | **Yes** |
| ABSENT rows not asserted on solver | `apply_canonical_facts_to_solver` | **Yes** |
| Bridge rule conflicts | `merge_bridge_rules_into_canonical_facts` | Blob only |
| `reach(q) → exactly one option` | `guards_radio` in \(T(\mathrm{IR})\) | Always in theory |
| `answered(q) → reach(q)` | **Not enforced** (intentional) | N/A |

---

## 7. Partial sessions and unanswered questions

`raw_answers_to_canonical_facts` still walks every question node for audit rows, but **unanswered** questions (`key` missing, `null`, or whitespace-only string) emit `confidence=ABSENT` rows only. **`apply_canonical_facts_to_solver` does not assert ABSENT rows** — option atoms stay unconstrained until the caller supplies an explicit answer. Audit `evidence_items` may still list ABSENT rows; `final_facts` contains only literals actually asserted on the solver.

**Ingest:** non-empty answer strings must match an IR option label (case-insensitive) or ingest hard-rejects with **`ingest_invalid_answer_option`** (`prepare_evaluate_ingest` → MCP/REST `error.code`). Invalid labels are not silently turned into all-false literals. Other answer-shape failures may still surface as `ingest_malformed` or `ingest_unknown_question_id`; post-ingest paths that call `validate_raw_answers_for_ir` directly without the ingest wrapper return **`invalid_answers`** (e.g. legacy evaluate-only callers).

Partial MCP evaluate (subset of questions answered) is therefore supported: unanswered nodes on the live path do not force `PbEq` into UNSAT via all-false pins.

---

## 8. Mental model (one paragraph)

> **Answers pin option atoms; the graph pins reach.** Radio semantics tie labeled guards to options and require exactly one option **when** the question is reachable. MCP sends one structured string per question so Stage A cannot emit conflicting option trues. All answered questions are asserted so counterfactual solver runs can reopen paths without re-ingesting; answers on currently dead branches stay in the formula but do not propagate reach below `q` while `reach[q]` is false.

---

## 9. Query modes (product map)

The same compiled \(T(\mathrm{IR})\) supports different query modes.

| Mode | Tool | Notes |
| ---- | ---- | ----- |
| Apply | `smeme_reasoning_evaluate_answers` | \(SAT(T \wedge E)\) + report |
| Compare | `smeme_reasoning_what_if` | Two answer maps (open alternate world) |
| Path under edit | `smeme_reasoning_edit_affects_path` | \(T \wedge E' \wedge \phi \models \bigwedge_{n \in R} reach(n)\) + conclusion side-car; not a `what_if` flag |
| Entail / Possible / Repair | `smeme_reasoning_how_to_reach` | `reach_mode=entailed\|possible`; plans are cardinality-minimal **answer edits**, not minimal sufficient evidence |
| Assume | `force_reachable_ids` / `force_unreachable_ids` on evaluate_answers + what_if + how_to_reach + decisive_support + edit_affects_path | [Decision-DAG calculus](../../docs/spec/decision-dag-calculus.md) §7 / §10 (cite a tag); locks remain how_to_reach-only |
| Minimal sufficient evidence | `smeme_reasoning_decisive_support` | Inclusion-minimal \(S \subseteq E\) that still forces \(c\) under fixed \(T\); **not** abduction |

**Grounding:** callers supply structured `raw_answers` (LLM extract client-side). Deploy freezes a `PublishedEvidenceContract` for `fact_projection`; free-form blob grounding is **not** shipped. Optional reach assumptions \(\phi\) compose as \(SAT(T \wedge E \wedge \phi)\). Logical analysis tools often follow evaluate on the same envelope but do not require a prior evaluate.

---

## 10. Related docs

- [`README.md`](README.md) — module map and publish path
- [`evidence_contract.md`](evidence_contract.md) — Deploy-frozen `PublishedEvidenceContract` + hash invariants
- [`workflow_design.md`](workflow_design.md) — broader design vision; some older “Phase 2+” wording predates shipped evaluate