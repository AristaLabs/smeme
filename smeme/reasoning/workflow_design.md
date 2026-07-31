Yeah—this got muddled because you were mixing *what exists*, *what you want*, and *what the math assumes*. Let’s reset it into a **clean, phase-separated workflow that matches your current system + decisions (DAG constraint, no phase bleed)**.

**Historical note:** “DTQ” in the title reflects the pre-cutover working name; current product behavior is **`smeme/reasoning/`**.

---

# 🧭 **Reasoning workflow — clean v1.0 design**

This version reflects:

* ✅ your **actual implementation**
* ✅ the **DAG constraint**
* ✅ strict **phase separation**
* ❌ no premature minimization / CEVI / proof claims

---

# 1. 🧠 **System Overview**

The system is a **two-phase pipeline**:

```text
PHASE 1: Structural Reasoning Core
PHASE 2: Interpretation & Explanation (future)
```

---

## 🔒 **Core Principle**

> Phase 1 is **closed, deterministic, and purely structural**.
> No language, no minimization, no interpretation.

---

# 2. ⚙️ **PHASE 1 — Structural Reasoning Core (CURRENT SYSTEM)**

---

## 2.1 Pipeline

```text
DecisionTree (author input)
   ↓
IR Compilation
   ↓
IR Validation (includes DAG enforcement)
   ↓
IR → Z3 Compilation
   ↓
SAT Execution (one reachability witness)
   ↓
ReachabilityWitness
```

---

## 2.2 Step A — DecisionTree Authoring

### Input

* SME-authored decision graph

### Properties

* human-readable
* may be ambiguous
* not logically validated

---

## 2.3 Step B — IR Compilation

### Function

```text
⟦·⟧ : DecisionTree → IR
```

### Output

```text
IR = (Nodes, Edges, Guards, Types)
```

### Invariants

* lossless structural encoding
* no semantics imposed yet

---

## 2.4 Step C — IR Validation (**CRITICAL BOUNDARY**)

### Function

```text
validate_ir : IR → ValidationReport
```

---

### **Hard Requirements**

#### 1. Graph must be a DAG

```text
No cycles
No self-loops
No disconnected cycles
```

---

#### 2. Structural correctness

* valid node references
* valid edges
* at least one root

---

#### 3. Guard validity

* well-formed
* type-correct
* canonicalizable

---

### Output

```text
ValidationReport {
  valid: bool
  errors: list
}
```

---

### 🚨 Enforcement Rule

```text
IF valid == false → STOP
```

Nothing proceeds past this point.

---

## 2.5 Step D — Guard Normalization (Implicit Algebra Construction)

**Happens inside validation**

### Purpose

Convert raw guard syntax into canonical form.

```text
canon : GuardSyntax → GuardNormalForm
```

---

### Result

* syntactic variation removed
* guards become stable identities
* defines implicit **Guard Algebra**

---

## 2.6 Step E — IR → Z3 Compilation

### Function

```text
compile_ir_to_z3 : IR_valid → Theory
```

---

### Output

Propositional constraints:

```text
reach(v) ↔ ⋁ (reach(u) ∧ guard_e)
```

---

### Key Property

* purely structural
* no CEVI
* no interpretation
* no minimization

---

## 2.7 Step F — SAT queries over `T(IR)`

Phase 1 can answer existential structural questions after `compile_ir_to_z3`. Two built-ins:

### F1 — `enumerate_conclusion_sat_queries` (systematic)

```text
enumerate_conclusion_sat_queries : IR → ConclusionSatQueryEnumeration
```

One compile, then scoped `push`/`pop` checks:

* **`SAT(T(IR))`** (base theory satisfiable)
* **`SAT(T(IR) ∧ reach(C))`** per conclusion `C`
* **`SAT(T(IR) ∧ reach(Ci) ∧ reach(Cj))`** per unordered conclusion pair

Pairwise work is **`O(|C|²)`** SAT calls in the number of conclusions; for typical DecisionTree sizes this is usually acceptable as a **publish preflight** or CI check. Use this when you need real answers to “is each ending reachable in isolation?” / “can two endings co-occur?”

### F2 — `solve_reachability_witness` (single model)

