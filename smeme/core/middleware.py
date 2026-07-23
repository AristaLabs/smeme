"""FastAPI middleware for security, logging, and HTMX handling."""

import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import defaultdict, deque
from threading import Lock
from urllib.parse import urlencode, urlsplit

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from smeme.core.config import settings

logger = logging.getLogger(__name__)

_CLERK_AFTER_MAX_LEN = 2048
_CSRF_COOKIE_NAME = "smeme_csrf"
_CSRF_HEADER_NAME = "x-csrf-token"
_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_CSRF_EXEMPT_PATHS = frozenset(
    {
        "/auth/clerk/webhook",
        "/billing/webhook",
        "/teams-waitlist",
    }
)
_CLERK_COOKIE_NAMES = frozenset({"__session", "__client_uat", "clerk_active_context"})


def _safe_clerk_after_path(path: str) -> str:
    """Allow only same-origin relative paths (open-redirect guard)."""
    if not path or not path.startswith("/") or path.startswith("//"):
        return "/decision-trees/dashboard"
    if len(path) > _CLERK_AFTER_MAX_LEN:
        return "/decision-trees/dashboard"
    return path


def _login_url_preserving_clerk_oauth(request: Request) -> str | None:
    """If this request carries Clerk dev OAuth query params, return /auth/login?...&clerk_after=."""
    clerk_items = [(k, v) for k, v in request.query_params.multi_items() if k.startswith("__clerk")]
    if not clerk_items:
        return None
    after = _safe_clerk_after_path(request.url.path)
    pairs = list(clerk_items) + [("clerk_after", after)]
    return f"/auth/login?{urlencode(pairs)}"


def _csrf_signature(nonce: str) -> str:
    return hmac.new(settings.secret_key.encode(), nonce.encode(), hashlib.sha256).hexdigest()


def _new_csrf_token() -> str:
    nonce = secrets.token_urlsafe(32)
    return f"{nonce}.{_csrf_signature(nonce)}"


def _valid_csrf_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    nonce, sig = token.rsplit(".", 1)
    if not nonce or not sig:
        return False
    return hmac.compare_digest(sig, _csrf_signature(nonce))


def _origin_for_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _request_allowed_origins(request: Request) -> set[str]:
    origins = {_origin_for_url(str(request.url))}
    for configured in (settings.effective_base_url, settings.base_url):
        if configured:
            origins.add(_origin_for_url(configured.rstrip("/")))
    return {origin for origin in origins if origin}


def _same_origin_mutation(request: Request) -> bool:
    allowed = _request_allowed_origins(request)
    origin = request.headers.get("origin")
    if origin:
        return (_origin_for_url(origin) or "") in allowed

    referer = request.headers.get("referer")
    if referer:
        return (_origin_for_url(referer) or "") in allowed

    return False


def _has_clerk_session_cookie(request: Request) -> bool:
    return any(name in request.cookies for name in _CLERK_COOKIE_NAMES)


def _is_csrf_exempt_path(path: str) -> bool:
    if path in _CSRF_EXEMPT_PATHS:
        return True
    if path.startswith("/api/"):
        return True
    return bool(_is_mcp_http_path(path))


# Cloudflare Turnstile (Clerk bot protection on production instances).
_CLERK_TURNSTILE_ORIGIN = "https://challenges.cloudflare.com"
_PLAUSIBLE_ORIGIN = "https://plausible.io"


def _plausible_analytics_enabled() -> bool:
    """Match layouts/_analytics.html opt-in gate (domain or site-specific pa-*.js loader)."""
    if settings.plausible_domain:
        return True
    return "/pa-" in (settings.plausible_script_url or "")


