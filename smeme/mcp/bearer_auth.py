"""MCP Bearer JWT verification: Clerk JWKS → local User (DR-3 P2).

Flow
----
1. Extract ``Authorization: Bearer <token>`` from the Starlette ``Request``.
2. Fetch Clerk's JWKS (``{clerk_oauth_issuer}/.well-known/jwks.json``) and cache
   keys in process memory for ``_JWKS_TTL`` seconds.
3. Validate the JWT with PyJWT (signature, issuer, expiry).
4. Map ``sub`` → ``User.clerk_user_id`` row in the local database.

Why PyJWT rather than ``python-jose`` or manual crypto
-------------------------------------------------------
PyJWT (the ``jwt`` package on PyPI) ships ``RSAAlgorithm.from_jwk`` which converts a
JWK dict to a ``cryptography`` RSA public key object.  The other popular option
(``python-jose``) has less active maintenance.  httpx is already a SMEme dependency
and handles the async JWKS fetch cleanly.

P2 auth contract + transport challenge (D016)
---------------------------------------------
- Token must be issued by Clerk (``iss == clerk_oauth_issuer``).
- When Clerk is configured, FastMCP uses ``ClerkMcpTokenVerifier`` (SDK
  ``RequireAuthMiddleware``) so missing/invalid Bearer fails at **HTTP 401**
  with ``WWW-Authenticate`` + ``resource_metadata``; see
  ``decode_clerk_oauth_access_token`` (JWT only, no DB).
- ``get_mcp_user`` maps ``sub`` → ``User.clerk_user_id`` (populated at first web
  login via ``get_or_create_user_for_clerk``; users **must** log into the SMEme
  web UI at least once before MCP tools return success — the web login creates
  the ``users`` row).
- OAuth client binding (P3): optional comma-separated
  ``SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS`` — after JWKS verification, require
  ``client_id`` or ``azp`` on the access JWT to match an allowed Clerk OAuth app.
  **Default empty list** = no binding (same as P2). Optional
  ``SMEME_MCP_OAUTH_ACCESS_TOKEN_AUDIENCE`` enforces ``aud`` when Clerk issues it.

- Custom scope enforcement (``reasoning:list``, ``reasoning:evaluate``) remains deferred
  until Clerk issues custom scopes on OAuth access tokens. See LESSONS_LEARNED §Clerk and D016 §P3.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from mcp.server.auth.provider import AccessToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from smeme.core.config import settings
from smeme.core.logging import get_logger
from smeme.core.models import User
from smeme.mcp.auth_telemetry import tool_auth_context

logger = get_logger(__name__)

# Re-fetch Clerk's JWKS at most once per 5 minutes.
# Shorter TTL → more network calls; longer TTL → stale keys during key rotation.
# 300 s is the de-facto standard (matches what e.g. Auth0 recommends for JWKS polling).
# Kid-rotation logic in _JwksCache.get_public_key handles the rare case where a new
# key arrives before the TTL expires.
_JWKS_TTL = 300  # seconds


class MCPAuthError(Exception):
    """Authentication failed for an MCP tool call.

    Raised by ``get_mcp_user`` and propagated to tool handlers, which catch it and
    return a structured ``{"error": {"code": "auth_error", ...}}`` JSON string so the
    MCP client receives a clean error payload rather than an unhandled 500.

    ``reason_code`` is optional telemetry for binding failures (e.g. ``unknown_oauth_client``).
    """

    def __init__(
        self,
        message: str,
        *,
        reason_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.details = details


class _JwksCache:
    """In-process RSA key cache with TTL refresh and kid-rotation awareness.

    Design
    ------
    Fetching JWKS on every MCP tool call would add ~50–200 ms of latency and
    hammer Clerk's endpoints.  Caching the RSA public key objects in process
    memory eliminates that round-trip for the common case.

    Thread/coroutine safety
    -----------------------
    All writes (including the re-fetch) hold ``_lock`` (an ``asyncio.Lock``).
    The first read within a held lock checks TTL and calls ``_refresh``; later
    readers find the lock free and take the fast path.

    Key-rotation handling
    ---------------------
    If a JWT's ``kid`` is absent from the cache (Clerk rotated its key mid-TTL),
    we attempt one additional re-fetch before giving up.  This means exactly one
    extra JWKS HTTP call for the first request after each key rotation, and zero
    extra calls for all subsequent requests.

    Transient JWKS fetch failures
    ---------------------------
    When a refresh is needed but the HTTP fetch fails, we keep serving previously
    fetched RSA keys (same process) so a brief Clerk or network outage at TTL
    boundary does not blank MCP auth.  If there is no key material yet, refresh
    failures still raise ``MCPAuthError``.
    """

    def __init__(self, ttl: int = _JWKS_TTL) -> None:
        # kid → cryptography RSA public key object (from RSAAlgorithm.from_jwk)
        self._keys: dict[str, Any] = {}
        # monotonic timestamp of the last successful _refresh; 0.0 = never fetched
        self._fetched_at: float = 0.0
        self._ttl = ttl
        # asyncio lock protects _keys and _fetched_at from concurrent refresh
        self._lock = asyncio.Lock()

    async def _refresh_or_keep_stale(self, jwks_url: str, *, context: str) -> None:
        """Run ``_refresh``; on ``MCPAuthError``, keep existing keys when non-empty.

        Must be called with ``_lock`` held. Logs a single warning on the stale-key
        path (no traceback) so transient outages stay observable without noise.
        """
        try:
            await self._refresh(jwks_url)
        except MCPAuthError as exc:
            if self._keys:
                logger.warning(
                    "JWKS refresh failed; continuing with stale in-memory keys "
                    "(jwks_url=%s, refresh_context=%s, cached_key_count=%d, "
                    "stale_keys_in_use=True, detail=%s)",
                    jwks_url,
                    context,
                    len(self._keys),
                    str(exc),
                )
            else:
                raise

    async def get_public_key(self, jwks_url: str, kid: str | None) -> Any:
        """Return the RSA public key for ``kid`` (or the first key if ``kid`` is ``None``).

        Three-tier lookup:
        1. TTL-expired or empty cache → refresh, then look up.
        2. kid present in fresh cache → return immediately.
        3. kid absent (possible rotation) → refresh once more, then look up.
           If still absent, fall back to the first key in the cache.
        """
        # Step 1: refresh if the cache is stale or has never been populated.
        # The lock prevents thundering-herd: only one coroutine calls _refresh
        # at a time; others wait and then find a fresh cache.
        async with self._lock:
            if time.monotonic() - self._fetched_at > self._ttl or not self._keys:
                await self._refresh_or_keep_stale(jwks_url, context="ttl_or_empty")

        # Step 2: fast path — kid is known and cache is fresh.
        if kid and kid in self._keys:
            return self._keys[kid]

        # Step 3: kid not found — Clerk may have rotated its signing key.
        # Re-fetch once under the lock if the kid is still absent.
        if kid:
            async with self._lock:
                # Re-check under the lock; another coroutine may have already refreshed.
                if kid not in self._keys:
                    await self._refresh_or_keep_stale(jwks_url, context="kid_rotation")
            if kid in self._keys:
                return self._keys[kid]

        # Fallback: no kid header in the JWT, or kid still absent after rotation refresh.
        if self._keys:
            if kid is None and len(self._keys) > 1:
                raise MCPAuthError(
                    "JWT missing kid header while JWKS has multiple keys; refusing ambiguous key"
                )
            return next(iter(self._keys.values()))

        raise MCPAuthError("JWKS: no usable keys after refresh")

    async def _refresh(self, jwks_url: str) -> None:
        """Fetch JWKS from Clerk and rebuild the key cache.

        Called only while holding ``_lock``, so no concurrent refresh is possible.
        A 5-second timeout prevents a slow Clerk endpoint from blocking the event loop.
        ``raise_for_status()`` turns 4xx/5xx responses into exceptions.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(jwks_url)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            msg = f"JWKS fetch failed ({jwks_url}): {exc}"
            raise MCPAuthError(msg) from exc

        # Build a fresh dict so a partial failure leaves the old cache intact.
        keys: dict[str, Any] = {}
        for jwk in data.get("keys", []):
            try:
                # RSAAlgorithm.from_jwk converts a JWK dict (with n, e, kty=RSA) to a
                # cryptography.hazmat.primitives.asymmetric.rsa.RSAPublicKey object that
                # PyJWT can use directly in jwt.decode().
                key = RSAAlgorithm.from_jwk(jwk)
                # Each JWK entry should have a "kid" (key ID).  If somehow absent,
                # assign a synthetic one so the dict stays consistent.
                kid_val = jwk.get("kid") or f"_key_{len(keys)}"
                keys[kid_val] = key
            except Exception as exc:
                # Skip malformed entries rather than failing the whole refresh.
                # A warning is sufficient — Clerk won't ship broken keys in prod.
                logger.warning("Skipping unparseable JWKS key entry: %s", exc)

        if not keys:
            raise MCPAuthError("JWKS: response contained no usable RSA keys")

        # Atomic swap: replace the old cache in one assignment.
        self._keys = keys
        self._fetched_at = time.monotonic()
        logger.debug("JWKS refreshed from %s; %d key(s) loaded", jwks_url, len(keys))

    def invalidate(self) -> None:
        """Force a re-fetch on the next request (useful in tests and after logout).

        Sets ``_fetched_at`` to zero so the TTL check in ``get_public_key`` always
        triggers a refresh.  Does not clear ``_keys`` because a concurrent caller
        holding the lock should still be able to return a key until the refresh lands.
        """
        self._fetched_at = 0.0
        self._keys = {}


