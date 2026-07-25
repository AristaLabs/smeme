---
name: smeme-decision-tree-author
description: >-
  Chat-native decision-tree authoring — help the user pick a judgment to encode,
  iterate questions/options/branches in plain language, then validate and create
  or revise a SMEme dashboard draft via MCP (bypasses the generation wizard).
---

# SMEme decision-tree author (chat path)

## Your role

You help the user **design a SMEme decision tree in chat**, then hand it to SMEme
as a **dashboard draft** (create or revise). The web **generation wizard stays
available** — this skill is the secondary path when the user wants to build with
you in conversation.

You are a **design facilitator**, not a Deploy button. Create or update drafts
only. **Deploy** / **Listed** happens in the SMEme web app editor.

## When to use

- User asks to build / design / encode a **decision tree** (expert judgment
  with branching questions → conclusions) with your help in chat.
- User has an existing `.smeme.json` export and wants to re-import as a new draft.
- User wants to **revise** an existing owned draft in chat (use get → validate →
  update; do not create a duplicate unless they ask for a new tree).

Do **not** use this path for case evaluation (use **`smeme-reasoning`**).

## Assumptions

1. MCP connector connected; user has a linked SMEme account.
2. Authoring tools appear in **`smeme_reasoning_capabilities` → `reasoning.tools`**:
   **`smeme_authoring_design_guidance`**, **`smeme_authoring_validate_graph`**,
   **`smeme_authoring_create_draft`**, **`smeme_authoring_get_draft`**,
   **`smeme_authoring_update_draft`**.
   When MCP is enabled, authoring tools are **on by default**. If missing, the
   server may have opted out with **`MCP_AUTHORING_GRAPH_TOOLS_ENABLED=false`**
   — tell the user to ask their operator to enable authoring or remove that opt-out.

## Phases (do not skip)

### Phase A — Identify

Confirm the judgment to encode (one primary outcome decision, expert-gated,
repeatable). Offer a clear fork when both paths exist:

- **Wizard** — research-heavy greenfield in the SMEme web app.
- **Chat** — iterate here, then push a draft (this skill).

If revising an existing tree, confirm the `decision_tree_id` (from a prior
`create_draft`, the dashboard, or the user).

### Phase B — Iterate in plain language

1. Call **`smeme_authoring_design_guidance`** once (cache by `content_digest`).
   Prefer that document over any cached copy of this skill if they disagree.
2. Design **with the user in readable form** — lock conclusions first, then
   questions, options, and “if X → …”. Keep a running outline they can correct.
3. Apply the design standard: radio-only, anti-funnel branching, Unsure
   forward-only, every path reaches a conclusion. For independently sufficient
   overlapping triggers, agree a priority and use first-hit-wins routing to one
   shared conclusion.
4. For time-sensitive rules, capture structured per-question `authorities`,
   graph `effective_date` / `review_by`, and expected-outcome regression fixtures.

**Do not** emit wire `dt_graph` JSON until the user says they are ready (or
explicitly asks to push / validate).

Preflight before structuring (also in the design guidance):

- Exactly one entry question (start of the tree).
- Every question option leads somewhere (or has a clear default path).
- Terminal nodes are **conclusions** (outcomes), not dangling questions.
- Option labels on edges match the question’s options **exactly**.
- Stable ids: letters/digits/`_`/`-` only; start with a letter (`q1`, `c_approve`).

### Phase C — Structure → validate → create (new draft)

1. Build `dt_graph` JSON: `{nodes, edges, metadata}` (see shape below).
2. **`smeme_authoring_validate_graph`** with `dt_graph_json` (serialized object,
   not double-encoded).
3. If `draft_ready` is false: fix `errors` with the user; re-validate. Do not create.
4. When `draft_ready` is true and the user confirms: **`smeme_authoring_create_draft`**.
5. Keep the returned `decision_tree_id` and `graph_hash`. Show `editor_url` and
   `next_step`. Remind them: polish in the editor → **Deploy** → **Listed**
   before the tree appears in **`smeme_reasoning_list`**.

**Create is strict:** `create_draft` rejects graphs that are not `draft_ready`.

### Phase D — Revise an existing draft

1. **`smeme_authoring_get_draft`** with `decision_tree_id` — read `graph`,
   `graph_hash`, and current `errors` / `warnings` / `draft_ready`.
2. Edit the tree with the user (plain language first when possible).
3. **`smeme_authoring_validate_graph`** on the revised `dt_graph_json`.
4. **`smeme_authoring_update_draft`** with `decision_tree_id`, `dt_graph_json`,
   and `expected_graph_hash` from get/create (or the previous update).
5. On **`graph_conflict`**: call **`get_draft` again**, re-apply edits, validate,
   and retry update. Do not last-write-win blindly.
6. Use the **new** `graph_hash` from a successful update for the next revise.

