"""Public creator docs (/docs/*); delete-account remains authenticated."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from smeme.core.config import settings
from smeme.core.dependencies import CurrentUser, OptionalUser
from smeme.core.templates import templates
from smeme.mcp.urls import mcp_connect_template_context

router = APIRouter(prefix="/docs", tags=["docs"])

_PUBLIC_CACHE = "public, max-age=300"
_PRIVATE_NO_STORE = "no-cache, no-store, must-revalidate, private"


def _no_store_html(response: HTMLResponse) -> HTMLResponse:
    response.headers["Cache-Control"] = _PRIVATE_NO_STORE
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _public_docs_html(response: HTMLResponse, *, signed_in: bool) -> HTMLResponse:
    """Cache policy: anonymous pages may be public; signed-in HTML stays private."""
    response.headers["Vary"] = "Cookie, Authorization"
    if signed_in:
        response.headers["Cache-Control"] = _PRIVATE_NO_STORE
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    else:
        response.headers["Cache-Control"] = _PUBLIC_CACHE
    return response


def _docs_response(
    request: Request,
    template: str,
    *,
    user: object | None,
    active_page: str,
    docs_section: str,
    **extra: object,
) -> HTMLResponse:
    response = templates.TemplateResponse(
        template,
        {
            "request": request,
            "user": user,
            "active_page": active_page,
            "docs_section": docs_section,
            **extra,
        },
    )
    return _public_docs_html(response, signed_in=user is not None)


@router.get("", response_class=HTMLResponse)
async def docs_index(request: Request, user: OptionalUser):
    """Hub for public creator docs."""
    return _docs_response(
        request,
        "docs/index.html",
        user=user,
        active_page="docs",
        docs_section="index",
    )


@router.get("/quick-start", response_class=HTMLResponse)
async def docs_quick_start(request: Request, user: OptionalUser):
    """Copy-paste prompts: connect, find a procedure, and build a first tree."""
    return _docs_response(
        request,
        "docs/quick_start.html",
        user=user,
        active_page="docs_quick_start",
        docs_section="quick_start",
        mcp_enabled=settings.mcp_enabled,
        **mcp_connect_template_context(settings),
    )


@router.get("/run-a-tree", response_class=HTMLResponse)
async def docs_run_a_tree(request: Request, user: OptionalUser):
    """Copy-paste prompts for running a deployed tree on a matter."""
    return _docs_response(
        request,
        "docs/run_a_tree.html",
        user=user,
        active_page="docs_run_a_tree",
        docs_section="run_a_tree",
    )


@router.get("/ask-more", response_class=HTMLResponse)
async def docs_ask_more(request: Request, user: OptionalUser):
    """Copy-paste prompts for what follows, facts that decided it, and what-if."""
    return _docs_response(
        request,
        "docs/ask_more.html",
        user=user,
        active_page="docs_ask_more",
        docs_section="ask_more",
    )


@router.get("/introduction", response_class=HTMLResponse)
async def docs_introduction(request: Request, user: OptionalUser):
    """Building decision trees — create, edit, save, and version."""
    return _docs_response(
        request,
        "docs/introduction.html",
        user=user,
        active_page="docs_introduction",
        docs_section="introduction",
    )


@router.get("/download-workflow", response_class=HTMLResponse)
async def docs_download_workflow(request: Request, user: OptionalUser):
    """Download your decision tree — export the saved graph as JSON."""
    return _docs_response(
        request,
        "docs/download_workflow.html",
        user=user,
        active_page="docs_download_workflow",
        docs_section="download_workflow",
    )


@router.get("/import", response_class=HTMLResponse)
async def docs_import(request: Request, user: OptionalUser):
    """Import a copy — upload a v2 export as a new Hidden draft."""
    return _docs_response(
        request,
        "docs/import.html",
        user=user,
        active_page="docs_import",
        docs_section="import_copy",
    )


@router.get("/plans", response_class=HTMLResponse)
async def docs_plans(request: Request, user: OptionalUser):
    """Plans, tier limits, and usage metering."""
    return _docs_response(
        request,
        "docs/plans.html",
        user=user,
        active_page="docs_plans",
        docs_section="plans",
    )


@router.get("/delete-account", response_class=HTMLResponse)
async def docs_delete_account(request: Request, user: CurrentUser):
    """Permanent account closure — profile flow, confirmation, and data removed."""
    return _no_store_html(
        templates.TemplateResponse(
            "docs/delete_account.html",
            {
                "request": request,
                "user": user,
                "active_page": "docs_delete_account",
                "docs_section": "delete_account",
            },
        )
    )


@router.get("/creator-dashboard", response_class=HTMLResponse)
async def docs_creator_dashboard(request: Request, user: OptionalUser):
    """Deploy, validate and list — preflight checks, Tools column, Listed/Hidden."""
    return _docs_response(
        request,
        "docs/creator_dashboard.html",
        user=user,
        active_page="docs_creator_dashboard",
        docs_section="creator_dashboard",
    )


@router.get("/changelog", response_class=HTMLResponse)
async def docs_changelog(request: Request, user: OptionalUser):
    """Docs version history and change log."""
    return _docs_response(
        request,
        "docs/changelog.html",
        user=user,
        active_page="docs_changelog",
        docs_section="changelog",
    )


@router.get("/langgraph", response_class=HTMLResponse)
async def docs_langgraph(request: Request, user: OptionalUser):
    """Builder front door for the ACME LangGraph technical preview."""
    from smeme.decision_tree.acme_example import ACME_EXAMPLE_DISCLAIMER

    return _docs_response(
        request,
        "docs/langgraph.html",
        user=user,
        active_page="docs_langgraph",
        docs_section="langgraph",
        acme_example_disclaimer=ACME_EXAMPLE_DISCLAIMER,
    )


@router.get("/mcp", response_class=HTMLResponse)
async def docs_mcp(request: Request, user: OptionalUser):
    """Connect your agent (MCP) — connector setup and guidance bootstrap."""
    return _docs_response(
        request,
        "docs/mcp.html",
        user=user,
        active_page="docs_mcp",
        docs_section="mcp",
        mcp_enabled=settings.mcp_enabled,
        **mcp_connect_template_context(settings),
    )
