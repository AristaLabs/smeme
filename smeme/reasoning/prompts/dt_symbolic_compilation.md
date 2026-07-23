
## Task

Compile the provided **SME-validated `dt_graph` JSON** into a **solver-ready predicate-calculus theory package** for the separate CEVI + satisfiability workflows.

This is **Workflow B (symbolic compilation)** in the architecture.

The output must be suitable for:

* persistent artifact storage
* reuse by runtime evidence reasoning
* satisfiability checking in Z3
* contradiction-core extraction
* future Horn-rule compression
* joining with CEVI-normalized evidence facts

Use only:

* typed constants
* unary predicates
* binary predicates
* Boolean operators (`¬`, `∧`, `∨`, `→`, `↔`)
* Horn-style implication schemas

No quantifiers.
No OWL/RDF.
No description logic.
No natural-language prose outside required notes.

---

## Compiler objective

Treat the `dt_graph` as the **authoritative decision semantics**.

The goal is to extract:

1. **branch-state theory**
2. **terminal outcome theory**
3. **mutual exclusion constraints**
4. **decision invariants**
5. **CEVI evidence attachment points**
6. **minimal Horn basis**
7. **runtime satisfiability hooks**

Optimize for:

* repeated Horn motifs
* stable solver symbols
* branch-path compressibility
* contradiction explainability
* future CEVI joins

---

## Critical extraction rules

### 1) Preserve DecisionTree branch truth exactly

Every edge condition must become a formal branch rule.

Example:
`At(q1) ∧ Selects(personal_use) → At(conclusion_1)`

Do not paraphrase away branch distinctions.

---

### 2) Compile conclusions into outcome predicates

Each conclusion node must become:

* a terminal node constant
* semantic outcome predicates
* solver-visible decision facts

Example:
`At(conclusion_2) → DeductionAvailable(property:p1)`

---

### 3) Extract CEVI join predicates

For every question node, define the **evidence predicates that future CEVI facts may satisfy**.

Example:

* `GeneratesIncome(property:p1)`
* `HeldForInvestment(property:p1)`
* `HasEligibleCarryingCosts(property:p1)`

These are the **runtime evidence attachment points**.

The runtime workflow will attempt to prove or refute these from arbitrary evidence corpora.

---

### 4) Emit contradiction constraints

Generate explicit forbidden states.

Examples:

* `DeductionAvailable(p) → ¬NoDeduction(p)`
* `CapitalizationAvailable(p) → ¬NoCapitalization(p)`
* `UsedForPersonal(p) → ¬UsedForTradeBusiness(p)`

These are required for Z3 unsat-core analysis.

---

### 5) Minimize to Horn spine

After exact branch extraction, derive the **compressed semantic Horn spine**.

Example:
`UsedForTradeBusiness(p) ∧ GeneratesIncome(p) → DeductionAvailable(p)`

This becomes the reusable runtime reasoning core.

---

## Required output package

### A. Typed constants

* node constants
* conclusion constants
* domain constants
* option constants

### B. Static topology facts

`LeadsTo(source,target)` graph facts

### C. Exact branch theory

Path-faithful Horn/Boolean branch rules

### D. CEVI runtime join predicates

Evidence predicates that arbitrary corpora may prove

### E. Terminal decision semantics

Formal meaning of each conclusion node

### F. Contradiction and exclusion constraints

Required for solver satisfiability analysis

### G. Minimal Horn semantic spine

The compressed reusable decision theory

### H. Runtime satisfiability notes

List which predicates are intended to be proven by CEVI evidence ingestion