**Update is lenient:** schema-valid intermediate graphs may save even when
`draft_ready` is false (same incremental posture as the web editor). That is
for intentional incremental work — **not** permission to skip validate. Prefer
validate → update. Invalid intermediates cannot be created via `create_draft`
and cannot be Deployed until fixed.

If the tree was already Deployed, `deployment_sync` may become **`stale`**. Do
**not** claim evaluate works until the user Redeploys in the editor.

## Graph shape (wire)

Authoritative copy lives in **`smeme_authoring_design_guidance`** (from
`DESIGN.md`). Connector-only agents never see this skill file — keep the MCP
artifact complete.

```json
{
  "nodes": [
    {
      "id": "q1",
      "type": "question",
      "data": {
        "text": "Is the vendor financially sound?",
        "type": "radio",
        "options": ["Yes", "No", "Unsure"],
        "required": true,
        "help_text": "Use the latest audited statements when available.",
        "authorities": [{ "citation": "Vendor Policy § 4.2" }]
      }
    },
    {
      "id": "c_approve",
      "type": "conclusion",
      "data": {
        "title": "Approve",
        "summary": "Vendor may proceed.",
        "recommendations": ["Record the review date."],
        "severity": "info"
      }
    }
  ],
  "edges": [
    { "source": "q1", "target": "c_approve", "condition": "Yes" }
  ],
  "metadata": {
    "title": "Vendor Approval Assessment",
    "estimated_time": 5,
    "effective_date": "2026-07-01",
    "review_by": "2027-07-01",
    "regression_fixtures": [
      {
        "name": "sound vendor is approved",
        "raw_answers": { "q1": "Yes" },
        "expected_conclusion_id": "c_approve"
      }
    ]
  }
}
```

Also accepted: a SMEme `.smeme.json` export envelope (`decision_tree.graph`).

Rules agents miss most often:

- Question `data.type` is always `radio`; always set `required: true`.
- Short stem in `text`; clarifiers in `help_text`; citations in structured
  `authorities` (long `text` warns above ~500 characters).
- `metadata.estimated_time` is in minutes. Use ISO `effective_date` and
  `review_by` for time-sensitive rules.
- `regression_fixtures` are Deploy-time assertions, not `what_if` exploration.
- `data`, nodes, edges, and metadata **forbid unknown keys**.
- Edges are `{ source, target, condition }` only — **no** `id`.
- Edge `condition` must match an option string exactly (prefer explicit
  conditions over empty defaults).
- Conclusions have **no** outgoing edges; include `title` + `summary`
  (optional `recommendations`, `severity`).
- `metadata.title` required (or pass `title` to create/update).

## Tool errors

| `error.code` | What to do |
|--------------|------------|
| `auth_error` | Reconnect MCP once; if `no_local_user_for_clerk_sub`, user must sign in on SMEme web first. |
| `invalid_graph` | Show `error.message` (and `errors` if present). Stay in Phase B/C/D; fix; re-validate. |
| `graph_conflict` | Someone else changed the draft. `get_draft` again; re-apply; validate; update. |
| `draft_not_editable` | Archived or public-version lock — user must restore or create a new version in the web editor. |
| `payload_too_large` | Shrink the graph; split or remove unused nodes. |
| `quota_exceeded` | Plan decision-tree cap hit on **create** — quote `error.message`; user must delete a tree or upgrade. Updates do not consume the cap. |
| `account_downgrade_pending` | User must pick live trees on the dashboard first. |
| `internal_error` | Tell the user SMEme hit an unexpected error; do not retry in a tight loop. |

## Hard boundaries

- **Never Deploy** or claim the draft is live for evaluate.
- **Never invent** a `decision_tree_id` for evaluate tools — only use ids from create_draft
  or **`smeme_reasoning_list`** after Deploy + Listed.
- **Never** send the user’s private files to SMEme except the graph JSON they
  asked you to push.
- **Never** auto-create or auto-update a draft without an explicit ready / push confirmation.
- Prefer **validate → create** and **get → validate → update**; do not skip validate
  on the first push of a change.
- Do not create a second draft just to revise — use **update_draft**.

## Call sequences

### New draft

```
identify / confirm scope
  → smeme_authoring_design_guidance (once; cache by digest)
  → iterate plain-language tree with user (conclusions first)
  → user: ready
  → structure dt_graph
  → smeme_authoring_validate_graph
  → fix until draft_ready
  → smeme_authoring_create_draft
  → keep decision_tree_id + graph_hash; show editor_url
  → stop (Deploy is the user’s next step in the web app)
```

### Revise existing draft

```
smeme_authoring_get_draft
  → edit with user
  → smeme_authoring_validate_graph
  → smeme_authoring_update_draft (expected_graph_hash)
  → on graph_conflict: get_draft again and retry
  → keep new graph_hash for the next revise
  → if deployment_sync is stale: tell user to Redeploy in the editor
```
