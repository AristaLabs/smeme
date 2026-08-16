# The SMEme Decision-DAG Calculus

**Finite Decision DAGs as Propositional Reachability Theories**

| | |
|---|---|
| **Version** | 1.2 |
| **Status** | **Public specification** (target Inquire added; Part I unchanged from v1.1) |
| **Conformance baseline** | SMEme Core commits identified in Appendix B |
| **Path** | `docs/spec/decision-dag-calculus.md` |

Versions are carried by document metadata, Git tags, and immutable commits — not by the filename. Cite this document at a commit or tag, never at `main`. v1.0 remains the historical snapshot at tag `decision-dag-algebra-v1.0`.

The baseline is not an open-ended claim about future `main`. A later Core release conforms only if it preserves these obligations and their conformance evidence.

**Maintainer process** (when reasoning / Deploy / MCP evaluate code changes): [decision-DAG calculus maintenance](../guides/decision-dag-calculus-maintenance.md).

---

## 0. How to read this document

The document is partitioned by *status*, not by annotation. Where a claim appears determines whether it is guaranteed.

| Part | Contains | Guarantee |
|---|---|---|
| **I — Normative** (§1–§12) | Definitions, scope, and executable obligations SMEme Core satisfies today | Every executable obligation is traced in Appendix B to implementation and test evidence |
| **II — Target** (§13) | Architecture not implemented | No conformance rows. Nothing here is guaranteed |
| **III — Informative** (§14, Appendix A) | Rationale, history, non-obligations | Explanatory only |

Part location determines status. If an executable behavior is described in Part I, it ships and is tested. If a capability is described in Part II, it does not ship. Appendix B supplies evidence for Part I; it does not decide status after the fact. A missing conformance entry is therefore a defect in this document, not a reason to silently demote a Part I obligation.

Some Part I prose explains a formula, fixes the scope of a guarantee, or states a non-certification boundary. Such prose is normative interpretation but is not itself a separately executable test assertion. Appendix B traces the executable obligations and identifies the scope declarations they support.

### 0.1 Scope

This specification governs the compilation of a finite typed decision DAG into a quantifier-free propositional theory, and the queries answerable over that theory under case evidence and assumptions. It governs the source-validation conditions necessary to establish the compilation domain (§4.1), but not authoring interfaces or workflows. It does not govern transport, authentication, or the language-model components that produce candidate graphs and candidate evidence. §12 states the boundary precisely.

**Kind of theory.** This document is a **formal semantics** and **constraint encoding**: a typed DAG data model, a canonical guard domain, a partial DAG→IR compiler, an IR→propositional-theory encoding, and a collection of satisfiability and consequence queries. It is **not** an algebra of decision DAGs in the universal-algebra or process-algebra sense. It does not define graph operations (merge, guarded choice, sequential composition), laws over those operations, or a structure-preserving homomorphism from DAG construction into theories. `GuardDomain` is a quotient of guard strings; no operations are defined over it. Compilation introduces auxiliary `reach` and `g` atoms, so even a later preservation result would be a **semantics-preserving encoding theorem** (a correspondence of models, possibly after hiding auxiliaries), not formula identity and not a homomorphism.

---

# Part I — Normative

## 1. Source object

The source is a finite, directed, typed graph. To keep graph arcs distinct from case evidence `E` (§7), write:

```text
G = (V, A, src, tgt, τ_V, τ_A)
```

- `V` — finite node set
- `A` — finite arc set, independent of `V`
- `src, tgt : A → V` — endpoint functions
- `τ_V : V → {QUESTION, CONCLUSION}` — assigns a node type
- `τ_A : A → GuardSyntax` — assigns a guard expression to each arc

`A` is an independent set rather than a subset of `V × V` because two distinct arcs may share endpoints while carrying different guards. A source question routing two of its options to the same target produces exactly that, and the guards must remain distinguishable.

`G` is a control-flow structure with syntactically scoped conditions. It is **not** a logical theory, and no semantic claim in this document applies to it until compilation (§5).

## 2. Intermediate representation

A deterministic mapping produces a finite relational structure:

```text
⟦·⟧_Core : DecisionDAG ⇀ IR
```

The mapping is **partial**: `⇀` marks that graphs outside the Core compilation domain — those carrying non-radio question shapes (§13.1) — have no image. Write `dom(⟦·⟧_Core)` for the graphs on which it is defined. Where `⟦G⟧_Core` is defined it yields:

```text
IR = (Nodes, Edges, Guards, Shapes)
```

- Nodes → symbolic constants (`Q_i`, `C_j`)
- Edges → `(s, t, g_k)`
- Guards → `(id, expr)`
- Shapes → typed domains

**Invariant.** IR is a deterministic encoding of graph *structure*, not semantics. The compiler is specified to preserve adjacency, identity via `Guard.id`, deterministic ordering, and node typing. That claim is an implementation invariant with test evidence in Appendix B, not a proved isomorphism.

The product object may be called a `DecisionTree`, but the validated source can contain converging paths and shared downstream nodes. The mathematical source is therefore a DAG. The distinction matters because a tree has a unique parent per non-root node; SMEme does not require that restriction.

**Interpreted shapes.** Core IR admits only `radio` question shapes. Source-level `checkbox` and `text` questions lie outside the current compilation domain; see §13.1.

## 3. Canonical guard domain

A guard is the branching condition attached to a directed arc. For an arc leaving a radio question, a non-default guard names the option that activates that arc. A default guard is unconditional.

Each IR edge retains its own guard identity even when two guard expressions have the same interpretation. Canonicalization identifies semantic equivalence without collapsing those structural identities:

```text
canon : GuardSyntax → GuardNormalForm
g₁ ~ g₂  ⟺  canon(g₁) = canon(g₂)
GuardDomain = GuardSyntax / ~
```

Write `[g]` for the equivalence class of guard expressions that share the canonical form of `g`. Core's guard classes are radio-option classes and the default class.

**Current Core `canon`.** There is no separate `canon()` API object. For radio guards today, canonicalization is strip of surrounding whitespace, with the empty string (after strip) identified with `DEFAULT_GUARD_EXPR` and hence with `⊤`, and every non-default expression required to be an exact member of the source question's option set. The quotient structure is retained so non-radio domains (§13.1) have a defined landing place.

Canonical form is question-independent: `[Yes]` is one class wherever it occurs. Its *interpretation* is not, because `Yes` on one question and `Yes` on another denote different option atoms. Three levels are therefore distinct and should not be conflated — guard **identity** is per-arc, guard **canonical form** is question-independent, and guard **meaning** is scoped to the source question. §5 supplies the interpretation map that carries that scope.

The default class supplies the distinguished unconditional element:

```text
⊤ := [DEFAULT_GUARD_EXPR]
```

This `⊤` is an unconditional **edge condition**. It does not identify or activate the entry node; entry reachability is established separately in §6.

## 4. Validation and closure of the compilation domain

Closure is established in two stages, by two distinct predicates over two distinct objects:

```text
validate_graph : DecisionDAG → {valid, errors}
validate_ir    : IR          → {valid, errors}
```

Neither is sufficient alone. Some obligations are stated over the source graph and are not re-derived from IR; a standalone IR can satisfy `validate_ir` and still violate them.

### 4.1 Source validation

Write `SourceValid(G)` when `validate_graph(G) = valid`. `validate_graph` enforces more than this specification requires; its authoring and publication rules are outside scope. This subsection claims only the compilation-relevant consequences of that predicate — not publication blocking or Deploy readiness (those live in §11). The **compilation-relevant consequences** of `SourceValid(G)` are:

1. the graph has exactly one entry node, defined as the unique node with no incoming arc;
2. that entry node is a `QUESTION`;
3. conclusions are terminal — no arc leaves a `CONCLUSION` node; and
4. every arc into a `CONCLUSION` carries a non-default guard.

`SourceValid` is therefore defined by reference to `validate_graph`, not by this list. The list states the four consequences on which §§5–6 depend, and Appendix B cites tests establishing them.

Conditions 2 and 4 carry logical weight and are not stylistic. Under §6, compilation asserts `reach(r) ↔ ⊤`; a conclusion-rooted graph would therefore yield an unconditionally reachable conclusion, returned for every case without evidence. Under §5, a default guard compiles to `g_k ↔ ⊤`; a default arc into a conclusion would make that conclusion reachable whenever its source question is reached, with no discriminating answer selected.

**Derived, not checked.** Every conclusion has at least one incoming arc. This follows from conditions 1 and 2 — the sole zero-indegree node is a question, so no conclusion has indegree zero — and requires no separate validation condition.

### 4.2 IR validation

Write `IRValid(IR)` when `validate_ir(IR) = valid`. It establishes:

1. every node, edge endpoint, and guard reference resolves within IR;
2. every node shape and guard is well-typed and supported by Core;
3. every guard is canonical and, **paired with its source question**, lies in `dom(γ_Core)` — that is, `γ_Core(src(a), [τ_A(a)])` is defined for every arc `a`;
4. the IR has exactly one zero-indegree node; and
5. the IR is a DAG.

For a radio guard, an expression is vacuous if it contains only whitespace after stripping or is not an exact member of the source question's option set. `DEFAULT_GUARD_EXPR` (the empty expression) denotes `⊤` and is not vacuous.

### 4.3 Closure

```text
SourceValid(G)
  ∧ G ∈ dom(⟦·⟧_Core)
  ∧ IR = ⟦G⟧_Core
  ∧ IRValid(IR)          ⇒  Closed_Core(G, IR)

Closed_Core(G, IR)       ⇒  T(IR) is defined

¬SourceValid(G) ∨ G ∉ dom(⟦·⟧_Core) ∨ ¬IRValid(IR)
                         ⇒  no conforming compilation or query
```

The conjunct `IR = ⟦G⟧_Core` is load-bearing. Closure holds only for an IR compiled from *that* source-validated graph. Nothing in the IR is re-derived at query time to establish this; provenance is a deployment fact, not a checkable property of the artifact, and it is therefore part of the trusted base (§12). The definedness conjunct `G ∈ dom(⟦·⟧_Core)` is likewise a precondition of compilation, not a property recoverable from the IR afterwards.

**Outside the pipeline.** An IR constructed directly, without a source-validated graph, may satisfy `IRValid` while violating §4.1 — a conclusion-rooted IR is the clearest case. Such an object is not an unvalidated IR; it is outside the conforming two-stage pipeline, and no claim in this document applies to it.

Closure here means that every admitted construct already has a finite, defined translation: compilation requires no new symbols, guessed meanings, repaired references, or unsupported operations. It does **not** mean that the represented world is complete or that missing facts are false; see §7.2.

Acyclicity is a validation obligation, not an emergent property. The reachability encoding in §6 depends on it.

## 5. Boolean interpretation

Given validated IR, the guard component of compilation is interpreted by the map:

```text
γ_Core : Question × GuardDomain ⇀ Prop(Atoms)
```

Here `Prop(Atoms)` is the set of finite propositional formulas constructed from these atoms:

- `reach_v` — node `v` is reachable
- `g_k` — edge guard `k` is active
- `opt_{q,i}` — option `i` is selected for radio question `q`

**The map takes the source question as an argument.** A guard class alone does not determine an atom: `[Yes]` leaving `q₁` and `[Yes]` leaving `q₂` are the same class and must compile to different atoms. The source question supplies that scope:

```text
γ_Core(q, [A]) = opt_{q,A}     where A ∈ options(q)
γ_Core(q, ⊤)   = ⊤
```

`γ_Core` is partial: `γ_Core(q, [A])` is undefined when `A` is not an option of `q`. That undefinedness is the vacuity condition §4.2 rejects. Call this an **interpretation** (or guard encoding), not an embedding: the map is partial, it is not shown to be injective, and there are no guard operations for it to preserve.

Each edge retains its own guard atom `g_k`. For an edge `(s, t, g_k)` carrying guard expression `expr_k`, compilation asserts:

```text
g_k ↔ γ_Core(s, [expr_k])
```

| Guard on an edge leaving `s` | Compiled constraint |
|---|---|
| radio option `A` | `g_k ↔ opt_{s,A}` |
| default guard | `g_k ↔ ⊤` |

This is why guard identities remain structural while option meaning is question-scoped: `g_k` is per-arc, and the right-hand side is determined by the arc's source.

The reachability equations refer to `g_k`; these constraints supply each guard atom with its truth-functional meaning. The full compiler also adds the reachability and radio-cardinality constraints described below.

### 5.1 Reachability-scoped radio exclusivity

For each radio question `q` with options `opt_{q,1}, …, opt_{q,n}`, the compiled theory contains:

```text
reach(q) → ExactlyOne(opt_{q,1}, …, opt_{q,n})
```

The antecedent `reach(q)` scopes the exclusivity constraint to questions that are active in the represented case.

For a reachable but unanswered question, every admissible model assigns exactly one option. Different models may assign different options, allowing possibility and entailment queries to range over the unanswered question's possible completions.

For an unreachable question, this axiom imposes no constraint on its option atoms. Although a total valuation still assigns those atoms truth values, they cannot transmit reachability because every outgoing reachability term from `q` also requires `reach(q)`.

Replacing the implication with an unconditional `ExactlyOne` would produce a different theory: questions on dead branches would constrain the model space and could turn otherwise irrelevant conflicting assignments into case-level inconsistency. The compiler must therefore preserve the reachability-scoped implication.

When `reach(q)` is false, the implication is satisfied regardless of the option atoms. This is intentional: it preserves models by imposing no radio-cardinality constraint on an inactive question. It is distinct from vacuous entailment from an unsatisfiable working base, which §8 classifies as inconsistency rather than reporting as entailment.

### 5.2 Truth-functional semantics

A valuation `ν` is a complete truth assignment: it assigns every propositional atom either false (`⊥`) or true (`⊤`):

```text
ν : Atoms → {⊥, ⊤}
```

The ordinary classical truth tables uniquely extend this atomic assignment to every compiled formula built with `¬`, `∧`, `∨`, `→`, and `↔`.

Let `F` denote any finite propositional formula produced by compilation or constructed for a query over the compiled theory. Write `ν ⊨ F`, read “`ν` satisfies `F`,” when `F` evaluates to `⊤` under `ν`. Therefore:

```text
SAT(F)   ⟺ ∃ν . ν ⊨ F
UNSAT(F) ⟺ ¬(∃ν . ν ⊨ F)
```

## 6. Reachability semantics

Validation requires exactly one entry node `r`, defined as the unique node with no incoming arc. Compilation asserts:

```text
reach(r) ↔ ⊤
```

Each guarded IR edge is a triple:

```text
(s, t, g_k) ∈ Edges
```

where `s` is the source node, `t` is the target node, and `g_k` is the edge's guard-activation atom.

For every non-entry node `t`, compilation asserts:

```text
reach(t) ↔ ⋁ { reach(s) ∧ g_k : (s, t, g_k) ∈ Edges }
```