# Content Security Policy - HTMX + Tailwind CDN compatible
# Allows HTMX from unpkg, Tailwind from cdn.tailwindcss.com
def _csp_policy_for_request() -> str:
    """Build CSP; extend with Clerk Frontend API when browser sync is enabled."""
    script = "'self' 'unsafe-inline' https://unpkg.com https://cdn.tailwindcss.com"
    connect = "'self'"
    frame = "'none'"
    img = "'self' data:"
    # base.html loads Inter from Google Fonts (link rel=stylesheet)
    style = "'self' 'unsafe-inline' https://fonts.googleapis.com"
    worker = ""
    if settings.clerk_browser_sync_enabled:
        host = settings.clerk_frontend_api_host
        if host:
            origin = f"https://{host}"
            script = f"{script} {origin} {_CLERK_TURNSTILE_ORIGIN}"
            connect = f"{connect} {origin} https://api.clerk.com"
            frame = f"{origin} {_CLERK_TURNSTILE_ORIGIN}"
            img = f"{img} {origin} https://img.clerk.com"
            # clerk.browser.js creates Web Workers from blob: URLs; without worker-src, script-src is used and blocks them.
            worker = "worker-src 'self' blob:; "
    if _plausible_analytics_enabled():
        script = f"{script} {_PLAUSIBLE_ORIGIN}"
        connect = f"{connect} {_PLAUSIBLE_ORIGIN}"
    return (
        "default-src 'self'; "
        f"script-src {script}; "
        f"style-src {style}; "
        f"{worker}"
        f"img-src {img}; "
        "font-src 'self' https://fonts.gstatic.com; "
        f"connect-src {connect}; "
        f"frame-src {frame}; "
        "frame-ancestors 'none'"
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses.

    Implements OWASP recommended security headers:
    - CSP: Prevents XSS by controlling resource loading
    - HSTS: Forces HTTPS in production
    - X-Content-Type-Options: Prevents MIME sniffing
    - X-Frame-Options: Prevents clickjacking
    - Referrer-Policy: Controls referrer information
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Basic security headers (always applied)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy (HTMX-compatible; Clerk FAPI when browser sync on)
        response.headers["Content-Security-Policy"] = _csp_policy_for_request()

        # Client hint for SSR theme when preference is ``system`` (repeat visits).
        response.headers["Accept-CH"] = "Sec-CH-Prefers-Color-Scheme"

        # HSTS - only in production (requires HTTPS)
        if settings.is_production:
            # max-age=31536000 (1 year), includeSubDomains
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


class CsrfProtectionMiddleware(BaseHTTPMiddleware):
    """Protect Clerk-cookie browser mutations from cross-site form posts."""

    async def dispatch(self, request: Request, call_next):
        cookie_token = request.cookies.get(_CSRF_COOKIE_NAME)
        csrf_token = cookie_token if _valid_csrf_token(cookie_token) else _new_csrf_token()
        request.state.csrf_token = csrf_token

        if (
            request.method.upper() not in _CSRF_SAFE_METHODS
            and _has_clerk_session_cookie(request)
            and not _is_csrf_exempt_path(request.url.path)
            and not self._request_has_valid_csrf(request, csrf_token)
        ):
            logger.warning(
                "Rejected potential CSRF request",
                extra={"method": request.method, "path": request.url.path},
            )
            return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)

        response = await call_next(request)
        if request.cookies.get(_CSRF_COOKIE_NAME) != csrf_token:
            response.set_cookie(
                _CSRF_COOKIE_NAME,
                csrf_token,
                max_age=24 * 60 * 60,
                secure=settings.is_production,
                httponly=False,
                samesite="lax",
                path="/",
            )
        return response

    @staticmethod
    def _request_has_valid_csrf(request: Request, csrf_token: str) -> bool:
        header_token = request.headers.get(_CSRF_HEADER_NAME)
        if header_token and hmac.compare_digest(header_token, csrf_token):
            return True
        return _same_origin_mutation(request)


class ClerkBrowserSyncContextMiddleware(BaseHTTPMiddleware):
    """Expose Clerk browser-sync flags on ``request.state`` for templates (dev URL session → ``__session`` cookie)."""

    async def dispatch(self, request: Request, call_next):
        request.state.clerk_browser_sync = settings.clerk_browser_sync_enabled
        request.state.clerk_publishable_key = (settings.clerk_publishable_key or "").strip()
        request.state.clerk_frontend_api_host = settings.clerk_frontend_api_host or ""
        return await call_next(request)


