"""Authentication routes."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from smeme.auth.clerk_auth import clear_clerk_browser_cookies
from smeme.auth.models import UserRead, UserUpdate
from smeme.auth.users import current_active_user
from smeme.core.callout_html import render_callout_html
from smeme.core.config import settings
from smeme.core.dependencies import AsyncSessionDep, CurrentUser, UserManagerDep
from smeme.core.logging import get_logger
from smeme.core.models import User
from smeme.core.rate_limiting import RATE_LIMIT_LOGIN, RATE_LIMIT_REGISTER, limiter
from smeme.core.templates import templates

logger = get_logger(__name__)

# Create authentication routes
auth_router = APIRouter()

# ---------------------------------------------------------------------------
# Front-end auth pages (Tailwind/HTMX templates)
# ---------------------------------------------------------------------------


@auth_router.get("/login", tags=["auth"], include_in_schema=False)
async def login_page(request: Request, db: AsyncSessionDep, user_manager: UserManagerDep):
    """Serve the login page.

    Check for an active Clerk session first. If the user is already
    authenticated, redirect straight to the dashboard.

    Exception: skip the session check when ``smeme_clerk_logout=1`` is present.
    That parameter signals a logout flow — the browser-sync script must run
    ``Clerk.signOut()`` on this page load.  Redirecting to dashboard before
    that happens would silently abort the logout.
    """
    if not request.query_params.get("smeme_clerk_logout"):
        from smeme.auth.clerk_auth import clerk_authenticated_user

        user = await clerk_authenticated_user(request, db, user_manager)
        if user is not None:
            return RedirectResponse(url="/decision-trees/dashboard", status_code=302)

    return templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "clerk_sign_in_url": settings.clerk_login_redirect_url(),
            "clerk_sign_up_url": settings.clerk_register_redirect_url(),
        },
    )


@auth_router.get("/clerk-callback", tags=["auth"], include_in_schema=False)
async def clerk_callback(
    request: Request,
    db: AsyncSessionDep,
    user_manager: UserManagerDep,
):
    """Post-sign-in/sign-up landing page for Clerk.

    Configure Clerk Dashboard → Paths → "After Sign-In URL" and
    "After Sign-Up URL" to point here (relative path: ``/auth/clerk-callback``).

    Flow:
    1. Clerk authenticates the user and redirects here.
    2. We validate the session JWT and resolve/create the local User (D026 gates
       for *new* create/link: verified primary email + legal acceptance).
    3. On success, redirect to the dashboard.
    4. On gate failure, show a recovery page (not a silent anonymous session).
    5. On missing server session (cookie lag), serve client sync HTML.
    """
    from smeme.auth.clerk_auth import ProvisionFailureReason, clerk_authenticated_provision

    outcome = await clerk_authenticated_provision(request, db, user_manager)
    if outcome.user is not None:
        logger.info(
            "Clerk callback: authenticated user %s (%s)", outcome.user.id, outcome.user.email
        )
        return RedirectResponse(url="/decision-trees/dashboard", status_code=302)

    if outcome.failure_reason is not None:
        logger.warning(
            "Clerk callback: provision blocked auth_reason=%s",
            outcome.failure_reason.value,
        )
        return templates.TemplateResponse(
            "auth/clerk_provision_blocked.html",
            {
                "request": request,
                "auth_reason": outcome.failure_reason.value,
                "terms_url": (settings.legal_terms_url or "").strip() or "/legal/terms",
                "privacy_url": (settings.legal_privacy_url or "").strip() or "/legal/privacy",
                "sign_in_url": settings.clerk_login_redirect_url(),
                "sign_up_url": settings.clerk_register_redirect_url(),
                "is_legal_config": (
                    outcome.failure_reason == ProvisionFailureReason.LEGAL_CONFIG_INCOMPLETE
                ),
            },
            status_code=403,
        )

    # Client may have Clerk.session before __session is visible to the server (modal
    # sign-in + custom FAPI domain). Serve HTML so clerk-js can sync cookies here,
    # then reload this URL once (see _clerk_browser_sync.html callback branch).
    logger.warning("Clerk callback: no server session yet — serving client sync page")
    return templates.TemplateResponse(
        "auth/clerk_callback_sync.html",
        {"request": request},
    )


@auth_router.post("/login", tags=["auth"], include_in_schema=False)
@limiter.limit(RATE_LIMIT_LOGIN)
async def login_submit(request: Request):
    """Handle login form — auth is managed by Clerk."""
    url = settings.clerk_login_redirect_url()
    return HTMLResponse(
        render_callout_html(
            body=f'<p class="text-sm">Sign in with Clerk: <a href="{url}" class="underline font-medium">Continue</a></p>',
            type="warning",
        )
    )


@auth_router.get("/register", tags=["auth"], include_in_schema=False)
async def register_page(request: Request, db: AsyncSessionDep, user_manager: UserManagerDep):
    """Serve the register page. Already-authenticated users are redirected to the dashboard."""
    from smeme.auth.clerk_auth import clerk_authenticated_user

    user = await clerk_authenticated_user(request, db, user_manager)
    if user is not None:
        return RedirectResponse(url="/decision-trees/dashboard", status_code=302)

    return templates.TemplateResponse(
        "auth/register.html",
        {
            "request": request,
            "clerk_sign_up_url": settings.clerk_register_redirect_url(),
            "clerk_sign_in_url": settings.clerk_login_redirect_url(),
        },
    )


@auth_router.post("/register", tags=["auth"], include_in_schema=False)
@limiter.limit(RATE_LIMIT_REGISTER)
async def register_submit(request: Request):
    """Handle register form — registration is managed by Clerk."""
    url = settings.clerk_register_redirect_url()
    return HTMLResponse(
        render_callout_html(
            body=f'<p class="text-sm">Create your account with Clerk: <a href="{url}" class="underline font-medium">Continue</a></p>',
            type="warning",
        )
    )


@auth_router.post("/logout", tags=["auth"], include_in_schema=False)
async def logout(response: Response):
    """Clear Clerk auth cookies and redirect to login.

    POST-only so CSRF middleware protects against cross-origin forced logout (L-02).
    Same-origin form posts (or requests with a valid CSRF header) are accepted.

    Server-side cookie deletion is not sufficient on its own — ``clerk-js`` stores
    session state in IndexedDB / localStorage and rehydrates it on ``Clerk.load()``.
    The full two-step handshake:

    1. **Server side** (this function): delete ``__session`` / ``__client_uat`` /
       ``clerk_active_context`` cookies and redirect to
       ``/auth/login?smeme_clerk_logout=1``.
    2. **Client side** (``_clerk_browser_sync.html``): sees ``smeme_clerk_logout=1``,
       calls ``await Clerk.signOut({ redirectUrl: ... })`` to invalidate Clerk's own
       client storage, then strips the query param.

    The ``login_page`` route MUST skip its Clerk session pre-check when
    ``smeme_clerk_logout=1`` is present — otherwise the server redirects to the
    dashboard before ``Clerk.signOut()`` can execute, silently aborting the logout.

    If ``CLERK_SIGN_OUT_URL`` is configured, we redirect there instead (e.g. Clerk's
    hosted sign-out page), bypassing the two-step flow entirely.
    """
    external = settings.clerk_external_logout_url()
    redirect_to = external if external else "/auth/login?smeme_clerk_logout=1"
    response = RedirectResponse(url=redirect_to, status_code=303)  # 303 prevents back caching

    clear_clerk_browser_cookies(response)

    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return response


# Custom profile routes (mounted under /auth in main.py)
profile_router = APIRouter(prefix="/auth/profile", tags=["profile"])


@profile_router.get("/me", response_model=UserRead)
async def get_my_profile(user: User = Depends(current_active_user)) -> UserRead:
    """Get current user's profile."""
    return UserRead(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        is_verified=user.is_verified,
        username=user.username,
        bio=user.bio,
        website_url=user.website_url,
        linkedin_url=user.linkedin_url,
        credential_level=user.credential_level,
        credential_details=user.credential_details,
        show_credential_details=user.show_credential_details,
        verified_at=user.verified_at,
        governance_role=user.governance_role,
        is_premium=user.is_premium,
        creator_page_public=user.creator_page_public,
    )