Thus, `t` is reachable exactly when at least one incoming edge has both a reachable source and an active guard. Where multiple incoming edges converge on `t`, any one satisfied incoming term is sufficient to make `t` reachable.

Because validated IR is a finite DAG with exactly one zero-indegree node `r`, every node is topologically reachable from `r`. Therefore, in any model of `T(IR)`, `reach(v)` being false means that every directed path from `r` to `v` is excluded by at least one inactive guard — not that `v` is disconnected from the entry node.

The graph-theoretic direction from `s` to `t` may be written informally as `s → t`. In that usage, the arrow denotes a directed graph arc, not logical implication. Logical implication appears only inside formulas such as the reachability-scoped constraint in §5.1.

Because validated IR is acyclic, these equations admit a unique reachability valuation once the guard atoms are fixed. That valuation can be computed in topological order; no recursive fixed-point interpretation is required.

The solver may still search over unanswered option atoms. The reachability equations ensure that node reachability cannot vary independently of the entry node, the selected options, and the guarded incoming edges.

The compiled theory `T(IR)` is the finite conjunction of these reachability equations, the guard interpretations in §5, and the reachability-scoped radio constraints in §5.1. It is a quantifier-free propositional theory fixed for each deployed artifact.

## 7. Evidence, assumptions, and admission staging

| Layer | Symbol | Content |
|---|---|---|
| Theory | `T(IR)` | Guard interpretation, reachability equations, and reachability-scoped radio cardinality |
| Evidence | `E` | Admitted unit literals on radio option atoms |
| Assumptions | `φ` | Constraints on node reachability: `⋀ reach(n_i) ∧ ⋀ ¬reach(m_j)` |

Working bases:

```
B_E = T(IR) ∧ E
B_φ = T(IR) ∧ E ∧ φ
```

Consequence queries operate over `B_φ`.

On the public radio-answer path, an admitted answer contributes a positive literal for the selected option and negative literals for the non-selected options. An unanswered question contributes no option literals.

**IR option string is canonical.** When option labels on a question are unique under case-insensitive comparison, admission matches answers case-insensitively (`strip` + `.lower()`), then binds each admitted answer to the matching **IR option label**. Projection and Z3 atoms use that IR casing. Guard membership remains exact against the same IR labels. The remapping direction — admitted input normalized to the IR string — is what makes case-insensitive admission consistent with exact guard membership rather than contradictory. See Appendix A for the case-colliding-options non-obligation.

### 7.1 Staging

Validation and semantic consistency occur at different stages. The distinction is normative because the outcome names are similar.

```text
candidate evidence
    ↓  admission
admitted E
candidate assumptions
    ↓  syntactic conflict validation     →  conflicting_assumptions
admitted φ
    ↓
target-bearing consequence query over B_φ
    ├─ SAT   → witness-backed possible / not_entailed
    └─ UNSAT → consistency disambiguation on the exact B_φ
                    ├─ SAT(B_φ)   → entailed / impossible
                    └─ UNSAT(B_φ) → semantic cause ladder (§8.3)
                                      ├─ answers_inconsistent
                                      └─ assumptions_inconsistent
```

`conflicting_assumptions` is a **pre-admission validation result**. It is not a cause in the §8.3 ladder and must never be emitted by it. The report kind `sources_conflict` is reserved for a deferred natural-language evidence path (§13.3); Core defines a mapping for it but has no emitter on the shipped admission path.

The diagram is intentionally query-first. The cause ladder is not a preliminary runtime sequence; it is invoked only after the target-bearing query returns UNSAT and consistency disambiguation shows that the working base itself is unsatisfiable.

### 7.2 Closed formal fragment, not a closed-world assumption

The atom space is finite, admissible guard expressions are fixed by `dom(γ_Core)`, and no runtime input introduces a new proposition. That is closure of the **language**.

It is not a closed-world assumption. An unanswered radio question contributes no unit literal to `E`. It is not thereby false, and no option atom is thereby false:

```text
unanswered  ≡  no answer admitted into E
            ≢  no option is true in the represented world
```

Where `q` is reachable and unanswered, each model of a consistent `B_φ` assigns exactly one option to `q`; different models may assign different options.

An admitted single radio answer for an unreachable question is reachability-inert: it does not by itself make an otherwise consistent working base unsatisfiable and cannot activate any descendant, because every outgoing reachability term also requires `reach(q)`. Core does not treat such an answer as an admission error.

**Consequence under evidence extension.** If `E⁺ = E ∧ Δ` adds admitted literals without retracting or replacing any literal, every model of `T ∧ E⁺ ∧ φ` is a model of `T ∧ E ∧ φ`. Adding conjunctive evidence eliminates models and never restores eliminated ones, so classical consequence is monotonic under that relation.

Changing an answer is different: it retracts or replaces a literal rather than merely adding one. No monotonicity claim transfers across that operation; §9 classifies it as a replaced base.

**Entailment under incomplete evidence is legitimate.** If a conclusion holds under every completion, it is entailed and must be reported as entailed — not as a request for more information. This is the evidence-sufficiency result: the unanswered question demonstrably does not bear on the conclusion.

## 8. Consistency and consequence

### 8.1 Semantic condition

Write `Cons(B) ⟺ SAT(B)`. Let `p` denote the proposition being queried, typically `p = reach(c)` for a target conclusion `c`. Then:

```text
Entailed(B, p)     ⟺  Cons(B) ∧ UNSAT(B ∧ ¬p)
Refuted(B, p)      ⟺  Cons(B) ∧ UNSAT(B ∧ p)
Undetermined(B, p) ⟺  SAT(B ∧ p) ∧ SAT(B ∧ ¬p)
Inconsistent(B)    ⟺  UNSAT(B)
```

The reachability surface reports `impossible` where the four-case vocabulary says `refuted`; they are the same relation under two names:

```text
Impossible(B, p) ⟺ Refuted(B, p)
```

**`Cons(B)` is a condition on what may be reported, not an instruction to issue a preliminary solver call.** Classical entailment from an unsatisfiable premise set is vacuous; SMEme retains classical explosion as a semantic fact and declines to report it as a decision result.

`inconsistent` is a **metalevel case status**, not a fourth object-language truth value. The object logic is classical two-valued propositional logic.

### 8.2 Witness-first evaluation

A model of `B ∧ p` or `B ∧ ¬p` is also a model of `B`. An UNSAT result for the larger formula does not establish whether `B` itself is satisfiable. Therefore the consequence query runs first, and consistency is disambiguated only on UNSAT.

**Entailment.** Check `SAT(B ∧ ¬p)`.

| Result | Status |
|---|---|
| SAT | `not_entailed` — the countermodel also proves `SAT(B)` |
| UNSAT | check `Cons(B)`: SAT → `entailed`; UNSAT → cause ladder |
| unknown / timeout / budget | operational status (§8.4) |

**Possibility.** Check `SAT(B ∧ p)`.

| Result | Status |
|---|---|
| SAT | `possible` — the witness also proves `SAT(B)` |
| UNSAT | check `Cons(B)`: SAT → `impossible`; UNSAT → cause ladder |
| unknown / timeout / budget | operational status (§8.4) |

**Ordinary completed-query cost.** On a consistent base, and absent timeout, `unknown`, or budget exhaustion, a SAT-witness answer takes one solver call. An UNSAT-backed logical answer takes the target-bearing call plus a consistency call. Thus `possible` and `not_entailed` take one call, while `entailed` and `impossible` take two.

