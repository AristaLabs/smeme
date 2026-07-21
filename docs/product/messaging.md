# SMEme messaging one-pager

**Audience for this doc:** landing page, AristaLabs product page, sales conversations, blog framing.  
**Last updated:** 2026-07-20  
**Buyer:** AI / IT people evaluating a reasoning layer (hosted or self-host) — not only Claude/ChatGPT enthusiasts.

**Related:** [`user-contract.md`](user-contract.md) (product promises) · AristaLabs mission (expertise in expert hands) · blog thesis (encode in logic, not weights).

---

## Thesis (one sentence)

Human expertise should live in **inspectable decision-trees and symbolic logic**, not be absorbed into **LLM model weights** — SMEme is the **logical analysis engine** that authors, deploys, and evaluates that logic, with **sovereignty** over how hosted trees are handled (or full control via self-host).

---

## Three pillars

| Pillar | Job | Lead with |
|--------|-----|-----------|
| **Encode** | Why this exists | Decision-trees / symbolic logic vs model weights |
| **Engine** | What it is | Not a flowchart — compile → validate → deterministic evaluate |
| **Sovereignty** | How hosted trees are handled | Ownership, isolation, eval boundary, lifecycle control; self-host when policy requires it |

Do not make sovereignty the product definition. Do not drop it for hosted buyers.

---

## Lexicon

| Say | Avoid as primary | Notes |
|-----|------------------|--------|
| **decision-tree** / **decision tree** | workflow (for the QNR artifact) | Two words in prose; hyphenate as adjective (“decision-tree build”) |
| **logical analysis engine** / **reasoning engine** | flowchart, chatbot, “AI workflow” | Runtime that evaluates deployed trees |
| **Deploy** / **Redeploy**, **Listed** / **Hidden**, **Live** / **Stale** | publish (when meaning reasoning artifact) | Unchanged product vocabulary |
| **hosted** / **self-host** | “sovereign” alone | Deploy modes; sovereignty is the trust story for hosted |
| **workflow** | — | Keep for LangGraph internals, agent run sequences, “agentic workflows” only |
| Wire IDs (`qnr_id`, REST paths, MCP tool names) | renaming | Do not rename for copy |

**Short product phrase:** Decision-tree you can inspect. Logical analysis you can trust.

---

## Hero (ready to drop in)

**Headline**

Sovereign expert reasoning — decision-trees your agents call through MCP

*(Alternate, more category-first:)*  
Encode expertise as decision-trees. Run logical analysis — not another LLM guess.

**Sub (tight)**

Not every task should run inside a language model — especially expert reasoning.

SMEme helps you encode judgment as **decision-trees**, then compiles them into a **logical analysis engine**. Your agent gathers evidence; SMEme evaluates against your rules and returns a deterministic, attributable result. Language models handle language. SMEme handles analysis.

