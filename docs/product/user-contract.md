# SMEme user contract (product-facing)

**Audience:** Business owners, study facilitators, end users, and anyone explaining **what the product promises today** versus **what engineering may still explore**. This is **not** a legal agreement; it is a clear narrative for **user testing**, sales conversations, and onboarding.

**Last updated:** 2026-07-16

**Technical depth:** For implementation and protocol detail, use [`ARCHITECTURE.md`](../ARCHITECTURE.md), [`DECISIONS.md`](../DECISIONS.md) (including **D016** MCP/OAuth, **D017** reasoning pipeline, and **D021** blind protocol / agent reliability), and [`smeme/reasoning/evidence_contract.md`](../../smeme/reasoning/evidence_contract.md) (CEVI / published evidence contract — engineer-oriented).

---

## What SMEme is

SMEme connects **subject matter experts** who encode know-how into **interactive workflows** (decision flows) with **people** who answer questions and receive **personalized outcomes** (including optional memo-style summaries).

A **deterministic reasoning layer** runs when a workflow is **deployed**: the platform stores a **compiled reasoning artifact** and can **evaluate** structured answers to produce a **clear outcome** (for example, a single matched conclusion among several possibilities), with reasoning logic staying **on the server**.

---

## Roles

| Role | What they do | What they care about |
|------|----------------|----------------------|
| **Creator** | Authors and deploys workflows; controls MCP discoverability (Listed / Hidden) | Accuracy of deployed logic, brand, who can invoke tools |
| **Consumer** | Completes a workflow in the **web app** (sessions, conclusions, memos) | Clear questions, fair flow, understandable result |
| **Agent user** (e.g. Cowork) | Uses **OAuth-connected** MCP tools to list workflows they own and submit **structured answers** for evaluation | Repeatable workflow, stable IDs, no accidental exposure of hidden decision logic |
| **Grantee** *(Business tier — Coming Soon)* | Accepts a **private share** from a **Business** author; uses the author's deployed workflow through MCP only | Who pays for MCP usage, whether the workflow is Listed in their tool list, author may revoke or pause sharing |

**Today:** Only **Creator**, **Consumer**, and **Agent user** (on workflows they **own**) reflect shipped product behavior. **Free** and **Pro** authors have **no sharing capabilities** — no invites, grants, or Sharing tab. The **Grantee** row and the section below describe the **future Business tier** — see [`business-marketplace-access-plan.md`](../planning/business-marketplace-access-plan.md). Join the **Business waitlist** on the landing page for early access interest.

---

## Private workflow sharing *(Business tier — Coming Soon)*

> **Status:** Engineering plan approved; **not in production**. **Business tier only** — Pro authors cannot share workflows. Do not promise dates to end users. The landing page captures interest via the **Business waitlist**.

### What it is

**Business** authors may invite specific people to use an **author-owned, deployed** workflow through **MCP-connected tools** (Cowork and similar). Sharing grants **usable access** to the author's deployed reasoning artifact. It does **not** copy the workflow, grant edit rights, or expose private branching logic.

**Pro** authors build and deploy workflows for **their own** use only — no outbound sharing.

**Marketplace** (public listings and paid subscriptions) is a separate, later capability — also not shipped.

### Author promises

