# MCP and OAuth operator guide

Use this list when implementing or spiking **remote MCP + OAuth 2.1** for SMEme. Prefer these over third-party tutorials; re-check **Anthropic** and **MCP** docs each release (connectors and betas change).

## Model Context Protocol (normative)

| Topic | URL | Notes |
|--------|-----|--------|
| Spec index (2025-11-25) | https://modelcontextprotocol.io/specification/2025-11-25/index.md | Version pin for implementation |
| **Authorization** | https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization.md | RS = OAuth 2.1 resource server; **RFC 9728** protected resource metadata **MUST**; AS discovery **RFC 8414** + OIDC discovery |
| **Transports** (Streamable HTTP) | https://modelcontextprotocol.io/specification/2025-11-25/basic/transports.md | Replaces 2024-11-05 HTTP+SSE; single MCP endpoint; POST+GET; `MCP-Protocol-Version`; **Origin** validation / DNS rebinding |
| Lifecycle | https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle.md | Initialize, version negotiation, `MCP-Session-Id` when stateful |
| Security best practices | https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices.md | Complements transport security rules |
| Authorization tutorial | https://modelcontextprotocol.io/docs/tutorials/security/authorization.md | Implementation-oriented |
| Connect remote servers | https://modelcontextprotocol.io/docs/develop/connect-remote-servers.md | Remote URL + client setup |
| MCP Inspector | https://modelcontextprotocol.io/docs/tools/inspector.md | Local debugging of HTTP servers |
| Full doc index | https://modelcontextprotocol.io/llms.txt | Machine-discoverable sitemap |

### Streamable HTTP (quick ref)

- Clients send JSON-RPC via **HTTP POST** to the **MCP endpoint**; **Accept** must include `application/json` and `text/event-stream`.
- Servers respond with **JSON** or **SSE** (`text/event-stream`) per request.
- **GET** on the same endpoint may open an SSE stream (optional); **405** if unsupported.
- **MCP-Protocol-Version** header (e.g. `2025-11-25`) on HTTP requests after negotiation.
- **Security:** validate **Origin**; reject invalid **Origin** with **403**; bind local servers to localhost when appropriate ([transports spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports.md)).

## IETF / OAuth (normative)