```text
solve_reachability_witness : IR → ReachabilityWitness
```

Runs **`check()`** once on `T(IR)` and reads **one** witness model’s `reach` flags. Cheap smoke / debugging; **not** a substitute for F1 on publish—if F1 already ran, an extra witness adds little (the model is one arbitrary satisfying assignment, not “the user’s” outcome).

---

### What this is **not**

This is **existential structural** analysis: “under **some** valuation of free guard atoms …?” It is **not** “given real user inputs / grounded evidence, what outcome occurs?”—that composition (`T(IR) ∧ E`) is what **`evaluate_reasoning`** does with structured answers (and Deploy-frozen contract projection).

---

### 🔒 Determinism note

Because **valid IR is a DAG**, the reachability **equations** admit a **unique** classical solution along a topological order; SAT/UNSAT **outcomes** for the queries above should be stable. Individual **witness models** may still differ in unconstrained atoms.

---

## 2.8 Step G — Example outputs

**Enumeration** returns flags such as `is_theory_satisfiable`, `conclusion_reachable`, `conclusion_pairs_co_reachable`.

**Witness** returns `ReachabilityWitness` (`z3_status`, `reachable_conclusion_ids`, `node_reachable` from **one** model).

---

### Important limitation

Any single model is:

> a **valuation**, not a proof — and not user-facing evaluation

---

## 2.9 Author journey — DecisionTree validation vs IR (product)

**Editing:** [`validate_graph_for_editing`](../../decision-trees/helpers/validation.py) in `smeme/decision-trees/helpers/validation.py` — errors + warnings for drafts; sidebar issues may include programmatic fix hints ([`docs/architecture/decision-trees/validation.md`](../../docs/architecture/decision-trees/validation.md#fix-hints)).

**Publish (app gate):** [`assess_publish_readiness`](publish_readiness.py) — **`validate_graph_for_publication`**, **`compile_dt_graph_to_ir`**, **`validate_ir`**, **`enumerate_conclusion_sat_queries`**. Editor routes: **`GET …/publish-preflight`**, **`POST …/publish`**.

**IR spine:** Same pipeline as the gate; runtime loads persisted IR from **`reasoning_compiled_artifacts`** (`evaluate_reasoning`).

---

# ✅ Phase 1 Summary

You now have:

> a **deterministic, DAG-constrained, propositional reachability system**

with:

* unique semantics
* no solver ambiguity
* no interpretation layer

---

# 3. 🚫 What Phase 1 Explicitly DOES NOT DO

This is where confusion came from.

### ❌ No CEVI

* no language mapping
* no text interpretation

---

### ❌ No Minimization

* no minimal supports
* no invariant subgraphs

---

### ❌ No Proof Objects

* no derivation traces
* no explanation graphs

---

### ❌ No Lemmas

* no reusable logical abstractions

---

# 4. 🧪 PHASE 2 — Interpretation & Explanation (FUTURE)

This is everything you were previously mixing in.

---

## 4.1 CEVI (Language Interface)

```text
Text ⇄ Σ ⇄ Atoms
```

* maps real-world evidence into atoms
* reconstructs explanations

---

## 4.2 Minimization Engine

Goal:

```text
Find minimal S ⊆ Atoms such that S ⊨ reach(v)
```

---

## 4.3 Projection Layer

Transforms results into:

* structural paths
* logical expressions
* natural language

---

## 4.4 Proof / Trace System

Adds:

```text
(model, derivation trace)
```

instead of just:

```text
(model)
```

---

## 4.5 Lemma System

```text
conditions → conclusion
```

* reusable reasoning units

---

# 5. 🧭 Final Mental Model (This Is the Key)

---

## Phase 1 (Today)

```text
Graph → Boolean system → Unique model
```

---

## Phase 2 (Later)

```text
Model → Minimal support → Explanation → Language
```

---

# 🔥 The One Sentence That Should Anchor You

> **Phase 1 computes what is true.
> Phase 2 explains why it is true.**

---

# 🎯 Why This Design Is Correct

You:

* enforce **DAG → uniqueness**
* avoid **fixpoint ambiguity**
* isolate **semantics from language**
* defer **complex reasoning to later layers**