@profile_router.put("/me")
async def update_my_profile(
    request: Request,
    profile_update: UserUpdate,
    user: CurrentUser,
    db: AsyncSessionDep,
):
    """Update current user's profile (SMEme-owned fields only). Email is managed by Clerk."""
    from fastapi.responses import HTMLResponse

    # Email is managed by Clerk — reject any attempt to CHANGE it here
    if profile_update.email and profile_update.email != user.email:
        msg = (
            "Email is managed in Clerk. Use 'Manage account in Clerk' on your profile "
            "to update your email, add an optional password, or edit your name."
        )
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                render_callout_html(
                    body=f'<p class="text-sm">{msg}</p>', type="error", variant="compact"
                ),
                status_code=200,
            )
        raise HTTPException(status_code=400, detail=msg)

    if profile_update.username is not None and profile_update.username != user.username:
        msg = (
            "Public creator handles are not editable yet. SMEme uses your sign-in email as the "
            "internal identifier until Business author profiles launch."
        )
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                render_callout_html(
                    body=f'<p class="text-sm">{msg}</p>', type="error", variant="compact"
                ),
                status_code=200,
            )
        raise HTTPException(status_code=400, detail=msg)

    # Creator profile fields (optional API updates; no marketplace UI)
    if profile_update.bio is not None:
        user.bio = profile_update.bio
    if profile_update.website_url is not None:
        user.website_url = profile_update.website_url
    if profile_update.linkedin_url is not None:
        user.linkedin_url = profile_update.linkedin_url
    if profile_update.credential_details is not None:
        user.credential_details = profile_update.credential_details
        # Auto-promote to self_attested when credential details are provided
        if profile_update.credential_details.strip() and user.credential_level == "unverified":
            user.credential_level = "self_attested"
    if profile_update.show_credential_details is not None:
        user.show_credential_details = profile_update.show_credential_details
    if profile_update.creator_page_public is not None:
        user.creator_page_public = profile_update.creator_page_public

    db.add(user)
    await db.commit()
    await db.refresh(user)

    # If this is an HTMX request, return a small HTML fragment for inline feedback
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            '<div class="bg-success-50 border border-success-200 text-success-800 px-3 py-2 rounded text-sm">'
            "Profile updated successfully."
            "</div>"
        )

    # Fallback for non-HTMX/API clients: return JSON payload
    return UserRead(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        is_verified=user.is_verified,
        username=user.username,
        bio=user.bio,
        website_url=user.website_url,
        linkedin_url=user.linkedin_url,
        credential_level=user.credential_level,
        credential_details=user.credential_details,
        show_credential_details=user.show_credential_details,
        verified_at=user.verified_at,
        governance_role=user.governance_role,
        is_premium=user.is_premium,
        creator_page_public=user.creator_page_public,
    )


