---
name: smeme-reasoning-manifest-{{SLUG}}
description: >-
  UNFILLED TEMPLATE — do not invoke as a skill until generated from SMEme publish output;
  placeholders like {{SLUG}} must be replaced. After fill: flat question manifest for
  the SMEme reasoning decision tree "{{TITLE}}" (slug {{SLUG}}). Load only when this decision tree is the
  evaluation target. Each question is independently answerable from local context —
  no branching hints.
---

# Reasoning question manifest — {{TITLE}}

**Slug / id:** `{{SLUG}}` · **Decision tree id (version):** `{{DECISION_TREE_ID}}`
**Intended audience (author):** {{INTENDED_AUDIENCE}}
**Use case (author):** {{USE_CASE}}

## How to use this skill

The agent maps **documents, email, chat, and user input** into **`raw_answers`**: a JSON object whose keys are **question node ids** from the evidence schema below. The server runs all reasoning; do not infer branch order or conclusions from this file.

## Evidence schema (compile-time ids and shapes)

Structured answers must **align** with these ids and option labels (no new questions, no invented labels):

```json
{{EVIDENCE_SCHEMA_JSON}}
```

## Per-question prompts (unordered checklist)

{{PER_QUESTION_BULLETS}}

## Answer formatting

Published decision trees are **radio-only**: each question has a finite option set. Set `raw_answers_json.answers[node_id]` to the chosen option string **exactly** as listed in the schema (case and spacing must match).

For **natural-language or document** evidence, map what the user said into `raw_answers_json.answers`: pick the option string from the schema that best matches each question. Do not put arbitrary freeform prose in answer values unless the manifest explicitly allows that shape (standard radio-only manifests do not).

## After answers are ready

1. Build **`raw_answers_json`**: a JSON object with `answers`, `evidence_items`, and `evidence_refs` (one ref per answered question). See **`smeme-reasoning-slot-fill`** for the provenance envelope and field rules.
2. Call **`smeme_reasoning_validate_answers`** first with that object. Fix any `missing_evidence_ref` warnings before evaluating.
3. Call **`smeme_reasoning_evaluate`** with `raw_answers_json` set to that object (bare JSON object, not double-encoded).
4. Use **`persist=false`** for exploration; default **`persist=true`** writes an audit row.
5. Read the **`report`**. If **`report.result_kind`** is not **`concluded`**, open **`smeme-reasoning-outcomes`**.

---

_This file is generated from SMEme — do not hand-edit for production; regenerate on republish (CWP-5). Until filled from publish output, it is not a loaded skill._