Those are the normal successful paths, not worst-case totals. If consistency disambiguation discovers an inconsistent base, attributing the first failing prefix can require additional checks of `T`, `B_E`, and `B_φ`. The semantic contract determines what may be reported; it does not require a uniform pre-gate or a fixed number of calls for every outcome.

**Witness scope.** A witness proves `SAT` only for the exact base it was found over — the same `T`, `E`, `φ`, artifact identity, and assertion state. A witness obtained under any different base proves nothing about the current one.

### 8.3 Cause ladder

When a target-bearing query returns UNSAT, SMEme checks the consistency of its exact working base. If that base is also UNSAT, the cause is the **first failing admitted prefix**:

| Step | Condition | Result |
|---|---|---|
| 1 | `UNSAT(T)` | artifact-integrity failure (§11) — not a case status |
| 2 | `SAT(T)` ∧ `UNSAT(B_E)` | `answers_inconsistent` |
| 3 | `SAT(B_E)` ∧ `UNSAT(B_φ)` | `assumptions_inconsistent` |

Where `E` is empty the ladder collapses to `SAT(T) → SAT(T ∧ φ)`, and failure at the second step is `assumptions_inconsistent`.

**The cause must never be inferred from whether `E` or `φ` is non-empty.** Every `inconsistent` status carries a cause drawn from this ladder; no path may return `inconsistent` with a null or unrecognized cause.

### 8.4 Operational statuses

Solver `unknown`, timeout, and budget exhaustion are operational results. They are disjoint from logical statuses, with this precedence:

1. budget exhausted before a solver call → `budget`
2. a direct Z3 `unknown` on a bounded consequence check → `timeout`
3. an independently surfaced operational `unknown` → `unknown`
4. target-bearing query returns `unsat` → consistency disambiguation; invoke the cause ladder only if the exact base is also `unsat`

A query that did not complete has determined nothing. If the first consequence check returns UNSAT and the consistency disambiguation then returns an operational status, the result is that operational status — never `entailed`, `impossible`, or `inconsistent`.

Operational results do not establish SAT or UNSAT and must not be reused as if they did.

### 8.5 Target validation

A target that is not a declared node of the deployed IR, has no corresponding reach atom, or has the wrong node kind for the requested mode is a domain error, raised before any solver call. Without that boundary, an unknown or stale identifier could produce a lookup failure or a misleading logical result rather than an explicit statement that the query is outside the deployed language.

## 9. Candidate relations

Every query that varies its premises falls into exactly one of three classes. The class determines where consistency is established.

| Class | Premise change | Policy |
|---|---|---|
| **Unchanged** | base fixed | Witness-first; disambiguate on UNSAT |
| **Weakened** | `S ⊆ E`, literal subconjunction | Consistency inherited — establish once |
| **Replaced** | `E ↦ E′` | Independent per candidate; nothing inherited |

**Lemma 1 (weakening).** `E` is a conjunction of unit literals. For `S ⊆ E`, every model of `T ∧ E ∧ φ` is a model of `T ∧ S ∧ φ`. Hence `SAT(T ∧ E ∧ φ) ⇒ SAT(T ∧ S ∧ φ)`.

The literal-subset invariant `Lit(S) ⊆ Lit(E)` is enforced at runtime, not only in tests. If a shrink step re-encodes or normalizes rather than dropping literals, the inheritance is unsound and the implementation fails loudly rather than continuing.

**Lemma 2 (replacement).** Repair maps `E ↦ E′` by changing answers, so `E′` is not a subconjunction of `E` and Lemma 1 does not transfer:

```text
SAT(T ∧ E ∧ φ) ⇏ SAT(T ∧ E′ ∧ φ)
```

Where `φ ≠ ∅`, a candidate edit can render `T ∧ E′ ∧ φ` unsatisfiable — for example, an answer that makes a `force_reachable_ids` node unreachable.

**Rule for future modes.** Classify at design time. The classification determines the policy; no mode is exempt. Inquire (§13.9) is a target mode: each `ANALYZE` is Unchanged on its current base; conjunctive `ACQUIRE` extends `E`; `REBASE` is Replaced.

## 10. Query modes

All modes query the same `T(IR)`. Their consistency policy follows §8.2 and §9. These query modes do not necessarily correspond one-for-one with public endpoints: some are selectable modes or assumption parameters on a broader tool. Inquire — evidence-demand over a growing admitted base — is specified in §13.9 and is **not** a shipped surface.

| Mode | Base | Public surface | Notes |
|---|---|---|---|
| **Apply** | `B_E`, or `B_φ` when assumptions are composed | `smeme_reasoning_evaluate` | Case evaluation; conclusion-uniqueness check yields `multiple_outcomes_possible` |
| **Compare** | `B₁`, `B₂` | `smeme_reasoning_what_if` | **Per side.** Each side has its own base; a witness for one proves nothing about the other |
| **Entail** | `B_φ` | `smeme_reasoning_how_to_reach` with `reach_mode="entailed"`; also used by path and support analysis | Witness-first per §8.2 |
| **Possible** | `B_φ` | `smeme_reasoning_how_to_reach` with `reach_mode="possible"` | Witness-first per §8.2; shipped as a mode, not a separate endpoint |
| **Path under edit** | `T ∧ E′ ∧ φ` | `smeme_reasoning_edit_affects_path` | Independent per `E′`; baseline path must already be entailed (`path_not_entailed_at_baseline` otherwise) — operational product gate, not a semantic axiom |
| **Repair** | `T ∧ E′_k ∧ φ` | `smeme_reasoning_how_to_reach` | **Per candidate** (Lemma 2) |
| **Minimal sufficient evidence** | `T ∧ S ∧ φ`, `S ⊆ E` | `smeme_reasoning_decisive_support` | Establish consistency once at full `E` (Lemma 1) |
| **Assume** | working base plus `φ` | `force_reachable_ids` / `force_unreachable_ids` on evaluation and analysis tools | Shipped as optional reachability constraints, not a separate endpoint; at most `MAX_ASSUMPTION_NODE_IDS` (= 32) ids — operational bound, not a semantic axiom |

### 10.1 Uniqueness — two distinct objects

| Object | Location | Failure surface |
|---|---|---|
| Radio exclusivity (§5.1) | axiom **in** `T(IR)` | can contribute to `answers_inconsistent` when the question is reachable |
| Conclusion uniqueness | **query** over the working base, `B_E` or `B_φ` | `multiple_outcomes_possible` |

Conclusion uniqueness is not detected merely by observing two true conclusions in one model. After a model with exactly one true conclusion is found, Apply probes for an **alternate model** under the same working base by asserting `¬reach(c)` for that sole conclusion. If the probe is SAT, another conclusion remains possible and the surface reports `multiple_outcomes_possible`.

### 10.2 Compare

