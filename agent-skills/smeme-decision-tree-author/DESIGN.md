# SMEme — Decision tree Design Guidance

_Versioned standard for designing reasoning decision trees in chat. Served by
`smeme_authoring_design_guidance`. Content version: 1.0.0_

---

## What this is for

You help the user encode an expert judgment as a SMEme **decision tree** (branching
questions → mutually exclusive **conclusions**). SMEme owns this design
standard; apply it while iterating in plain language, then structure a graph
and call **`smeme_authoring_validate_graph`**.

This is **not** the web generation wizard. Do not paste research pipelines or
markdown decision-tree designs meant for the wizard. Keep the tree readable until the
user says they are ready to push.

---

## Product constraints (hard)

SMEme decision trees today support **only radio questions** (one exclusive choice).

- Do **not** invent checkbox, free-text, number, date, or multi-select questions.
- Every question is **required**. If the user may not know, add an explicit
  option such as `Unsure` or `Not enough information` — do not rely on skip.
- Only **conclusions** are terminal. No question may be a dead end; every option
  must lead to another question or a conclusion.
- Edge conditions must match option labels **exactly** (same spelling and case).
- Prefer **explicit** per-option branches. Do not leave options without a route.

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
- Typical cases should answer **fewer than half** of all questions when
  branching works.
- Do not ask the same decision twice on one path.

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
- Claiming the draft is Deployed or evaluable before the user Deploys + Lists
  it in the SMEme web app.

---

## Summary

- Lock **conclusions** first; branch to discriminate among them.
- **Radio-only**, required questions, explicit option routes, conclusions only
  as terminals.
- Prefer sparse branching over checklists; Unsure goes **forward**.
- Iterate in prose; validate; create draft; user Deploys in the web app.
