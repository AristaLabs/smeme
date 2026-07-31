# Published evidence contract (Deploy freeze)

What **Deploy** freezes today as interpretive metadata alongside IR, and how evaluate uses it.

**Code:** `published_evidence_contract.py`, `evidence_contract.py` (hashing), `cevi/` (induction + `fact_projection`).

---

## What Deploy freezes

On successful compile/publish, each `ReasoningCompiledArtifact` stores:

| Column | Role |
| ------ | ---- |
| `cevi_contract_json` | Frozen `PublishedEvidenceContractV1` (JSONB) |
| `cevi_contract_hash` | SHA-256 of canonical JSON of that contract ([D025](../../docs/DECISIONS.md) identity) |
| `research_corpus_hash` | Digest of normalized research-corpus bytes used at induction (nullable) |

The contract does **not** extend \(T(\mathrm{IR})\). Atom ids and option labels must stay on the IR carrier set (`validated_contract_with_ir_json`).

---

## Induction today (deterministic)

`induce_published_evidence_contract_at_publish` builds a **deterministic** contract from graph copy + optional research corpus:

- Atom glosses from question/conclusion text
- Identity option paraphrases
- Optional corpus chunk manifest + gloss citations when corpus bytes exist
- Honest `kind`: typically `corpus_partial` (graph texture present); empty interpretive maps may still use `ir_only` helpers in tests

There is **no** LLM induction path, **no** ontology enrichment, and **no** legal-ontology toggle in this tree.

Package name `cevi/` and column prefix `cevi_contract_*` are historical identifiers for this Deploy freeze + evaluate projection path.

---

## Hash / identity invariants (D025)

- `cevi_contract_hash = hash_contract(stored_json)` via `canonical_json_dumps` + SHA-256 (`evidence_contract.py`).
- Artifact immutability trigger rejects mutation of identity fields after insert (including `cevi_contract_json` / `cevi_contract_hash`).
- **Legacy rows** may still contain a removed `provenance.legal` key in stored JSON. Raw hash validation must use the **stored** dict unchanged. Semantic parse (`validated_contract_with_ir_json`) copies and drops that key before Pydantic; reserializing the parsed model is **not** expected to reproduce the historical hash. New deploys omit `legal`.

---

## Evaluate path

Product evaluate uses structured `raw_answers` → Stage A canonical facts → Stage B `fact_projection` (using the frozen contract where applicable) → shared Z3 tail in `evaluate_reasoning`.

See [`evaluate_semantics.md`](evaluate_semantics.md).

---

## Explicit non-goals (this tree)

- No free-form evidence-blob evaluate tool or optional MCP blob-ingest flag
- No ontology / legal-ontology validation at Deploy
- No re-induction from corpus on the evaluate hot path
- No extension of \(T(\mathrm{IR})\) from evidence text
