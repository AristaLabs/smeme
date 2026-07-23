"""Core FastAPI application factory (public Core product surface).

Must not import SAAS-ONLY packages (landing, legal, Stripe billing routes, downgrade
middleware). See D022 / D023. The private SaaS overlay mounts commercial routers via
``smeme.saas_overlay``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from smeme.api.health import router as health_router
from smeme.api.reasoning_preflight import router as reasoning_preflight_router
from smeme.auth.clerk_webhook import router as clerk_webhook_router
from smeme.auth.routes import auth_router, profile_router
from smeme.core.callout_html import render_callout_html
from smeme.core.config import Settings, settings
from smeme.core.exception_handlers import (
    generic_error_handler,
    http_exception_handler,
    validation_error_handler,
)
from smeme.core.logging import get_logger, setup_logging
from smeme.core.middleware import (
    ClerkBrowserSyncContextMiddleware,
    CsrfProtectionMiddleware,
    HTMXLoginRedirectMiddleware,
    LoggingMiddleware,
    McpInboundAuthTelemetryMiddleware,
    McpTransportRateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from smeme.core.rate_limiting import limiter
from smeme.docs.routes import router as docs_router
from smeme.mcp.discovery_routes import register_mcp_oauth_discovery_routes
from smeme.mcp.reasoning_fastmcp import McpMountPathNormalizeMiddleware, mount_mcp_on_app
from smeme.decision_tree.editor.routes import router as decision_tree_editor_router
from smeme.decision_tree.routes import router as decision_tree_router
from smeme.decision_tree.viewer.routes import router as decision_tree_viewer_router

logger = get_logger(__name__)

_LANGSMITH_ENV_KEYS = (
    "LANGCHAIN_API_KEY",
    "LANGCHAIN_PROJECT",
    "LANGCHAIN_ENDPOINT",
    "LANGCHAIN_TRACING_V2",
)


def disable_langsmith_tracing() -> None:
    """Ensure workflow I/O is not sent to LangSmith or other LangChain tracing backends."""
    import os

    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    for key in _LANGSMITH_ENV_KEYS:
        if key != "LANGCHAIN_TRACING_V2":
            os.environ.pop(key, None)


RATE_LIMIT_HTML = render_callout_html(
    body='<p class="text-sm font-medium">Too many attempts. Please wait a few minutes before trying again.</p>',
    type="warning",
)


async def rate_limit_exceeded_handler(request, exc):  # noqa: ANN001
    """Return user-visible HTML for HTMX requests, else use slowapi default."""
    if request.headers.get("HX-Request"):
        return HTMLResponse(RATE_LIMIT_HTML, status_code=429)
    return _rate_limit_exceeded_handler(request, exc)


def _make_lifespan(mcp_runtime_settings: Settings):
    """Lifespan factory so MCP mount and session manager follow the same ``Settings``."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        disable_langsmith_tracing()
        setup_logging()
        logger.info(
            f"Starting {mcp_runtime_settings.app_name} v{mcp_runtime_settings.version} "
            f"{mcp_runtime_settings.startup_deploy_label}"
        )
        logger.info(f"Environment: {settings.environment}")
        logger.info(
            f"AI generation: {'enabled' if settings.smeme_ai_generation_enabled else 'disabled'}"
        )
        logger.info(f"Clerk auth: {'configured' if settings.clerk_enabled else 'not configured'}")
        logger.info(f"BASE_URL: {settings.effective_base_url}")

        async with AsyncExitStack() as stack:
            if mcp_runtime_settings.mcp_enabled:
                from smeme.mcp.reasoning_fastmcp import mcp_lifespan, validate_mcp_startup_config

                validate_mcp_startup_config(mcp_runtime_settings)
                await stack.enter_async_context(mcp_lifespan())
                logger.info(
                    f"MCP Streamable HTTP enabled at {mcp_runtime_settings.effective_base_url.rstrip('/')}"
                    f"{mcp_runtime_settings.mcp_http_path} (see docs/guides/dr3-mcp-oauth-authoritative-sources.md)"
                )

            maintenance_stop_event: asyncio.Event | None = None
            maintenance_task: asyncio.Task[None] | None = None

            if settings.smeme_ai_generation_enabled:
                try:
                    from smeme.decision_tree.generation.agentic.checkpointer import checkpointer_manager
                    from smeme.decision_tree.generation.agentic.maintenance import (
                        periodic_maintenance_loop,
                        run_startup_cleanup,
                    )

                    await checkpointer_manager.initialize()
                    await run_startup_cleanup()
                    maintenance_stop_event = asyncio.Event()
                    maintenance_task = asyncio.create_task(
                        periodic_maintenance_loop(maintenance_stop_event)
                    )
                except Exception as e:
                    logger.error(f"Failed to initialize checkpointer: {e}", exc_info=True)
                    raise

            try:
                yield
            finally:
                logger.info("Shutting down application")
                if maintenance_stop_event is not None:
                    maintenance_stop_event.set()
                if maintenance_task is not None:
                    maintenance_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await maintenance_task
                if settings.smeme_ai_generation_enabled:
                    try:
                        from smeme.decision_tree.generation.agentic.checkpointer import checkpointer_manager

                        await checkpointer_manager.shutdown()
                    except Exception:
                        pass

    return lifespan