class McpTransportRateLimitMiddleware(BaseHTTPMiddleware):
    """Best-effort in-process MCP transport limiter (per-IP + verified per-sub).

    This guards the mounted MCP HTTP surface before auth/session work. The limit
    is intentionally independent of monthly quota caps.

    Per-sub bucketing uses JWKS-verified JWT ``sub`` only (same path as transport
    auth) so unverified Bearer payloads cannot target another account's bucket.
    """

    _STATE_LOCK = Lock()
    _REQUEST_TIMES: dict[str, deque[float]] = defaultdict(deque)

    def __init__(
        self,
        app,
        *,
        mcp_path: str,
        limit_ip_per_minute: int,
        limit_sub_per_minute: int,
        clerk_oauth_issuer: str | None = None,
    ) -> None:
        super().__init__(app)
        self._prefix = mcp_path.rstrip("/")
        self._ip_limit = max(0, limit_ip_per_minute)
        self._sub_limit = max(0, limit_sub_per_minute)
        self._clerk_oauth_issuer = (clerk_oauth_issuer or "").rstrip("/") or None
        self._window_seconds = 60.0
        # Fresh app instance (tests frequently create many): avoid carrying
        # previous-request counters across app lifetimes in the same process.
        with self._STATE_LOCK:
            self._REQUEST_TIMES.clear()

    def _is_mcp_path(self, path: str) -> bool:
        prefix = self._prefix
        if not prefix:
            return False
        return path == prefix or path.startswith(f"{prefix}/")

    @staticmethod
    def _bearer_token(request: Request) -> str | None:
        auth_header = (request.headers.get("authorization") or "").strip()
        if not auth_header.lower().startswith("bearer "):
            return None
        token = auth_header[7:].strip()
        return token or None

    async def _verified_subject_from_bearer(self, request: Request) -> str | None:
        """Return ``sub`` only after JWKS signature verification (no spoofed payloads)."""
        if not self._clerk_oauth_issuer:
            return None
        token = self._bearer_token(request)
        if not token:
            return None
        from smeme.mcp.bearer_auth import MCPAuthError, decode_clerk_oauth_access_token

        try:
            payload = await decode_clerk_oauth_access_token(
                token,
                issuer=self._clerk_oauth_issuer,
            )
        except MCPAuthError:
            return None
        sub = payload.get("sub")
        if isinstance(sub, str) and sub.strip():
            return sub.strip()
        return None

    @classmethod
    def _consume_bucket(
        cls,
        *,
        key: str,
        limit: int,
        now: float,
        window_seconds: float,
    ) -> tuple[bool, int]:
        """Record one hit; return (allowed, retry_after_seconds)."""
        if limit <= 0:
            return True, 0
        with cls._STATE_LOCK:
            bucket = cls._REQUEST_TIMES[key]
            cutoff = now - window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(bucket[0] + window_seconds - now))
                return False, retry_after
            bucket.append(now)
            return True, 0

    async def dispatch(self, request: Request, call_next):
        if not self._is_mcp_path(request.url.path):
            return await call_next(request)

        now = time.time()
        ip = request.client.host if request.client else "unknown"

        ip_allowed, ip_retry_after = self._consume_bucket(
            key=f"ip:{ip}",
            limit=self._ip_limit,
            now=now,
            window_seconds=self._window_seconds,
        )
        if not ip_allowed:
            return JSONResponse(
                {
                    "error": "rate_limited",
                    "message": "Too many MCP requests from this IP. Please retry shortly.",
                },
                status_code=429,
                headers={"Retry-After": str(ip_retry_after)},
            )

        sub = await self._verified_subject_from_bearer(request)
        if sub is not None:
            sub_allowed, sub_retry_after = self._consume_bucket(
                key=f"sub:{sub}",
                limit=self._sub_limit,
                now=now,
                window_seconds=self._window_seconds,
            )
            if not sub_allowed:
                return JSONResponse(
                    {
                        "error": "rate_limited",
                        "message": (
                            "Too many MCP requests for this account token. Please retry shortly."
                        ),
                    },
                    status_code=429,
                    headers={"Retry-After": str(sub_retry_after)},
                )

        return await call_next(request)


