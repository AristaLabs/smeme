"""Application configuration using Pydantic Settings."""

import base64
import binascii
import json
from typing import TYPE_CHECKING, Any, Literal, get_args, get_origin
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, EnvSettingsSource, SettingsConfigDict

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo


class _LenientEnvSource(EnvSettingsSource):
    """EnvSettingsSource tolerant of common Render env-var quirks.

    - **list[str]**: bare URL, comma-separated, or blank instead of JSON array
    - **bool**: blank string (env var declared but empty) → field default
    """

    @staticmethod
    def _field_is_bool(field: "FieldInfo") -> bool:
        ann = field.annotation
        if ann is bool:
            return True
        if get_origin(ann) is Literal:
            return all(isinstance(a, bool) for a in get_args(ann))
        args = get_args(ann)
        return bool in args

    def prepare_field_value(
        self,
        field_name: str,
        field: "FieldInfo",
        value: Any,
        value_is_complex: bool,
    ) -> Any:
        if isinstance(value, str) and not value.strip() and self._field_is_bool(field):
            return None
        return super().prepare_field_value(field_name, field, value, value_is_complex)

    def decode_complex_value(
        self,
        field_name: str,
        field: "FieldInfo",
        value: Any,
    ) -> Any:
        if not isinstance(value, str):
            return super().decode_complex_value(field_name, field, value)
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.startswith(("[", "{")):
            return json.loads(stripped)
        # Bare string or comma-separated — convert to a single-element or multi-element list.
        return [v.strip() for v in stripped.split(",") if v.strip()]


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ) -> tuple:  # type: ignore[override]
        """Replace the default EnvSettingsSource with our lenient variant.

        Handles blank bool env vars and list fields (e.g. ALLOWED_ORIGINS) when
        Render sets them to empty, bare URLs, or comma-separated strings.
        """
        return (
            init_settings,
            _LenientEnvSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    # Application
    app_name: str = "SMEme Platform"
    version: str = "1.0.0"
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=False, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    show_decision_tree_generation_region_selector: bool = Field(
        default=True,
        alias="SHOW_DECISION_TREE_GENERATION_REGION_SELECTOR",
        description=(
            "When true, show the optional Region (Tavily country) control on the agentic "
            "generation brief form. When false, hide it and ignore submitted country "
            "(auto-detect behavior only)."
        ),
    )

    smeme_ai_generation_enabled: bool = Field(
        default=True,
        alias="SMEME_AI_GENERATION_ENABLED",
        description=(
            "When true, mount the AI generation wizard and initialize its checkpointer. "
            "Requires OPENAI_API_KEY. Core self-host appliances may set false so the app "
            "boots without OpenAI (D022 / D023). SaaS default remains true."
        ),
    )

    # Security
    secret_key: str = Field(..., alias="SECRET_KEY")
    jwt_secret_key: str = Field(..., alias="JWT_SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    # Database
    database_url: str = Field(..., alias="DATABASE_URL")
    test_database_url: str | None = Field(default=None, alias="TEST_DATABASE_URL")

    @model_validator(mode="after")
    def validate_database_config(self) -> "Settings":
        """Validate PostgreSQL is being used."""
        if not self.database_url.startswith(("postgresql://", "postgresql+asyncpg://")):
            raise ValueError(
                "PostgreSQL required. DATABASE_URL must start with 'postgresql://' or 'postgresql+asyncpg://'"
            )
        return self

    # CORS
    allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        alias="ALLOWED_ORIGINS",
    )

    # OpenAI (required only when AI generation is enabled)
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    @model_validator(mode="after")
    def validate_openai_when_generation_enabled(self) -> "Settings":
        """OPENAI_API_KEY is required when SMEME_AI_GENERATION_ENABLED is true."""
        if self.smeme_ai_generation_enabled and not (self.openai_api_key or "").strip():
            raise ValueError(
                "OPENAI_API_KEY is required when SMEME_AI_GENERATION_ENABLED is true. "
                "Set SMEME_AI_GENERATION_ENABLED=false for Core boots without OpenAI."
            )
        return self

    # Tavily (web search for agentic decision-tree generation)
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")

    # Email (SendGrid)
    sendgrid_api_key: str | None = Field(default=None, alias="SENDGRID_API_KEY")
    email_from_address: str = Field(default="noreply@localhost", alias="EMAIL_FROM_ADDRESS")
    email_from_name: str = Field(default="SMEme", alias="EMAIL_FROM_NAME")
    teams_waitlist_notify_email: str = Field(
        default="contact@aristalabs.ai",
        alias="TEAMS_WAITLIST_NOTIFY_EMAIL",
        description="Internal inbox for Business tier waitlist signups (SendGrid; env name legacy).",
    )
    base_url: str = Field(default="http://localhost:8000", alias="BASE_URL")
    # Render sets RENDER_EXTERNAL_URL automatically; we prefer it when present
    render_external_url: str | None = Field(default=None, alias="RENDER_EXTERNAL_URL")
    # Render sets these when the service deploys from Git (startup log provenance)
    render_git_commit: str | None = Field(default=None, alias="RENDER_GIT_COMMIT")
    render_git_branch: str | None = Field(default=None, alias="RENDER_GIT_BRANCH")
    render_service_name: str | None = Field(default=None, alias="RENDER_SERVICE_NAME")

    # Privacy-respecting, cookieless analytics (Plausible). When unset, no analytics
    # script is emitted at all — tracking is strictly opt-in via this env var.
    plausible_domain: str | None = Field(default=None, alias="PLAUSIBLE_DOMAIN")
    plausible_script_url: str = Field(
        default="https://plausible.io/js/script.js", alias="PLAUSIBLE_SCRIPT_URL"
    )

    @property
    def effective_base_url(self) -> str:
        """Base URL for redirects/links and OAuth ``resource`` metadata.

        On Render, ``RENDER_EXTERNAL_URL`` is auto-set to ``*.onrender.com``. When
        a custom domain is configured, set ``BASE_URL`` to the public HTTPS origin;
        it wins over ``RENDER_EXTERNAL_URL`` so MCP metadata matches the connector URL.
        """
        default_local = "http://localhost:8000"
        base = self.base_url.rstrip("/")
        if base and base != default_local:
            return base
        if self.render_external_url:
            return self.render_external_url.rstrip("/")
        return base or default_local

    @property
    def startup_deploy_label(self) -> str:
        """Human-readable deploy id for startup logs (Render Git env or local)."""
        commit = (self.render_git_commit or "").strip() or None
        branch = (self.render_git_branch or "").strip() or None
        service = (self.render_service_name or "").strip() or None
        if commit:
            short = commit[:7]
            ref = branch or "?"
            inner = f"{ref} @ {short}"
        elif branch:
            inner = branch
        else:
            inner = "local"
        if service:
            return f"[{service}] ({inner})"
        return f"({inner})"

    # Stripe (Sprint 7)
    stripe_secret_key: str | None = Field(default=None, alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str | None = Field(default=None, alias="STRIPE_WEBHOOK_SECRET")
    stripe_premium_price_id: str | None = Field(default=None, alias="STRIPE_PREMIUM_PRICE_ID")

    @property
    def stripe_configured(self) -> bool:
        """True if Stripe billing is configured (secret key + premium price)."""
        return bool(self.stripe_secret_key and self.stripe_premium_price_id)

    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment.lower() == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment.lower() == "production"

    @property
    def is_testing(self) -> bool:
        """Check if running in testing."""
        return self.environment.lower() == "testing"

    sqlalchemy_log_level: str = Field(default="WARNING", alias="SQLALCHEMY_LOG_LEVEL")
    """Level for ``sqlalchemy.engine`` (SQL text). Default WARNING keeps console readable when DEBUG enables engine echo."""

    # DR-3 — remote MCP (Streamable HTTP) + OAuth discovery (see docs/guides/dr3-mcp-oauth-authoritative-sources.md)
    mcp_enabled: bool = Field(default=False, alias="MCP_ENABLED")
    """Mount Streamable HTTP MCP and OAuth protected-resource / AS metadata when true."""

    mcp_http_path: str = Field(default="/api/v1/mcp", alias="MCP_HTTP_PATH")
    """URL path of the MCP endpoint (no trailing slash). Used as RFC 9728 ``resource`` identifier suffix."""

    mcp_transport_rate_limit_per_ip_per_minute: int = Field(
        default=120,
        alias="SMEME_MCP_TRANSPORT_RATE_LIMIT_PER_IP_PER_MINUTE",
        ge=0,
        description=(
            "Max MCP transport HTTP requests per minute per client IP. "
            "Set 0 to disable the IP dimension."
        ),
    )
    mcp_transport_rate_limit_per_sub_per_minute: int = Field(
        default=240,
        alias="SMEME_MCP_TRANSPORT_RATE_LIMIT_PER_SUB_PER_MINUTE",
        ge=0,
        description=(
            "Max MCP transport HTTP requests per minute per OAuth subject (`sub`) when a Bearer "
            "token is present. Set 0 to disable the subject dimension."
        ),
    )

    mcp_allowed_oauth_client_ids: list[str] = Field(
        default_factory=list,
        alias="SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS",
    )
    """Clerk OAuth application client IDs allowed to call MCP tools (Bearer access tokens).

    Comma-separated in env. **Empty (default)** = do not enforce client_id/azp binding.
    **SaaS prod (DCR on):** leave blank — DCR mints per-connector client ids.
    **Self-hosted DCR-off:** set to your static Clerk OAuth app client id(s).
    """

    mcp_oauth_access_token_audience: str | None = Field(
        default=None,
        alias="SMEME_MCP_OAUTH_ACCESS_TOKEN_AUDIENCE",
    )
    """If set, OAuth access JWTs must list this string in their ``aud`` claim (string or array).

    Leave unset when Clerk does not emit a stable audience for MCP (see DR-3 P3 notes).
    """

    mcp_invocation_telemetry_enabled: bool = Field(
        default=True,
        alias="MCP_INVOCATION_TELEMETRY_ENABLED",
        description="Emit structured logs and (when persist is on) rows for MCP tool invocations.",
    )

    mcp_invocation_telemetry_persist: bool = Field(
        default=True,
        alias="MCP_INVOCATION_TELEMETRY_PERSIST",
        description="Write mcp_tool_invocations rows; logs still emit when enabled.",
    )

    mcp_cost_baseline_usd_micros: int = Field(
        default=200,
        alias="MCP_COST_BASELINE_USD_MICROS",
        ge=0,
        description="Fixed micro-USD per MCP invocation in internal COGS estimate (default $0.0002).",
    )

    mcp_cost_usd_micros_per_second: int = Field(
        default=800,
        alias="MCP_COST_USD_MICROS_PER_SECOND",
        ge=0,
        description="Micro-USD per second of handler wall time in COGS estimate (default $0.0008/s).",
    )

    mcp_authoring_graph_tools_enabled: bool = Field(
        default=True,
        alias="MCP_AUTHORING_GRAPH_TOOLS_ENABLED",
    )
    """When true, register chat-authoring tools: design guidance, validate, create/get/update draft.

    Defaults on whenever MCP is used: the agent builds a decision-tree draft in chat using
    server-owned design guidance (no server-side LLM/search), validates ``dt_graph_json``,
    then creates or revises a dashboard draft. Set ``false`` to opt out. Independent of
    ``SMEME_AI_GENERATION_ENABLED`` (web wizard only). Quota weight 0 for MCP weighted
    calls; create_draft still enforces the active decision-tree plan cap. Updates are
    lenient (may persist intermediate graphs) and never Deploy or List.
    """

    mcp_inquire_tools_enabled: bool = Field(
        default=False,
        alias="MCP_INQUIRE_TOOLS_ENABLED",
    )
    """When true, mount the Inquire **orchestrator** MCP surface at
    ``{MCP_HTTP_PATH}/orchestrator`` with durable session tools
    (``smeme_inquire_*``) and ``smeme_inquire_guidance_*``.

    Default **off**: chat ``/mcp`` uses the Inquire gather facade
    (``smeme_reasoning_evaluate`` / ``evaluate_continue``) without VERIFY.
    Explicit protocol tools require an isolated-evaluator harness.
    Independent of ``MCP_AUTHORING_GRAPH_TOOLS_ENABLED``.
    """

    # D026 — MCP-first local User provision (temporary operational rollout switch; not licensing).
    mcp_first_provisioning_enabled: bool = Field(
        default=False,
        alias="MCP_FIRST_PROVISIONING_ENABLED",
    )
    """When true, a valid MCP Bearer with no local ``users`` row may provision after Clerk
    verified-email + express legal-acceptance gates (D026). Default false for safe rollout.
    Incomplete legal config fails only the first-provision path (``legal_config_incomplete``),
    not unrelated MCP startup.
    """

    mcp_first_provision_rate_limit_per_ip_per_minute: int = Field(
        default=10,
        alias="SMEME_MCP_FIRST_PROVISION_RATE_LIMIT_PER_IP_PER_MINUTE",
        ge=0,
        description=(
            "Max first-provision attempts per minute per client IP when MCP-first "
            "provisioning is enabled. Set 0 to disable the IP dimension."
        ),
    )
    mcp_first_provision_rate_limit_per_sub_per_minute: int = Field(
        default=5,
        alias="SMEME_MCP_FIRST_PROVISION_RATE_LIMIT_PER_SUB_PER_MINUTE",
        ge=0,
        description=(
            "Max first-provision attempts per minute per Clerk ``sub`` when MCP-first "
            "provisioning is enabled. Set 0 to disable the subject dimension."
        ),
    )

    legal_terms_url: str | None = Field(default=None, alias="SMEME_LEGAL_TERMS_URL")
    """Public Terms URL recorded at provision and shown in gated auth_error details (D026)."""

    legal_privacy_url: str | None = Field(default=None, alias="SMEME_LEGAL_PRIVACY_URL")
    """Public Privacy URL recorded at provision and shown in gated auth_error details (D026)."""

    legal_terms_version: str | None = Field(default=None, alias="SMEME_LEGAL_TERMS_VERSION")
    """Operator version label for Terms (e.g. ``2026-07-20``). Config constant only — never scrape HTML."""

    legal_privacy_version: str | None = Field(default=None, alias="SMEME_LEGAL_PRIVACY_VERSION")
    """Operator version label for Privacy (e.g. ``2026-07-20``). Config constant only — never scrape HTML."""

    def mcp_first_legal_config_complete(self) -> bool:
        """True when Terms/Privacy URL + version constants are all non-empty."""
        return bool(
            (self.legal_terms_url or "").strip()
            and (self.legal_privacy_url or "").strip()
            and (self.legal_terms_version or "").strip()
            and (self.legal_privacy_version or "").strip()
        )

    # Clerk (hosted auth). When ``clerk_secret_key`` and ``clerk_sign_in_url`` are set, the app uses
    # Clerk session JWTs (``__session`` cookie or ``Authorization: Bearer``) instead of FastAPI-Users cookies.
    clerk_secret_key: str | None = Field(default=None, alias="CLERK_SECRET_KEY")
    clerk_publishable_key: str | None = Field(default=None, alias="CLERK_PUBLISHABLE_KEY")
    clerk_sign_in_url: str | None = Field(default=None, alias="CLERK_SIGN_IN_URL")
    clerk_sign_up_url: str | None = Field(default=None, alias="CLERK_SIGN_UP_URL")
    clerk_sign_out_url: str | None = Field(default=None, alias="CLERK_SIGN_OUT_URL")
    clerk_webhook_secret: str | None = Field(default=None, alias="CLERK_WEBHOOK_SECRET")
    """Svix signing secret for Clerk webhooks (starts with ``whsec_``).

    Obtain from the Clerk Dashboard → Webhooks → your endpoint → Signing Secret.
    When unset the ``/auth/clerk/webhook`` endpoint returns HTTP 500 and logs a warning.
    """
    """Optional Clerk URL to open after clearing app cookies.

    Must **not** be the same as ``CLERK_SIGN_IN_URL``: opening the sign-in page does not end
    the Clerk session, so users get SSO'd back to the app (logout loop). Leave unset to
    redirect to ``/auth/login`` only. Use a dedicated sign-out URL from the Clerk dashboard
    if available (e.g. ``.../sign-out``).
    """

    @property
    def clerk_enabled(self) -> bool:
        """Use Clerk for web authentication (JWT verification via Clerk Backend API)."""
        return bool(self.clerk_secret_key and self.clerk_sign_in_url)

    @property
    def clerk_frontend_api_host(self) -> str | None:
        """Frontend API hostname for loading ``clerk-js`` (decoded from ``clerk_publishable_key``)."""
        pk = (self.clerk_publishable_key or "").strip()
        if not pk:
            return None
        parts = pk.split("_", 2)
        if len(parts) < 3 or not parts[2]:
            return None
        raw = parts[2]
        padded = raw + "=" * (-len(raw) % 4)
        try:
            decoded = base64.b64decode(padded).decode("ascii")
        except (binascii.Error, UnicodeDecodeError):
            return None
        host = decoded.rstrip("$").strip()
        return host or None

    @property
    def clerk_browser_sync_enabled(self) -> bool:
        """Load Clerk browser SDK so dev URL-based session sync can set ``__session`` (see partial ``_clerk_browser_sync``)."""
        return bool(
            self.clerk_enabled
            and (self.clerk_publishable_key or "").strip()
            and self.clerk_frontend_api_host
        )

    clerk_oauth_issuer_override: str | None = Field(default=None, alias="CLERK_OAUTH_ISSUER")
    """Explicit Clerk OAuth AS issuer URL (e.g. ``https://valued-civet-29.clerk.accounts.dev``).
    Falls back to ``https://{clerk_frontend_api_host}`` decoded from ``CLERK_PUBLISHABLE_KEY`` when unset.
    Required in production when using a custom domain (``https://clerk.yourdomain.com``).
    """

    clerk_oauth_dynamic_registration: bool = Field(
        default=False, alias="CLERK_OAUTH_DYNAMIC_REGISTRATION"
    )
    """When true, mirrored RFC 8414 / OIDC discovery includes ``registration_endpoint`` (Clerk
    ``POST {issuer}/oauth/register``).  Enable only if **Dynamic OAuth Client Registration** is
    on in the Clerk Dashboard (Instance settings).  Required by some MCP clients (e.g. Cursor)
    that refuse OAuth without DCR; keep false for static-``clientId`` flows (Cowork) when DCR is off.
    """

    @property
    def clerk_oauth_issuer(self) -> str | None:
        """Clerk OAuth AS issuer for RFC 9728 ``authorization_servers`` and ``/.well-known/oauth-authorization-server`` redirect.

        Returns the issuer origin (no trailing slash) when Clerk is configured as the OAuth AS
        (P1-Clerk path, D016). Returns ``None`` when no Clerk publishable key is present, which
        causes discovery routes to fall back to the SMEme-hosted stub.
        """
        if self.clerk_oauth_issuer_override:
            return self.clerk_oauth_issuer_override.rstrip("/")
        host = self.clerk_frontend_api_host
        if host:
            return f"https://{host}"
        return None

    def clerk_authorized_parties(self) -> list[str]:
        """Origins allowed in the session JWT ``azp`` claim (see Clerk manual JWT docs).

        The ``azp`` claim is the frontend origin that *initiated* the Clerk session.
        For sessions started from the Clerk Account Portal
        (``https://<instance>.accounts.dev``), ``azp`` is the Account Portal domain —
        not the SMEme origin.  We therefore also include the Clerk frontend-API host
        decoded from ``CLERK_PUBLISHABLE_KEY``, and the Account Portal host derived
        from ``CLERK_SIGN_IN_URL``.

        Passing an empty list disables ``azp`` validation entirely; we avoid that for
        production but accept Account Portal origins for development instances.
        """
        parties: set[str] = {
            self.effective_base_url.rstrip("/"),
            self.base_url.rstrip("/"),
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        }
        # Apex vs www: users may land on either; modal sign-in azp matches page origin.
        for origin in (self.effective_base_url.rstrip("/"), self.base_url.rstrip("/")):
            if origin.startswith("https://www."):
                parties.add(origin.replace("https://www.", "https://", 1))
            elif origin.startswith("https://") and ".www." not in origin:
                from urllib.parse import urlparse as _p

                parsed = _p(origin)
                if parsed.hostname and parsed.hostname.count(".") >= 1:
                    parties.add(f"https://www.{parsed.hostname}")
        for o in self.allowed_origins:
            if o:
                parties.add(o.rstrip("/"))

        # Include the Clerk Account Portal host so sessions created there are accepted.
        # e.g. CLERK_SIGN_IN_URL = https://valued-civet-29.accounts.dev/sign-in
        #      → adds https://valued-civet-29.accounts.dev
        if self.clerk_sign_in_url:
            from urllib.parse import urlparse as _urlparse

            parsed = _urlparse(self.clerk_sign_in_url.strip())
            if parsed.scheme and parsed.netloc:
                parties.add(f"{parsed.scheme}://{parsed.netloc}")

        # Include the Clerk frontend API host decoded from the publishable key.
        if self.clerk_frontend_api_host:
            parties.add(f"https://{self.clerk_frontend_api_host}")

        return sorted(parties)

    def clerk_login_redirect_url(self, next_path: str = "/auth/clerk-callback") -> str:
        """Clerk sign-in URL with ``redirect_url`` pointing to our callback route.

        The callback route (``/auth/clerk-callback``) is the canonical re-entry
        point from Clerk.  Using it here keeps ``redirect_url`` and the Clerk
        Dashboard "After Sign-In URL" in sync — both point to the same place.
        """
        import urllib.parse

        if not self.clerk_sign_in_url:
            return "/auth/login"
        base = self.clerk_sign_in_url.strip()
        dest = urllib.parse.quote(
            f"{self.effective_base_url.rstrip('/')}{next_path}",
            safe="",
        )
        sep = "&" if ("?" in base) else "?"
        return f"{base}{sep}redirect_url={dest}"

    def clerk_register_redirect_url(self, next_path: str = "/auth/clerk-callback") -> str:
        """Clerk sign-up URL with ``redirect_url`` pointing to our callback route."""
        if not self.clerk_sign_up_url:
            return self.clerk_login_redirect_url(next_path)
        import urllib.parse

        base = self.clerk_sign_up_url.strip()
        dest = urllib.parse.quote(
            f"{self.effective_base_url.rstrip('/')}{next_path}",
            safe="",
        )
        sep = "&" if ("?" in base) else "?"
        return f"{base}{sep}redirect_url={dest}"

    @property
    def clerk_account_portal_url(self) -> str | None:
        """Clerk hosted Account Portal URL (email, optional password, name).

        Derived from ``CLERK_SIGN_IN_URL`` (same host, path ``/user``).
        Example: ``https://valued-civet-29.accounts.dev/user``.
        Returns ``None`` when Clerk is not configured.
        """
        url = (self.clerk_sign_in_url or "").strip()
        if not url:
            return None
        parsed = urlparse(url)
        if not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}/user"

    def clerk_account_portal_url_with_redirect(
        self, return_path: str = "/auth/profile/dashboard"
    ) -> str | None:
        """Clerk Account Portal URL with a ``redirect_url`` back to SMEme.

        Appending ``redirect_url`` causes Clerk to send the user back to the
        specified SMEme page after they close the portal.  Without it, Clerk
        leaves users on ``accounts.dev`` with no obvious way back.

        Also fixes the Google-session confusion bug: when the user opens this
        URL in a new tab, Clerk picks up whichever Google session Chrome
        considers active.  The redirect URL gives authors a clear path back
        regardless of which account Clerk shows them.
        """
        base = self.clerk_account_portal_url
        if not base:
            return None
        import urllib.parse

        dest = urllib.parse.quote(
            f"{self.effective_base_url.rstrip('/')}{return_path}",
            safe="",
        )
        sep = "&" if ("?" in base) else "?"
        return f"{base}{sep}redirect_url={dest}"

    def clerk_external_logout_url(self) -> str | None:
        """Return a Clerk-hosted URL to visit after logout, or ``None`` to stay on-app only.

        When ``CLERK_SIGN_OUT_URL`` is the same page as sign-in, returning users still have a
        Clerk session; Clerk immediately sends them back to the app — use ``/auth/login`` instead.
        """
        out = (self.clerk_sign_out_url or "").strip()
        if not out:
            return None
        inn = (self.clerk_sign_in_url or "").strip()
        if inn and _clerk_portal_url_fingerprint(out) == _clerk_portal_url_fingerprint(inn):
            return None
        return out


def _clerk_portal_url_fingerprint(url: str) -> str:
    p = urlparse(url.strip())
    if not p.netloc:
        return url.strip().lower().rstrip("/")
    path = (p.path or "").rstrip("/").lower()
    return f"{p.netloc.lower()}{path}"


# Global settings instance
settings = Settings()