# Module-level singleton — one cache per worker process.
# Re-created by reset_mcp_runtime_for_tests() between test cases.
_jwks_cache = _JwksCache()


def mcp_web_auth_urls() -> tuple[str, str]:
    """``(signup_url, sign_in_url)`` on the SMEme web app origin."""
    base = settings.effective_base_url.rstrip("/")
    return f"{base}/auth/register", f"{base}/auth/login"


def unlinked_account_mcp_auth_error() -> MCPAuthError:
    """MCP-first callers: valid Clerk token, no ``users`` row yet."""
    signup_url, sign_in_url = mcp_web_auth_urls()
    host = signup_url.split("/")[2] if "://" in signup_url else "the SMEme website"
    message = (
        "No SMEme account is linked to this connector yet. "
        f"Create a free account at {signup_url} "
        f"(or sign in at {sign_in_url} if you already have one). "
        "Use the same email or sign-in method you used in your MCP client. "
        f"After you finish on {host}, return to your MCP client, reconnect the SMEme connector, "
        "and try again."
    )
    return MCPAuthError(
        message,
        reason_code="no_local_user_for_clerk_sub",
        details={
            "signup_url": signup_url,
            "sign_in_url": sign_in_url,
            "next_steps": [
                f"Open {signup_url} and create a SMEme account (or sign in at {sign_in_url}).",
                "Complete sign-in on the web so your account links to this connector.",
                "In your MCP client, disconnect and reconnect the SMEme connector.",
                "Retry the SMEme tool.",
            ],
        },
    )


