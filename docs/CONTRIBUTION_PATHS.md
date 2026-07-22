# Contribution paths

**Audience:** public Core contributors (`AristaLabs/smeme`).  
**Status:** curated themes — not a commitment schedule.

This is the **canonical** list of contribution-friendly directions for Core.
Internal sprint docs and the private roadmap should **point here** instead of
maintaining a second stretch list.

For how to open a PR and the CLA, see [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## How to use this list

1. Pick a theme below (or propose a related Core improvement in an issue).
2. Open an issue before large changes so maintainers can confirm scope.
3. Keep PRs in **Core** product surface only — no hosted billing, marketing,
   waitlist, or Arista legal pages.

Out of scope for community PRs against public Core: Stripe Checkout/Portal,
SaaS Free/Pro enforcement product, Business marketplace timing, and extract/ops
work for the private overlay.

## Themes

### Auth — generic OIDC MRS

SMEme is an MCP **resource server**. Clerk is the first documented profile.
Help generalize issuer + JWKS verify and `sub` → local user so operators can
bring another OIDC authorization server without embedding an AS in SMEme.

### Quotas — operator-managed limits

Core **meters** MCP/wizard usage with **enforcement off** by default. A useful
contribution is operator-managed caps: install **defaults** and optional
**per_user** overrides in the DB (env may seed defaults only).

This is **not** “turn on hosted Free/Pro tiers for self-host.” Hosted Mode B
caps stay in the commercial overlay.

### Observability — optional LangSmith

LangSmith is hard-off today. An opt-in operator switch (default off, documented
egress implications) is a possible path — product decision required before
merge.

### Docs, tests, and Core polish

Self-host guides, MCP connector docs, engine promises, unit/integration tests
for KEEP surfaces, and small UX fixes in the editor/dashboard are always
welcome when they improve the public appliance.

## Non-goals (do not propose here)

- Reintroducing deleted lab surfaces (gallery, scout-as-default, etc.)
- License-key / entitlement servers for a paid self-host SKU
- n8n-style `.ee` files in the public tree
- Calling the product “open source” in docs or marketing copy

## Maintainers

Private priorities and sprint status live outside this file. When stretch items
change, **edit this document** and leave one-line pointers from ADRs / sprints /
guides.
