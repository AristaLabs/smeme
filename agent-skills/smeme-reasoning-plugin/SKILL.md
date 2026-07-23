---
name: smeme-reasoning-plugin
description: >-
  SMEme reasoning plugin — OAuth MCP, list your decision trees, build provenance
  ingest, validate then evaluate, logical analysis tools (what_if / how_to_reach /
  decisive_support / edit_affects_path; often after evaluate, not required).
  Call smeme_reasoning_capabilities for authoritative reasoning.tools catalog;
  deferred client tool lists may omit smeme_reasoning_evaluate.
  Slot-fill: smeme-reasoning-slot-fill. Non-concluded results: smeme-reasoning-outcomes.
---

<!-- installed_plugin_version: 3.0.0 -->

# SMEme reasoning plugin (Cowork)

## What SMEme reasoning does

- **Deterministic** evaluation: a published **decision tree** + provenance ingest (answers + evidence) → a server **`report`** (brief memo, reasoning path, candidates).
- **Logical analysis** on the same \(T\) and envelope: what-if, how-to-reach, decisive support, path-under-edit, list conclusions — **often after evaluate**, but **not required** to run evaluate first.
- The decision tree's decision logic lives on SMEme. You are an **answer mapper**, not a reasoner — you **do not** reinterpret branches, infer hidden rules, or fix the decision tree.

## Assumptions (do not pre-confirm with the user)

