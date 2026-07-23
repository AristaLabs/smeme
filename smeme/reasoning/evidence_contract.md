# Published evidence contract and CEVI (design)

This document fixes the **architectural contract** for **Phase 2+** evidence grounding: how unstructured (or semi-structured) text is encoded into the **published propositional language** \(\mathcal{L}\) of an IR artifact, without extending the theory at runtime.

## Terminology: CEVI induction vs CEVI runtime

**Do not** use “CEVI” as a single undifferentiated thing. In this repo it names **two** linked phases:

| Name | When | What it is |
| ---- | ---- | ---------- |
| **CEVI induction** | **Compile-time / pre-publish** (with or without an LLM assist) | Builds **`PublishedEvidenceContract`**: glosses, synonym hints, span rules, defaults, and policies, using **QNR + IR + the same research corpus** (when available) as inputs. This step **invents no new carriers** in \(\mathcal{L}\); it only produces **frozen interpretive** data keyed to **existing** atom names. |
| **CEVI runtime** | **Evaluate / tool calls** (per request) | An **admissible rewrite system** over **evidence terms** (structured lists, spans, confidences): validate, merge corroboration, surface conflicts, closed-world fill—**only** into facts over the **published** \(\mathcal{L}\), using **only** the frozen contract. **No** re-induction from corpus, **no** extension of \(T(\mathrm{IR})\). |

**Summary:** induction **freezes** meaning hints; runtime **applies** them. Mixing the two under one label is what made earlier docs sound as if the same step both “invented meanings” and “evaluated evidence.”

### Architecture anchor

Unless stated otherwise, **\(\mathcal{L}\)** in the terminology table above is **\(\mathcal{L}_{\text{decision}}\)** — the propositional carriers fixed by **graph → IR** and the theory \(T(\mathrm{IR})\).

- **\(\mathcal{L}_{\text{decision}}\)** — Decision vocabulary and structure come **only** from the authored graph and its compiled IR. **CEVI induction** binds surface material to the **canonical IR atom catalog**; the default engineering scope does **not** mint new decision carriers at Deploy.

- **Surface theory** — **`PublishedEvidenceContract`** holds **interpretive** and **surface-side** structure (glosses, bridge rules, lexical signatures, normalization, optional ontology snapshots when a QNR is marked **legal**). Its job is to **bind** natural language and lexical evidence **onto** \(\mathcal{L}_{\text{decision}}\) at evaluate time—not to replace \(T(\mathrm{IR})\) with a second unconstrained logical story.

- **No runtime extension** — **CEVI runtime** does not introduce new decision carriers or mutate \(T(\mathrm{IR})\) per request.

- **\(\mathcal{L}_{\text{evidence}}\) (future, explicit product choice)** — An optional **evidence-side** vocabulary for richer bridging (corpus + IR–anchored), with its own semantics and publish-time discipline. **Out of scope** until adopted by ADR or sprint; not implied by corpus text alone.

**Related:** [`workflow_design.md`](workflow_design.md) (CEVI, high level) and
[`evaluate_semantics.md`](evaluate_semantics.md) (\(T(\mathrm{IR}) \land E\)).

---

## 1. Four roles (do not conflate)

| Layer | Role |
| ----- | ---- |
| **IR** | **What may be said:** formal carriers, structural constraints, and the compiled theory \(T(\mathrm{IR})\) over a fixed atom set \(\mathcal{L}\). |
| **DTGraph** | **How** the decision structure was **authored** (nodes, edges, question copy, options). Provenance for “who said what in the product.” |
| **Research corpus** | **Why** those symbols **mean** what they mean in the SME domain: the same text (pasted + files + research merge) that fed **agentic decision-tree generation**, when present. Supplies **interpretive legitimacy** for **CEVI induction** (and thus for later runtime encoding). |
| **CEVI induction** | **Pre-publish:** from QNR + IR + corpus (and policies), build **`PublishedEvidenceContract`**. |
| **CEVI runtime** | **Per request:** map blob / encoded output to facts over \(\mathcal{L}\) via **admissible rewrites** using **only** the frozen contract—**not** a second prover, **not** a language extension, **not** a repeat of induction. |

