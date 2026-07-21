
# Prompt CEVI as evidence normalization source

This is the build-time compiler prompt for the research corpus used during QNR authoring.

## Task

Compile the provided **research corpus** (the same source material used during SME `qnr_graph` generation) into a **Canonical Evidence Vocabulary Interface (CEVI)**.

This workflow is the **evidence normalization compiler**.

The output is **not a theory** and must **not infer decision outcomes**.

Its sole purpose is to define how arbitrary future evidence corpora can be normalized into the **predicate join points required by the separately compiled QNR theory**.

The CEVI package will be consumed by a runtime LangGraph workflow that:

1. ingests arbitrary evidence documents
2. converts them into canonical CEVI facts
3. joins those facts with the QNR-derived theory in a solver

Use only:

* typed constant sort families
* unary predicates
* binary predicates
* Boolean composability compatibility
* synonym normalization maps
* forbidden merge constraints

No quantifiers.
No axioms.
No Horn rules except optional normalization heuristics.
No decision outcomes.

---

## Compiler objective

Extract the **smallest stable canonical evidence interface** that allows future corpora to prove or refute the **QNR theory join predicates**.

Optimize for:

* lexical drift resistance
* synonym collapse
* repeated evidence motifs
* stable typed sort families
* future Horn-rule compressibility
* QNR theory join compatibility
* Z3 symbol readability

The output should maximize the probability that future evidence corpora collapse into the same CEVI symbols.

---

## Critical design rule: target QNR join predicates

The CEVI must explicitly align with the **runtime join predicates expected by the QNR theory compiler**.

Examples:

* `GeneratesIncome(property:*)`
* `HeldForInvestment(property:*)`
* `HasEligibleCarryingCosts(property:*)`
* `UsedForTradeBusiness(property:*)`
* `UsedForPersonal(property:*)`

For each canonical predicate, include:

* surface lexical realizations from the corpus
* synonymous expressions
* likely future lexical variants
* distinction boundaries

These predicates are the **semantic ABI between evidence ingestion and solver reasoning**.

---

## Extraction rules

### 1) Build canonical typed constant sort families

Extract reusable domain sort families from the corpus.

Examples:

* `property:*`
* `expense:*`
* `tax_record:*`
* `income_event:*`
* `maintenance_cost:*`

Prefer semantic stability over corpus wording.

---

### 2) Extract only evidence-facing predicates

Extract predicates that can be directly evidenced by documents.

Good:

* `GeneratesIncome(property:*)`
* `HeldForInvestment(property:*)`
* `HasEligibleCarryingCosts(property:*)`

Bad:

* `DeductionAvailable(property:*)`
* `CapitalizationAllowed(property:*)`

Decision semantics belong exclusively to the QNR theory workflow.

---

### 3) Build synonym normalization maps

This is mandatory.

For each canonical predicate, provide:

* corpus phrases
* lexical variants
* paraphrase families
* domain jargon variants
* future likely wording drift

Format:
`surface phrase -> canonical predicate`

Example:

* “earns rental income” → `GeneratesIncome`
* “held as an appreciating asset” → `HeldForInvestment`
* “interest and tax carrying costs” → `HasEligibleCarryingCosts`

---

### 4) Extract forbidden merges

Explicitly identify near-synonyms that must remain separate.

Examples:

* `HeldForInvestment` ≠ `UsedForTradeBusiness`
* `MaintenanceExpense` ≠ `CapitalizableCarryingCost`
* `PersonalOccupancy` ≠ `InvestmentHolding`

These are critical for runtime satisfiability integrity.

---

### 5) Optimize for cross-corpus Horn compressibility

Choose symbols that maximize reuse in future QNR joins.

The ideal CEVI should encourage repeated runtime motifs like:

`HeldForInvestment(p) ∧ HasEligibleCarryingCosts(p)`

rather than fragmented lexical variants.

This is the primary optimization objective.

---

## Required output package

### A. Typed constant sort families

Stable evidence-facing sort namespaces

### B. Canonical evidence predicate basis

Predicates intended for runtime CEVI facts

### C. Synonym normalization table

`surface phrase -> canonical symbol`

### D. Forbidden merge table

Semantic distinctions required for solver correctness

### E. QNR join compatibility notes

Explicit list of predicates expected to satisfy QNR theory conditions

### F. Cross-corpus compression notes

Explain why this CEVI maximizes repeated runtime Horn motifs

