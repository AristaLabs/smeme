# SMEme licensing FAQ (plain language)

**Licensor:** Arista Labs, LLC  
**Software license:** [SMEme Sustainable Use License 1.0](LICENSE.md)  
**Status:** Source-available / fair-code — **not** OSI-approved open source. Prefer those words in marketing and docs; never call SMEme “open source.”

This FAQ explains common cases. It does **not** replace the license. When in doubt, the [LICENSE.md](LICENSE.md) text controls. Commercial arrangements: contact Arista Labs, LLC.

The license text is adapted from the Sustainable Use License 1.0 published by n8n GmbH. n8n’s own docs state that other projects may use that license; this adaptation is renamed and published under Arista Labs, LLC to avoid confusion with n8n’s product license. SMEme is not affiliated with or endorsed by n8n.

**Self-review note:** Arista Labs is shipping this pack without outside counsel review. Residual risk remains (license adaptation, commercial boundary examples, corresponding-source offer). Treat this FAQ as guidance, not legal advice.

---

## Allowed under the SMEme Sustainable Use License

- A company **self-hosts** SMEme for its employees (internal business use).
- **Network access** to that instance (browser, API, MCP) for the organization’s own internal users, contractors, and agents acting on its behalf.
- **Commercial use of outputs** produced with SMEme (reports, documents, decisions derived from evaluation) — see [Outputs](#outputs-and-model-providers) below.
- **Consultants** installing, customizing, and supporting a customer’s **internal** instance (charging for services, not for the software — expressly permitted by the professional-services provision in the license Limitations).
- **Private modifications** for internal use (you must mark modified copies per the license).
- **Integrations and extensions** that interoperate with SMEme (agents, MCP clients, connectors) without offering SMEme itself as a paid hosted product.
- Running SMEme on **infrastructure the customer controls** (their VPS, cloud account, or on-prem), including one-click / template installs where the customer owns the instance and uses it for internal business purposes.

## Requires a commercial agreement with Arista Labs, LLC

- Charging customers for access to a **hosted** SMEme instance (competing with `smeme.ai` / managed service).
- **White-labeling** SMEme as another product.
- **Reselling** SMEme or a substantially similar managed service.
- **Embedding** the SMEme application as a **material customer-facing feature** of another commercial product or service — contact Arista Labs / commercial terms before shipping.
- Operating a **multi-tenant** service whose primary value is access to SMEme for unrelated third parties (invoice labels such as “compute only” do not change the substance of the offer).

Consulting, implementation, and support engagements for a customer’s own internal deployment remain permitted under the license limitations above.

## What we copy from n8n — and what we do not

SMEme follows an n8n-shaped **fair-code** model: public self-hostable product + commercial hosted service + optional paid proprietary functionality later.

**We do not** mix enterprise-only code into the public repository under `.ee` filename conventions. Commercial / SaaS-only code lives in a **private overlay** (`smeme-cloud`), built on a pinned public `smeme` image. See [D023](docs/DECISIONS.md#d023-public-core-repo--private-saas-overlay-distribution).

## Outputs and model providers

The SMEme Sustainable Use License governs the **SMEme software**, not ownership of:

- **User inputs** (decision-trees, answers, prompts you supply), or
- **Generated or evaluated outputs** (drafts from optional AI generation, MCP reports, documents your agents produce from those reports).

You (or your organization) retain rights in your content subject to your own policies and any **third-party model or API terms** that apply when you enable optional egress (for example OpenAI or Tavily when AI generation is on). Self-host defaults keep generation **off**; see [self-host quickstart — sovereignty](docs/guides/self-host-quickstart.md#sovereignty--third-party-egress).

## Contributions

Accepted contributions are licensed so Arista Labs, LLC can distribute them under the project license and related commercial terms. See [CONTRIBUTOR_LICENSE_AGREEMENT.md](CONTRIBUTOR_LICENSE_AGREEMENT.md) and [CONTRIBUTING.md](CONTRIBUTING.md).