def create_core_app(
    *,
    _register_settings: Settings | None = None,
    include_product_root: bool = True,
) -> FastAPI:
    """Create the Core product FastAPI app (no SAAS-ONLY routers).

    ``_register_settings`` is optional (tests): if set, MCP discovery routes use it instead of
    the process-global ``settings`` snapshot.

    ``include_product_root``: when True (standalone Core), ``GET /`` redirects to the dashboard.
    SaaS composition sets this False so the marketing landing owns ``/``.
    """
    from smeme.billing.providers import CORE_QUOTA_POLICY

    reg = _register_settings or settings
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="SMEme Core — decision-tree authoring and logical analysis (MCP)",
        debug=settings.debug,
        lifespan=_make_lifespan(reg),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )
    app.state.mcp_enabled = reg.mcp_enabled
    app.state.mcp_http_path = reg.mcp_http_path
    app.state.smeme_distro = "core"
    app.state.quota_policy = CORE_QUOTA_POLICY

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ClerkBrowserSyncContextMiddleware)
    app.add_middleware(HTMXLoginRedirectMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(CsrfProtectionMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    if reg.mcp_enabled:
        app.add_middleware(McpMountPathNormalizeMiddleware, mcp_path=reg.mcp_http_path)
        app.add_middleware(McpInboundAuthTelemetryMiddleware)
        app.add_middleware(
            McpTransportRateLimitMiddleware,
            mcp_path=reg.mcp_http_path,
            limit_ip_per_minute=reg.mcp_transport_rate_limit_per_ip_per_minute,
            limit_sub_per_minute=reg.mcp_transport_rate_limit_per_sub_per_minute,
            clerk_oauth_issuer=reg.clerk_oauth_issuer,
        )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    if not settings.debug:
        app.add_exception_handler(Exception, generic_error_handler)

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(reasoning_preflight_router, prefix="/api/v1")
    app.include_router(docs_router)
    app.include_router(auth_router, prefix="/auth")
    app.include_router(clerk_webhook_router)
    app.include_router(profile_router)
    app.include_router(decision_tree_router)
    app.include_router(decision_tree_viewer_router)
    app.include_router(decision_tree_editor_router)

    if settings.smeme_ai_generation_enabled:
        from smeme.decision_tree.generation.agentic.routes import router as agentic_router

        app.include_router(agentic_router)

    _static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    register_mcp_oauth_discovery_routes(app, reg)
    if reg.mcp_enabled:
        mount_mcp_on_app(app, reg)

    _favicon_svg = _static_dir / "favicon.svg"

    if include_product_root:

        @app.get("/", include_in_schema=False)
        async def core_root():
            """Core has no marketing landing — send browsers to the product dashboard entry."""
            return RedirectResponse(url="/decision-trees/dashboard", status_code=302)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(_favicon_svg, media_type="image/svg+xml")

    return app
