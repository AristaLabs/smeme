# MCP Official Registry — publish runbook

**Audience:** Operator publishing `registry/server.json` to the [Official MCP Registry](https://modelcontextprotocol.io/registry/about).

**Prerequisite:** Identity decision resolved — `ai.smeme/reasoning` on `smeme.ai` (see [GEO execution plan](../business/geo-execution-plan.md)).

---

## Files

| Path | Role |
|------|------|
| `registry/server.json` | Registry metadata (remote Streamable HTTP) |
| `registry/README.md` | Copy constants + version coupling |
| `smeme/mcp/urls.py` | Canonical SaaS MCP URL + OAuth Client ID (`MCP_SAAS_*`) |

---

## Pre-flight

1. Prod MCP endpoint live: `GET https://www.smeme.ai/.well-known/oauth-protected-resource/api/v1/mcp` → 200
2. `registry/server.json` `version` matches `REASONING_CAPABILITIES_VERSION` in `smeme/mcp/reasoning_fastmcp.py`
3. Validate locally:

```bash
python scripts/validate_server_json.py
# Optional (requires Go): mcp-publisher validate registry/server.json
```

---

## DNS authentication

```bash
mcp-publisher login dns
```

Follow prompts to add a **TXT record on `smeme.ai`**. This authorizes the `ai.smeme/*` namespace.

Store the publisher private key in GitHub Actions secrets (e.g. `MCP_REGISTRY_SIGNING_KEY`) for CI publish on release tags.

---

## Publish

```bash
mcp-publisher publish registry/server.json
```

Treat the registry as **preview** — be ready to republish if metadata resets.

After publish, add the registry listing URL to landing JSON-LD `sameAs` on the next deploy.

---

## Downstream marketplaces (manual)

Claim and polish — do **not** trust auto-ingestion:

- Smithery
- Glama
- PulseMCP
- mcp.so
- GitHub MCP Registry

Use the **long description** from `registry/README.md`. Lead with category sentence + capability line; do not lead with Arista Labs mission copy.

---

## CI hook (recommended)

On production release tag:

1. Bump `registry/server.json` `version` if plugin semver changed
2. `python scripts/validate_server_json.py`
3. `mcp-publisher publish registry/server.json` (OIDC or stored key)

See [Cowork plugin artifacts](internal/cowork-plugin-artifacts-and-releases.md) for semver coupling.

---

## Rollback

Republish prior `server.json` from git tag. Registry namespace is sticky — prefer republish over creating a second name.
