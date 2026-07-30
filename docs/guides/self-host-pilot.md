# Self-host pilot: Clerk, MCP, and capability choices

Turn a healthy Core appliance into an authenticated MCP resource server with
optional draft authoring and/or the web generation wizard.

**Prerequisites:** [self-host-quickstart.md](self-host-quickstart.md) (health on
loopback or HTTPS). Env knobs: [self-host-env.md](self-host-env.md). Deep OAuth
reference: [dr3-mcp-oauth-authoritative-sources.md](dr3-mcp-oauth-authoritative-sources.md).

## Support boundary

- Core is the **MCP resource server**. The **authorization server** is separate.
- Turnkey AS today = **Clerk**. Do not assume generic OIDC works.
- Client contract = your **HTTPS** MCP resource URL + OAuth discovery
  (+ static Clerk OAuth app / client ID when DCR is off).
- Image: `ghcr.io/aristalabs/smeme` only.
- **MCP authoring ≠ web wizard.** Authoring uses the client model (no server
  OpenAI/Tavily). Wizard needs `OPENAI_API_KEY` (+ `TAVILY_API_KEY` for full
  research). **Deploy** remains human-in-editor.

Design guidance content version **2.5.0** (Quick encode + Research & critique)
already ships in Core `v0.9.8+` via `smeme_authoring_design_guidance`.

---

## 1. Clerk setup (browser + MCP OAuth)

1. Create a Clerk application (development instance is fine for a lab pilot).
2. Copy into `.env.core`:
   - `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`
   - `CLERK_SIGN_IN_URL`, `CLERK_SIGN_UP_URL`, `CLERK_SIGN_OUT_URL`
     (sign-out must **not** be the sign-in URL)
   - Optional: `CLERK_WEBHOOK_SECRET` if you wire `/auth/clerk/webhook`
   - Optional: `CLERK_OAUTH_ISSUER` for custom Clerk domains
3. In Clerk, allow redirects / callbacks that match your `BASE_URL`
   (e.g. `https://app.example.com/auth/clerk/callback` — use the paths your
   instance documents under Core’s Clerk routes).
4. Recreate `web` so env loads.

Web-first users: complete a browser sign-in once so a local `User` row exists
before MCP, **or** enable MCP-first provision (below).

## 2. Legal gates (required for new Users / MCP-first)

When provisioning new local users (especially
`MCP_FIRST_PROVISIONING_ENABLED=true`), set all four:

```bash
SMEME_LEGAL_TERMS_URL=https://www.smeme.ai/legal/terms
SMEME_LEGAL_PRIVACY_URL=https://www.smeme.ai/legal/privacy
SMEME_LEGAL_TERMS_VERSION=2026-07-20
SMEME_LEGAL_PRIVACY_VERSION=2026-07-20
```

Incomplete legal config fails the **first-provision** path only
(`legal_config_incomplete`), not unrelated MCP startup.

## 3. Enable MCP

```bash
MCP_ENABLED=true
BASE_URL=https://app.example.com          # must match public HTTPS origin
ALLOWED_ORIGINS=["https://app.example.com"]
# MCP_HTTP_PATH=/api/v1/mcp               # default
```

Use the [production HTTPS overlay](self-host-quickstart.md#production-overlay-https--caddy)
so clients see TLS discovery documents.

### Static client vs DCR

| Mode | Clerk | Core env |
|------|-------|----------|
| **Static (default pilot)** | Create an OAuth application; DCR **off** in Clerk | `CLERK_OAUTH_DYNAMIC_REGISTRATION=false` and `SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS=<app-id>` |
| **DCR** | Enable Dynamic OAuth Client Registration in Clerk | `CLERK_OAUTH_DYNAMIC_REGISTRATION=true`; leave allowlist empty if you rely on DCR-minted clients |

Some hosts (e.g. Cursor) refuse OAuth without DCR. Cowork-style connectors often
use a **static** client ID. Pick one and document the client/app ID for operators.

Optional: `SMEME_MCP_OAUTH_ACCESS_TOKEN_AUDIENCE` when Clerk emits a stable `aud`.

## 4. Web-first vs MCP-first

| Path | When |
|------|------|
| **Web-first** | Authors use the dashboard; Clerk session/webhook creates `User`. MCP uses the same identity. |
| **MCP-first** | `MCP_FIRST_PROVISIONING_ENABLED=true` + complete legal constants. A valid MCP Bearer may create the local row after Clerk email + legal acceptance gates. |

## 5. Capability choices

### Reasoning-only MCP

```bash
MCP_ENABLED=true
MCP_AUTHORING_GRAPH_TOOLS_ENABLED=false
SMEME_AI_GENERATION_ENABLED=false
```

Agents: capabilities → guidance → list Listed trees → evaluate → **report**.

### MCP draft authoring

```bash
MCP_AUTHORING_GRAPH_TOOLS_ENABLED=true
```

Uses guidance **2.5.0**:

- **Quick encode** — conclusions → outline → validate (skip research).
- **Research & critique** — host context → factors → pause → critique → outline.

No server OpenAI. Create/update draft tools never Deploy or List — humans Deploy
in the editor. Details: [authoring-decision-trees.md](authoring-decision-trees.md)
(guidance 2.5.0 section).

### Web wizard

```bash
SMEME_AI_GENERATION_ENABLED=true
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...    # optional full research
```

Independent of MCP authoring. Accepts OpenAI (+ Tavily) egress.

## 6. Verification ladder

Run in order; stop at the first failure.

1. **Install / health** — quickstart curl health + health/db.
2. **HTTPS / discovery** — `GET {BASE_URL}/.well-known/oauth-protected-resource`
   (and related AS metadata redirects) over TLS with `MCP_ENABLED=true`.
3. **OAuth** — MCP client completes Clerk login; obtains Bearer for the resource URL
   (`{BASE_URL}{MCP_HTTP_PATH}`).
4. **Authenticated tools** — `smeme_reasoning_capabilities` then
   `smeme_reasoning_guidance_get` succeed.
5. **List / evaluate** — with a **Listed** deployed tree, list + evaluate return a
   server **report**.
6. **Draft authoring (optional)** — `smeme_authoring_design_guidance` returns 2.5.0
   content; validate + create draft; confirm dashboard draft (no auto-Deploy).
7. **Wizard (optional)** — open generation UI; complete a brief with keys set.

## Stuck?

Discussions ([Self-host / operators](https://github.com/AristaLabs/smeme/discussions/categories/self-host-operators))
or [Get started](https://github.com/AristaLabs/smeme/discussions/categories/get-started).
Include image digest; never paste secrets.
