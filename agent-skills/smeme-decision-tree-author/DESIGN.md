# SMEme — Decision Tree Design Guidance

_Versioned standard for designing reasoning decision trees in chat. Served by
`smeme_authoring_design_guidance`. Content version: 2.2.0_

---

## What this is for

You help the user encode an expert judgment as a SMEme **decision tree** (branching
questions → mutually exclusive **conclusions**). SMEme owns this design
standard; apply it while iterating in plain language, then structure a graph
and call **`smeme_authoring_validate_graph`**.

This document **is** the connector-reachable authoring contract. There is no
separate installable skill over MCP — treat this markdown as authoritative for
both design rules and the `dt_graph` wire shape below.

This is **not** the web generation wizard. Do not paste research pipelines or
markdown decision-tree designs meant for the wizard. Keep the tree readable until the
user says they are ready to push.

---

## Product constraints (hard)

SMEme decision trees today support **only radio questions** (one exclusive choice).

- Do **not** invent checkbox, free-text, number, date, or multi-select questions.
- Every question is **required** on the wire: set `data.required: true`. If the
  user may not know, add an explicit option such as `Unsure` or
  `Not enough information` — do not rely on skip / `required: false`.
- Only **conclusions** are terminal. No question may be a dead end; every option
  must lead to another question or a conclusion.
- Edge conditions must match option labels **exactly** (same spelling and case).
- Prefer **explicit** per-option branches. Do not leave options without a route.

---

## Wire shape (`dt_graph`)

Validate expects this object (or a SMEme `.smeme.json` export with
`decision_tree.graph`). Unknown keys under `data`, nodes, edges, or metadata
are **rejected** (`extra=forbid`).

```
Node:            { id, type: "question"|"conclusion", data }
Question data:   { text, type: "radio", options: [str], required: true,
                   help_text? }
Conclusion data: { title, summary, recommendations?: [str],
                   severity?: "info"|"warning"|"critical" }
Edge:            { source, target, condition }   // no id
Graph:           { nodes, edges, metadata: { title, ... } }
```

Rules agents miss most often:

- Put the short stem in `text`. Put clarifiers, examples, and statute citations
  in `help_text` — long `text` triggers warnings above ~500 characters.
- Always set `required: true` on questions (do not omit and hope for a default).
- Edges are `{ source, target, condition }` only — **no** `id` (or any other key).
- `condition` must equal an option string exactly (prefer explicit conditions;
  empty/default edges are for rare skip paths, not normal radio trees).
- Conclusions need `title` + `summary`; optional `recommendations` (string list)
  and `severity` (`info` | `warning` | `critical`).
- Ids: start with a letter; letters, digits, `_`, `-` only.
- `metadata.title` required (or pass `title` to `smeme_authoring_create_draft`).