These are normal preconditions. Call the tools; if one fails, follow the [error map](#reading-mcp-tool-errors).

1. The user has **published** a reasoning-eligible **decision tree** in the **SMEme web app**.
2. The **MCP connector** is connected (OAuth in Cowork). On **`auth_error`**, reconnect once; do **not** retry in a loop.
3. **The user has logged into SMEme web at least once** so their account is linked (Bearer `sub` matches their SMEme account).
4. Pick the decision tree via **`smeme_reasoning_list`**. Load the worksheet via **`smeme_reasoning_template_get`** (or a filled manifest skill).

### Worksheet: `template_check` vs `template_get`

| Tool | Returns | When |
|------|---------|------|
| **`smeme_reasoning_template_check`** | `decision_tree_id`, `slug`, `in_sync`, `manifest_core_digest` | Cheap drift gate |
| **`smeme_reasoning_template_get`** | `manifest_markdown` + envelope metadata | Authoritative checklist |

### Plugin version check

<!-- connector_guidance_transform: this ### block through the next ## is stripped for MCP guidance_get — version-only copy here -->

Every **success** response includes `_server_plugin_version`. Compare it against
**`3.0.0`** (this skill's installed version, from the `<!-- installed_plugin_version -->` comment above).

- **Match** — continue normally.
- **Mismatch** — call **`smeme_reasoning_guidance_get`** (or re-check digest via **`smeme_reasoning_guidance_check`** then get) and prefer that contract over this skill file. Show the user one short line, then continue:

  > ⚠️ Local skill version (`3.0.0`) doesn’t match the server (`{_server_plugin_version}`). Using live SMEme guidance for this session.

## Two intents (peers)

| Intent | When | Path |
|--------|------|------|
| **Case evaluation** | User wants a conclusion / report for a case | validate → evaluate → read `report` |
| **Logical analysis** | User asks what-if / how to reach C / what locked it in / would this edit affect the path | same provenance envelope → analysis tools; **reuse envelope after evaluate when available**; evaluate first is **common, not required** |

When the user asks **what these tools let them do**, call **`smeme_reasoning_capabilities`**, summarize **both** intents, and ask which they want — do **not** default to evaluate unless the open thread is already a case run.

## Case evaluation happy path

1. **`smeme_reasoning_capabilities`** — session bootstrap; `reasoning.tools` is the authoritative tool list. See [Tool catalog](#tool-catalog).
2. **`smeme_reasoning_list`** — your discoverable decision trees. **If this is empty, see [When `smeme_reasoning_list` is empty](#when-smeme_reasoning_list-is-empty) — do not guess decision tree ids.**
3. **`smeme_reasoning_template_get`** — question ids, labels, exact option strings.
4. **`smeme-reasoning-slot-fill`** — establish the subject, gather sources, build **`raw_answers_json`** (provenance envelope).
5. **`smeme_reasoning_validate_answers`** — same envelope. Branch on **`harness_next`** (authoritative server routing):

   | `harness_next` | Meaning | Action |
   |----------------|---------|--------|
   | **`phase_2_ok`** | Ingest clean | Safe to call evaluate (or logical analysis on this envelope) |
   | **`user_input_needed`** | Needs the human (commonly **`missing_evidence_ref`** only) | Ask the user for sources; re-validate; **do not** evaluate yet |
   | **`phase_1_continue`** | Other ingest warnings | Stay in gather/validate; fix warnings; re-validate |

6. **`smeme_reasoning_evaluate`** — same envelope. Use **`persist=false`** only for dry runs. Success also returns **`harness_next`** / **`warnings`** from the same ingest gate.
7. Read the **`report`** — present **`brief_memo`**, **`reasoning_path`**, **`candidates`**, and **`answer_sheet`** to the user. Branch on **`report.result_kind` only**. The conclusion **title** names the **terminal outcome**, not the previous question's wording — follow **`reasoning_path`** order; do not infer branch logic from headlines alone.

### Provenance envelope (`raw_answers_json`)

Set **`raw_answers_json`** to a serialized JSON object with **`answers`**, **`evidence_items`**, and **`evidence_refs`**. Use the same value for validate and evaluate. Do not double-encode (pass the object, not a JSON string of a JSON string).

```json
{
  "answers": { "q1": "Yes" },
  "evidence_items": [{ "id": "e1", "title": "...", "locator": "...", "locator_kind": "file", "excerpt": "..." }],
  "evidence_refs": { "q1": ["e1"] }
}
```

See **`smeme-reasoning-slot-fill`** for field rules.

| `report.result_kind` | Meaning |
|----------------------|---------|
| **`concluded`** | One outcome selected — summarize **`brief_memo`** and the path |
| **`multiple_outcomes_possible`** | Several outcomes still fit — use **`candidates`**; ask the user to refine |
| **`needs_more_information`** | Not enough answered — ask targeted follow-ups |
| **`answers_inconsistent`** | Answers cannot all hold — the user must adjust answers |
| **`sources_conflict`** | Sources disagree — the user must resolve conflicts |

If **`result_kind`** is not **`concluded`**, load **`smeme-reasoning-outcomes`**.

## Tool catalog

`smeme_reasoning_capabilities` → `reasoning.tools` is the authoritative list of tools this server exposes. Client tool lists and `tool_search` results may be incomplete due to deferred loading — do not use them to conclude a tool is unavailable.

| Tools | Availability |
|-------|-------------|
| `smeme_reasoning_list`, `smeme_reasoning_validate_answers`, `smeme_reasoning_evaluate`, `smeme_reasoning_what_if`, `smeme_reasoning_edit_affects_path`, `smeme_reasoning_how_to_reach`, `smeme_reasoning_decisive_support`, `smeme_reasoning_list_conclusions`, `smeme_reasoning_template_*` | Always in `reasoning.tools` when the server exposes logical analysis tools. If a tool is absent from the client UI, deferred loading is the cause — call it by name. |

`capabilities` has quota weight 0.

## Logical analysis tools (success shapes)

These tools are **first-class**. They **often follow** an evaluate run on the same case (reuse that envelope). They **do not have to** — a baseline envelope is enough to call them without a prior evaluate.

| User asks | Call |
|-----------|------|
| “What **if** we said X?” / show the other world / what **happens** if… | **`smeme_reasoning_what_if`** |
| “Would changing X **affect this path**?” / is the **current path** sensitive to X? | **`smeme_reasoning_edit_affects_path`** |
| “Which answers **mattered** / were **sufficient**?” (no hypothetical edit) | **`smeme_reasoning_decisive_support`** |
| “How do I get to conclusion C?” | **`smeme_reasoning_how_to_reach`** |
| “What outcomes exist?” | **`smeme_reasoning_list_conclusions`** |

Do **not** describe `edit_affects_path` as “which answers mattered” or as “would the outcome change” in the vague sense — that tool is **path sensitivity** under an override. Outcome tours own **`what_if`**. “Which answers mattered” owns **`decisive_support`**. Prefer **affect / sensitive / current path / under this change** for `edit_affects_path`.

When the user asks **both** “what if X?” **and** “does that affect this path?”, call **`what_if` and `edit_affects_path`** with the same base + override — two tools, two answers; do not collapse.

**`smeme_reasoning_what_if`**, **`smeme_reasoning_edit_affects_path`**, **`smeme_reasoning_how_to_reach`**, and **`smeme_reasoning_decisive_support`** use the same provenance envelope as evaluate; v1 supports **`persist=false`** only.

Prefer a prior evaluate when the question needs a **current forced path** (`edit_affects_path`) or an already-forced target (`decisive_support`). Otherwise do **not** force evaluate first.

Use **`smeme_reasoning_list_conclusions`** when the user asks what outcomes exist, or **before** **`smeme_reasoning_how_to_reach`** / **`decisive_support`** — it is the supported way to obtain **`target_conclusion_id`** (no dry-run evaluate probes, no editor access).

Optional reach assumptions \(\phi\): `force_reachable_ids` / `force_unreachable_ids` (empty = identity). Same \(\phi\) on both what_if passes. Locks (`locked_question_ids`) are **not** \(\phi\).

### `list_conclusions` success

| Field | Meaning |
|-------|---------|
| `conclusions[]` | Each possible decision tree outcome with `conclusion_id`, `conclusion_title`, `summary`, `reachable` |
| `count` / `reachable_count` | Total conclusions vs structurally reachable under published rules |
| `workflow_rules_consistent` | `false` when branching rules cannot all hold together |
| `hint` | Present when rules are inconsistent or some conclusions are unreachable |

Reachability is **structural** (some valid answer path could reach the conclusion), not case-specific. For a particular user's answers, use **`smeme_reasoning_evaluate`**.

**`how_to_reach` input:** copy **`conclusion_id`** from a row here into **`target_conclusion_id`**. Show **`conclusion_title`** to the user when choosing a target. Do **not** take ids from evaluate **`report.candidates`** or guess from titles alone.

### `how_to_reach` procedure

1. **`smeme_reasoning_list_conclusions`** — list outcomes; pick **`conclusion_id`** + **`conclusion_title`** for the target.
2. Build baseline **`base_raw_answers_json`** (same provenance envelope as evaluate).
3. **`smeme_reasoning_how_to_reach`** — pass **`target_conclusion_id`** from step 1.
   - Default **`reach_mode=entailed`**: the target must be forced under every completion of unanswered questions (same as prior builds).
   - Use **`reach_mode=possible`** for exploratory logical-analysis probes: the target only needs to remain reachable under *some* completing assignment.
   - Optional **`force_reachable_ids` / `force_unreachable_ids`**: assume nodes must stay on-path or off-path (same ids as evaluate; from **`template_get`** / **`list_conclusions`**). Echoed under **`assumptions`** when set.
   - Echoed **`reach_mode`** on the success payload — narrate accordingly when `already_reachable` is true.

### `what_if` success

Optional **`force_reachable_ids` / `force_unreachable_ids`**: same path assumptions as evaluate / `how_to_reach`, applied to **both** baseline and after-override evaluates. Echoed under **`assumptions`** when set.

| Field | Meaning |
|-------|---------|
| `before.report` | Evaluate report for baseline answers |
| `after.report` | Evaluate report after merging override answers (override wins per question id) |
| `delta` | Structured diff in report vocabulary only |
| `assumptions` | Echo of force lists when non-empty |
| `warnings` | Same ingest warnings as validate/evaluate |

| `delta` field | Meaning |
|---------------|---------|
| `changed_answers` | Question ids whose answer changed (`before` / `after` per id) |
| `result_kind_changed` | `before_result_kind` ≠ `after_result_kind` |
| `outcome_changed` | Result kind, candidate titles, or candidate status changed — **not** headline-only drift |
| `candidates.added_titles` / `removed_titles` | Outcome titles that appeared or disappeared |
| `candidates.status_changes` | Same title, different `selected` / `possible` status |
| `reasoning_path_changed` | Ordered path narrative differs |

Explain deltas to the user in plain language — never invent graph ids or branch rules.

### `edit_affects_path` procedure

Use when the user asks whether a **hypothetical change** would **affect the current decision path** (not when they want a full alternate-world tour — that is **`what_if`**).

1. Prefer a prior **`smeme_reasoning_evaluate`** so the case is coherent.
2. Pass the same provenance envelope as baseline **`base_raw_answers_json`** plus **`override_raw_answers_json`** (hypothetical edits; override wins per question id).
3. Read **`path_still_entailed`** / **`edit_affects_path`**, **`path_nodes_lost`**, and the conclusion side-car (**`conclusions_newly_entailed`**, **`conclusions_no_longer_entailed`**, **`conclusions_still_entailed`**).

Optional **`force_reachable_ids` / `force_unreachable_ids`**: same path assumptions as evaluate. Echoed under **`assumptions`** when set.

On **`path_not_entailed_at_baseline`**: gather or fix answers via evaluate/validate, or fall back to open **`what_if`** if they still want an alternate world.

| Field | Meaning |
|-------|---------|
| `path_still_entailed` | `true` when the baseline path stays forced under the override |
| `edit_affects_path` | `true` when the edit breaks the forced path (inverse of `path_still_entailed`) |
| `path_nodes_lost` | Path steps no longer forced (question text / conclusion titles) |
| `conclusions_*` | Which conclusions stay / become / stop being forced under the same override |
| `changed_answers` | Question ids whose answer changed |
| `assumptions` | Echo of force lists when non-empty |
| `warnings` | Same ingest warnings as validate/evaluate |

### `decisive_support` procedure (minimal sufficient evidence)

Use **only** when the current answers already force the target outcome (typically after **`concluded`** evaluate, or when the user asks “which answers mattered?”). This returns inclusion-minimal answered supports under fixed decision tree rules and fixed answers — **not** a tentative conclusion from incomplete evidence, and **not** conflict reconciliation.

1. **`smeme_reasoning_list_conclusions`** — obtain **`target_conclusion_id`**.
2. Pass the same provenance envelope as evaluate plus that target.
3. Read **`supports[]`**: each row is an inclusion-minimal map of question id → option string.

Do **not** call this for `answers_inconsistent`, `assumptions_inconsistent`, `needs_more_information`, or `multiple_outcomes_possible`. Do **not** use it to invent edits toward a different outcome — that is **`how_to_reach`** (repair).

| Field | Meaning |
|-------|---------|
| `target_conclusion_id` / `target_conclusion_title` | Forced outcome under study |
| `supports[]` | Up to `top_k` inclusion-minimal answered supports |
| `supports[].support_question_ids` | Question ids in the support |
| `supports[].support_answers` | Question id → option string |
| `supports[].support_size` | Number of answered questions in the support |
| `assumptions` | Echo of force lists when non-empty |
| `warnings` | Same ingest warnings as validate/evaluate |

### `how_to_reach` success

| Field | Meaning |
|-------|---------|
| `target_conclusion_id` / `target_conclusion_title` | Desired outcome — **`target_conclusion_id`** from **`smeme_reasoning_list_conclusions`**; title for user-facing copy |
| `reach_mode` | Echo of input: `entailed` (default) or `possible` |
| `satisfiable` | `true` when at least one plan exists within `max_changes`, or baseline already reaches the target |
| `already_reachable` | `true` when baseline already reaches the target under the chosen `reach_mode` — tell the user; do **not** fabricate edits |
| `minimal_change_count` | Smallest edit count among returned plans; `0` when `already_reachable`; `null` when `satisfiable` is false |
| `plans[]` | Up to `top_k` suggested edits (empty when `already_reachable`) |
| `blockers` | Present when `satisfiable` is false — branch on `blockers.code` like `error.code` |

| `plans[]` field | Meaning |
|-----------------|---------|
| `change_count` | Number of answer edits in this plan |
| `changed_answers` | Map of question id → new option string |
| `dropped_answers` | Question ids cleared in this plan |
| `preview_report` | Report if the user applied this plan — may show `multiple_outcomes_possible` even when the target is reachable |
| `preview_target_reached` | Informational hint only; omitted when `already_reachable` |

| `blockers` field | Meaning |
|------------------|---------|
| `code` | `no_plan_within_max_changes` or `search_cap_exceeded` |
| `message` | Quote to the user |
| `search_complete` | `true` = search finished; `false` = server search limit hit (`search_cap_exceeded`) |
| `max_changes_searched` | Effective `max_changes` cap used |
| `locked_question_ids` | Echo of input locks |
| `target_conclusion_title` | User-facing outcome title |

Ignore `blockers.sat_calls` if present — do not quote engineering counters to the user.

## Reading MCP tool errors

Every tool returns either a success object **or** `{"error": {"code": "...", "message": "...", ...}}`. Parse `error.code` and act on it — and **read `error.message` to the user**, because the server messages tell them exactly what to fix in the SMEme web app.

| `error.code` | What it means | What to do |
|--------------|---------------|------------|
| `auth_error` | Not connected, or no linked SMEme account | Read `error.message` to the user. If `auth_reason` is `no_local_user_for_clerk_sub` (or `signup_url` is present), they need a SMEme account first: open **`signup_url`** (or **`sign_in_url`** if they already registered) and complete web sign-in, then **reconnect** the MCP connector in Cowork. Quote the URLs from the error — do **not** retry in a loop. |
| `not_found` | Decision tree id unknown, or not owned by this user | Call `smeme_reasoning_list` and use an `id` from there. Do not invent ids. |
| `not_discoverable` | Decision tree exists but is hidden from MCP | Ask the user to go to their **SMEme dashboard**, find the decision tree, and turn on the **Listed** toggle. Then retry. |
| `no_reasoning_artifact` | Decision tree not published/deployed for reasoning | Ask the user to **publish** the decision tree from the SMEme editor, then retry. |
| `stale_theory` | Decision tree changed since it was last published | Ask the user to **re-publish** it from the SMEme editor, then retry the same answers. |
| `account_downgrade_pending` | Plan/billing limits this decision tree right now | Surface the `message` (and any `choose_workflow_url`); the user resolves it in SMEme. Do not retry blindly. |
| `quota_exceeded` | Monthly reasoning allowance reached | Tell the user plainly. The allowance resets at the start of their next billing period — they can see the exact date on the **SMEme billing page**. Suggest upgrading if they need access sooner. Do not retry. |
| `concurrency_limit` | Another MCP tool call is already in flight for this account | Wait a moment and retry once. This is transient coordination, not a monthly cap hit — do not suggest upgrading. |
| `invalid_answers_json` | `raw_answers_json` is not a valid provenance envelope | Rebuild the envelope (see `smeme-reasoning-slot-fill`); pass a bare JSON object, not double-encoded. |
| `invalid_answers` / `ingest_*` | Keys, option strings, or evidence refs don't match the worksheet | Re-open the worksheet; fix question ids and exact option strings; ensure every answered question has an evidence ref. |
| `payload_too_large` | Ingest exceeds caps | Trim excerpts; keep evidence bounded (locator + short quote, not full documents). |
| `internal_error` | Unexpected server error | Retry **once**. If it persists, tell the user and include the approximate time. |
| `persist_not_implemented` | v1 logical analysis tools do not write audit rows | Retry with `persist=false`. Do not block the user. |
| `invalid_target_conclusion_id` | Bad or non-conclusion target id | Call `smeme_reasoning_list_conclusions` for valid ids, or ask the decision tree owner; do not guess from `report.candidates`. |
| `invalid_locked_question_id` | Lock list references unknown question | Re-read `template_get`; only lock ids that appear on the worksheet. |
| `invalid_reach_mode` | `reach_mode` not `entailed` or `possible` | Retry with `entailed` (default) or `possible`. |
| `invalid_assumption_node_id` | Bad id in force_reachable / force_unreachable | Use ids from `template_get` or `list_conclusions`. |
| `conflicting_assumptions` | Same id in both force lists | Remove it from one list. |
| `assumptions_cap_exceeded` | Too many assumption ids | Narrow the lists (server cap 32). |
| `target_not_reachable_under_locks` | Target impossible with current locks/baseline | Tell the user which locks were set; suggest removing locks or pick another target from **`smeme_reasoning_list_conclusions`** |
| `target_not_entailed` | Current answers do not force the target (decisive_support) | Use **`how_to_reach`** for edit plans, or re-evaluate; do not invent supports |
| `path_not_entailed_at_baseline` | Current answers do not fully force the baseline path (`edit_affects_path`) | Gather/fix via **`evaluate`**, or use open **`what_if`** for an alternate world |
| `no_plan_within_max_changes` | Search finished; no matching plan within `max_changes` | Read `blockers.message` on the success payload. Suggest higher `max_changes` (≤ 5), fewer locks, or different baseline answers — not a server retry loop. |
| `search_cap_exceeded` | Server search limit exhausted (`search_complete: false`) | **Do not** say "no plan exists." Suggest lowering `max_changes` or simplifying locks; retry once; escalate if persistent. |
| `solver_timeout` | Reasoning engine timed out | Retry once with lower `max_changes`; then escalate with time of failure. |

> **`how_to_reach` blockers:** When the response includes **`blockers`** (no reachable plan), branch on `blockers.code` the same way as `error.code` above.

> Connector hiccups (timeouts, dropped connection) are not tool errors — re-establish the MCP connection rather than changing the answers.

## Tips for a smooth session

### When `smeme_reasoning_list` is empty

An empty `decision_trees` array (`count: 0`) means nothing is currently discoverable for this account. Tell the user:

> "Nothing showed up in the list. On your **SMEme dashboard**, find the decision tree and make sure (1) it's been **published** from the editor, and (2) the **Listed** toggle is **on**. Then I'll try again."

Never fabricate a `decision_tree_id` to work around an empty list.

### When the user asks what MCP tools exist

Call `smeme_reasoning_capabilities` and report `reasoning.tools`. Present **case evaluation** and **logical analysis** as peers ([Two intents](#two-intents-peers)). Do not answer from an earlier tool listing — see [Tool catalog](#tool-catalog).

If `reasoning.tools` includes **`smeme_authoring_design_guidance`** /
**`smeme_authoring_validate_graph`** / **`smeme_authoring_create_draft`**, those
are for **building** a decision tree in chat — they create an **unpublished** decision tree
in the user’s SMEme account (`create_draft` returns `editor_url`). That decision tree
is **not** ready for evaluate until the user **Deploys** it and sets **Listed**.
Do not use these tools for case evaluation. Follow **`smeme-decision-tree-author`**
for the build path.

### Other quick checks

- **Hold the `id` for the session** — once you have a decision tree `id` from `smeme_reasoning_list`, keep it in memory for all subsequent tool calls. Do not re-call list on every round-trip.
- **Same `id` for list and evaluate** — pass the exact `id` from `smeme_reasoning_list` into the evaluate/template tools.
- **Exact option strings** — answer values must match the worksheet's option labels exactly (case and spacing). When unsure, re-read `template_get`.
- **Provenance + `harness_next`** — every answered question needs ≥1 evidence ref; validate first; only evaluate when **`harness_next` is `phase_2_ok`** (or after resolving `user_input_needed` / `phase_1_continue`).
- **Re-publish fixes most "it changed" errors** — `stale_theory` / `no_reasoning_artifact` are almost always resolved by publishing in the SMEme editor.
- **Logical analysis** — reuse the evaluate envelope when one exists; otherwise build a baseline envelope. Do not force evaluate first unless the tool requires a forced path/target.
- **`what_if`** — same provenance envelope for `base_raw_answers_json` and `override_raw_answers_json`; optional shared `force_*_ids`; narrate using `delta` fields (see [Logical analysis tools](#logical-analysis-tools-success-shapes)).
- **`decisive_support`** — **minimal sufficient evidence** only when the target is already forced; narrate `supports[].support_answers`. Never use for incomplete or inconsistent evaluate results; never describe it as abduction.
- **`how_to_reach`** — call **`smeme_reasoning_list_conclusions`** first for **`target_conclusion_id`**; then pass baseline **`base_raw_answers_json`**. When `already_reachable` is true, say the baseline already reaches the target; otherwise present `changed_answers` / `preview_report` as suggested edits, not proofs.

## Hard boundaries

- **Use `report` only** — On evaluate success, branch on **`report.result_kind`** and documented report fields. Do not expect or invent engineering-only payload fields.
- **Answer mapper, not reasoner** — Do not invent options or infer hidden branch rules.
- **Ask the user** when validate warns on missing evidence or when results are inconclusive.

## Where to go next

- **Slot-fill + provenance** — **`smeme-reasoning-slot-fill`**
- **Non-concluded results** — **`smeme-reasoning-outcomes`**