| Doc | URL | Role |
|-----|-----|------|
| **RFC 9728** — OAuth 2.0 Protected Resource Metadata | https://www.rfc-editor.org/rfc/rfc9728.html | `resource`, `authorization_servers`, `scopes_supported`; well-known path construction |
| **RFC 8414** — OAuth 2.0 Authorization Server Metadata | https://www.rfc-editor.org/rfc/rfc8414.html | `/.well-known/oauth-authorization-server` (+ path variants) |
| **RFC 7591** — Dynamic Client Registration | https://www.rfc-editor.org/rfc/rfc7591.html | Optional; MCP allows DCR **MAY** |
| **OAuth 2.1** (I-D; referenced by MCP) | https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-15 | Active draft (**-15**, March 2026); consolidates 2.0 + PKCE + security BCPs; [introduction — roles & flows](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-15#name-introduction) |
| RFC 6750 — Bearer token usage | https://www.rfc-editor.org/rfc/rfc6750.html | `WWW-Authenticate` **scope** parameter (OAuth 2.1 draft obsoletes/updates bearer text; still useful for header shape) |

### Authorization server vs resource server (why split them?)

OAuth 2.1 defines **four roles** and states that the **authorization server may be the same server as the resource server or a separate entity**, and that a single AS may issue tokens accepted by **multiple** resource servers ([introduction / roles](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-15#name-roles)). The **interaction between the authorization server and resource server** (how the RS validates tokens) is **out of scope** of the core OAuth document—implementations use shared storage, JWT verification, introspection ([RFC 7662](https://www.rfc-editor.org/rfc/rfc7662.html)), etc.

**Why people recommend not collapsing AS and RS in production:**

- **Trust boundary:** The AS holds **long-lived** and **high-value** artifacts (refresh tokens, client secrets, consent state, user login sessions). The RS (your **MCP** endpoint) only needs to **validate** access tokens and enforce **scope**. Keeping issuance and consumption in separate processes (or services) limits blast radius if the MCP worker is compromised.
- **Attack surface:** The RS is often exposed to **untrusted MCP clients** and broad HTTP; the AS endpoints (`/authorize`, `/token`) have different traffic and hardening needs (rate limits, CSRF on redirects, CORS only where required—see OAuth 2.1 §3.1 on **no CORS** at the authorization endpoint).
- **Scaling & rotation:** Token signing keys, client registries, and login UX can evolve on the AS without redeploying every RS instance; RS nodes only need verification material (JWKS, shared secret, or introspection URL).
- **MCP alignment:** MCP treats the protected MCP server as an OAuth 2.1 **resource server** and expects **RFC 9728** metadata to point at one or more **authorization servers**—a **logical** split is already the interoperability model, even if both share a hostname in small deployments.

**SMEme posture:** Prefer a **logical** AS separable from the MCP **resource**
worker for security and portability. The Core app acts as the resource server
and validates tokens issued by the operator-configured authorization server.

## Official Python SDK (SMEme implementation)

| Resource | URL |
|----------|-----|
| **modelcontextprotocol/python-sdk** | https://github.com/modelcontextprotocol/python-sdk |
| PyPI `mcp` | https://pypi.org/project/mcp/ |

This repo uses **`mcp.server.fastmcp.FastMCP`** with **`streamable_http_app()`**, optional **`TransportSecuritySettings`**, **`AuthSettings` + `TokenVerifier`** (Clerk JWKS) when `clerk_oauth_issuer` is set so unauthenticated MCP POSTs return **401** with **`WWW-Authenticate`** and **`resource_metadata`** (challenge-based RFC 9728 discovery). Parent-app well-known routes remain in **`smeme/mcp/discovery_routes.py`** (do not rely only on the inner Starlette metadata mount). Align versions with the **2025-11-25** spec where possible.

**Clerk access tokens** must be **JWTs** verifiable with JWKS (Clerk default for new OAuth apps in 2026; confirm per environment). **Opaque** access tokens need introspection — not implemented here.

## Try locally

1. **Environment** (e.g. `.env`):
   - `MCP_ENABLED=true`
   - Optional: `MCP_HTTP_PATH=/api/v1/mcp` (this is the **default** if unset)
   - Set **`BASE_URL`** to the origin clients use (default `http://localhost:8000`). If the app runs on another host/port, `BASE_URL` must match or **RFC 9728** `resource` URLs in metadata will be wrong.

2. **Restart** the app so settings reload.

3. **MCP URL:** `{effective_base_url}{MCP_HTTP_PATH}` — e.g. `http://localhost:8000/api/v1/mcp`. **Do not expect a normal browser tab to “load” this page.** Streamable HTTP requires clients to send **`Accept: application/json, text/event-stream`** ([transports spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports.md)); a browser **GET** uses a different `Accept`, so you may see **406** with a JSON-RPC body such as `Not Acceptable: Client must accept text/event-stream` — that means the server is enforcing the spec, not that the mount is broken.

   **Trailing slash:** Starlette’s `Mount` matches **`…/mcp/`** (with slash), not bare **`…/mcp`**. Without middleware, the app returns **307** to add the slash; some clients repeat **POST** after redirect **without** the required `Accept` header and get **406**. SMEme enables **`McpMountPathNormalizeMiddleware`** when `MCP_ENABLED` to rewrite bare `{MCP_HTTP_PATH}` to the slash form before routing.

   **Recommended curl (finishes — use this first):** OAuth / RFC 9728 metadata is a normal JSON **GET** that completes. Replace the origin with yours (no trailing slash on the origin):

   `curl -sS -o /dev/null -w "%{http_code}\n" --max-time 20 "http://127.0.0.1:8000/.well-known/oauth-protected-resource/api/v1/mcp"`

   Expect **`200`**. Repo helper: `bash scripts/smoke_mcp_url.sh https://your-core.example`

   **Why `GET …/api/v1/mcp/` “times out” in curl:** That URL starts the **standalone SSE** leg of Streamable HTTP. The server keeps the response open to push events, so **`curl` waits for the body to end** until **`--max-time`** fires → **`curl: (28) Operation timed out`** and often **`0 bytes received`** on the wire for the **body** (headers may still have been parsed). **`-w "%{http_code}"` showing `200` usually means the TCP connection and HTTP status line succeeded** — it does **not** mean curl “failed to reach” the server. **Do not use this GET as your only uptime check**; use well-known above.

   **Shell pitfall:** Line continuation must be **backslash immediately followed by newline**. A **space after `\`** (`\␠` before newline) **breaks** the command; headers may not attach to `curl` and behavior becomes misleading.

   - **Optional noisy probe** (headers to stdout, body discarded, will still hit max-time on SSE):  
     `curl -sS -D - -o /dev/null --max-time 3 -H "Accept: application/json, text/event-stream" -H "MCP-Protocol-Version: 2025-11-25" "http://127.0.0.1:8000/api/v1/mcp/"`  
   - **Real test:** [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector.md) against the same URL (with or without trailing slash once the normalize middleware is deployed).

   **Inspector usage (common pitfalls):**

   - Run **`npx @modelcontextprotocol/inspector`** with **no** URL argument. Configure the backend in the UI: transport **Streamable HTTP**, server URL e.g. `http://127.0.0.1:8000/api/v1/mcp`. A positional URL is treated as **stdio** (spawn a command), not HTTP.
   - The UI may default to **`http://localhost:3001/sse`** (legacy SSE samples / `localStorage`); change transport and URL to match SMEme.
   - Open the link that includes **`MCP_PROXY_AUTH_TOKEN`** (or paste the token in Configuration). Leave **optional HTTP headers** (e.g. Authorization) **disabled** unless you set a real value; an enabled-but-empty Authorization row causes Inspector-side validation errors.
   - **SDK + reconnect:** Stateless Streamable HTTP in the Python `mcp` package uses **`event_store=None`**. Clients that send **`Last-Event-ID`** on SSE reconnect can hit an upstream bug (no HTTP response → 500). SMEme wraps the mounted MCP app with **`StripLastEventIdMiddleware`** (`smeme/mcp/reasoning_fastmcp.py`), which strips that header so reconnect works at the cost of **no SSE replay** for this mount.

4. **Metadata (GET)** — only registered when **`MCP_ENABLED`** is true:
   - `/.well-known/oauth-protected-resource` and `/.well-known/oauth-protected-resource{MCP_HTTP_PATH}` (e.g. `/.well-known/oauth-protected-resource/api/v1/mcp`)
   - `/.well-known/oauth-authorization-server`

5. **Authorize / token URLs** — **Clerk path (default):** Mirrored **`/.well-known/oauth-authorization-server`** and **`/.well-known/openid-configuration`** advertise **`authorization_endpoint`** and **`token_endpoint`** on the **Clerk issuer** (e.g. `{issuer}/oauth/authorize`), not on the SMEme origin. Users complete OAuth in Clerk; SMEme serves discovery, the MCP mount, and JWT verification (**`TokenVerifier`**, **`dtq:*` tools** — **P2**). **Embedded / no Clerk:** AS metadata may advertise `{effective_base_url}/oauth/authorize` and `…/oauth/token`, but the app **does not register those routes** today — requests are **404** until **P1-Embedded** (e.g. Authlib) adds real handlers. (Older notes about **501** stubs are outdated; there are no `501` handlers for those paths in this repo.)

## Clerk + FastAPI (MVP roll-out, non-normative)

Third-party summaries often conflate specs—**protected resource metadata** is **[RFC 9728](https://www.rfc-editor.org/rfc/rfc9728.html)**; **[RFC 8414](https://www.rfc-editor.org/rfc/rfc8414.html)** is **authorization server** metadata. MCP clients need **both**: they read **9728** for the MCP URL, then **8414** (or OIDC discovery) for the AS.

**Architecture (aligned with D016)**

- **Authorization server:** **Clerk** — login, consent, PKCE, short-lived access tokens + refresh. For a static-client deployment, leave DCR off and set **`SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS`** to the client ID users paste into their connector. If the operator enables Clerk DCR, also set **`CLERK_OAUTH_DYNAMIC_REGISTRATION=true`** so mirrored metadata includes **`registration_endpoint`**; a static allowlist is not practical for dynamically minted client IDs. See [Dynamic Client Registration](#dynamic-client-registration-clerk_oauth_dynamic_registration).
- **Resource server:** **SMEme** — Streamable HTTP MCP at **`MCP_HTTP_PATH`** (default **`/api/v1/mcp`**, not Clerk’s doc examples at **`/mcp`**); validate **`Authorization: Bearer`** with **Clerk JWKS** (Backend SDK or generic JWT library + issuer/audience checks); map **`sub`** → **`users`**; enforce **`dtq:*` scopes** as Clerk exposes them (custom OAuth scopes — **spike required**).
- **Clients:** Clerk documents HTTP URLs for [Cursor](https://clerk.com/docs/guides/ai/mcp/connect-mcp-client), VS Code, **Claude Code** (`claude mcp add --transport http …`), and Claude Desktop/Windsurf via [`mcp-remote`](https://github.com/geelen/mcp-remote) where the host app does not speak authenticated remote MCP natively. Use **HTTPS** in production; drop dev-only flags like `--allow-http` when deployed.

**Python / zero-JS**

- Clerk’s **`@clerk/mcp-tools`** and Express/Next **metadata handlers** are **not** required for a FastAPI app; replicate the **small set of JSON routes** you need using **Clerk’s documented issuer and endpoints** (or HTTP redirect to Clerk’s `/.well-known/oauth-authorization-server`).
- **`fastapi-mcp`** in generic articles is a different package than this repo’s **`mcp` + `FastMCP`**; keep **`FastMCP`** unless you deliberately standardize on another bridge.

**Same FastAPI app as HTMX**

- A single app is acceptable when MCP never trusts **cookies** and only
  **validates Bearer tokens** issued for the MCP **resource** / audience.
  Operators with stricter isolation requirements can deploy the MCP resource
  server separately.

## Product / connector practice (non-normative, high signal)

| Source | URL | Use |
|--------|-----|-----|
| Anthropic — connect remote MCP | https://modelcontextprotocol.io/docs/develop/connect-remote-servers.md | Remote MCP URL, OAuth-oriented setup |
| **Clerk** — connect MCP clients | https://clerk.com/docs/guides/ai/mcp/connect-mcp-client | DCR (instance-level) vs static **Client ID**; Cursor / VS Code / Claude Code / Desktop+`mcp-remote`; pair with [Build an MCP server](https://clerk.com/docs/guides/ai/mcp/build-mcp-server) (stack may differ from this repo’s FastAPI **`mcp` SDK**) |

## SMEme implementation status

- **Implemented:** Streamable HTTP MCP endpoint (opt-in **`MCP_ENABLED`**), **RFC 9728** protected resource metadata for the MCP URL, **RFC 8414-style** AS metadata + **OIDC discovery** mirrored inline from the Clerk issuer (no 302 to Clerk — CORS), conditional **`registration_endpoint`** via **`CLERK_OAUTH_DYNAMIC_REGISTRATION`** (see [below](#dynamic-client-registration-clerk_oauth_dynamic_registration)), and **`StripLastEventIdMiddleware`** around the MCP mount (a workaround for Python SDK reconnects without an event store).
- **Validated clients:** **MCP Inspector**, Anthropic clients using DCR or a custom connector with a static client ID, and Cursor using DCR.

## Dynamic Client Registration (`CLERK_OAUTH_DYNAMIC_REGISTRATION`) {#dynamic-client-registration-clerk_oauth_dynamic_registration}

**Why:** Some MCP hosts (**Cursor**, flows aligned with [Clerk — connect MCP clients](https://clerk.com/docs/guides/ai/mcp/connect-mcp-client)) perform **RFC 7591** **`POST {issuer}/oauth/register`** after discovery. Without **`registration_endpoint`** in mirrored metadata, they **never get a `client_id`** — OAuth stalls **even when** well-known **GET**s return **200** and MCP returns **401** + **`WWW-Authenticate`**.

**SMEme behavior:**

| `CLERK_OAUTH_DYNAMIC_REGISTRATION` | **`/.well-known/oauth-authorization-server`** and **`/.well-known/openid-configuration`** |
|-------------------------------------|------------------------------------------------------------------------------------------|
| unset / `false` | **`registration_endpoint` omitted** — for **self-hosted DCR-off** + static **`oauth.clientId`**. |
| `true` | **`registration_endpoint`** = **`{issuer}/oauth/register`** when the operator has enabled Clerk **Dynamic OAuth Client Registration**. |

**Operator steps:** (1) Enable **Dynamic OAuth Client Registration** in the **Clerk Dashboard** (instance-level; read Clerk’s security notice). (2) Set **`CLERK_OAUTH_DYNAMIC_REGISTRATION=true`** on SMEme; restart. (3) Verify **`GET /.well-known/oauth-authorization-server`** shows **`registration_endpoint`**. (4) Connect from Cursor again; allowlist **Cursor’s** redirect URI if Clerk reports **`redirect_uri` mismatch**.

**Code:** `smeme/core/config.py` (`clerk_oauth_dynamic_registration`); `smeme/mcp/discovery_routes.py` (`_clerk_as_metadata`, `_clerk_oidc_config`). **Tests:** `tests/unit/mcp/test_dr3_discovery.py::test_well_known_routes_clerk_dcr_advertises_registration_endpoint`.



## Transport-layer auth and HTMX middleware

**Shipped:** FastMCP **`AuthSettings`** + **`ClerkMcpTokenVerifier`** (`mcp` SDK **`RequireAuthMiddleware`**) when `clerk_oauth_issuer` is set. Unauthenticated Streamable HTTP requests to the MCP mount get **401** with **`WWW-Authenticate`** including **`resource_metadata`** (RFC 9728 challenge path). Shared JWT verification: **`decode_clerk_oauth_access_token`** in `smeme/mcp/bearer_auth.py`.

**Checkpoint A (capabilities):** **`smeme_reasoning_capabilities`** uses the same **Bearer** token and linked **`User`** row as **`smeme_reasoning_list`** / **`smeme_reasoning_evaluate`** / **`smeme_reasoning_evaluate_answers`** — no unauthenticated capabilities probe in production. See `smeme/mcp/reasoning_fastmcp.py` .

**Verifier vs application auth:** **`ClerkMcpTokenVerifier`** is stateless (signature, `iss`, `exp`, JWKS only). **`get_mcp_user`** loads **`User`** from **`users.clerk_user_id`**; a valid JWT with no row still returns tool-level **`auth_error`**, not transport **401**.

**Inner Starlette metadata:** When FastMCP `auth` is enabled, the SDK may register protected-resource metadata on the **inner** Starlette app under the mount. Those URLs are non-standard; the **authoritative** metadata stays on the parent FastAPI app (`smeme/mcp/discovery_routes.py`). Do not remove the FastAPI well-known handlers.

**`HTMXLoginRedirectMiddleware`:** Converts **401** → **302** to **`/auth/login`** for browser / HTMX **`Accept`**. MCP clients must keep **401** + **`WWW-Authenticate`** for OAuth bootstrap. **`_is_mcp_http_path()`** in `smeme/core/middleware.py` skips the redirect for **`MCP_HTTP_PATH`**, including when **`Accept`** mixes **`text/html`** with JSON/SSE (some connectors do this).

**Tests:** `tests/unit/mcp/test_dr3_mcp_transport_oauth.py` (401 challenge shape, no **302** on MCP **POST**, **`resource_metadata`** alignment). Broader Bearer behavior: `tests/unit/mcp/test_p2_bearer_auth.py`.

## Stuck?

Ask in [GitHub Discussions → Get started](https://github.com/AristaLabs/smeme/discussions/categories/get-started-mcp-cowork)
or [Integrations](https://github.com/AristaLabs/smeme/discussions/categories/integrations).
Mention which client (Cowork, Cursor, …), smeme.ai vs self-host, and what you expected.
Do not post OAuth client secrets or tokens.

## See also

- [Self-host quickstart](self-host-quickstart.md)
- [MCP specification](https://modelcontextprotocol.io/specification/2025-11-25/index.md)
