# Symbolic reasoning (`smeme/reasoning`)

Production-path **IR-first** compiler spine ([D017](../../docs/DECISIONS.md#d017-dtq-proof-of-concept-vs-production-symbolic-reasoning-pipeline)). The pre-cutover symbolic-reasoning package under `decision_tree` has been removed; product publish and evaluate load **`smeme/reasoning/`** only.

---

## What to read first (new agent / developer)

Load these in order; stop when your task is clear.

| Order | Doc | Purpose |
| ----- | --- | ------- |
| 1 | [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) | System map: web, MCP, and the IR reasoning stack. |
| 2 | [`docs/spec/decision-dag-calculus.md`](../../docs/spec/decision-dag-calculus.md) | Canonical public theory (cite a tag/commit, not `main`). |
| 3 | [Calculus maintenance](../../docs/guides/decision-dag-calculus-maintenance.md) | When this package changes: update spec, re-audit, theory tags. |
| 4 | [D017 in `docs/DECISIONS.md`](../../docs/DECISIONS.md#d017-dtq-proof-of-concept-vs-production-symbolic-reasoning-pipeline) | Why the new pipeline exists; what to reuse vs replace. |
| 5 | **This file** | Current checkpoint and next steps. |
| 6 | [`SPRINT_PLAN.md`](SPRINT_PLAN.md) | Original day-by-day spine (structure differs slightly from repo layout). |
| 7 | [`workflow_design.md`](workflow_design.md) | Broader design vision (minimization, projection) — only if scope goes beyond the spine. |
| 8 | [`evidence_contract.md`](evidence_contract.md) | **Deploy freeze today:** `PublishedEvidenceContract` → `cevi_contract_*`; deterministic induction + evaluate `fact_projection`. |
| 9 | [`IR_validator.md`](IR_validator.md) | Tiered validation / counterexamples — when extending `validate_ir`. |
| — | [`evaluate_semantics.md`](evaluate_semantics.md) | **Evaluate contract:** \(T(\mathrm{IR})\) vs evidence \(E\), radio/PbEq, why all answered questions hit the solver, MCP structured ingest. |
| — | [`docs/planning/dtq-to-reasoning-cutover.md`](../../docs/planning/dtq-to-reasoning-cutover.md) | **Completed cutover plan** (historical): naming, DB, API/MCP migration reference. |

Repo-wide harness: [`CLAUDE.md`](../../CLAUDE.md) at the repository root.

---

## Where to pick up (implemented today)

Code layout (actual repo, not the sprint’s `dtq_v1/` sketch):

| Area | Location | Notes |
| ---- | -------- | ----- |
| IR types | `ir/types.py` | `IR`, `IRNode` + `IRQuestionShape`, `Guard`, `DEFAULT_GUARD_EXPR`, `IR_FORMAT_VERSION` (bump when serialized shape changes). |
| DecisionTree → IR | `ir/dt_graph_to_ir.py` | `compile_dt_graph_to_ir`; import via [`dt_graph_bridge.py`](dt_graph_bridge.py) so `import smeme.reasoning` stays free of `decision_tree.models`. |
| Validation | `ir/validate.py` | `validate_ir`: structure + **DAG** (no self-loops / directed cycles) + **radio** non-default guards (expr must match an option label). Raises nothing—inspect `ValidationReport`. |
| IR → Z3 | `theory/compile_to_z3.py`, `theory/guards_radio.py` | Reachability recurrence; **radio** guard wiring via option atoms. **Requires** `validate_ir(ir).valid` before compile (documented in module + `compile_ir_to_z3`); unvalidated IR may raise `KeyError`. |
| Runtime | `runtime/run.py`, `runtime/evaluate.py` | **Phase 1:** `solve_reachability_witness` (debug / smoke). **`evaluate_reasoning`** (`runtime/evaluate.py`) is the production runtime over persisted IR. `enumerate_conclusion_sat_queries` in `runtime/analyze.py` powers the publish preflight gate. |
| Publish gate | `publish_readiness.py` | Async **`assess_publish_readiness`**: DecisionTree publication validation → **`compile_dt_graph_to_ir`** → **`validate_ir`** → **`enumerate_conclusion_sat_queries`**. |
| Wire surfaces | `mcp/reasoning_fastmcp.py` | MCP **`smeme_reasoning_*`** tools call **`evaluate_reasoning`** on persisted **`ReasoningCompiledArtifact`** IR. |
| Evidence contract | `cevi/*`, `runtime/evaluate.py` | Deterministic Deploy induction → **`PublishedEvidenceContract`**; structured answers via **`fact_projection`** before the shared Z3 tail in **`evaluate_reasoning`**. |
| Tests | `tests/unit/reasoning/` | Unit tests for compile, validate, Z3, runtime. |

Public imports: `smeme.reasoning` exports IR, `validate_ir`, `IRValidationError`, `compile_ir_to_z3`, `solve_reachability_witness`, `ReachabilityWitness`, etc. Use `smeme.reasoning.dt_graph_bridge` for `compile_dt_graph_to_ir`.

---

## What to do next (suggested order)

Aligned with [`SPRINT_PLAN.md`](SPRINT_PLAN.md) **Week 1 Days 6–7** and **Week 2**, adjusted to the real module paths:

1. **Validator / UX (continued)** — Radio option guards are enforced in `validate_ir`. Next: unreachable-node warnings, structured `ValidationError(code, message, location)`.
2. **Theory / runtime depth** — Minimization, broader projection, lemma store (see `workflow_design.md`). Deploy already freezes a deterministic evidence contract; evaluate uses structured `raw_answers` + `fact_projection`.

Structured session answers use **radio** `fact:radio:*` atoms through **`evaluate_reasoning(raw_answers)`** (Stage A canonical facts + Stage B projection).

Explicit **non-goals** (still open): minimization (B0.6), broad projection, lemma store, blob-evaluate ingest — see sprint non-goals / `evidence_contract.md`.

---

## Conventions

### Axioms vs SMT encoding (proof theory vs models)

On paper, \(T(\mathrm{IR})\) is a **set of formulas** (reachability, guard definitions, typed semantics). In code, each conjunct is added with **`solver.add(φ)`**: Z3 must satisfy **all** of them in one model. There is no separate natural-deduction engine: **finding a satisfying assignment** is the operational meaning of “the theory holds.” For **Boolean** guard and option variables, an equation **`G == p`** in Z3 is the same as the **biconditional** \(G \leftrightarrow p\)—a **definitional** axiom that pins a guard symbol to a **radio** option atom (see `theory/guards_radio.py`). User/session evidence (`evaluate_reasoning`) adds more **unit literals** on those atoms; the solver then decides **`SAT(T(IR) ∧ E)`**. Longer evaluate framing: [`evaluate_semantics.md`](evaluate_semantics.md); broader design notes: [`workflow_design.md`](workflow_design.md).

- **Spine vs open work:** The compiled reachability theory and publish SAT gate are **structural** (`SAT(T(IR) ∧ φ)`). **User-grounded evaluate** (`evaluate_reasoning`) and Deploy evidence-contract freeze are shipped; **still open:** minimization, proof traces, and broader projection vision in `workflow_design.md`.
- **Validated IR before Z3:** `compile_ir_to_z3(ir)` assumes `validate_ir(ir).valid` is true; it does not call `validate_ir` itself. Use `solve_reachability_witness(ir)` on integration paths (default validates and raises `IRValidationError` on failure).
- **DAG + single entry:** `validate_ir` enforces a DAG and exactly one entry; theory matches single-start session semantics.
- **Format version:** Compiler emits `IR_FORMAT_VERSION`; mismatch in validation means recompile or migrate stored JSON.
- **Import hygiene:** Heavy DecisionTree dependency only through `dt_graph_bridge.py` or `ir/dt_graph_to_ir.py`, not `smeme.reasoning.__init__`.
- **Guards:** One `Guard` per edge in IR (`g_000000`, …); theory pins each non-default guard to the matching **radio** option atom. **Do not** collapse distinct guard ids in the IR without an explicit migration—identity stays structural.

### Publish path (product)

**Editor “Publish”:** **`assess_publish_readiness`** in [`publish_readiness.py`](publish_readiness.py): **`validate_graph_for_publication`** (tier-3 + **`enforce_reasoning_authoring_contract`**), then **`compile_dt_graph_to_ir`** → **`validate_ir`** → **`enumerate_conclusion_sat_queries`** (publish gate; no witness path). Wired from **`POST /decision-trees/editor/{id}/publish`** and **`GET …/publish-preflight`**. On success → persist **`ReasoningCompiledArtifact`**; DecisionTree **`reasoning_status`** reflects compilation.

**Debugging:** **`solve_reachability_witness`** remains optional cheap smoke; it is not used for the publish decision.

### Hardening: “validated IR” type boundary (still open)

**MCP evaluate is live** (`mcp/reasoning_fastmcp.py`); tools call **`evaluate_reasoning`**, which runs **`validate_ir` by default** before Z3. Publish and preflight also validate before compile.

**What is still missing:** proof of validity in **types**, not just runtime. `IR` does not imply `validate_ir` ran; `skip_ir_validation` / `validate=False` plus calling **`compile_ir_to_z3`** directly remain **deliberate escape hatches** (tests, trusted internals). A future tighten—for example a `ValidIR` wrapper or `typing.NewType` produced only from validation, with `compile_ir_to_z3` taking that type—would make invalid graphs harder to pass to Z3 by accident. Loud comments in `theory/compile_to_z3.py` and `runtime/run.py` document the same intent.