def auth_error_tool_json(exc: MCPAuthError) -> str:
    """Structured ``auth_error`` payload; merges optional ``exc.details`` for clients/skills."""
    from smeme.mcp.tool_contract import tool_error_json

    extra: dict[str, Any] = dict(exc.details or {})
    if exc.reason_code:
        extra.setdefault("auth_reason", exc.reason_code)
    return tool_error_json("auth_error", str(exc), **extra)


def oauth_client_id_from_clerk_access_payload(payload: dict[str, Any]) -> str | None:
    """Clerk OAuth access JWT: OAuth app id from ``client_id`` or ``azp`` (first non-empty).

    Some issuers encode ``client_id`` as a JSON number; normalize to string for allowlist matching.
    """
    for key in ("client_id", "azp"):
        raw = payload.get(key)
        if raw is None:
            continue
        if isinstance(raw, str):
            s = raw.strip()
            if s:
                return s
        # bool is a ``int`` subclass — skip accidental ``True``/``False`` claims.
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            return str(raw)
    return None


def _audiences_from_claim(aud: Any) -> set[str]:
    if aud is None:
        return set()
    if isinstance(aud, str):
        s = aud.strip()
        return {s} if s else set()
    if isinstance(aud, list):
        out: set[str] = set()
        for x in aud:
            if x is None:
                continue
            s = str(x).strip()
            if s:
                out.add(s)
        return out
    return set()


def _enforce_optional_mcp_access_token_binding(payload: dict[str, Any]) -> None:
    """If config demands it, enforce ``aud`` and/or allowed OAuth client ids."""
    aud_cfg = settings.mcp_oauth_access_token_audience
    aud_expected = aud_cfg.strip() if isinstance(aud_cfg, str) else ""
    if aud_expected:
        if aud_expected not in _audiences_from_claim(payload.get("aud")):
            raise MCPAuthError(
                "OAuth access token audience does not match configured MCP resource",
                reason_code="audience_mismatch",
            )

    allowed = settings.mcp_allowed_oauth_client_ids
    if not isinstance(allowed, list):
        return
    allow_set = {x.strip() for x in allowed if isinstance(x, str) and x.strip()}
    if not allow_set:
        return

    oauth_cid = oauth_client_id_from_clerk_access_payload(payload)
    if not oauth_cid:
        raise MCPAuthError(
            "OAuth access token has no client_id or azp claim "
            "(required when SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS is set)",
            reason_code="unknown_oauth_client",
        )
    if oauth_cid not in allow_set:
        # Keep message short: token_verifier telemetry truncates ``detail`` to 200 chars.
        msg = (
            "OAuth client not allowlisted for MCP "
            f"(resolved_from_token={oauth_cid!r}; add to SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS)"
        )
        raise MCPAuthError(msg, reason_code="unknown_oauth_client")


