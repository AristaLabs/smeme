# Symbolic reasoning (`smeme/reasoning`)

Production-path **IR-first** compiler spine. The pre-cutover
symbolic-reasoning package under `qnr` has been removed; product Deploy and
evaluate load **`smeme/reasoning/`** only.

---

## What to read first (new agent / developer)

Load these in order; stop when your task is clear.

| Order | Doc | Purpose |
| ----- | --- | ------- |
| 1 | [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) | System map: web, MCP, and the IR reasoning stack. |
| 2 | **This file** | Current checkpoint and next steps. |
| 3 | [`SPRINT_PLAN.md`](SPRINT_PLAN.md) | Original day-by-day spine (structure differs slightly from repo layout). |
| 4 | [`workflow_design.md`](workflow_design.md) | Full B0–C vision (minimization, CEVI, projection) — only if scope goes beyond the spine. |
| 5 | [`evidence_contract.md`](evidence_contract.md) | **Phase 2+ target:** `PublishedEvidenceContract`; **CEVI induction** vs **CEVI runtime**; **`smeme/reasoning/cevi/`** (Phase A: corpus normalize, IR atom catalog, publish induction hook) — see §7–§8.7. |
| 6 | [`IR_validator.md`](IR_validator.md) | Tiered validation / counterexamples — when extending `validate_ir`. |
| — | [`evaluate_semantics.md`](evaluate_semantics.md) | **Evaluate contract:** \(T(\mathrm{IR})\) vs evidence \(E\), radio/PbEq, why all answered questions hit the solver, MCP structured ingest. |

---

## Where to pick up (implemented today)

Code layout (actual repo, not the sprint’s `dtq_v1/` sketch):

| Area | Location | Notes |
| ---- | -------- | ----- |
| IR types | `ir/types.py` | `IR`, `IRNode` + `IRQuestionShape`, `Guard`, `DEFAULT_GUARD_EXPR`, `IR_FORMAT_VERSION` (bump when serialized shape changes). |
| QNR → IR | `ir/qnr_to_ir.py` | `compile_qnr_to_ir`; import via [`qnr_bridge.py`](qnr_bridge.py) so `import smeme.reasoning` stays free of `qnr.models`. |
| Validation | `ir/validate.py` | `validate_ir`: structure + **DAG** (no self-loops / directed cycles) + **radio** non-default guards (expr must match an option label). Raises nothing—inspect `ValidationReport`. |
| IR → Z3 | `theory/compile_to_z3.py`, `theory/guards_radio.py` | Reachability recurrence; **radio** guard wiring via option atoms. **Requires** `validate_ir(ir).valid` before compile (documented in module + `compile_ir_to_z3`); unvalidated IR may raise `KeyError`. |
| Runtime | `runtime/run.py`, `runtime/evaluate.py` | **Phase 1:** `solve_reachability_witness` (debug / smoke). **`evaluate_reasoning`** (`runtime/evaluate.py`) is the production runtime over persisted IR. `enumerate_conclusion_sat_queries` in `runtime/analyze.py` powers the publish preflight gate. |
| Publish gate | `publish_readiness.py` | Async **`assess_publish_readiness`**: QNR publication validation → **`compile_qnr_to_ir`** → **`validate_ir`** → **`enumerate_conclusion_sat_queries`**. |
| Wire surfaces | `mcp/reasoning_fastmcp.py` | MCP **`smeme_reasoning_*`** tools call **`evaluate_reasoning`** on persisted **`ReasoningCompiledArtifact`** IR. |
| CEVI (partial) | `cevi/*`, `runtime/evaluate.py` | Deterministic publish induction → **`PublishedEvidenceContract`**; structured answers via **`fact_projection`** Stage B before the shared Z3 tail in **`evaluate_reasoning`**. |
| Tests | `tests/unit/reasoning/` | Unit tests for compile, validate, Z3, runtime. |

Public imports: `smeme.reasoning` exports IR, `validate_ir`, `IRValidationError`, `compile_ir_to_z3`, `solve_reachability_witness`, `ReachabilityWitness`, etc. Use `smeme.reasoning.qnr_bridge` for `compile_qnr_to_ir`.

---

## What to do next (suggested order)

Aligned with [`SPRINT_PLAN.md`](SPRINT_PLAN.md) **Week 1 Days 6–7** and **Week 2**, adjusted to the real module paths:

1. **Validator / UX (continued)** — Radio option guards are enforced in `validate_ir`. Next: unreachable-node warnings, structured `ValidationError(code, message, location)`.
2. **CEVI / Phase 2+ (continued)** — Corpus-backed deterministic induction on publish is in tree; remaining work: minimization, broader projection, lemma store (see `workflow_design.md`).

Structured session answers use **radio** `fact:radio:*` atoms through **`evaluate_reasoning(raw_answers)`** (Stage A canonical facts + Stage B projection).

Explicit **non-goals** (still open): minimization (B0.6), full CEVI surface area beyond current slices, broad projection, lemma store — see sprint non-goals section.

---

## Conventions

### Axioms vs SMT encoding (proof theory vs models)

On paper, \(T(\mathrm{IR})\) is a **set of formulas** (reachability, guard definitions, typed semantics). In code, each conjunct is added with **`solver.add(φ)`**: Z3 must satisfy **all** of them in one model. There is no separate natural-deduction engine: **finding a satisfying assignment** is the operational meaning of “the theory holds.” For **Boolean** guard and option variables, an equation **`G == p`** in Z3 is the same as the **biconditional** \(G \leftrightarrow p\)—a **definitional** axiom that pins a guard symbol to a **radio** option atom (see `theory/guards_radio.py`). User/session evidence (`evaluate_reasoning`) adds more **unit literals** on those atoms; the solver then decides **`SAT(T(IR) ∧ E)`**.

- **Phase 1 spine vs Phase 2+:** The compiled reachability theory and publish SAT gate are **structural** (`SAT(T(IR) ∧ φ)`). **User-grounded evaluate** (`evaluate_reasoning`) is shipped; **still Phase 2+ / incomplete:** minimization, proof traces, and the full CEVI / projection vision in `workflow_design.md`.
- **Validated IR before Z3:** `compile_ir_to_z3(ir)` assumes `validate_ir(ir).valid` is true; it does not call `validate_ir` itself. Use `solve_reachability_witness(ir)` on integration paths (default validates and raises `IRValidationError` on failure).
- **DAG + single entry:** `validate_ir` enforces a DAG and exactly one entry; theory matches single-start session semantics.
- **Format version:** Compiler emits `IR_FORMAT_VERSION`; mismatch in validation means recompile or migrate stored JSON.
- **Import hygiene:** Heavy QNR dependency only through `qnr_bridge.py` or `ir/qnr_to_ir.py`, not `smeme.reasoning.__init__`.
- **Guards:** One `Guard` per edge in IR (`g_000000`, …); theory pins each non-default guard to the matching **radio** option atom. **Do not** collapse distinct guard ids in the IR without an explicit migration—identity stays structural.

### Publish path (product)

**Editor “Publish”:** **`assess_publish_readiness`** in [`publish_readiness.py`](publish_readiness.py): **`validate_graph_for_publication`** (tier-3 + **`enforce_reasoning_authoring_contract`**), then **`compile_qnr_to_ir`** → **`validate_ir`** → **`enumerate_conclusion_sat_queries`** (publish gate; no witness path). Wired from **`POST /qnr/editor/{id}/publish`** and **`GET …/publish-preflight`**. On success → persist **`ReasoningCompiledArtifact`**; QNR **`reasoning_status`** reflects compilation.

**Debugging:** **`solve_reachability_witness`** remains optional cheap smoke; it is not used for the publish decision.

### Hardening: “validated IR” type boundary (still open)

**MCP evaluate is live** (`mcp/reasoning_fastmcp.py`); tools call **`evaluate_reasoning`**, which runs **`validate_ir` by default** before Z3. Publish and preflight also validate before compile.

**What is still missing:** proof of validity in **types**, not just runtime. `IR` does not imply `validate_ir` ran; `skip_ir_validation` / `validate=False` plus calling **`compile_ir_to_z3`** directly remain **deliberate escape hatches** (tests, trusted internals). A future tighten—for example a `ValidIR` wrapper or `typing.NewType` produced only from validation, with `compile_ir_to_z3` taking that type—would make invalid graphs harder to pass to Z3 by accident. Loud comments in `theory/compile_to_z3.py` and `runtime/run.py` document the same intent.
