Here’s a **tight, execution-oriented sprint plan** you can paste into your AI IDE and drive step-by-step. It’s designed to produce a working vertical slice quickly, while enforcing your architecture (IR-first, structure → logic → solver).

**Historical note:** authored during the internal “DTQ” naming era; the shipped compiler spine is **`smeme/reasoning/`**.

---

# 🏁 **Sprint Plan: Reasoning v1 compiler spine (2 weeks)**

## 🎯 Sprint Goal

> Build a minimal, end-to-end pipeline:

```text
DecisionTree → IR → Validator → Z3 Theory → Runtime Result
```

No minimization, no CEVI, no projection. Just the **core compiler spine**.

---

# 📦 Deliverables

By end of sprint, you must have:

* ✅ Deterministic IR generation from decision tree
* ✅ Basic IR validator (shape correctness)
* ✅ IR → Z3 compiler
* ✅ Runtime execution producing a decision
* ✅ 1–2 hardcoded DecisionTree examples

---

# 🗂️ Project Structure (Create First)

```text
dtq_v1/
  ├── ir/
  │   ├── types.py
  │   └── builder.py
  ├── compiler/
  │   └── compile_to_ir.py
  ├── validator/
  │   └── validate_ir.py
  ├── theory/
  │   └── compile_to_z3.py
  ├── runtime/
  │   └── run.py
  ├── examples/
  │   └── decision_tree_example.py
  └── main.py
```

---

# 🗓️ **Week 1 — Core Representation + Execution**

---

## 🔹 Day 1–2: IR Definition

### Tasks

* Define core classes:

```python
Node(id, kind)
Edge(source, target, guard_id)
Guard(id, expr)
IR(nodes, edges, guards)
```

* Define enums:

  * NodeKind: QUESTION, STATE, CONCLUSION
* Keep `expr` as simple string for now

### IDE Prompts

* “Define Python dataclasses for IR nodes, edges, and guards”
* “Ensure all objects are immutable or treated as value objects”

### Done When

* You can instantiate a valid IR object manually

---

## 🔹 Day 3: DecisionTree → IR Compiler

### Tasks

* Implement:

```python
compile_dt_graph_to_ir(dt_graph_dict) -> IR
```

* Map:

  * DecisionTree nodes → IR nodes
  * DecisionTree edges → IR edges
  * edge conditions → guards

### Constraints

* No logic parsing yet
* Just carry guard strings through

### Done When

* A simple JSON DecisionTree converts to IR deterministically

---

## 🔹 Day 4: IR Validator (B0.5-lite)

### Tasks

Implement checks:

* all node IDs unique
* all edge sources/targets exist
* all guard references exist

Return:

```python
ValidationReport(valid: bool, errors: list)
```

### IDE Prompts

* “Write validation functions for graph integrity”
* “Return structured error messages”

### Done When

* Invalid IR is rejected with clear errors

---

## 🔹 Day 5: IR → Z3 Compiler (Critical)

### Tasks

Implement:

```python
compile_ir_to_z3(ir: IR) -> (solver, symbols)
```

### Mapping Strategy

* Each node → `Bool("At_<node>")`
* Each guard → `Bool("G_<id>")` (placeholder)

Edges:

```python
Implies(And(At_source, G_guard), At_target)
```

### Hardcode guard truth for now:

```python
solver.add(G_guard == True)
```

### Done When

* Solver builds without error
* Graph transitions exist in Z3

---

## 🔹 Day 6–7: Runtime Execution

### Tasks

Implement:

```python
run(ir)
```

* compile to Z3
* assert starting node
* check satisfiability
* print reachable conclusions

### Output Example

```text
VALID IR
SAT
Reachable: C_1
```

### Done When

* End-to-end execution works

---

# 🗓️ **Week 2 — Correctness + Refinement**

---

## 🔹 Day 8: Add Real Guard Semantics (Minimal)

### Tasks

Replace:

```python
G_guard == True
```

With:

* simple parser:

  * `"x == true"` → Bool
  * `"not x"` → Not(x)

Keep it minimal.

### Done When

* Guards affect reachability

---

## 🔹 Day 9: Improve Validator

Add:

* unreachable node detection (warning)
* missing terminal node (error)

### Done When

* Validator catches structural issues beyond syntax

---

## 🔹 Day 10: Multiple Paths / Branching

### Tasks

* Support multiple outgoing edges
* ensure solver allows OR-style reachability

Test:

```text
Q1 → Q2
Q1 → Q3
```

### Done When

* Both branches can be reachable

---

## 🔹 Day 11: Add Trace Output

### Tasks

Track:

* which nodes are true in model

Print:

```text
Trace:
Q1 → Q2 → C1
```

### Done When

* You can see reasoning path

---

## 🔹 Day 12: Second Example (Edge Case)

Create:

* contradictory graph
* dead-end graph

Ensure:

* validator catches issues OR
* solver result is meaningful

---

## 🔹 Day 13: Refactor + Clean Boundaries

### Tasks

* ensure modules are cleanly separated
* no cross-import leakage
* IR is not modified by downstream steps

---

## 🔹 Day 14: Final Integration

### Tasks

* run everything from `main.py`
* validate → compile → run

---

# 🧪 Testing Checklist

* [ ] valid DecisionTree runs end-to-end
* [ ] invalid DecisionTree is blocked
* [ ] branching works
* [ ] guards affect outcomes
* [ ] trace is readable

---

# 🚫 Explicit Non-Goals (This Sprint)

Do NOT implement:

* minimization engine
* unsat core logic
* CEVI
* projection layer
* lemma system

---

# 🧠 How to Use Your AI IDE

Use prompts like:

* “Implement IR node and edge dataclasses”
* “Write a function that validates graph edges”
* “Convert this IR into Z3 constraints using implications”

Avoid:

* “Build the full system”
* “Implement reasoning engine”

---

# 🔥 Definition of Success

At the end:

```bash
python main.py
```

Outputs:

```text
IR VALID
SAT
Conclusion: C_1 = TRUE
Trace: Q1 → Q2 → C1
```

---

# 🧭 Next Sprint (Preview)

After this:

* B0.6 Minimization Engine (reuse your Z3 core logic)
* Projection Layer
* Proper BooleanExpr AST
* CEVI integration

---

# 🔥 Final Guidance

> Move fast, but only along the **correct abstraction boundaries**.

If something feels hard, it’s usually because you’re accidentally:

* mixing structure and logic
* or skipping the IR boundary

