# Roadmap

**Last updated:** 2026-07-20

This file is the canonical **current priorities** list. Deep dives live in linked docs. For day-to-day assistant context, see [`CLAUDE.md`](../CLAUDE.md) at the repo root.

For **product positioning**, **user-testing scripts**, and stakeholder-facing promises in plain language (distinct from ADRs and architecture), see **[`docs/product/user-contract.md`](product/user-contract.md)**.

---

## Now

1. **Design system** — Roll semantic tokens and macro patterns through editor and QNR generation templates.
2. **Admin panel** — Operations and moderation surface (backlog).
3. **Reasoning / DR-4+** — **`evaluate_reasoning`**, persisted runs, `triggered_edges`, and MVP `explanation` are shipped; IR-first cutover is complete. Next: full dev plan **§6** explanation schema, **§5.2.7** golden matrix expansion, and deferred instrumentation (**§5.1** `P_e` / `triggered_rules`) per [`smeme/reasoning/README.md`](../smeme/reasoning/README.md), [DTQ → reasoning cutover](planning/dtq-to-reasoning-cutover.md), and the legacy spec ([dev plan §5–§7](planning/Determinisitc%20Reasoning%20Planning/SMEme%20deterministic%20reasoning%20dev%20plan.md)).
4. **DR-3 / Cowork / MCP (remaining)** — P0–P2 + MCP hardening sprint **shipped** (see Shipped). **Still open:** OAuth refresh UX (connector de-auth); **`reasoning:*`** scope enforcement when Clerk supports custom scopes; optional **`aud`** binding when a stable JWT audience is confirmed (benched — [D016 P3](DECISIONS.md#d016-authentication--permissions--final-plan-cowork-launch-remote-mcp-sso)). **Client registration:** GTM (July 2026) uses **DCR-off + static Client ID + guidance tools**; **CIMD** researched, not implemented — [cimd research](planning/cimd-mcp-client-registration-research-2026-07.md). **Not planned:** first-class HTTP API keys for external agents. Ops: [runbooks](guides/cowork-reasoning-plugin-runbooks.md), [DR-3 guide](guides/dr3-mcp-oauth-authoritative-sources.md).
5. **Clerk profile / account UX** — Refactor `/auth/profile` for Clerk ownership split (see D016 pre-deployment notes).
6. **Discovery metadata + Cowork skills** — Iterate after real connector and LLM usage. Two-phase harness skills/docs pass (**`harness_next`**, shipping §2.8, logical analysis as first-class) landed in capabilities **2.16.0** / guidance **1.1.0**. Continue refining from live Cowork sessions.
7. **Microsoft 365 Copilot Cowork plugin (M365-CWP)** — Optional second distribution (M365 App Package) from skills + MCP server; personal sideload + tenant admin upload in v1. **Planning:** [sprint-m365-copilot-cowork-plugin.md](planning/sprint-m365-copilot-cowork-plugin.md). Anthropic installable zip path is **retired** (connector + guidance only).
8. **Chat authoring → draft (secondary path)** — Agent helps identify a workflow, fetches `smeme_authoring_design_guidance`, iterates Q/options/branches in chat, then `smeme_authoring_validate_graph` → `smeme_authoring_create_draft`. Skill: `smeme-workflow-author` + `DESIGN.md`. Flag `MCP_AUTHORING_GRAPH_TOOLS_ENABLED` (default **off**). Wizard remains the primary research-heavy path.
9. **Self-host / public product distro** — Inventory: **[D022](DECISIONS.md#d022-product-surface-inventory--keep--saas-only--removed-core-distro-prep)**. Distribution: **[D023](DECISIONS.md#d023-public-core-repo--private-saas-overlay-distribution)** (public `AristaLabs/smeme` + private `smeme-cloud`; `ghcr.io/AristaLabs/smeme`; SMEme SUL 1.0). Sprint: **[sprint-core-public-release.md](planning/sprint-core-public-release.md)** — A appliance proof → B legal pack (counsel waived) → C extract. Stretch: generic OIDC MRS, admin quotas.

---

## Shipped (reference)

| Theme | Where to read |
|--------|----------------|
| MCP counterfactual tools (`what_if`, `how_to_reach`, `list_conclusions`) | [sprint-mcp-counterfactual-whatif-howto.md](planning/sprint-mcp-counterfactual-whatif-howto.md) |
| Subscription billing, quotas, downgrade lifecycle (Mode B caps, Pro $49, dormant + pick-live) | [sprint-subscription-billing-quotas.md](planning/sprint-subscription-billing-quotas.md) |
| Billing Sprint 7–8 (Premium, Stripe webhooks, Customer Portal) | [Sprint 7](historical/sprints/sprint-07-stripe-implementation.md), [Sprint 8](historical/sprints/sprint-08-stripe-revenue-implementation.md) |
| DR-3 P0–P2 (Streamable HTTP MCP, RFC 9728 + AS metadata, Clerk Bearer, transport **401** challenge) | [DR-3 sprint](planning/sprint-dr3-clerk-oauth-as-metadata.md), [DR-3 guide](guides/dr3-mcp-oauth-authoritative-sources.md), [D016](DECISIONS.md#d016-authentication--permissions--final-plan-cowork-launch-remote-mcp-sso) |
| MCP hardening — quota (A0–A4), transport rate limits (B1-a), invocation telemetry + COGS, plugin delivery (C), unlinked-account auth UX | [sprint-mcp-quota-enforcement-hardening.md](planning/sprint-mcp-quota-enforcement-hardening.md) |
| DR-3 P3 partial — `mcp_tool_invocations` metering, quota enforcement on billable tools, OAuth client allowlist code (SaaS: **DCR on**, blank allowlist) | [D016 P3](DECISIONS.md#d016-authentication--permissions--final-plan-cowork-launch-remote-mcp-sso), [mcp-cost-telemetry.md](guides/mcp-cost-telemetry.md) |
| Cowork plugin bundle — gate, `plugin_bundle_releases`, same-origin download *(retired 2026-07; connector + guidance only)* | [cowork-plugin-delivery-sprints.md](planning/cowork-plugin-delivery-sprints.md), [plugin static sprint (archived)](historical/planning/sprint-plugin-bundle-fastapi-static.md) |
| MCP reasoning template / worksheet tools | [sprint-mcp-reasoning-template-tools.md](planning/sprint-mcp-reasoning-template-tools.md) |
| MCP guidance tools (`guidance_check`, `guidance_get`) — connector-only bootstrap | [sprint-mcp-guidance-tools.md](planning/sprint-mcp-guidance-tools.md) |
| LangGraph checkpoint + wizard event retention (quota counting) | [checkpoint-maintenance-plan.md](planning/checkpoint-maintenance-plan.md) |
| Lab surface strip + keep/SaaS-only inventory (2026-07-18); public Core + private SaaS overlay ADR (2026-07-20) | **[D022](DECISIONS.md#d022-product-surface-inventory--keep--saas-only--removed-core-distro-prep)**, **[D023](DECISIONS.md#d023-public-core-repo--private-saas-overlay-distribution)**, this ROADMAP gated table |
| Clerk web auth (modal sign-in, callback route, logout contract, `azp` parties) | [D016 P1-Web / P2](DECISIONS.md#d016-authentication--permissions--final-plan-cowork-launch-remote-mcp-sso) |
| Agentic QNR generation subgraph redesign | [Sprint overview](historical/sprints/SPRINT_OVERVIEW.md) |
| Long-form “6-month” sprint narrative (Feb 2026 snapshot; many items since superseded) | [Archived development roadmap](historical/plans/smeme_dev_roadmap_corrected.md) |

---

## Gated surfaces

Defaults in [`smeme/core/config.py`](../smeme/core/config.py). Operator toggles via env.

| Flag (env) | Default | What it gates |
|------------|---------|----------------|
| `SHOW_QNR_GENERATION_REGION_SELECTOR` | **on** | Tavily region control on agentic generation brief |
| `SMEME_AI_GENERATION_ENABLED` | **on** (SaaS default) | AI generation wizard + checkpointer; requires `OPENAI_API_KEY`. Core appliances may set **off** |
| `MCP_AUTHORING_GRAPH_TOOLS_ENABLED` | off | `smeme_authoring_design_guidance` + `smeme_authoring_validate_graph` + `smeme_authoring_create_draft`; skill `smeme-workflow-author` + `DESIGN.md` |
| `MCP_ENABLED` | off | Streamable HTTP MCP mount + OAuth discovery |

**Removed / SaaS-only / Keep:** canonical inventory is **[D022](DECISIONS.md#d022-product-surface-inventory--keep--saas-only--removed-core-distro-prep)**. Distribution (public `AristaLabs/smeme` + private `smeme-cloud`, `ghcr.io/AristaLabs/smeme`, SMEme SUL 1.0) is **[D023](DECISIONS.md#d023-public-core-repo--private-saas-overlay-distribution)**. Summary: lab surfaces deleted; Business waitlist remains **SaaS-only** (private overlay); public extract in progress — [checklist](planning/core-public-extract-checklist.md).

---

## Product and stakeholder docs

- **[`docs/product/user-contract.md`](product/user-contract.md)** — Features, roles, and roadmap framing for **business owners** and **user testing** (plain language).

---

## Other planning dirs

- **Active specs:** [`docs/planning/`](planning/) — deterministic reasoning plans, QNR generation UX refinement (cited from code), feature memos not yet folded into architecture.
- **Business and Marketplace access (Coming Soon):** [`docs/planning/business-marketplace-access-plan.md`](planning/business-marketplace-access-plan.md) — future **Business tier**: MCP-only workflow sharing, paid private access, and (deferred) public marketplace. **Not on current GTM path** — today's offering is **Free + Pro only** with no sharing; Business interest captured via landing-page waitlist.
- **Backlog ideas:** [`docs/planning/future-features.md`](planning/future-features.md)
- **Architecture & ADRs:** [`docs/ARCHITECTURE.md`](ARCHITECTURE.md), [`docs/DECISIONS.md`](DECISIONS.md)