async def decode_clerk_oauth_access_token(
    token: str,
    *,
    issuer: str | None = None,
) -> dict[str, Any]:
    """Verify a Clerk OAuth access JWT (JWKS, RS256, ``iss``, ``exp``, required claims).

    Used by transport-layer ``TokenVerifier`` and by ``get_mcp_user`` for the JWT leg.
    Does **not** touch the database.

    Raises
    ------
    MCPAuthError
        Malformed token, JWKS failure, wrong issuer, expired signature, missing ``sub``, etc.
    """
    effective_issuer = (issuer or settings.clerk_oauth_issuer or "").rstrip("/") or None
    if not effective_issuer:
        raise MCPAuthError(
            "Clerk OAuth is not configured on this server (MCP Bearer auth unavailable)"
        )

    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        msg = f"Malformed JWT header: {exc}"
        raise MCPAuthError(msg) from exc

    kid = unverified_header.get("kid")
    jwks_url = f"{effective_issuer}/.well-known/jwks.json"
    public_key = await _jwks_cache.get_public_key(jwks_url, kid)

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=effective_issuer,
            options={
                "verify_aud": False,
                "require": ["sub", "iat", "exp"],
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise MCPAuthError("Bearer token has expired") from exc
    except jwt.InvalidIssuerError as exc:
        msg = f"JWT issuer mismatch: {exc}"
        raise MCPAuthError(msg) from exc
    except jwt.DecodeError as exc:
        msg = f"JWT decode error: {exc}"
        raise MCPAuthError(msg) from exc
    except jwt.InvalidTokenError as exc:
        msg = f"Invalid JWT: {exc}"
        raise MCPAuthError(msg) from exc

    clerk_user_id: str | None = payload.get("sub")
    if not clerk_user_id or not isinstance(clerk_user_id, str):
        raise MCPAuthError("JWT has no usable sub claim")

    _enforce_optional_mcp_access_token_binding(payload)

    # Use ``is True`` so test ``MagicMock`` settings do not treat a nested mock as enabled.
    if getattr(settings, "debug", False) is True:
        logger.debug(
            "MCP OAuth access JWT binding (no secrets) %s",
            json.dumps(
                {
                    "has_client_id": bool(
                        isinstance(payload.get("client_id"), str) and payload["client_id"].strip()
                    ),
                    "has_azp": bool(isinstance(payload.get("azp"), str) and payload["azp"].strip()),
                    "resolved_oauth_client_id": oauth_client_id_from_clerk_access_payload(payload),
                    "aud_claim_present": payload.get("aud") is not None,
                },
                separators=(",", ":"),
            ),
        )

    return payload


class ClerkMcpTokenVerifier:
    """MCP SDK ``TokenVerifier``: JWT-only (no DB). Maps valid tokens to ``AccessToken``."""

    async def verify_token(self, token: str) -> AccessToken | None:
        stripped = (token or "").strip()
        if not stripped:
            logger.info(
                "MCP transport auth telemetry %s",
                json.dumps(
                    {
                        "stage": "token_verifier",
                        "outcome": "reject",
                        "reason": "missing_or_empty_bearer_token",
                        "bearer_token_length": 0,
                    },
                    separators=(",", ":"),
                ),
            )
            return None
        try:
            payload = await decode_clerk_oauth_access_token(stripped)
        except MCPAuthError as exc:
            logger.info(
                "MCP transport auth telemetry %s",
                json.dumps(
                    {
                        "stage": "token_verifier",
                        "outcome": "reject",
                        "reason": exc.reason_code or "jwt_verification_failed",
                        "bearer_token_length": len(stripped),
                        "detail": str(exc)[:200],
                    },
                    separators=(",", ":"),
                ),
            )
            return None
        sub = payload["sub"]
        assert isinstance(sub, str)
        exp = payload.get("exp")
        expires_at: int | None
        if isinstance(exp, (int, float)):
            expires_at = int(exp)
        else:
            expires_at = None
        return AccessToken(token=stripped, client_id=sub, scopes=[], expires_at=expires_at)


async def get_mcp_user(request: Request | None, db: AsyncSession) -> User:
    """Validate the Bearer JWT and return the matching local ``User``.

    Called from every authenticated MCP tool handler.  Any failure raises
    ``MCPAuthError``, which the tool catches and converts to a structured error
    JSON response so the MCP client always receives a well-formed payload.

    Auth steps
    ----------
    1. Verify the request has an ``Authorization: Bearer <token>`` header.
    2. Confirm Clerk is configured (``settings.clerk_oauth_issuer`` non-empty).
    3. Decode the JWT header (unverified) to extract the ``kid``.
    4. Look up the matching RSA public key from the JWKS cache.
    5. Fully verify the JWT: signature, issuer, expiry, required claims.
    6. Resolve ``sub`` → ``User.clerk_user_id`` in the local DB.

    P2 / P3 auth contract (D016)
    ----------------------------
    - ``iss`` must equal ``settings.clerk_oauth_issuer``.
    - ``sub`` must match a ``users.clerk_user_id`` row (created on first web login).
    - Optional: ``SMEME_MCP_OAUTH_ACCESS_TOKEN_AUDIENCE`` enforces ``aud``.
    - Optional: ``SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS`` enforces OAuth ``client_id`` / ``azp``.
    - ``reasoning:*`` token scope enforcement (forward-looking name) is deferred until
      Clerk exposes custom scopes on access tokens.

    Raises
    ------
    MCPAuthError
        On any authentication failure.  The caller is responsible for translating
        this to a JSON error payload.
    """
    # Non-HTTP transports (stdio) have no request context.
    if request is None:
        raise MCPAuthError("No HTTP request context available (non-HTTP transport?)")

    # RFC 6750 §2.1: token in Authorization header as "Bearer <token>".
    # Using .lower() for case-insensitive header name comparison
    # (Starlette preserves original case; HTTP/2 lowercases; be defensive).
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        logger.info(
            "MCP tool auth telemetry %s",
            json.dumps(
                {
                    "stage": "tool_auth",
                    "outcome": "reject",
                    "reason": "no_bearer_scheme",
                    "note": "oauth_token_not_forwarded_to_mcp_http",
                    **tool_auth_context(request),
                },
                separators=(",", ":"),
            ),
        )
        raise MCPAuthError("Authorization: Bearer <token> required for MCP reasoning tools")

    # Slice off the 7-char "bearer " prefix and trim whitespace.
    token = auth_header[7:].strip()
    if not token:
        logger.info(
            "MCP tool auth telemetry %s",
            json.dumps(
                {
                    "stage": "tool_auth",
                    "outcome": "reject",
                    "reason": "empty_bearer_token",
                    **tool_auth_context(request),
                },
                separators=(",", ":"),
            ),
        )
        raise MCPAuthError("Empty Bearer token")

    try:
        payload = await decode_clerk_oauth_access_token(token)
    except MCPAuthError as exc:
        logger.info(
            "MCP tool auth telemetry %s",
            json.dumps(
                {
                    "stage": "tool_auth",
                    "outcome": "reject",
                    "reason": exc.reason_code or "jwt_verification_failed",
                    "detail": str(exc)[:200],
                    **tool_auth_context(request),
                },
                separators=(",", ":"),
            ),
        )
        raise
    clerk_user_id: str = payload["sub"]
    assert isinstance(clerk_user_id, str)

    # Resolve Clerk sub → local users row.
    # The clerk_user_id column is populated in get_or_create_user_for_clerk()
    # (smeme/auth/clerk_auth.py) the first time this user logs into the SMEme web UI.
    # If a user authenticates an MCP connector before ever logging into SMEme, their
    # sub will not match any row — this is the expected "sign in first" requirement.
    result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        logger.info(
            "MCP tool auth telemetry %s",
            json.dumps(
                {
                    "stage": "tool_auth",
                    "outcome": "reject",
                    "reason": "no_local_user_for_clerk_sub",
                    "bearer_token_length": len(token),
                },
                separators=(",", ":"),
            ),
        )
        raise unlinked_account_mcp_auth_error()
    if not user.is_active:
        logger.info(
            "MCP tool auth telemetry %s",
            json.dumps(
                {
                    "stage": "tool_auth",
                    "outcome": "reject",
                    "reason": "user_inactive",
                    "bearer_token_length": len(token),
                },
                separators=(",", ":"),
            ),
        )
        # Deactivated accounts (e.g. banned users) cannot call MCP tools even with
        # a valid Bearer token.
        raise MCPAuthError("User account is deactivated")

    from smeme.mcp.invocation_telemetry import cache_oauth_client_id_on_request

    cache_oauth_client_id_on_request(request, payload)

    return user
