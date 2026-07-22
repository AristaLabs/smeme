---
name: smeme-reasoning-slot-fill
description: >-
  Phase 1 slot-fill: establish the subject, gather sources, build the provenance
  envelope (answers + evidence_items + evidence_refs), validate (branch on
  harness_next) before evaluate or logical analysis.
  Load after template_get and before smeme_reasoning_evaluate / analysis tools.
---

# SMEme reasoning — slot-fill (Phase 1)

Use this skill **after** a **worksheet** is loaded and **before** **`smeme_reasoning_evaluate`** or logical analysis tools that need a baseline envelope.

You are a **slot-filler**, not a reasoner. The server owns the workflow's decision logic; you supply structured answers plus **provenance** so each answered question cites where the answer came from.

## Provenance envelope (required)

Build **`raw_answers_json`** as a JSON object with **`answers`**, **`evidence_items`**, and **`evidence_refs`**. Do not double-encode.

```json
{
  "answers": { "q_foo": "Yes" },
  "evidence_items": [
    {
      "id": "file:04-call-transcript",
      "title": "Call transcript — property use",
      "locator": "/path/in/cowork-project/local-files/04-call-transcript.txt",
      "locator_kind": "workspace_path",
      "source_id": "local-files",
      "retrieved_at": "2026-05-19T18:00:00Z",
      "excerpt": "Short quote supporting the answer (bounded)."
    }
  ],
  "evidence_refs": { "q_foo": ["file:04-call-transcript"] }
}
```

| Field | Required | Purpose |
|-------|----------|---------|
| **`answers`** | Yes | Question node id → exact option string from the worksheet |
| **`evidence_items[].id`** | Yes | Stable cite id within this payload |
| **`evidence_items[].title`** | Yes | Human label for the user |
| **`evidence_items[].locator`** | Yes | Path, URL, or MCP resource URI to **re-open** the full source |
| **`evidence_items[].locator_kind`** | Yes | `file` \| `url` \| `mcp_resource` \| `workspace_path` \| `other` |
| **`evidence_items[].excerpt`** | Yes | Brief supporting quote |
| **`evidence_refs`** | Yes for every answered question | Question id → list of `evidence_items[].id` |

**Mandatory:** Every **answered** question must have **≥1** entry in **`evidence_refs`**. Do not call evaluate without this.

## Subject (evaluation target)

Establish **one subject** (case, patient, vendor, matter, etc.) before wide search. Connector results count only if they pertain to that subject. Do not merge two subjects into one payload.

## Workflow

1. **Worksheet** — `smeme_reasoning_template_get` (or a filled manifest). If **`in_sync: false`**, ask the user to re-publish the workflow in the SMEme web app.
2. **Subject** — Confirm with the user when ambiguous.
3. **Gather** — Subject-scoped connectors, files, chat.
4. **Build envelope** — Map each question to one exact option string; register each source in **`evidence_items`** with a **`locator`** you can reuse to read the full document again.
5. **`smeme_reasoning_validate_answers`** — Same `raw_answers_json`. Branch on **`harness_next`**:
   - **`phase_2_ok`** — proceed to evaluate or logical analysis.
   - **`user_input_needed`** — usually **`missing_evidence_ref`** in **`warnings`**: **stop and ask the user** which questions need a source (use the question text from the worksheet, not just ids). Offer to accept a file path, URL, or pasted excerpt. Re-gather and re-validate until **`phase_2_ok`**.
   - **`phase_1_continue`** — other warnings; stay in Phase 1, fix, re-validate.
6. **`smeme_reasoning_evaluate`** — Same envelope only when **`harness_next` is `phase_2_ok`**. Read the **`report`** only (see **`smeme-reasoning-plugin`**). For logical analysis without a case report, keep the same envelope and call analysis tools from **`smeme-reasoning-plugin`**.

   > `smeme_reasoning_evaluate` may not appear in the client's visible tool list due to deferred loading. If `reasoning.tools` from `smeme_reasoning_capabilities` includes it, call it by name — it is available.

For **hypothetical reruns** (user asks "what if X were Y?"), add an evidence item with **`locator_kind`: `other`**, **`locator`**: `user-instruction`, and an **`excerpt`** quoting the user's instruction so provenance stays honest and validate stays clean.

## When validate reports `missing_evidence_ref`

Tell the user plainly, for example:

- "I need a supporting source for: *[question text]*. Please point me to the file, link, or paste the relevant excerpt."

Do **not** invent placeholder evidence ids or locators.

## Reading errors during slot-fill

`smeme_reasoning_validate_answers` returns either a result object or `{"error": {"code": "...", "message": "..."}}`. Parse `error.code` and surface the message; common ones here:

| `error.code` | Fix |
|--------------|-----|
| `invalid_answers_json` | The payload isn't a valid provenance envelope — pass a bare JSON object, not double-encoded. |
| `ingest_unknown_question_id` | A key in `answers`/`evidence_refs` isn't in the worksheet — re-open `template_get` and use exact ids. |
| `ingest_invalid_answer_option` | An answer value doesn't match an option label — copy the exact option string (case + spacing). |
| `ingest_dangling_evidence_ref` | An `evidence_refs` id has no matching `evidence_items[].id` — add the evidence item or fix the id. |
| `payload_too_large` / `ingest_cap_exceeded` | Trim excerpts and keep evidence bounded; never paste whole documents. |

For the full error map and report handling, see **`smeme-reasoning-plugin`**.

## Data boundary

| Stays client-side | Goes to SMEme |
|-------------------|---------------|
| Full emails, PDFs, CRM JSON | **`answers`** + bounded **`excerpt`** + **`locator`** metadata only |

Never upload raw source blobs for server-side slot-fill.

## Hard boundaries

- **No graph reasoning** — Do not infer branch order, edge conditions, or conclusion targets.
- **No evaluate without validate** — Validate after every material change to answers or evidence; proceed only when **`harness_next` is `phase_2_ok`**.
- **No invented vocabulary** — Question ids and option strings must match the worksheet exactly.

## Handoff

| Next | Skill / tool |
|------|----------------|
| OAuth, validate, evaluate, logical analysis, **`report`** | **`smeme-reasoning-plugin`** |
| Non-`concluded` **`report.result_kind`** | **`smeme-reasoning-outcomes`** |