def _mcp_http_path_from_request(request: Request) -> str | None:
    """MCP mount prefix from app state (B2-d) with process-settings fallback."""
    state = getattr(request.app, "state", None)
    if state is not None:
        enabled = getattr(state, "mcp_enabled", None)
        path = getattr(state, "mcp_http_path", None)
        if enabled is not None and path is not None:
            if not enabled:
                return None
            prefix = str(path).rstrip("/")
            return prefix or None
    if not settings.mcp_enabled:
        return None
    prefix = settings.mcp_http_path.rstrip("/")
    return prefix or None


def _is_mcp_http_path(path: str, request: Request | None = None) -> bool:
    """True when this request targets the mounted Streamable HTTP MCP app.

    MCP OAuth clients often send ``Accept`` values that include ``text/html`` alongside
    JSON/SSE. ``HTMXLoginRedirectMiddleware`` must not turn MCP **401** responses into
    **302** to ``/auth/login`` — connectors need **401** + ``WWW-Authenticate`` (RFC 9728
    bootstrap). See ``docs/guides/dr3-mcp-oauth-authoritative-sources.md`` (*Transport-layer auth and HTMX middleware*).
    """
    prefix = _mcp_http_path_from_request(request) if request is not None else None
    if prefix is None:
        if not settings.mcp_enabled:
            return False
        prefix = settings.mcp_http_path.rstrip("/")
        if not prefix:
            return False
    return path == prefix or path.startswith(f"{prefix}/")


class McpInboundAuthTelemetryMiddleware(BaseHTTPMiddleware):
    """Log safe auth shape for HTTP requests to the MCP mount path.

    Runs after transport rate limiting (which is outermost) so abusive floods
    that receive **429** are not logged at INFO. Helps distinguish connector
    bugs (OAuth completes but no ``Authorization`` on MCP POST) from server-side JWT
    or user-link failures.
    """

    async def dispatch(self, request: Request, call_next):
        if _is_mcp_http_path(request.url.path, request):
            from smeme.mcp.auth_telemetry import inbound_http_telemetry_dict

            payload = inbound_http_telemetry_dict(request)
            log_line = f"MCP inbound auth telemetry {json.dumps(payload, separators=(',', ':'))}"
            # B1-c: INFO floods under abuse; production uses DEBUG (rate limiter is outermost).
            if settings.is_production:
                logger.debug(log_line)
            else:
                logger.info(log_line)
        return await call_next(request)


class HTMXLoginRedirectMiddleware(BaseHTTPMiddleware):
    """Redirect 401 Unauthorized to login page for browser and HTMX requests."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Redirect 401 (Unauthorized) to login for browser and HTMX requests
        if response.status_code == 401:
            if _is_mcp_http_path(request.url.path, request):
                return response
            # Check if this is a browser request (not an API call)
            accept_header = request.headers.get("accept", "")
            is_browser_or_htmx = "text/html" in accept_header or "HX-Request" in request.headers

            if is_browser_or_htmx:
                preserved = _login_url_preserving_clerk_oauth(request)
                if preserved:
                    logger.info(
                        "Redirecting unauthorized request to login with Clerk OAuth params: %s",
                        request.url.path,
                    )
                    return RedirectResponse(url=preserved, status_code=302)
                logger.info(f"Redirecting unauthorized request to login: {request.url.path}")
                return RedirectResponse(url="/auth/login", status_code=302)

        return response


class LoggingMiddleware(BaseHTTPMiddleware):
    """Log all requests."""

    async def dispatch(self, request: Request, call_next):
        logger.info(f"{request.method} {request.url.path}")
        response = await call_next(request)
        logger.info(f"{request.method} {request.url.path} - {response.status_code}")
        return response
