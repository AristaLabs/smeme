---
name: smeme-reasoning-outcomes
description: >-
  Handle the case report when result_kind is not concluded — multiple outcomes,
  inconsistent answers, source conflicts, needs more information. Uses report
  fields only (product vocabulary — no implementation terms).
---

# SMEme reasoning — outcomes other than concluded

Use when **`smeme_reasoning_evaluate_answers`** (bulk Apply) or a guided gather that ends with a **`report`** returns **`report.result_kind`** other than **`concluded`**, or preload before Apply when ambiguity is likely.

If the tool returned **`{"error": {...}}`**, use **`smeme-reasoning`** — that is an error, not a report. Guided chat **`isolated_evaluations_required`** is also an error path (session stays ACTIVE); do not treat it as a report.

## Quick map (`report.result_kind`)

| `result_kind` | Meaning | Your job |
|---------------|---------|----------|
| **`concluded`** | One outcome applies | Summarize **`report.brief_memo`** and **`reasoning_path`** for the user |
| **`multiple_outcomes_possible`** | More than one outcome fits | Present **`report.candidates`** (titles + summaries). Do **not** pick arbitrarily. Ask which fits, or what extra facts would disambiguate. See [example phrasing below](#multiple-outcomes-example). |
| **`needs_more_information`** | Not enough to force a conclusion | Use **`report.answer_sheet`** and the worksheet; ask targeted follow-ups |
| **`answers_inconsistent`** | Answers cannot all be true together | Explain via **`brief_memo`**; the user adjusts **`answers`**; re-validate and re-Apply |
| **`assumptions_inconsistent`** | Path assumptions conflict with answers or rules | Adjust or clear force/forbid assumptions; do **not** treat this as an answer-only conflict when the report says assumptions |
| **`sources_conflict`** | Evidence disagrees (before answers are admitted) | The user resolves which source to trust; update evidence in the envelope; re-validate |

### <a name="multiple-outcomes-example"></a>What to say for `multiple_outcomes_possible`

List the candidate titles from `report.candidates`, then invite the user to narrow it down:

> "SMEme found [N] possible outcomes for this case:
> - **[Candidate title 1]** — [summary if present]
> - **[Candidate title 2]** — [summary if present]
>
> Which description best fits your situation? Or can you tell me more about [the key factor that differs between them]?"

Use the candidate **title** (not `result_kind`) when speaking to the user. Never guess which candidate applies — the user or additional evidence must decide.

## Presenting the report

- **`headline`** — one-line status for the user
- **`brief_memo`** — canonical server text; you may paraphrase but do not contradict it
- **`reasoning_path`** — ordered steps (questions answered, then outcome). Use it for narrative; it is **not** permission to edit the decision tree. The terminal **conclusion title** names the outcome — it may differ from an earlier answer label (for example **Business** on one question vs a **personal-use** conclusion after a later **No**).
- **`answer_sheet`** — all slots with answers and **`supporting_evidence`** (includes **`locator`** to re-open files)
- **`candidates`** — possible conclusions with **`status`**: `selected` or `possible`

## After remediation

1. Update the ingest (answers and/or evidence).
2. **`smeme_reasoning_validate_answers`**
3. **`smeme_reasoning_evaluate_answers`** (bulk Apply). For ordinary chat gathering, resume **`evaluate_continue`** instead of dumping a full worksheet.
4. Note **`decision_tree_id`** and **`evaluation_run_id`** on retries.

## If the user wants to explore "what would change the outcome"

1. **`smeme_reasoning_what_if`** — compare baseline vs hypothetical answers (two provenance envelopes). Optional shared `force_reachable_ids` / `force_unreachable_ids`. Read `before.report`, `after.report`, and `delta`. See **`smeme-reasoning`** (Logical analysis tools section).
2. **`smeme_reasoning_how_to_reach`** — suggest minimal answer edits toward a target outcome (`target_conclusion_id` from **`smeme_reasoning_list_conclusions`** — **not** from Apply `report`). Default `reach_mode=entailed`; use `possible` when the user is probing whether an outcome can still be reached under some completion. Optional `force_unreachable_ids` / `force_reachable_ids` to assume a branch dead or forced. When `already_reachable` is true, tell the user the baseline already reaches that outcome under the chosen mode.
3. **`smeme_reasoning_decisive_support`** — **minimal sufficient evidence** when Apply already **`concluded`** (or the user asks which answers forced the outcome): inclusion-minimal answered supports for a `target_conclusion_id` from **`list_conclusions`**. Do **not** call this for incomplete results (`needs_more_information`, `multiple_outcomes_possible`) or for `answers_inconsistent` / `assumptions_inconsistent`. Do **not** describe it as abduction.
4. **Fallback** — change answers in the envelope, re-`validate`, re-`evaluate_answers`, and compare reports.

Never invent branch rules to predict outcomes — let the server decide via these tools or Apply / guided gather.

## Handoff

- Building ingest — **`smeme-reasoning-slot-fill`**
- MCP tools and errors — **`smeme-reasoning`**
