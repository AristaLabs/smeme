"""Authenticated HTML docs for creators (in-app help)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from smeme.auth.users import current_active_user
from smeme.core.config import settings
from smeme.core.models import User
from smeme.core.templates import templates
from smeme.mcp.urls import mcp_connect_template_context

router = APIRouter(prefix="/docs", tags=["docs"])


def _no_store_html(response: HTMLResponse) -> HTMLResponse:
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@router.get("", response_class=HTMLResponse)
async def docs_index(
    request: Request,
    current_user: Annotated[User, Depends(current_active_user)],
):
    """Hub for authenticated in-app docs."""
    return _no_store_html(
        templates.TemplateResponse(
            "docs/index.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "docs",
                "docs_section": "index",
            },
        )
    )


@router.get("/introduction", response_class=HTMLResponse)
async def docs_introduction(
    request: Request,
    current_user: Annotated[User, Depends(current_active_user)],
):
    """Building workflows — create, edit, save, and version."""
    return _no_store_html(
        templates.TemplateResponse(
            "docs/introduction.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "docs_introduction",
                "docs_section": "introduction",
            },
        )
    )


@router.get("/download-workflow", response_class=HTMLResponse)
async def docs_download_workflow(
    request: Request,
    current_user: Annotated[User, Depends(current_active_user)],
):
    """Download your workflow — export the saved graph as JSON."""
    return _no_store_html(
        templates.TemplateResponse(
            "docs/download_workflow.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "docs_download_workflow",
                "docs_section": "download_workflow",
            },
        )
    )


@router.get("/plans", response_class=HTMLResponse)
async def docs_plans(
    request: Request,
    current_user: Annotated[User, Depends(current_active_user)],
):
    """Plans, tier limits, and usage metering."""
    return _no_store_html(
        templates.TemplateResponse(
            "docs/plans.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "docs_plans",
                "docs_section": "plans",
            },
        )
    )


@router.get("/delete-account", response_class=HTMLResponse)
async def docs_delete_account(
    request: Request,
    current_user: Annotated[User, Depends(current_active_user)],
):
    """Permanent account closure — profile flow, confirmation, and data removed."""
    return _no_store_html(
        templates.TemplateResponse(
            "docs/delete_account.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "docs_delete_account",
                "docs_section": "delete_account",
            },
        )
    )


@router.get("/creator-dashboard", response_class=HTMLResponse)
async def docs_creator_dashboard(
    request: Request,
    current_user: Annotated[User, Depends(current_active_user)],
):
    """Deploy, validate and list — preflight checks, Tools column, Listed/Hidden."""
    return _no_store_html(
        templates.TemplateResponse(
            "docs/creator_dashboard.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "docs_creator_dashboard",
                "docs_section": "creator_dashboard",
            },
        )
    )


@router.get("/changelog", response_class=HTMLResponse)
async def docs_changelog(
    request: Request,
    current_user: Annotated[User, Depends(current_active_user)],
):
    """Docs version history and change log."""
    return _no_store_html(
        templates.TemplateResponse(
            "docs/changelog.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "docs_changelog",
                "docs_section": "changelog",
            },
        )
    )


@router.get("/mcp", response_class=HTMLResponse)
async def docs_mcp(
    request: Request,
    current_user: Annotated[User, Depends(current_active_user)],
):
    """Connect your agent (MCP) — connector setup and guidance bootstrap."""
    return _no_store_html(
        templates.TemplateResponse(
            "docs/mcp.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "docs_mcp",
                "docs_section": "mcp",
                "mcp_enabled": settings.mcp_enabled,
                **mcp_connect_template_context(settings),
            },
        )
    )