**CEVI induction** must not use IR alone: IR supplies the carrier set and theory shape, but not enough **semantic texture** to fill a contract (phrases, exclusions, domain paraphrases)—the **corpus** and QNR copy carry that. **CEVI runtime** must not re-run induction or mutate \(T(\mathrm{IR})\): the corpus is not consulted again to **change** meanings for that artifact version.

---

## 2. Pipeline (conceptual)

```text
research corpus
   ├── agentic decision-tree generation
   │      └── dt_graph
   │             └── IR / solver theory T(IR)
   │
   └── CEVI induction (compile-time)
          └── evidence glosses, synonym hints, span rules, FactType defaults, …
                    ↓
          PublishedEvidenceContract
```

At **evaluate**, **CEVI runtime** (not induction) maps user/tool evidence into facts using that contract.

- **Corpus alignment (induction only):** **CEVI induction** uses the **same** research corpus as agentic decision-tree generation when that corpus is persisted, so lexical context matches the graph’s domain. If there is no saved corpus, induction may fall back to graph-only metadata (weaker texture; product policy may require corpus for certain tiers).
- **No open-web search in CEVI induction:** **Tavily** (or equivalent live crawl) is **not** part of the publish-time surface-theory pipeline—results would be hard to freeze and would weaken `cevi_contract_hash` reproducibility. **Agentic QNR generation** may keep its own research stack; that is separate from **freezing** `PublishedEvidenceContract`.
- **Established ontologies (validation):** When a QNR is marked **legal** (product toggle), induction may call a **stable ontology HTTP API** (e.g. [FOLIO — Federated Open Legal Information Ontology](https://openlegalstandard.org/resources/folio-api/), base `https://folio.openlegalstandard.org/`) **after** the LLM proposes glosses, synonym tables, and bridge rules, to **check** proposals for errors and omissions—not to replace the LLM as the primary author of bindings. **Snapshot** ontology hits (class id + definition text or digest at induction time) into the contract so audit and hashes remain stable if the public ontology evolves.
- **Published boundary:** At publish, the product commits an artifact that includes **IR** and **PublishedEvidenceContract**. **CEVI runtime** only reads that contract—it does not re-derive it.

---

## 3. What goes into `PublishedEvidenceContract` (frozen)

Induced **at compile / pre-publish**, then treated as **immutable for that artifact version** for **IR / graph / corpus binding**—with one intentional exception: **optional same-row interpretive enrichment** (§4) may replace hint slices and bump `cevi_contract_hash` without a new IR compile.

- **Atom glosses** (short natural-language anchors per atom in \(\mathcal{L}\)).
- **Option paraphrases** and **domain synonyms** (hints for encoding, not new propositional letters).
- **Negative cues** and **span relevance hints** (where to look, what to treat as out-of-scope).
- **Closed- vs open-world defaults** and **FactType**-driven fill policy, per family of atoms.
- **Evidence confidence policy** (how explicit / inferred / absent lines combine before facts reach Z3).
- **`version`** (schema seam, currently `1`), **`kind`** — explicit capability discriminator: **`ir_only`** (no corpus-backed interpretive hints; runtime should disable or degrade blob evidence without inferring from empty maps); **`corpus_partial`** (some publish-time interpretive structure succeeded—e.g. glosses, normalization, lexical hints—but not the full truth-facing bridge set the product treats as “complete”; avoids labeling **`corpus_induced`** when bridge rules failed or were dropped); **`corpus_induced`** (full agreed CEVI hints at publish, including **bridge rules** per policy). A **warnings** or diagnostics field may accompany any `kind`; **`kind` must not overstate** completeness.
- **Bridge rules (truth-facing)** — Mappings from a **structured surface feature** (machine-checkable extractor: pattern over normalized tokens, regex over a defined segment type, slot schema, etc.) **to** **existing** IR catalog atom ids—**not** raw phrase or substring matching as logic. Arbitrary co-occurring text belongs in **lexical / retrieval hints** or glosses, not as the assertion mechanism for \(L(a)\), so **CEVI runtime** never treats bare string snippets as \(\mathcal{L}_{\text{decision}}\).
- **Integrity:** row-level **`cevi_contract_hash`** over canonical stored JSON (see §4).

Nothing in this list **adds** carriers to \(\mathcal{L}\). It **annotates** and **constrains** how text maps to **existing** names.

**Operational checklist:** corpus-backed induction and UI work must account for
**bridge rules**, **lexical signatures**, **normalization**, **induction
provenance** (chunk ids), **dehydrate/rehydrate**, and **evaluate-time binding
provenance** (§8.4).

---

## 4. Artifact and provenance (target shape)

The compile row (e.g. `ReasoningCompiledArtifact`) should be able to attest:

- **`ir_json`**, **`ir_format_version`**, **`graph_hash`** (existing story).
- **`PublishedEvidenceContract`:** stored as **`cevi_contract_json`** with **`cevi_contract_hash`**. Columns are nullable in DDL for legacy or incomplete rows; **successful publish** writes both (today: v1 with `kind: ir_only` until corpus-backed induction).
- **Provenance (hashes or ids):** at least `dt_graph_hash` (or canonical graph hash already stored), `ir_hash` if you maintain a separate IR digest, **`research_corpus_hash`** (of the byte-identical corpus used for induction, or empty if none), **`cevi_contract_hash`**.

**Reference implementation (Python):** [`evidence_contract.py`](evidence_contract.py) — `canonical_json_dumps`, `sha256_hex`, `hash_contract`; use anywhere that persists or compares `cevi_contract_hash` (covered by [`test_evidence_contract_hash.py`](../../tests/unit/reasoning/test_evidence_contract_hash.py)).

**Invariant — `cevi_contract_hash` (same discipline as `graph_hash`):**  
When `cevi_contract_json` is non-null, `cevi_contract_hash` is the **hex-encoded SHA-256** digest of a **single canonical JSON** representation of that object. Implementations must not depend on ad hoc serialization.

- **Canonical JSON:** `json.dumps` with `sort_keys=True` and `separators=(",", ":")` (no extra whitespace), UTF-8 when hashing.
- **Digest:** SHA-256 over those UTF-8 bytes; store as a **64-character lowercase hex** string (match `graph_hash` style in the product).

When there is no contract row payload, **both** `cevi_contract_json` and `cevi_contract_hash` are **null**. A non-null JSON object must always be paired with the hash of its **canonical** form so artifact identity and cache keys stay stable across services and environments.

For **changes to IR, graph, corpus inputs, or author Lexicon edits**, ship a **new publish** (replace the artifact row and hashes). Publish does not run an automatic post-response LLM enrichment job and does not mutate `cevi_contract_json` / `cevi_contract_hash` after the response. Runtime evidence evaluation is where LLM language interpretation belongs, using the submitted evidence text plus the frozen QNR/contract context loaded for that evaluation.

**Optional later:** If the same `cevi_contract_hash` appears on many rows and deduplication matters, a **separate** table keyed by `cevi_contract_hash` (body stored once) with the artifact row storing **hash + FK** is a natural extension. The 1:1 **JSON on `ReasoningCompiledArtifact`** remains correct for the default case (one load, no join).

**Recomputation note:** The solver may rebuild Z3 from `ir_json` on load; you do not have to persist a separate “\(T(\mathrm{IR})\)” blob if `compile_ir_to_z3` is deterministic. What must be frozen is anything required to **rebuild the same evidence-to-facts boundary**—the contract and IR, not necessarily a cached `.smt2` file.

---

## 5. CEVI runtime: admissible rewrites

This section is **only** about **CEVI runtime** (not induction). A transformation on **evidence terms** (lists of structured items, spans, confidences) is **admissible** if and only if:

1. **Output is facts** (or fact-shaped inputs to the existing closed-world / stratification step) **over the published atom language** \(\mathcal{L}\) only.
2. **Type and mutex constraints** implied by the graph and IR (e.g. exactly one true radio option per question) are **not violated** by the emitted fact pattern; ill-typed emissions are **rejected** or routed to **conflict / user resolution**, not fixed by inventing symbols.
3. **Only frozen QNR context and submitted evidence** are used: graph/IR semantics and interpretive hints from **PublishedEvidenceContract** for this artifact version, plus the evidence text supplied to the evaluation request—**no** fresh research-corpus read and **no** new decision carriers.
4. **The theory is not extended:** CEVI **runtime** does not add propositional letters or change \(T(\mathrm{IR})\). It maps evidence into **unit facts** (or their agreed generalization) such that the solver checks **\(T(\mathrm{IR}) \land E\)** as already designed.

---

## 6. Monotonicity (one paragraph)

**Monotonicity** of the *product claim* “outcome follows from this published QNR / IR” requires a **fixed** \(\mathcal{L}\) and a **fixed** \(T(\mathrm{IR})\) for that version. **CEVI runtime** may **improve** how well raw text **lines up** with \(\mathcal{L}\) (given the frozen hints), but it **cannot expand** the theory. **CEVI induction** (with corpus + graph + IR) is what bakes in interpretive hints **once**; the research corpus gives **interpretive legitimacy** at that step; the IR gives **logical closure**; the QNR gives **authorial provenance**; **PublishedEvidenceContract** freezes all of that for **CEVI runtime**. Any change to induced interpretation requires a **new** contract and **new** publish (new hashes), not a silent patch at evaluate time.

---

## 7. Implementation status

**Shipped:** **`PublishedEvidenceContractV1`** (default `kind: ir_only`; schema includes **`corpus_partial`** / **`corpus_induced`** for honest upgrades) and **publish-time** `cevi_contract_json` + `cevi_contract_hash` on every successful premium publish — see [`published_evidence_contract.py`](published_evidence_contract.py) and editor publish flow. Hashing: [`evidence_contract.py`](evidence_contract.py).

**Shipped (CEVI Phase A — corpus + provenance):** durable **`qnr_research_corpora`** (per-QNR research text), **`qnrs.cevi_legal`**, editor **GET/POST/DELETE** corpus routes + settings + publish preflight copy, **`research_corpus_hash`** on **`reasoning_compiled_artifacts`** (and matching **`provenance.research_corpus_hash`** in the frozen contract), agentic **save** merges pasted + factor research into the corpus row, and **`smeme/reasoning/cevi/`** (`atom_catalog`, `corpus_normalize`, `generation_corpus`, `induce_published_evidence_contract_at_publish`).

**Shipped (blob evaluate baseline):** **`evaluate_reasoning_with_blob`** kernel in `runtime/evaluate.py`, typed bridge-rule runtime in `cevi/bridge_runtime.py`, one-row artifact+contract loader in `runtime/blob_evaluate_loader.py`, MCP tool **`smeme_reasoning_evaluate_blob`** (implementation + capabilities when enabled) with plugin coupling, and unit coverage for kernel/loader/tool contract. **MCP surface:** registration and **`smeme_reasoning_capabilities`** listing for **`smeme_reasoning_evaluate_blob`** require **`MCP_REASONING_BLOB_TOOL_ENABLED=true`** (default **`false`** in `smeme/core/config.py`). Evaluation remains primarily **`evaluate_reasoning(raw_answers)`** for structured answers, and that path already uses explicit **Stage A** (`fact:*` records via `raw_answers_to_canonical_facts`) + **Stage B** (projection in `cevi/fact_projection.py`) before the shared Z3 tail.

**Not yet:** **FOLIO** when `cevi_legal`, full product-facing **binding provenance DTO** for blob responses (beyond internal audit fields), and contract `normalization_rules` application in the blob bridge path. The operational sequence and boundaries remain in [§8](#8-implementation-roadmap).

---

## 8. Implementation roadmap

This section **operationalizes** the contract: what to build, in what order, and how to keep **monotonicity** and **no runtime corpus creep**.

### 8.1 The non-negotiable boundary

| Stage | What is read / used |
| ----- | ------------------- |
| **Publish / induction** | Research corpus (durable), QNR, IR → **CEVI induction** → **`PublishedEvidenceContract`** |
| **Runtime / evaluate** | **`ReasoningCompiledArtifact` + `PublishedEvidenceContract` only** (one logical load) |

The **research corpus** is a **publish-time** input to induction, not a per-request evaluate dependency. **PublishedEvidenceContract** is a **runtime artifact** shipped with the compile row. **Evaluate** should not fan out into repeated corpus or exploratory graph reads; that preserves the monotonicity story and avoids **DB-read creep** on the hot path.

**Pipeline (target end state):**

```text
persist corpus
  → induce contract at publish
  → store contract with artifact
  → load artifact once at evaluate
  → rewrite evidence into facts over L
  → SAT(T(IR) ∧ E) on existing solver path
```

### 8.2 Artifact identity (versioned, immutable)

Treat each compiled **reasoning** release as a **versioned, immutable** record. Identity and audit should tie to:

- **`qnr_id`**
- **`graph_hash`**
- **`ir_hash`** (or equivalent canonical digest of `ir_json`)
- **`research_corpus_hash`** (of the byte-identical corpus used for induction, or a sentinel when none)
- **`cevi_contract_hash`**

**Rule:** if **any** of these meaningfully change, **create a new artifact / version** (new row or monotonic version field). **Do not** mutate an existing artifact in place. That gives reproducible evaluation and clear provenance for “which theory + which contract + which corpus snapshot.”

**Corpus mutability:** If the editable “current corpus” lives on the **`qnrs`** row (or similar) and authors can change it **after** a publish, the artifact must still record **`research_corpus_hash`** (and, when used, chunk ids) for the **bytes actually fed to induction for that artifact**—never inferred only from “latest QNR corpus” at read time. Otherwise the hash tuple is not audit-grade.

(Exact schema—single table vs. child `reasoning_artifact_versions`—is a storage detail; the **invariant** is immutability per hash tuple.)

### 8.3 Induction failure policy (phased)

Recommended split so you can **ship incrementally** without blurring the formal story:

- **Default (current product):** **Graph / IR compile and deterministic `PublishedEvidenceContract` persistence** gate **Deploy to MCP** / **`reasoning_status=compiled`**. The optional **legal ontology enrichment** layer is **fail-open**: it records **`passed` / `failed` / `pending` / `not_required`** (and errors) on the artifact row and does not block publish or Lexicon editing on the deterministic baseline. If CEVI induction fails or the corpus is missing, publish may still emit an **IR-only** or minimal contract per existing policy; use honest **`kind`** (`ir_only`, `corpus_partial`, …).
- **Ontology / legal HTTP unavailable:** When **`legal`** is on but the ontology validator cannot complete (timeout, 5xx, outage), the implementation **does not block publish**: legal status is **`failed`** (or reconciled from stuck **`pending`**) with a persisted error string; the frozen contract remains usable for MCP tools and Lexicon review. Author copy must not describe this as “graph validation failed.”
- **Production / high-trust mode (future config or product flag):** optional **block publish** unless a **corpus-backed** `PublishedEvidenceContract` was produced (or an explicit “IR-only QNR” waiver). Use when the product promise is “blob evidence is first-class.” **Not** the default today.

The formal spine—**fixed \(\mathcal{L}\)**, **\(T(\mathrm{IR})\)**, **no runtime extension**—is the same in both; only **richness of hints** and **gating** differ.

### 8.4 Runtime API split

Keep **structured answers** and **free-text / blob** evidence **separate at the API** so CEVI does not leak into the small, well-tested path:

- **`evaluate_reasoning(raw_answers, …)`** (existing shape): structured slot answers → facts over \(\mathcal{L}\) (no blob semantics).
- **`evaluate_reasoning_with_blob(blob, …, artifact)`** (new): natural-language (or document) **blob** → CEVI runtime rewrites (using **only** the frozen contract) → facts over \(\mathcal{L}\).

**Both** converge to the same core:

**facts over \(\mathcal{L}\) → `SAT(T(\mathrm{IR}) \land E)`** (shared solver entry after facts are fixed).

Names may vary in code; the **boundary** is: two entry points, one fact layer, one solver core.

**Binding provenance (blob / NL path only, per request):** The **frozen contract** holds interpretive hints and rule ids (induction output). The **evaluate response** should be able to explain how evidence became facts—for example: blob substring [120,189] matched contract rule `R` and contributed literal \(L(a)=\text{true}\). That record is **not** stored in `cevi_contract_json` (it references user-private text); it is part of the **evaluate result DTO** (and optional audit log), keyed by `rule_id` / `bridge_rule_id` **defined in** the published contract so runs are reproducible and explainable without re-reading the corpus at evaluate time.

For product-grade traces, each accepted NL-derived fact should carry:

- canonical fact id (e.g. `fact:*`);
- projected solver symbol id (`ir_*`) when projection occurs;
- grounding pointer (`source_item_id`, `span` offsets/snippet, `bridge_rule_id`, confidence).

For NL-derived or bridge-attributed facts in traces, include **both** a human-readable normalized anchor and a stable digest when the contract requires it (see blob-evaluate planning).

This dual payload keeps traces explainable to users while preserving deterministic mapping stability across refactors.

**IR v3:** compiled question vertices are **radio-only** (finite option sets);
structured session answers map to `fact:radio:*` atoms alongside the existing
reachability theory.

### 8.5 Delivery order (concrete)

**Done (IR-only path):** **`PublishedEvidenceContractV1`**, `induce_published_evidence_contract_ir_only`, publish writes **`cevi_contract_json`** + **`cevi_contract_hash`** (see `published_evidence_contract.py`, editor publish).

**Next:** preserve an **artifact-grade** `research_corpus_hash` and an honest
**`ir_only` freeze** before LLM/FOLIO enrichment.

1. **Persist research corpus** when a QNR is produced/saved from agentic generation (durable store + hash; see generation/save hook).
2. **Corpus-backed CEVI induction** on **publish** (enrich contract using IR + QNR + corpus; still one row on `ReasoningCompiledArtifact`).
3. **Evaluate path (blob tool path):** load **artifact + contract** in one query via loader (`blob_evaluate_loader.py`); structured-answer REST evaluate remains on `raw_answers`.
4. **CEVI runtime** + **`evaluate_reasoning_with_blob` (baseline shipped):** rewrites on blob evidence; shared fact layer → existing solver. Remaining work is provenance DTO surfacing + normalization/hardening polish.
5. Harden: admissible rewrites, contract versioning, optional high-trust publish gating, optional **`ir_hash` / `research_corpus_hash`** columns.

### 8.6 Code layout (`cevi/` package)

**Shipped:** **`smeme/reasoning/cevi/`** — `atom_catalog.py` (IR allowlist ids), `corpus_normalize.py`, `generation_corpus.py` (agentic merge), `induction.py` (publish entrypoint; still **IR-only** `kind` until LLM/FOLIO phases). **Unit tests:** `tests/unit/reasoning/cevi/`. Types and hashing for **`PublishedEvidenceContract`** remain in [`published_evidence_contract.py`](published_evidence_contract.py); **`cevi` depends on `ir/`** only (no reverse import from `theory/` yet).

**Later:** optional `cevi/runtime.py` or `rewrites.py` for evaluate-time blob path; optional `cevi/README.md` split from this doc.

### 8.7 What is left (after v1 + publish hook)

| Item | Status |
| ---- | ------ |
| **`PublishedEvidenceContract` v1 + `cevi_contract_hash` + publish hook** | **Shipped** (`published_evidence_contract.py`, editor publish). |
| **Durable research corpus** | **Shipped** — `qnr_research_corpora`, editor + agentic save paths. |
| **Corpus-backed CEVI induction** | **Partial** — publish uses `induce_published_evidence_contract_at_publish` (atom catalog + corpus digest); **LLM/FOLIO enrichment** still **open**. |
| **`research_corpus_hash` on artifact row** | **Shipped** (migration `a9b8c7d6e5f4`); mirrors `provenance.research_corpus_hash` in JSON. |
| **Optional: `ir_hash` on artifact row** | **Open** — digest of `ir_json` if split from `graph_hash` is insufficient. |
| **Blob entry point + CEVI runtime rewrites** | **Shipped baseline** — `evaluate_reasoning_with_blob` + bridge runtime + loader + MCP tool are live; remaining gaps are response-level provenance DTO completeness and normalization/hardening follow-through. |
| **Product / config** | **Open** — e.g. high-trust “require corpus-backed contract” per §8.3. |

**Smallest “vertical slice” to start coding:** (done) v1 Pydantic type + IR-only default + publish writes `cevi_contract_json` and `cevi_contract_hash` on every successful compile. **Done (Phase A):** `qnr_research_corpora`, `research_corpus_hash` on artifact, `cevi_legal`, editor routes + UI, agentic corpus merge, `smeme/reasoning/cevi/` (normalize + atom catalog + publish hook). **Next:** LLM propose → validate → freeze, FOLIO when legal, blob evaluate path, optional `ir_hash` column.

### 8.8 After `cevi/` exists (later)

- Move or mirror this document under `cevi/`, re-export public types from `smeme.reasoning` if needed.
- Keep **Phase 1** imports (`ir`, `theory`, `runtime/evaluate`) free of CEVI by default (lazy or separate submodule).