@profile_router.get("/dashboard", include_in_schema=False)
async def profile_dashboard(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
):
    """Serve the profile dashboard page."""
    from smeme.billing.access_policy import billing_lifecycle_context, count_active_root_workflows
    from smeme.billing.providers import hosted_quota_enforcement_enabled
    from smeme.billing.usage import build_usage_summary

    usage_summary = await build_usage_summary(db, user)
    active_root_count = await count_active_root_workflows(db, user.id)
    billing_ctx = billing_lifecycle_context(user, active_root_count=active_root_count)
    billing_unlinked = request.query_params.get("billing") == "unlinked"
    return templates.TemplateResponse(
        "auth/profile.html",
        {
            "request": request,
            "user": user,
            "active_page": "profile",
            "clerk_account_portal_url": settings.clerk_account_portal_url_with_redirect(
                "/auth/profile/dashboard"
            ),
            "stripe_configured": settings.stripe_configured,
            "quota_enforcement_enabled": hosted_quota_enforcement_enabled(),
            "usage_summary": usage_summary,
            "billing_unlinked": billing_unlinked,
            **billing_ctx,
        },
    )


@profile_router.get("/close-modal", include_in_schema=False)
async def close_modal():
    """Return an empty fragment to allow HTMX to clear the modal container."""
    from fastapi.responses import HTMLResponse

    return HTMLResponse("")


