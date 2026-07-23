"""RFC 9728 protected resource metadata + RFC 8414 AS metadata (DR-3 P1-Clerk).

What this module registers
--------------------------
Four well-known routes on the FastAPI application (only when ``MCP_ENABLED=true``):

1. ``/.well-known/oauth-protected-resource/<path>``  — RFC 9728 scoped sub-path
2. ``/.well-known/oauth-protected-resource``          — RFC 9728 root (no path component)
3. ``/.well-known/oauth-authorization-server``        — RFC 8414 AS metadata
4. ``/.well-known/openid-configuration``              — OIDC Discovery

Clients walk these in order during OAuth flow initialization.  MCP Inspector
fetches all four before presenting the OAuth start button.

Two architectural fixes vs the original 302-redirect design
-----------------------------------------------------------

Fix 1 — Trailing slash on ``authorization_servers``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pydantic ``AnyHttpUrl`` normalises bare origins to ``https://host/`` (note the
trailing slash).  MCP Inspector constructs discovery URLs by string-concatenating
``authorization_servers[0]`` with ``/.well-known/oauth-authorization-server``.
That produces ``https://host//.well-known/...`` — double slash — which Clerk
returns 404 on.

Mitigation: strip the trailing slash from each entry in ``authorization_servers``
*after* calling ``model_dump()``.  The raw string ``"https://host"`` is valid
per RFC 8414 §3 (the value MUST NOT have a path component; a bare slash is a
path component and should be absent).

Fix 2 — 302 → inline JSON for AS metadata and OIDC config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The original plan was to ``302``-redirect browsers to Clerk's own
``/.well-known/oauth-authorization-server`` endpoint.  In practice this fails for
browser-based MCP clients (Inspector, Cowork):

- The browser follows the redirect to ``https://instance.clerk.accounts.dev/...``.
- Clerk does **not** emit ``Access-Control-Allow-Origin`` for arbitrary
  ``localhost:*`` origins (and won't for arbitrary production origins either).
- The browser blocks the CORS-restricted response and Inspector reports
  "Failed to discover OAuth metadata".

Fix: derive the AS metadata document **locally** from the Clerk issuer URL.
Clerk's endpoint structure is stable and follows the standard OAuth 2.0
conventions, so no network round-trip is needed.  The browser only talks to
``localhost:8000`` (or the production SMEme origin), which our CORS config allows.
The same logic applies to ``/.well-known/openid-configuration``.

See LESSONS_LEARNED §MCP OAuth for the full diagnostic story.

DCR (``registration_endpoint``) policy
--------------------------------------
While **Clerk instance-level Dynamic Client Registration** is **off** (SMEme default —
Clerk warns that ``POST {issuer}/oauth/register`` is a public API), we **omit**
``registration_endpoint`` from the mirrored RFC 8414 and OIDC documents so clients
prefer a **static** Clerk OAuth app ``clientId`` configured by the Core operator.
When DCR is enabled in Clerk, add ``"registration_endpoint": f"{base}/oauth/register"``
in ``_clerk_as_metadata`` and ``_clerk_oidc_config`` (see inline comments there).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.shared.auth import ProtectedResourceMetadata
from pydantic import AnyHttpUrl

from smeme.core.config import Settings, settings
from smeme.mcp.urls import mcp_resource_url, oauth_protected_resource_metadata_path


def _protected_resource_payload(s: Settings) -> dict[str, Any]:
    """Build the RFC 9728 Protected Resource Metadata document.

    The ``resource`` field must exactly match the MCP endpoint URL that
    clients connect to.  MCP Inspector validates this and rejects connections
    where the URL does not match (even ``localhost`` vs ``127.0.0.1``).

    ``authorization_servers`` lists the OAuth AS that can issue tokens for this
    resource.  For P1-Clerk this is Clerk's issuer URL.  For the P1-Embedded
    fallback (no Clerk configured) it is SMEme's own origin.

    ``scopes_supported`` must align with what the listed authorization server
    actually allows on ``/oauth/authorize``.  Advertising custom resource scopes
    that the AS does not allow caused conforming clients (e.g. DCR playgrounds) to
    request them while Clerk rejects them with ``invalid_scope``.  Do **not**
    advertise ``openid`` here unless the Clerk OAuth application explicitly allows
    it: many setups (including some DCR-registered clients) only permit
    ``profile``, ``email``, and ``offline_access`` on ``/oauth/authorize``.
    MCP access control remains ``sub`` + local ``User`` (see D016); custom
    ``reasoning:*`` token scopes at the RS are P3.
    """
    resource = mcp_resource_url(s)

    # P1-Clerk: point at Clerk's issuer.
    # Falls back to SMEme's own origin only when Clerk is not configured
    # (local dev without Clerk, or the P1-Embedded future path).
    issuer = s.clerk_oauth_issuer or s.effective_base_url.rstrip("/")

    meta = ProtectedResourceMetadata(
        resource=AnyHttpUrl(resource),
        authorization_servers=[AnyHttpUrl(issuer)],
        # Clerk OAuth apps often allow these without ``openid`` (DCR clients may
        # not be permitted to request ``openid`` — invalid_scope).
        scopes_supported=["profile", "email", "offline_access"],
        resource_name="SMEme MCP",
    )
    payload = meta.model_dump(mode="json", exclude_none=True)

    # Pydantic AnyHttpUrl.model_dump() → "https://host/" (trailing slash added).
    # Strip it so clients build /.well-known URLs without a double slash.
    # This is Fix 1 from the module docstring.
    payload["authorization_servers"] = [
        str(u).rstrip("/") for u in payload["authorization_servers"]
    ]
    return payload


def _clerk_as_metadata(
    issuer: str, *, advertise_registration_endpoint: bool = False
) -> dict[str, Any]:
    """Build an RFC 8414 Authorization Server Metadata document from Clerk's issuer URL.

    Why derive locally instead of fetching from Clerk?
    --------------------------------------------------
    1. **No CORS issue**: The document is served from SMEme's own origin, so
       browser-based clients (Inspector, Cowork) can fetch it without a
       cross-origin preflight that Clerk would block.
    2. **No latency**: Each discovery request hits SMEme's in-process handler;
       no outbound HTTP to Clerk is needed per request.
    3. **Stable structure**: Clerk follows the standard OAuth 2.0 endpoint
       naming conventions (``/oauth/authorize``, ``/oauth/token``, etc.) and
       these are documented in Clerk's public API.  We're not guessing.

    Note: Clerk's *actual* ``/.well-known/oauth-authorization-server`` response
    includes additional fields (``revocation_endpoint``, ``service_documentation``,
    ``ui_locales_supported``, etc.) that we omit.  We omit ``registration_endpoint``
    unless ``settings.clerk_oauth_dynamic_registration`` is true (Clerk DCR on).
    Clients only need the core endpoint URLs for the authorization code flow.

    The ``issuer`` value must be exactly the string Clerk includes in JWT ``iss``
    claims — no trailing slash.  Clients perform strict equality checks.
    """
    base = issuer.rstrip("/")
    doc: dict[str, Any] = {
        "issuer": base,
        # Authorization endpoint: where users are redirected to authenticate.
        # Clerk presents its hosted sign-in UI (supporting Google, LinkedIn, etc.).
        "authorization_endpoint": f"{base}/oauth/authorize",
        # Token endpoint: where MCP clients exchange the authorization code for
        # access + refresh tokens after the user completes the consent screen.
        # The client presents client_id + client_secret here.
        "token_endpoint": f"{base}/oauth/token",
        # JWKS endpoint: where SMEme's bearer_auth.py fetches RSA public keys to
        # validate access token signatures.  Cached in _JwksCache with 5-min TTL.
        "jwks_uri": f"{base}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        # PKCE (S256) is required for public clients (Inspector, Cursor, VS Code).
        # Clerk enforces it for all public clients regardless of whether the
        # "Public" toggle is enabled in the Clerk dashboard.
        "code_challenge_methods_supported": ["S256"],
        # "none" is required for public clients (PKCE-only, no client_secret).
        # Cowork and other MCP connectors that use Authorization Code + PKCE rely on this.
        # Requires "Public" to be enabled on the Clerk OAuth application in the dashboard.
        "token_endpoint_auth_methods_supported": [
            "none",
            "client_secret_basic",
            "client_secret_post",
        ],
        # DCR (RFC 7591): registration_endpoint only when Clerk instance DCR is on
        # and CLERK_OAUTH_DYNAMIC_REGISTRATION=true (see Settings).
        # Align with _protected_resource_payload (no ``openid`` — see PRM docstring).
        "scopes_supported": ["profile", "email", "offline_access"],
    }
    if advertise_registration_endpoint:
        doc["registration_endpoint"] = f"{base}/oauth/register"
    return doc


def _clerk_oidc_config(
    issuer: str, *, advertise_registration_endpoint: bool = False
) -> dict[str, Any]:
    """Build an OpenID Connect Discovery document from Clerk's issuer URL.

    Why this endpoint is needed
    ---------------------------
    MCP Inspector's Guided OAuth flow fetches **three** documents from the resource
    server origin before presenting the "Start OAuth" button:
      - ``/.well-known/oauth-protected-resource``   (RFC 9728 — always)
      - ``/.well-known/oauth-authorization-server`` (RFC 8414)
      - ``/.well-known/openid-configuration``       (OIDC Discovery)

    Inspector accepts *either* the RFC 8414 or OIDC document as the AS metadata
    source; it checks both paths.  A 404 on either blocks the flow with
    "Failed to discover OAuth metadata".

    Same CORS rationale as ``_clerk_as_metadata``: serve inline from SMEme's
    origin rather than redirecting to Clerk, which does not emit CORS headers
    for arbitrary origins.

    The derived document omits some fields present in Clerk's actual
    ``/openid-configuration`` (``op_tos_uri``, ``service_documentation``,
    ``revocation_endpoint``, etc.).  That is acceptable — Inspector only needs
    the core endpoint URLs.
    """
    base = issuer.rstrip("/")
    doc: dict[str, Any] = {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        # userinfo_endpoint is part of OIDC but not used by MCP tools.
        # Included for completeness so clients that probe it know where to go.
        "userinfo_endpoint": f"{base}/oauth/userinfo",
        "jwks_uri": f"{base}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        # Clerk signs all JWTs with RS256.
        "id_token_signing_alg_values_supported": ["RS256"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": [
            "none",
            "client_secret_basic",
            "client_secret_post",
        ],
        # Omit ``openid`` from scopes_supported when Clerk disallows it for the app (DCR).
        "scopes_supported": ["profile", "email", "offline_access"],
        "claims_supported": ["sub", "email", "name", "given_name", "family_name"],
    }
    if advertise_registration_endpoint:
        doc["registration_endpoint"] = f"{base}/oauth/register"
    return doc


def _authorization_server_metadata_payload(s: Settings) -> dict[str, Any]:
    """Build RFC 8414 AS metadata for the P1-Embedded fallback path (no Clerk configured).

    This document points at OAuth URLs on SMEme's own origin.  It is only
    served when ``clerk_oauth_issuer`` is unset (no Clerk AS).  The app does
    **not** register ``/oauth/authorize`` or ``/oauth/token`` handlers yet —
    clients that follow these URLs get FastAPI **404** until P1-Embedded
    (e.g. Authlib) implements them.

    The payload exists so discovery shape stays stable when a real embedded AS
    is added; production MCP flows use Clerk instead of this fallback.
    """
    base = s.effective_base_url.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        # Stub AS: same scope surface as Clerk path for consistency.
        "scopes_supported": ["profile", "email", "offline_access"],
    }


def register_mcp_oauth_discovery_routes(app: FastAPI, s: Settings | None = None) -> None:
    """Register all well-known OAuth discovery endpoints on the FastAPI app.

    Called once from ``smeme/main.py`` after ``MCP_ENABLED`` is confirmed.
    Registers four GET routes using ``app.add_api_route`` (not ``@app.get``) so
    we can define the handler functions inline inside this factory, capturing
    the ``cfg`` closure without a module-level global.

    Route layout
    ------------
    Two RFC 9728 routes are registered to maximise client compatibility:
    - Sub-path form: ``/.well-known/oauth-protected-resource/api/v1/mcp``
      (the path component matches the MCP endpoint URL path, per RFC 9728 §2)
    - Root form: ``/.well-known/oauth-protected-resource``
      (some clients probe this fallback when they don't know the MCP path)

    ``include_in_schema=False`` keeps these out of the OpenAPI docs; they are
    part of the OAuth infrastructure, not the REST API.
    """
    cfg = s or settings
    if not cfg.mcp_enabled:
        # Discovery routes are gated behind MCP_ENABLED to avoid advertising
        # OAuth endpoints on deployments where MCP is not active.
        return

    # The sub-path is derived from the MCP endpoint URL
    # (e.g. "/.well-known/oauth-protected-resource/api/v1/mcp").
    sub_path = oauth_protected_resource_metadata_path(cfg)

    async def protected_resource_metadata_subpath() -> JSONResponse:
        # Both RFC 9728 routes return the same payload; the sub-path form
        # is the canonical one per the spec.
        return JSONResponse(_protected_resource_payload(cfg))

    async def protected_resource_metadata_root() -> JSONResponse:
        # Root fallback: some MCP clients (including older Inspector versions)
        # probe /.well-known/oauth-protected-resource without the path component.
        return JSONResponse(_protected_resource_payload(cfg))

    async def authorization_server_metadata() -> JSONResponse:
        clerk_issuer = cfg.clerk_oauth_issuer
        if clerk_issuer:
            # P1-Clerk path: serve Clerk AS metadata derived locally.
            # This avoids the CORS failure that would occur if we 302-redirected
            # browser clients to Clerk's own endpoint (Fix 2 in module docstring).
            return JSONResponse(
                _clerk_as_metadata(
                    clerk_issuer,
                    advertise_registration_endpoint=cfg.clerk_oauth_dynamic_registration,
                )
            )
        # P1-Embedded fallback: no Clerk; metadata only — no /oauth/* routes yet.
        return JSONResponse(_authorization_server_metadata_payload(cfg))

    async def openid_configuration() -> JSONResponse:
        clerk_issuer = cfg.clerk_oauth_issuer
        if clerk_issuer:
            # MCP Inspector Guided flow fetches this in addition to RFC 8414.
            # Serve inline to avoid CORS failure (same reason as AS metadata).
            return JSONResponse(
                _clerk_oidc_config(
                    clerk_issuer,
                    advertise_registration_endpoint=cfg.clerk_oauth_dynamic_registration,
                )
            )
        # No Clerk configured — 404 is correct.
        # In the P1-Embedded path, SMEme is an OAuth 2.0 AS but not an OIDC OP;
        # OIDC discovery should not be advertised.
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    app.add_api_route(
        sub_path,
        protected_resource_metadata_subpath,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/.well-known/oauth-protected-resource",
        protected_resource_metadata_root,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/.well-known/oauth-authorization-server",
        authorization_server_metadata,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/.well-known/openid-configuration",
        openid_configuration,
        methods=["GET"],
        include_in_schema=False,
    )