- May invite by email; recipients on **any plan** (including Free) may accept.
- May **Stop sharing** (pause all grantees) or **Revoke** one recipient — access checks apply on the next MCP call.
- May edit and redeploy the source workflow; grantees continue on the **latest deployed artifact** (they may see **Stale** on the author's dashboard; that badge does not block grantee MCP use).
- May opt in, per invite, to **author-paid MCP usage** so tool calls debit the **author's** plan quota instead of the recipient's (default is **recipient-paid**).

### Grantee promises

- Sees a **Shared with me** row on the dashboard with author attribution.
- Sets their own **Listed / Hidden** for that workflow in **their** MCP tool list (independent of the author's Listed setting).
- Uses the workflow only through MCP; **cannot** edit, redeploy, reshare, or delete the underlying workflow.
- **Remove** from their library ends their access until the author sends a **new invite** (no self-service undo).
- Accepts explicit consent showing **who pays** for MCP tool usage (recipient or author).
- For paid private access (Phase 2): receives clear consent language before any recurring access fee begins; can decline with no change to existing free grant; in-place conversion attaches billing to the current grant without requiring a new invite.

### Quota and plans

| Who pays (`quota_bearer`) | MCP tool usage counts against |
| ------------------------- | ----------------------------- |
| **Recipient** *(default)* | Grantee's own plan limits |
| **Author** | Author's plan limits; grantee quota untouched (including Free grantees) |

Author-paid grants **do not consume the grantee's plan quota** — a Free grantee can use a shared workflow without touching their Free-tier MCP bucket. *(Business tier only.)*

### Dashboard (when Business tier ships)

Three tabs on the dashboard — **always visible** for every signed-in user:

- **Workflows** — workflows you own.
- **Shared with me** — workflows others shared with you (empty how-to until you accept an invite).
- **Sharing** — invite and manage outbound shares (**Business** authors only; Free and Pro users see an upgrade/waitlist path; unused → how-to empty state).

Author-paid usage and alerts appear on **Sharing** for Business authors.

### MCP behavior (when shipped)

- **`smeme_reasoning_list`** will include shared workflows the grantee may invoke and has set to **Listed**.
- Invocation requires an active grant, author **Share** on (not paused), and grantee **Listed**.
- Stable error codes will distinguish revoked access, paused sharing, hidden (not listed), and author quota exhaustion on author-paid shares.

### Not in this release

- Web-app session runs for shared workflows (MCP-only).
- Grantee edits, forks, or reshares.
- Per-grant tool allowlists or edit/redeploy toggles (ideation only).

**Implementation plan:** [`business-marketplace-access-plan.md`](../planning/business-marketplace-access-plan.md)

---

## Creator dashboard: Deploy and Listed

These two controls on the **Dashboard** mean **different things**.

| What you see | What it does |
|----------------|----------------|
| **Deploy** / **Redeploy** (Tools column) | Runs preflight validation checks then compiles the workflow into a reasoning artifact stored on your account. The column shows **Live**, **Stale**, or a **Deploy** button — see below. |
| **Listed** vs **Hidden** (Listed column) | After a workflow is compiled, chooses whether it appears in **your MCP-connected AI tool list** (`Listed`) or stays off that list (`Hidden`). You must Deploy before Listed is available. Listed does **not** affect gallery visibility. |

### Tools column: Live, Stale, and Deploy

The **Tools** column compares your **saved workflow graph** (what is in the editor today) with the **deployed reasoning snapshot** from your last successful **Deploy** or **Redeploy**. Connected AI tools (MCP) evaluate against that deployed snapshot — not every unsaved or undeployed edit.

| What you see | What it means |
|--------------|----------------|
| **Live** | Saved graph matches the deployed reasoning artifact. MCP evaluation reflects the current editor graph. |
| **Stale** | You deployed at least once, but the graph **changed since that deploy**. Connected tools still use the **older version** until you redeploy. This is expected after edits — it is not a bug. |
| **Deploy** (button) | Tools have never been deployed for this workflow, or it is not in a compiled state yet. |

**Why Stale appears:** Any edit after deploy can trigger it — for example nodes, edges, conditions, question text or options. A workflow can still be **compiled** in the editor while the dashboard marks tools **Stale** when the live graph no longer matches the deployed artifact.

**What to do:** Click **Redeploy** on that row (same flow as Deploy in the editor). That recompiles from your **current saved graph** and updates the artifact MCP tools use. After a successful redeploy, the badge should return to **Live**.

---

## Primary product stance: structured answers

**Designed experience:** Evaluation for external agents is centered on **structured inputs**: the caller supplies **`raw_answers`** — a JSON object whose keys are **question identifiers** and whose values match the **published answer shapes** (for example exact option strings for multiple choice, arrays for multi-select, plain text for free-text questions).

**Why:** This keeps the integration **predictable**, **auditable**, and aligned with the **blind evaluation protocol** (below): the assistant maps documents and conversation into **slots**, and the server performs **all** branching and conclusion logic.

**Natural language blobs:** The codebase includes server-side paths that can interpret packaged natural-language evidence in specialized setups. **For this product line and user-testing phase, that path is not the narrative we optimize for.** Roadmap may revisit richer evidence ingestion; until then, treat **structured `raw_answers`** as the **supported story** for Cowork and similar clients.

---

## Blind evaluation (plain language)

**Rule:** Assistants may see **each question's text and valid answers** (for choice questions), but **not** the workflow's internal branching rules, edge conditions, or conclusion wiring.

**Intent (in order):**

1. Keep the assistant in a **gather / slot-fill** role — not reverse-engineering or re-running the decision tree in the model (see [D021](../DECISIONS.md#d021-blind-protocol-retained-for-agent-reliability-not-license-dependent)).
2. Users should answer questions **honestly from their situation**, not game which conclusion "looks best."
3. Creators' decision logic stays **server-side** on the default agent path (still useful for playbook confidentiality; not the only reason for the rule).

**Practical implication:** Worksheets and MCP template tools expose a **flat checklist** of questions — not "if you pick A, you will see question B." A source-available engine license does **not** mean agents receive the branching playbook on evaluate.
---

## MCP and Cowork (high level)

- Connectors use **OAuth**; the user links their **Clerk** identity to their **SMEme account** once.
- **`smeme_reasoning_list`** shows workflows that are **compiled**, **current**, and **marked Listed** by the creator.
- **`smeme_reasoning_capabilities`** describes what a specific workflow can reason about.
- **`smeme_reasoning_template_check`** / **`smeme_reasoning_template_get`** let an **owner** fetch a **digest** and **downloadable worksheet** (markdown) aligned with the blind protocol.
- **`smeme_reasoning_validate_answers`** validates the structured evidence before evaluation.
- **`smeme_reasoning_evaluate`** takes **`raw_answers_json`** and returns an outcome object.

Capabilities and version coupling are advertised via **`smeme_reasoning_capabilities`** (see plugin packaging and server version alignment).

---

## Data and trust (summary)

- **Workflows and deployed artifacts** are controlled by the creator's account and MCP discoverability settings.
- **Session and memo content** follow normal app privacy and retention policies for your deployment.
- **OAuth tokens** authorize MCP tools **for that user**; they do not replace browser cookies for the HTMX app.

For deployment-specific guarantees (hosting region, DPA, retention), use your operator-run customer-facing documents — this file does not replace legal terms.

---

## What we are still building

See **[`ROADMAP.md`](../ROADMAP.md)** for engineering priorities. Roadmap items do **not** automatically promise dates to end users; use this section only to set **expectations** ("in progress," "planned," "not on the near-term path").

| Capability | Status |
| ---------- | ------ |
| **Private workflow sharing** (Business authors → grantees via MCP) | **Business tier — Coming Soon** (waitlist on landing page); see section above and [`business-marketplace-access-plan.md`](../planning/business-marketplace-access-plan.md) |
| **Marketplace** (public listings, subscriptions, author payouts) | Planned later — not on current GTM path |

---

## Related documents

| Doc | Use when |
|-----|-----------|
| [`ROADMAP.md`](../ROADMAP.md) | Engineering priorities and backlog |
| [`ARCHITECTURE.md`](../ARCHITECTURE.md) | System map (web, reasoning, MCP) |
| [`DECISIONS.md`](../DECISIONS.md) | Why key choices were made (ADRs) |
| [`business-marketplace-access-plan.md`](../planning/business-marketplace-access-plan.md) | Private sharing + Marketplace engineering plan (grantee role, quota bearer) |
| [`cowork-reasoning-plugin-runbooks.md`](../guides/cowork-reasoning-plugin-runbooks.md) | Operator and end-user steps for Cowork |
| [`plugin/cowork-skills/README.md`](../../plugin/cowork-skills/README.md) | Agent Skills source layout |
| **In-app creator docs** (signed-in web UI) | **`/docs`** (index), **`/docs/creator-dashboard`**, **`/docs/mcp`** |

---

## Revision notes

Update this file when **product-facing promises** change (for example: enabling new MCP tools broadly, changing the primary integration story from structured answers, or shipping a user-visible blob-evidence flow).

**2026-07-16:** Blind evaluation intent updated for [D021](../DECISIONS.md#d021-blind-protocol-retained-for-agent-reliability-not-license-dependent) — primary rationale is agent reliability / division of labor; source-available licensing does not relax the default MCP wire contract.

**2026-06-30:** **GTM decision:** Current offering is **Free + Pro only** — no workflow sharing. Sharing and monetization are **Business tier only** (Coming Soon / waitlist). Updated Grantee role, private-sharing section, dashboard tabs, and status table accordingly.

**2026-06-26:** Added **Grantee** role and **Private workflow sharing** stub (planned, not shipped): dashboard tabs (Workflows / Shared with me / Sharing — always visible), empty/upgrade states, MCP-only access, per-user Listed, quota bearer (recipient vs Business-only author-paid), Share/Unshare/Revoke/Remove semantics. Marketplace remains future work.

**2026-06-09:** Removed Publish/marketplace, pricing, Revenue, and Visibility column references — none exist in the current default deployment. Added `smeme_reasoning_validate_answers` to MCP tools list. Updated Roles (removed pricing). Corrected "published" → "deployed" throughout.

**2026-05-22:** Documented **Tools column** states **Live**, **Stale**, and **Deploy**.