Compare always returns both side reports and a structural report `delta`. Each side retains its own `result_kind` (including `answers_inconsistent` or `assumptions_inconsistent` when that side's working base is unsatisfiable). A witness for one side proves nothing about the other.

The `delta` is a **structural report diff** (changed answers, headline/outcome flags derived from the reports), not a logical comparison between two valid outcomes.

**Consumer guidance (not enforced by Core):** when either side is inconsistent, do not interpret the delta as an outcome transition. The shipped contract does not refuse or omit the delta in that case; refuse-Δ remains a target capability (§13.6).

### 10.3 Repair

Each replacement candidate has its own working base and must be evaluated independently. Mode determines the ordinary acceptance cost:

- **Possible-mode acceptance** — `SAT(B′_k ∧ p)` accepts in one call; the witness proves the candidate's base consistent.
- **Entailment-mode acceptance** — `UNSAT(B′_k ∧ ¬p)` does not prove `SAT(B′_k)`. Acceptance requires a consistency check afterward. Accepted entailing candidates are **not** one-call.

An inconsistent candidate is **discarded**: it does not enter `plans[]`, is never reported as reaching or entailing the target, and is never presented as a valid repair.

**Rejection is silent.** No public cause is surfaced for a discarded candidate; `plans[]` is simply empty of it. See §13.4.

Accordingly, an empty `plans[]` does not by itself distinguish an inconsistent candidate from an otherwise unsuccessful search candidate. The shipped contract guarantees that an invalid candidate is not presented as a repair; public rejection attribution remains a target capability.

### 10.4 Minimal sufficient evidence

`decisive_support` returns inclusion-minimal answered supports that still force `reach(c)`, in worksheet vocabulary — question ids and options only. It does not change `E` or `T`.

It is **not** abduction. Abductive inference from incomplete or conflicting evidence would map to Apply outcomes and to Possible / Repair probes. `decisive_support` searches only `S ⊆ E` with `T` and `E` fixed.

It is the evidence-atom projection of the minimality problem, not an algebraic minimal decisive support over `Reach × GuardDomain × Evidence`. Repair plans are cardinality-minimal edits in normalized answers, not proof objects. See §13.2.

## 11. Theory integrity

An unsatisfiable theory under empty `E` and empty `φ` is a compiler or graph defect, not a case outcome. Deploy further requires every declared conclusion to be existentially reachable. The **logical** Deploy obligation is:

```text
LogicalDeployReady(G, IR)  ⟺
    Closed_Core(G, IR)
    ∧ SAT(T(IR))
    ∧ ∀c ∈ Conclusions(IR). SAT(T(IR) ∧ reach(c))

LogicalDeployReady(G, IR)           ⇒  logically eligible for Deploy
¬SAT(T(IR))                         ⇒  Deploy fails (THEORY_UNSAT)
SAT(T(IR)) ∧ ∃c. UNSAT(T ∧ reach(c)) ⇒  Deploy fails (DEAD_CONCLUSION)
```

`LogicalDeployReady` is necessary for Deploy; it is not sufficient for product publication. Other nonlogical publication checks (regression fixtures, authoring contracts, evidence-contract machinery, etc.) remain outside this predicate.

The universal conclusion check is shipped conclusion feasibility, distinct from the target per-option feasibility analysis in §13.5. Both `SAT(T)` and dead-conclusion obligations discharge at Deploy (`publish_readiness`). Runtime on published artifacts assumes step 1 of §8.3 has passed; encountering `UNSAT(T)` at query time is an integrity failure, never `answers_inconsistent`.

### 11.1 Publication boundary and theory establishment

Public runtime **trusts the publication boundary**: successful Deploy has established `LogicalDeployReady` (among any additional product checks) for the published artifact. Query paths do not perform identity-triple lookup or mismatch refusal against a persistent validation record.

The natural identity for a future persistent validation record remains the triple:

```text
(artifact_hash, ir_format_version, compiler_version)
```

Helpers that match that triple and assert establishment exist and are unit-tested, but **no query-time identity-record lookup is wired**. Low-level consequence helpers default `sat_t_established=True`, treating the publication (or caller) obligation as already discharged. Callers may set `sat_t_established=False` to force request-local `SAT(T)` recomputation; that opt-in is not selected automatically by production query paths. Runtime identity-triple enforcement is a target capability (§13.7).

Changing `E` or `φ` does **not** invalidate `SAT(T)`, because those premises are not part of `T`; it does invalidate every witness or consistency conclusion about the working base `B_φ`. That distinction is what Probe 4 in Appendix B protects.

## 12. Trusted base

The **trusted base** is the set of components whose correctness the formal guarantees presuppose. Those guarantees attach to specific stages of a longer pipeline:

```text
decision source → candidate graph → source-validated graph → validated IR → compiled theory
case sources → candidate evidence → admitted evidence → projected facts
selected published artifact → trusted publication boundary (§11.1)

(compiled theory, projected facts, publication boundary) → consequence query
```

The guarantees begin only after source validation, IR validation, evidence admission, and selection of a published artifact under the trusted publication boundary. They do not certify the fidelity of the upstream transformations or the correctness of artifact selection. No query-time identity-record validation ships.

**Obligations discharged by pipeline discipline rather than by types.** Three preconditions are enforced procedurally and are not encoded in any object the runtime inspects:

- `compile_ir_to_z3` is a trusted internal primitive whose precondition is `IRValid(IR)`. Its argument type does not encode proof that validation succeeded. Public and first-party reasoning paths discharge that obligation before invoking it; direct invocation with unvalidated IR is outside this specification's guarantees.
- The conjunct `IR = ⟦G⟧_Core` for a source-validated `G` is a deployment fact. A deployed artifact carries an IR; it does not carry a checkable proof of that IR's provenance, and nothing at query time re-derives the §4.1 source obligations.
- Consequence helpers default `sat_t_established=True`, asserting that `SAT(T)` has already been established. Only Deploy (or an explicit caller setting `sat_t_established=False` and accepting request-local recomputation) discharges that obligation. A caller that reaches those helpers with never-Deployed IR under the default trusts an obligation nobody discharged — the same unencoded-precondition pattern as the two bullets above.

All three are trusted, not verified. They are named here rather than assumed.

**Inside the trusted base:**

- the Z3 solver;
- the source-graph validator, the IR validator, and the compiler;
- the provenance of the deployed IR — that it was produced by `⟦·⟧_Core` from a source-validated graph (§4.3);
- evidence and assumption admission validation;
- fact projection from admitted answers onto option atoms;
- witness-first query orchestration, consistency attribution, and status mapping; and
- the publication boundary that establishes `LogicalDeployReady` at Deploy (§11).

**Outside the trusted base, and not certified by any claim in this document:**

- **Formalization.** Whether the compiled theory expresses the decision its author intended. Validation checks well-formedness, not fidelity.
- **Evidence extraction.** Whether an admitted answer accurately reflects its source material. This process is typically language-model mediated and is the largest uncertified surface.
- **Scope selection.** Whether the selected artifact is the correct microtheory for the case. Provenance and solver acceptance do not establish that the selected theory governs the matter under consideration.

**What the consistency ladder does and does not catch.** Joint consistency detects admitted facts whose combination conflicts with the theory or with other admitted evidence. A coherent but factually incorrect extraction remains satisfiable and is therefore invisible to the ladder. Provenance, source inspection, admission policy, and human review address fidelity; consistency checking detects incoherence after formalization.

The guarantees are therefore conditional: given the selected theory, admitted evidence, and admitted assumptions, Core can certify the stated logical relation. The calculus does not certify that humans or language models selected and formalized the correct premises.

**Boundary support, not certification.** Publish-time evidence-contract machinery can bind vocabulary and provenance metadata to an artifact. It supports inspection and stable admission interfaces; it does not perform natural-language grounding or certify that a proposed fact is true.

---

# Part II — Target

The capabilities in this part are not implemented and have no conformance rows. A subsection may name a shipped prerequisite from Part I to make the remaining gap precise; that contrast does not make the target capability normative.

## 13. Not shipped

**13.1 Non-radio shapes.** Extending the IR, validation rules, compiler, and evidence projection to `checkbox` finite-selection domains and canonical `text` domains. These source-level shapes are outside the current Core IR and are rejected rather than carried as uninterpreted guards.

**13.2 Proof-relevant interpretation.** Independently checkable UNSAT certificates, full derivation traces, guard-labeled DAG cutsets, and algebraic minimal decisive support over `Reach × GuardDomain × Evidence`. Shipped SAT models and worksheet projections are not such proof objects.

**13.3 Natural-language evidence grounding.** Grounding a natural-language blob into admitted facts through frozen bindings. The shipped evidence-contract machinery described in §12 records the boundary but does not perform this grounding. The report kind `sources_conflict` is reserved for a future pre-admission process that detects incompatible source claims before forming `E`; Core currently defines a report mapping but has no emitter for that condition.

**13.4 Repair rejection attribution.** Distinguishing, on the public surface, whether a discarded candidate was rejected for evidence inconsistency or assumption incompatibility. The shipped behavior remains silent discard (§10.3).

**13.5 Authoring-quality analysis.** Two publish-time warnings, not Deploy failures, that should be introduced together:

- *Option feasibility* — `SAT(T ∧ reach(q) ∧ opt_{q,i})` per option. An infeasible option may indicate dead authoring logic, though it can be intentional. Distinct from shipped conclusion feasibility (`DEAD_CONCLUSION`) in §11.
- *Determinacy* — whether every complete admissible assignment yields exactly one conclusion. Acyclicity bounds the encoding; it does not make the theory functional.

**13.6 Compare refuse-Δ.** Omit or refuse the ordinary structural `delta` when either Compare side is inconsistent, and surface which side failed. Shipped Compare always emits the delta (§10.2).

**13.7 Runtime identity-triple enforcement.** Query-time match of `(artifact_hash, ir_format_version, compiler_version)` against a persistent Deploy validation record, with mismatch refusal. Helpers exist; public query paths do not invoke them (§11.1).

**13.8 Case-unique option validation.** Reject or normalize question option sets that collide under case-insensitive admission matching. Closes the Appendix A non-obligation on colliding options.

**13.9 Inquire (evidence-demand).** A query that allocates the next isolated, outcome-blind extraction over the deployed artifact's frozen worksheet vocabulary, given the formal consequences of the current admitted base. It does not retrieve evidence, assess truth, or perform probabilistic inference. Extraction and verification remain outside the trusted base (§12). No public endpoint, MCP contract, or conformance row ships (yet).

Throughout §13.9, `B` denotes the **fully composed** working base: `T ∧ E` when `φ` is empty, and `T ∧ E ∧ φ` (`B_φ`) when assumptions are composed. `Resolved`, `S_R`, `D_1`, and `Resolvable` are predicates of this `B`. Minimizing admitted evidence does not drop `φ`. Let `U` be the unanswered worksheet questions of the loaded artifact. Let `A_q` be the option set of question `q`. Let `C_poss(B) = { c | SAT(B ∧ reach(c)) }` and `C_ent(B) = { c | Entailed(B, reach(c)) }`. Worksheet assignments admitted in `E` are pairs `(q, a)`; `proj(q, a)` is their Stage B unit-literal image. The epistemic object is the worksheet pair, not an individual projected literal.

Normative start is `E = ∅`. Bulk initial extraction over the full worksheet is an optional latency heuristic, not the algorithm. Inquire constructs `E` on demand. Each issued extraction is a **singleton**: the stochastic extractor receives one question stem and its options, and does not receive the conclusion space, `result_kind`, why the question was selected, a prior answer or citation, sibling questions from the same support or witness, or whether the call is verification or acquisition.

### 13.9.1 Resolution

```text
Resolved(B)  ⟺  Cons(B) ∧ C_poss(B) = C_ent(B) = {c}
```

for a unique conclusion `c`. Entailment of some conclusion is not resolution. Joint entailment or co-reachability of two conclusions is not resolution. Shipped Apply `SAT_UNIQUE` is not a substitute: a witness with exactly one true conclusion `c` and `UNSAT(B ∧ ¬reach(c))` does not imply `C_poss(B) = {c}`, because another conclusion may remain possible in a model that still satisfies `reach(c)`. Tightening Apply to this property is a separate Part I candidate; Inquire uses the property, not the first-model shortcut.

A legitimate final **set** of jointly entailed conclusions is not a shipped Apply outcome (`SAT_AMBIGUOUS` is unresolved). `Resolved` and `S_R` must change together if that product status is ever added.

### 13.9.2 Minimum-cardinality resolving worksheet support

When `Resolved(B)` holds with unique `c`, write `B_S` for the base that retains `φ` and replaces `E` by a candidate subset `S` of admitted worksheet assignments:

```text
B_S  =  T ∧ φ ∧ ⋀{ proj(q,a) | (q,a) ∈ S }

S_R(B) ∈ arg min_{S ⊆ admitted worksheet assignments of E} |S|
          s.t.  Resolved(B_S)
```

Equivalently, `C_poss(B_S) = C_ent(B_S) = {c}` for that same `c`. Ties break by stable worksheet-id order. Minimum cardinality implies inclusion-minimality; this is not a MUS and is not named as one.

Entailment support `T ∧ S ⊨ reach(c)` is **not** enough. A subset may still force `c` while leaving another conclusion possible, so `¬Resolved(B_S)`. VERIFY of that subset would confirm premises sufficient for entailment, not premises sufficient for the resolved decision state. Shipped `decisive_support` computes entailment support under fixed `T` and `E` (§10.4) and is not a substitute for `S_R`.

One such `S_R(B)` is enough. If every member satisfies verification policy, the worksheet assignments constituting a formally resolving support have passed `P_v`, and the case may STOP. Core, not `P_v`, is what established `Resolved(B_S)`. If a member fails, rebase and reanalyze rather than treating `c` as unsupported.

### 13.9.3 Myopic discrimination

```text
q ∈ D_1(B)  ⟺  q ∈ U ∧ ∃ o, o' ∈ A_q.
                 C_poss(B ∧ q=o) ≠ C_poss(B ∧ q=o')
```

SAT already ranges over the other free variables. `D_1(B) = ∅` means no one-step question currently changes the possible-conclusion set. It does **not** mean remaining evidence cannot settle the case.

### 13.9.4 Residual resolvability and resolving witnesses

Let `Ω(U)` be the admissible **consistent full completions** of `U`: assignments `α` of every `q ∈ U` to a member of `A_q` such that `Cons(B ∧ α)`.

```text
Resolvable(B, U)  ⟺  ∃ α ∈ Ω(U). Resolved(B ∧ α)
```

Quantifying over full completions is enough. If a partial assignment already yields `Resolved`, conjunctive evidence extension (§7.2) preserves the unique entailed conclusion and keeps every other conclusion impossible, so some resolving full completion exists.

Three objects remain distinct:

| Object | Meaning |
|---|---|
| `D_1(B)` | immediately discriminating questions |
| `(D, α_D)` | a **resolving witness**: `D ⊆ U` and `Resolved(B ∧ α_D)` |
| `Resolvable(B, U)` | existence of at least one resolving full completion |

A resolving witness is stronger than a joint discriminator (two assignments to `D` that merely change `C_poss`). When `D_1(B) = ∅` and `Resolvable(B, U)` is true, the implementation may search for a small resolving witness internally and issue **one** `q ∈ D` as the next singleton acquisition. Changing `C_poss` is not the same as eventually resolving the case.

Semantic exhaustion is `¬Resolvable(B, U)`. Immediate when `U = ∅` and `¬Resolved(B)`. Related to, but not the same as, publish-time determinacy of `T` (§13.5): this predicate is case-level, relative to the current `E`.

Operational budget failure is not semantic exhaustion. Those statuses must never collapse:

```text
no_joint_discriminator_within_budget
    — the computation gave up; Resolvable is undecided

not_resolvable_by_remaining_evidence_vocabulary
    — ¬Resolvable(B, U) is proved; the frozen vocabulary cannot settle this base
```

How a solver establishes `Resolvable` (enumeration, SAT search, QBF, compilation) is not part of the definition.

### 13.9.5 Control protocol

```text
ADMIT → ANALYZE → { VERIFY | ACQUIRE | STOP }

ANALYZE
  if ¬Cons(B):                          STOP (inconsistent; §8.3)
  if Resolved(B):
        VERIFY S_R(B) serially, one unverified (q, a) at a time
        P_v says retain all members → STOP (verified resolved consequence)
        P_v says retract/replace     → REBASE → ANALYZE
  else if D_1(B) ≠ ∅:
        ACQUIRE one ranked singleton from D_1 → ADMIT → ANALYZE
  else if Resolvable(B, U):
        ACQUIRE one member of a resolving witness → ADMIT → ANALYZE
  else if ¬Resolvable(B, U) proved:
        STOP (not_resolvable_by_remaining_evidence_vocabulary)
  else:
        STOP (no_joint_discriminator_within_budget)
```

`VERIFY` before further `ACQUIRE` when `Resolved(B)` holds and `S_R(B)` is unverified: conjunctive extension cannot undo `Resolved(B)`; the threat is that a premise already in `S_R` does not deserve to remain.

Ranking among `D_1` (for example worst-case remaining `|C_poss|`) and later weighted-model-counting information gain are optimization, not semantics.

### 13.9.6 Verification policy and rebase

`Verified_{P_v}(artifact, q, a, p)` means worksheet assignment `(q, a)` under canonical provenance identity `p` has satisfied verification policy `P_v`. It does not mean `a` is true. Session state binds that tuple, including `P_v`'s version — not a bare `question_id`.

A verification procedure returns a result `r`. Logic does not map “second extractor failed” to retraction. `P_v` interprets `r`:

```text
P_v(r) = RETAIN                 → keep e in E
P_v(r) = RETRACT                → REBASE(E \ {e})
P_v(r) = REPLACE(e')            → REBASE((E \ {e}) ∪ {e'})
P_v(r) = INSUFFICIENT            → escalate or retry; do not modify E
```

`REBASE` discards `C_poss`, `D_1`, `S_R`, `Resolved`, and every witness computed from the old base (Probe 4). Retract and replace are Replaced bases (§9 Lemma 2), not conjunctive extensions. What constitutes sufficient verification remains outside the trusted base (§12).

### 13.9.7 Non-goals

Inquire is not Apply, Compare, Repair, or `how_to_reach`. Target-directed search would contaminate acquisition with outcome information. It is not natural-language blob grounding (§13.3). It does not extend `T(IR)` or the worksheet vocabulary at query time.

**13.9.8 Target goldens.** Worked examples a future implementation must satisfy are in [`decision-dag-calculus-inquire-goldens.md`](./decision-dag-calculus-inquire-goldens.md). They are not Part I conformance and do not ship.

---

# Part III — Informative

## 14. Correction record

**v1.2 (this revision).** Adds target Inquire (§13.9): resolution over the whole conclusion space, minimum-cardinality **resolving** worksheet support `S_R` (not entailment support), myopic discrimination, residual resolvability by full completions, policy-relative rebase, and the evidence-demand control protocol. Working-base `B` is the fully composed `B_φ` throughout §13.9. Target goldens: [`decision-dag-calculus-inquire-goldens.md`](./decision-dag-calculus-inquire-goldens.md). A one-line §10 pointer and a §9 future-mode classification name the target without shipping it. Executable Part I obligations and Appendix B evidence are unchanged from v1.1 (tag `decision-dag-calculus-v1.1`).

**v1.1.** Retitles the document as a calculus rather than an algebra; moves the canonical path from `docs/spec/decision-dag-algebra.md` to `docs/spec/decision-dag-calculus.md`; replaces “Boolean embedding” with “Boolean interpretation”; records in §0.1 that the specification does not define DAG operations, algebraic laws, or a homomorphism. Executable Part I obligations and Appendix B evidence are unchanged. The first public snapshot remains tag `decision-dag-algebra-v1.0` (old path, at that commit).

**v1.0.** First public specification. Earlier drafts existed only in a private repository.

**Released Core images contained incorrect consequence behavior.** Releases `v0.9.9` and `v0.9.10` exhibited three defects on the consequence surfaces:

| Finding | Behavior | Direction |
|---|---|---|
| 1 | Entailment reported `entailed` for every target when the working base was unsatisfiable | vacuous false positive |
| 2 | Possibility reported `impossible` when the working base was unsatisfiable, conflating inconsistent premises with an unreachable target | confident false negative |
| 3 | Cause attribution inferred `assumptions_inconsistent` from non-empty `φ`, mislabeling cases where `B_E` alone was unsatisfiable | misattributed cause |

Findings 1 and 3 originate at different layers. The prior internal specification stated classical entailment without a consistency side-condition. Finding 1 conformed to that incomplete equation while remaining unsound as a decision-reporting contract. Finding 2 was an implementation defect not licensed by any reading of the prior text, and finding 3 was an attribution shortcut with no basis in it at all.

Corrected in production commit `C1` and locked by the additional coverage in `C2` and `C3` (Appendix B). Images built from those release tags retain the incorrect behavior until upgraded past `C1`.

The relevant discipline is not that the defects were avoided — they were not — but that the commitment was written down in a form specific enough for the defect to be locatable, that the correction is versioned, and that the affected surfaces were enumerated rather than described in general terms.

---

## Appendix A — Non-obligations

This document does not claim:

- that the compiled theory faithfully represents its author's intent (§12);
- that admitted evidence is factually accurate (§12);
- that the deployed artifact is the correct one for a given case (§12);
- that a decidable propositional fragment is expressively adequate for any particular domain;
- that consistency checking substitutes for human review;
- that option labels on a single question are unique under case-insensitive matching (see below);
- that compilation is a homomorphism of DAG or guard operations (§0.1, §5);
- that `γ_Core` is an embedding (injective or structure-preserving) into propositional formulas (§5);
- that IR is a proved isomorphism of the source graph (§2).

**Case-colliding options (defect in `E`, not in `T(IR)`).** When two options on one question differ only by case (for example `Yes` and `yes`), `T(IR)` still carries two distinct option atoms and remains faithful to those labels. Case-insensitive admission can nonetheless assert **both** atoms true in `E`, so `B_E` misrepresents the intended single answer. If the question is reachable, reachability-scoped `ExactlyOne` (§5.1) then makes the case inconsistent; if unreachable, the cardinality constraint is inactive. Closing this requires case-unique option validation (§13.8). This document does not certify single-answer projection under colliding options.

The expressiveness limit is deliberate. For a finite propositional theory, satisfiability and entailment are decidable. Given a valuation, checking whether it satisfies a finite encoded formula is linear in the size of that formula's representation. A satisfying valuation is therefore an independently checkable witness. Core does not currently retain an independently checkable UNSAT certificate and instead trusts Z3 for that result (§13.2).

These properties do not make SAT search itself linear or guarantee that a production solver will finish within an imposed timeout.

Operational `timeout`, `unknown`, and budget outcomes remain possible and are governed by §8.4. The fragment was chosen because its semantic contract is crisp and its witnesses are cheap to check, not because every solver run has a constant or linear cost.

## Appendix B — Conformance

The conformance baseline consists of ancestor-ordered commits on Core `main`. `C1` contains the production correction; `C2` and `C3` add permanent coverage without changing production behavior; `C4` is the squash-merged coverage commit for §4.1 source validation, structural Compare always-delta, and Deploy `THEORY_UNSAT` / `DEAD_CONCLUSION` entry-point codes ([PR #73](https://github.com/AristaLabs/smeme/pull/73)).

| ID | Role | Full commit |
|---|---|---|
| `C1` | Production semantics and primary regression suite | `4fd308e6e7b56277bbd13b4ddf0b7a5d88d882c0` |
| `C2` | Post-merge coverage: unpublished-theory handling, repair asymmetry, silent rejection, and UNSAT-then-operational outcomes | `92d3132b4861b6dcfb48c8d5d4968eb1fa0c51f5` |
| `C3` | Probe 4: no consistency or witness reuse across a working-base change within one request | `bdc0fc8d767569d2f41f0ab871644edf121cfae2` |
| `C4` | §4.1 `validate_graph` exact-message tests; Compare always-delta with one inconsistent side; Deploy `THEORY_UNSAT` / `DEAD_CONCLUSION` codes | `6ff0d455ec824ab553a649351467d8fb369f4bf5` |

### B.1 Normative traceability

Repository paths below are relative to SMEme Core. A commit reference identifies the immutable baseline containing the implementation and evidence; it does not imply that the named behavior was first introduced in that commit.

**Evidence rule.** Test evidence must exercise the path a caller actually reaches. Helper-only coverage is cited as such and does **not** discharge a public query-path or Deploy-path obligation. Unit tests that prove a policy helper is implementable are insufficient when the normative claim concerns a shipped entry point that never invokes that helper.

| Normative reference | Executable obligation or scope | Implementation evidence | Test evidence | Baseline |
|---|---|---|---|---|
| §§1–3, §4.2 | Deterministic DAG-to-IR mapping; typed guard closure; guards within `dom(γ_Core)`; exactly one zero-indegree node; acyclicity; reject invalid IR before solving | `smeme/reasoning/ir/dt_graph_to_ir.py`; `smeme/reasoning/ir/validate.py`; `smeme/reasoning/ir/types.py` | `tests/unit/reasoning/test_dt_graph_to_ir.py`; `tests/unit/reasoning/test_validate_ir.py` | `C1` |
| §4.1 | Exactly one entry node; entry is a `QUESTION`; conclusions terminal; arcs into conclusions non-default (`validate_graph` only) | `smeme/decision_tree/helpers/validation.py` (`validate_graph`) | `test_validate_graph_rejects_conclusion_as_entry_node`; `test_validate_graph_rejects_arc_leaving_conclusion`; `test_validate_graph_rejects_default_guard_into_conclusion` | `C4` |
| §§5–6 | Classical truth-functional interpretation; distinct edge-guard atoms with defining equivalences; reachability-scoped `ExactlyOne`; true unique entry; incoming-edge reachability recurrence | `smeme/reasoning/theory/guards_radio.py`; `smeme/reasoning/theory/compile_to_z3.py` | `tests/unit/reasoning/test_compile_to_z3.py`; `test_i_guarded_exactly_one_only_applies_when_question_reachable` | `C1` |
| §7 | Evidence projection with IR-canonical remapping (when options are case-unique); unanswered-option behavior; assumption admission; `conflicting_assumptions` pre-admission (not `sources_conflict`) | `smeme/reasoning/cevi/fact_projection.py`; `smeme/reasoning/runtime/canonical_facts.py`; `smeme/reasoning/runtime/input_validation.py`; `smeme/reasoning/runtime/assumptions.py` | `tests/unit/reasoning/runtime/test_evaluate_raw_answers_goldens.py`; `tests/unit/reasoning/runtime/test_assumptions.py` | `C1` |
| §8 | Four-case logical status; witness-first entailment and possibility; E-then-φ cause ladder; operational precedence; target domain validation | `smeme/reasoning/runtime/consistency_gate.py`; `smeme/reasoning/runtime/counterfactual.py`; `smeme/reasoning/runtime/evaluate.py` | `tests/unit/reasoning/runtime/test_vacuous_premise_gate.py`, including A-φ, A-E, A-attrib, E, F, J, collapse, one-call, and operational tests | `C1`, `C2` |
| §9 | Consistency inheritance only for literal-subset weakening; loud invariant failure; independent replacement candidates | `smeme/reasoning/runtime/decisive_support.py`; `smeme/reasoning/runtime/counterfactual.py` | `test_decisive_support_lit_invariant_fails_loudly`; repair force-kill and repair-mode tests; `test_probe4_no_stale_cons_across_base_change_within_request` | `C1`, `C2`, `C3` |
| §10 | Apply (incl. alternate-model uniqueness), Compare structural always-delta, entailment, possibility, path-under-edit, repair, decisive-support, reach-assumption surfaces | `smeme/reasoning/runtime/evaluate.py`; `smeme/reasoning/runtime/counterfactual.py`; `smeme/reasoning/runtime/path_under_edit.py`; `smeme/reasoning/runtime/decisive_support.py`; `smeme/mcp/reasoning_fastmcp.py` | `tests/unit/reasoning/runtime/test_counterfactual.py` (incl. `test_run_what_if_emits_delta_when_one_side_inconsistent`); `test_path_under_edit.py`; `test_decisive_support.py`; repair tests in `test_vacuous_premise_gate.py` | `C1`, `C2`, `C4` |
| §11 | `LogicalDeployReady`: Deploy-time `SAT(T)` (`THEORY_UNSAT`) and `∀c. SAT(T ∧ reach(c))` (`DEAD_CONCLUSION`); publication-boundary trust at query time | `smeme/reasoning/publish_readiness.py` (`assess_publish_readiness_sync`); `smeme/reasoning/runtime/analyze.py` | `test_theory_unsat_blocks_deploy_with_theory_unsat_code`; `test_dead_conclusion_blocks_deploy_with_dead_conclusion_code` in `tests/unit/reasoning/test_publish_readiness_fixtures.py`; identity helpers in `test_vacuous_premise_gate.py` are **helper-only** (§13.7) | `C4` |
| §12 | Guarantees attach after source validation, IR validation, evidence admission, and selection of a published artifact under the publication boundary; unencoded preconditions include `sat_t_established` default | `smeme/decision_tree/helpers/validation.py`; `smeme/reasoning/publish_readiness.py`; `smeme/reasoning/cevi/fact_projection.py`; `smeme/reasoning/published_evidence_contract.py`; scope declaration in this specification | `tests/unit/test_graph_entry_validation.py`; `tests/unit/reasoning/test_publish_readiness_fixtures.py`; `tests/unit/reasoning/runtime/test_evaluate_raw_answers_goldens.py`; `tests/unit/reasoning/test_published_evidence_contract.py`; CEVI contract tests | `C1`, `C4` |

Part I determines normativity. If an executable Part I obligation lacks corresponding implementation and test evidence here, that omission is a conformance defect in this document and should be reported rather than silently reclassified.

**Public specification.** Entry-point re-audit: [`decision-dag-calculus-entry-point-reaudit.md`](./decision-dag-calculus-entry-point-reaudit.md).

---

*Cite this document at an immutable commit or tag. Record the content hash externally — in the citing work or a release manifest — rather than inside the file, since an embedded hash cannot cover its own bytes.*