**Hosted or self-host.** On SMEme-hosted, your trees stay yours: evaluation runs on our infrastructure under your controls — not inside the LLM provider. Prefer self-host when residency or policy requires your VPC. Self-host runs the **source-available** SMEme product image (`ghcr.io/AristaLabs/smeme`); `smeme.ai` is the managed commercial layer (`smeme-cloud`) on top of that same image ([D023](../DECISIONS.md#d023-public-core-repo--private-saas-overlay-distribution)).

**CTAs**

1. Start free  
2. See how it works  
3. Sovereignty *(→ `/legal/principles` — how we handle hosted decision-trees)*

**Demote from hero (move to principles / security / pricing footnote)**

- “Zero out IP exposure” as the closer  
- Long Cowork-only happy path  
- Stacking “proprietary / never shared / micro-theories” in one paragraph  

---

## Section blurbs (landing)

### Encode — where knowledge lives

Expertise that only lives in prompts, RAG corpora, or fine-tuned weights is hard to audit and easy to drift. SMEme encodes that judgment as **decision-trees** you can inspect, version, and deploy — aligned with Arista Labs’ mission to keep expertise in expert hands.

*Blog owns the technical argument (logic vs weights). Landing states the claim; blog proves it.*

### Engine — not a flowchart

A diagram for humans is not enough. SMEme decision-trees **compile** into a reasoning model: structural checks at deploy, then deterministic **evaluate** at runtime. Same facts in → same conclusion out. Agents submit structured answers; the **server** runs the analysis and returns a report with an attributable path — not a plausible guess.

| Flowchart (what buyers fear) | SMEme decision-tree |
|------------------------------|---------------------|
| Drawing for humans | Artifact that compiles to a reasoning model |
| Paths are documentation | Paths are constraints the engine checks |
| Soft “usually goes here” | Same facts → same conclusion |
| Agent reads the diagram | Agent submits answers; server runs analysis |
| Edit = redraw | Edit → redeploy → Live / Stale is real |

### Integrate — agents call the engine

Connect any MCP-capable agent. The agent maps case facts into typed answers; SMEme validates and evaluates against your **deployed** decision-tree. Results return as trusted context for chat or the next agent step. Lead with “your agent stack”; Claude Cowork is an example, not the product.

### Deploy — hosted or self-host

| Mode | Promise |
|------|---------|
| **SMEme-hosted** | We operate the platform. You own the trees. Evaluation runs on SMEme, not in the LLM. Lifecycle (Listed / Hidden, deploy, export, delete) stays under your control. See Sovereignty. |
| **Self-host** | Source-available **Core** Docker image in your environment ([D023](../DECISIONS.md#d023-public-core-repo--private-saas-overlay-distribution)). Same product engine; you own the control plane when policy requires it. Public Core is the contributor and self-host codebase — not a closed binary-only drop. |

---

## Sovereignty blurb (hosted — principles / CTA target)

**For marketing (short)**

On SMEme-hosted, sovereignty means **control of your decision-trees and where analysis runs**: you own what you encode; we do not train foundation models on your Expert Assets; evaluation happens on SMEme infrastructure, not inside the LLM provider; agents receive outcomes and attributable paths — they do not become co-authors of your rulebase. Need the trees in your VPC? Self-host.

**Five points (principles page / sales)**

1. You own the decision-trees; using SMEme does not transfer ownership.  
2. We do not use your Expert Assets to train or fine-tune artificial-intelligence or machine-learning models.  
3. Deterministic evaluation runs on SMEme (or your self-host), not inside the LLM provider.  
4. You control lifecycle: Deploy, Listed / Hidden, export, delete.  
5. Self-host when residency or organizational policy requires your infrastructure. Self-host operators: see which optional flags send decision-tree content to third parties in [`self-host-quickstart.md` — Sovereignty](../guides/self-host-quickstart.md#sovereignty--third-party-egress) (generation wizard / OpenAI / Tavily are the main opt-in egress; evaluate stays local).

*(Principles HTML still says “workflows” in places — update to decision-trees when the product vocabulary pass lands.)*

---

## AristaLabs (parent) one-liner

Arista Labs builds AI that keeps expertise in expert hands. SMEme, our flagship, lets experts encode judgment as **decision-trees** and run them through a **logical analysis engine** — hosted or self-host — so agents get deterministic answers while knowledge stays in inspectable logic, not model weights.

---

## What “sovereignty” is / is not

| Is | Is not |
|----|--------|
| Trust story for **hosted** buyers | The entire product pitch |
| Ownership + eval boundary + lifecycle | “We hide your IP from the internet” as the category |
| Complementary to self-host | A substitute for clear encode + engine messaging |

---

## Implementation checklist (copy pass — later)

1. Replace landing hero with the hero block above.  
2. Reframe how-it-works / pricing around encode → engine → deploy modes; keep Sovereignty CTA.  
3. Product vocabulary: public “workflow” (QNR artifact) → “decision-tree” (templates, billing/MCP user strings, Cowork skill prose, in-app docs).  
4. Update `user-contract.md` + `CLAUDE.md` product vocabulary table.  
5. Align AristaLabs `product.html` with parent one-liner.  
6. Blog post: technical argument for logic/trees vs weights; link back to SMEme as the operationalization.  
7. Do **not** rename wire IDs, packages, LangGraph “workflow”, or MCP tool names in that pass.

---

## Voice notes for IT / AI buyers

- Prefer **governance, audit, change control, deterministic, deploy** over enthusiast MCP jargon.  
- Name MCP once as the integration surface; do not require Cowork literacy in the first viewport.  
- Micro-theory language is optional in deeper pages and not required in the hero.  
- “Logical analysis engine” is enough for marketing; leave Z3 / IR detail to docs and the blog.