Minimal example:

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
        "help_text": "Use the latest audited statements when available."
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
  "metadata": { "title": "Vendor Approval Assessment" }
}
```

---

## Start with conclusions (closed outcome set)

Before deep branching, lock a small set of outcomes with the user:

1. **2–6 conclusions** — mutually exclusive (exactly one applies per case).
2. **Exhaustive for the scope** — every plausible case lands somewhere; use a
   conservative / defer outcome if needed (e.g. `Needs more review`).
3. **Actionable titles** — short names the user recognizes (`Approve`,
   `Reject`, `Escalate`).
4. **Discriminable** — the questions you ask must be enough to tell conclusions
   apart.

Do not grow the conclusion list during branching without re-confirming with the
user. Extra outcomes that no path can reach will fail validation or Deploy later.

---

## Design principles

### Conclusion-driven branching

- Every path reaches a conclusion — no orphan questions.
- Early questions should **discriminate** among conclusions (eliminate whole
  subtrees when an answer is dispositive).
- Multiple paths may reach the same conclusion.
- Conclusions are reached by **specific answers**, never as an unspoken default.

### Efficient trees (anti-funnel)

- Prefer a **branching tree**, not a linear checklist of every factor.
- Skip irrelevant blocks: if Factor X does not apply after answer A, do not ask
  Factor X on that path.
- For **diagnostic** trees (answers eliminate subtrees), typical cases should
  answer **fewer than half** of all questions when branching works.
- **Conjunctive / multi-element tests** are different: when the rule requires N
  independent findings that must *all* be established before an outcome (or
  exception) applies, the main path may legitimately visit most of those
  element questions. That is not a funnel — a funnel asks *irrelevant* factors.
  Name the pattern for the user (“conjunctive test: five elements of Rule X”)
  and still skip any factor that a prior answer made moot.
- Do not ask the same decision twice on one path.

### Path-dependent reuse (radio-only)

Radio-only trees have no shared “subroutine” nodes. If the same check must
resolve to **different next steps** depending on how you reached it (e.g.
overlay “clear” → outside-the-rule on one path, de minimis on another),
**duplicate the question** with distinct ids (`q7a`, `q7b`) and route each
copy explicitly. Do not force a single shared node when outcomes diverge.

### Routing vs collect-only

Default every question to **routing**: different options lead to materially
different next steps (different questions, skipped groups, or conclusions).

Use **collect-only** rarely: every option goes to the same next node because the
answer is needed later for wording or evidence quality — **not** for routing.
Say so to the user when you do this.

**Forbidden pattern:** Q1 options `Yes` / `No` / `Unsure` all go to Q2 except
one token route to a conclusion, while claiming Q1 is a real gate. Early gates
(Q1–Q3) that matter should create **at least two materially different routes**.

### Unsure / unknown policy

`Unsure` must **not** automatically mean “continue to the next sequential
question.” Choose deliberately with the user:

- Route to a **conservative conclusion** when uncertainty should not proceed, or
- Route to a **forward** diagnostic follow-up (higher question or a conclusion), or
- Treat Unsure as equivalent to a named option — and say so.

**Forbidden:** child Unsure routes **back** to the parent question (ping-pong /
cycle). Always route Unsure **forward**.

```
Bad:  Q4 Unsure → Q5, Q5 Unsure → Q4
Good: Q4 Unsure → Q5, Q5 Unsure → Q6 or a conclusion
```

---

## Plain-language iteration (before JSON)

Work with the user in readable outline form:

1. Goal / decision in one sentence.
2. Conclusion list (titles + one-line meaning).
3. Questions with options and “if X → …”.
4. Preflight checklist (below).
5. Only then structure wire JSON and validate.

Do **not** emit `dt_graph` JSON until the user is ready (or explicitly asks to
validate / push).

---

## Preflight checklist (before validate)

- [ ] Exactly one entry question (start of the tree).
- [ ] Every question option has an outgoing route.
- [ ] Every conclusion is reachable from at least one path (for the agreed set).
- [ ] No cycles / Unsure ping-pong.
- [ ] Option strings on edges match question options exactly.
- [ ] Stable ids: start with a letter; letters, digits, `_`, `-` only.
- [ ] Question `data` has `type: "radio"`, `required: true`, short `text`,
      clarifiers in `help_text` (not stuffed into `text`).
- [ ] Edges are `{ source, target, condition }` only (no `id`).
- [ ] No unknown keys under `data` / nodes / edges / metadata.
- [ ] `metadata.title` set (or you will pass `title` to create_draft).

Then: **`smeme_authoring_validate_graph`** → fix `errors` → when `draft_ready`,
**`smeme_authoring_create_draft`** after user confirmation.

---

## Anti-patterns (reject in design)

- Linear funnel that asks every factor on every path.
- Terminal questions (no outgoing routes).
- Hidden / implicit defaults to a conclusion.
- Checkbox or free-text “questions.”
- Growing the tree without a locked conclusion set.
- Long question stems that belong in `help_text`.
- Claiming the draft is Deployed or evaluable before the user Deploys + Lists
  it in the SMEme web app.

---

## Summary

- Lock **conclusions** first; branch to discriminate among them.
- **Radio-only**, `required: true`, explicit option routes, conclusions only
  as terminals.
- Prefer sparse branching over checklists; Unsure goes **forward**.
- Structure only the allowed wire fields; put guidance in `help_text`.
- Iterate in prose; validate; create draft; user Deploys in the web app.