@auth_router.get("/account-deleted", tags=["auth"], include_in_schema=False)
async def account_deleted_page(request: Request):
    """Static confirmation after account closure."""
    return templates.TemplateResponse(
        "auth/account_deleted.html",
        {"request": request, "show_nav": False},
    )


@profile_router.get("/delete-account-confirm", include_in_schema=False)
async def delete_account_confirm_step1(request: Request, user: CurrentUser):
    """Step 1: warn about permanent account deletion."""
    return templates.TemplateResponse(
        "auth/_delete_account_step1.html",
        {"request": request, "user": user},
    )


@profile_router.get("/delete-account-confirm-phrase", include_in_schema=False)
async def delete_account_confirm_step2(request: Request, user: CurrentUser):
    """Step 2: typed confirmation phrase."""
    from smeme.auth.account_delete import DELETE_ACCOUNT_CONFIRM_PHRASE

    return templates.TemplateResponse(
        "auth/_delete_account_step2.html",
        {
            "request": request,
            "confirm_phrase": DELETE_ACCOUNT_CONFIRM_PHRASE,
        },
    )


@profile_router.post("/delete-account", include_in_schema=False)
async def delete_account_submit(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    confirm_phrase: str = Form(...),
):
    """Permanently delete the signed-in user's account and owned data."""
    from smeme.auth.account_delete import (
        DELETE_ACCOUNT_CONFIRM_PHRASE,
        AccountDeletionLockError,
        AccountDeletionPurgeError,
        DeleteAccountStatus,
        delete_user_account,
        phrase_matches,
    )

    if not phrase_matches(confirm_phrase):
        return templates.TemplateResponse(
            "auth/_delete_account_step2.html",
            {
                "request": request,
                "confirm_phrase": DELETE_ACCOUNT_CONFIRM_PHRASE,
                "error_message": f'Type "{DELETE_ACCOUNT_CONFIRM_PHRASE}" to confirm.',
            },
            status_code=400,
        )

    try:
        result = await delete_user_account(db, user, actor="profile")
    except AccountDeletionLockError:
        return templates.TemplateResponse(
            "auth/_delete_account_step2.html",
            {
                "request": request,
                "confirm_phrase": DELETE_ACCOUNT_CONFIRM_PHRASE,
                "error_message": "Deletion already in progress. Wait a moment and try again.",
            },
            status_code=409,
        )
    except AccountDeletionPurgeError:
        raise HTTPException(
            status_code=500,
            detail="Account deletion failed. Please try again or contact support.",
        ) from None

    redirect_url = (
        "/auth/account-deleted"
        if result.status == DeleteAccountStatus.ALREADY_DELETED
        else "/auth/login?smeme_clerk_logout=1"
    )
    if request.headers.get("HX-Request"):
        response = HTMLResponse(status_code=200)
        response.headers["HX-Redirect"] = redirect_url
        if "smeme_clerk_logout=1" in redirect_url:
            clear_clerk_browser_cookies(response)
        return response

    response = RedirectResponse(url=redirect_url, status_code=303)
    if "smeme_clerk_logout=1" in redirect_url:
        clear_clerk_browser_cookies(response)
    return response
