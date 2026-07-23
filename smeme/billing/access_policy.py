"""Core access / workflow lifecycle policy (provider-neutral).

KEEP for public ``smeme`` (D022). Stripe adapters and SaaS pick-flow routes live
elsewhere; Core must not import ``stripe_sync``, ``subscription_cancel``, or
``downgrade``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.billing.tiers import TIER_LIMITS, BillingTier
from smeme.core.config import settings
from smeme.core.models import DecisionTree, User

CHOOSE_WORKFLOW_CONFIRM_PHRASE = "keep these decision trees live"

# Prefix paths allowed while workflow_pick_required (see sprint doc).
# ``/billing/*`` prefixes matter only when SaaS mounts billing routes.
_PICK_REQUIRED_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/billing/choose-workflow",
    "/billing/subscribe",
    "/billing/portal",
    "/billing/upgrade-modal",
    "/billing/webhook",
    "/billing/cancellation-explainer",
    "/auth/profile",
    "/auth/logout",
    "/docs/",
    "/legal/",
    "/changelog",
    "/auth/delete-account",
    "/static/",
    "/health",
    "/.well-known/",
    "/downloads/",
)

_PICK_REQUIRED_ALLOWED_EXACT: frozenset[str] = frozenset(
    {
        "/health",
        "/changelog",
        "/mcp",
    }
)


def free_max_workflows() -> int:
    return TIER_LIMITS[BillingTier.FREE].max_workflows


def path_allowed_during_workflow_pick(path: str) -> bool:
    """Return True when an authenticated request may proceed during pick-required.

    Downloads are always allowed so dashboard rows remain downloadable while the
    picker is open (spec: "Dashboard shows all rows grayed with download enabled").
    """
    if path in _PICK_REQUIRED_ALLOWED_EXACT:
        return True
    if path.endswith("/download"):
        return True
    return any(path.startswith(prefix) for prefix in _PICK_REQUIRED_ALLOWED_PREFIXES)


def is_workflow_pick_required(user: User) -> bool:
    from smeme.billing.providers import hosted_quota_enforcement_enabled

    return hosted_quota_enforcement_enabled() and bool(
        getattr(user, "workflow_pick_required", False)
    )


def is_decision_tree_live(user: User, decision_tree: DecisionTree) -> bool:
    """Whether the root workflow has full Free/Pro access (not dormant / limbo)."""
    from smeme.billing.providers import hosted_quota_enforcement_enabled

    if not hosted_quota_enforcement_enabled():
        return True
    if user.is_premium:
        return True
    if user.workflow_pick_required:
        return False
    if decision_tree.billing_dormant:
        return False
    live_id = user.live_workflow_root_id
    if live_id is not None:
        return decision_tree.id == live_id
    return True


def is_decision_tree_dashboard_grayed(user: User, decision_tree: DecisionTree) -> bool:
    """Dashboard row styling: pick limbo or dormant."""
    from smeme.billing.providers import hosted_quota_enforcement_enabled

    if not hosted_quota_enforcement_enabled():
        return False
    if is_workflow_pick_required(user):
        return True
    return bool(not user.is_premium and decision_tree.billing_dormant)


def raise_if_workflow_edit_denied(user: User, decision_tree: DecisionTree) -> None:
    """Block editor, deploy, MCP discoverability toggles on non-live workflows."""
    if is_workflow_pick_required(user):
        raise HTTPException(
            status_code=403,
            detail=(
                "Your Pro subscription ended with multiple decision trees. "
                "Choose which decision tree to keep live at /billing/choose-workflow before editing."
            ),
        )
    if not is_decision_tree_live(user, decision_tree):
        raise HTTPException(
            status_code=403,
            detail=(
                "This decision tree is dormant on your Free plan (download only). "
                "Upgrade to Pro to edit it again, or permanently delete it."
            ),
        )


def mcp_account_downgrade_pending_response(*, user: User) -> str:
    from smeme.mcp.tool_contract import tool_error_json

    base = settings.effective_base_url.rstrip("/")
    return tool_error_json(
        "account_downgrade_pending",
        (
            "Your Pro subscription ended with multiple decision trees. "
            "Choose which decision tree to keep live before using MCP tools."
        ),
        choose_workflow_url=f"{base}/billing/choose-workflow",
    )


def mcp_workflow_dormant_response() -> str:
    from smeme.mcp.tool_contract import tool_error_json

    return tool_error_json(
        "account_downgrade_pending",
        (
            "This decision tree is dormant on your Free plan (download only). "
            "Upgrade to Pro to use MCP tools on it again."
        ),
    )


async def count_active_root_workflows(db: AsyncSession, user_id: UUID) -> int:
    result = await db.execute(
        select(func.count(DecisionTree.id)).where(
            DecisionTree.author_id == user_id,
            DecisionTree.is_current.is_(True),
            DecisionTree.is_archived.is_(False),
            DecisionTree.parent_decision_tree_id.is_(None),
        )
    )
    return int(result.scalar() or 0)


async def count_live_root_workflows(db: AsyncSession, user: User) -> int:
    """Inventory cap counter: Pro = all active roots; Free = non-dormant live roots."""
    from smeme.billing.providers import hosted_quota_enforcement_enabled

    conditions = [
        DecisionTree.author_id == user.id,
        DecisionTree.is_current.is_(True),
        DecisionTree.is_archived.is_(False),
        DecisionTree.parent_decision_tree_id.is_(None),
    ]
    if hosted_quota_enforcement_enabled() and not user.is_premium:
        conditions.append(DecisionTree.billing_dormant.is_(False))
    result = await db.execute(select(func.count(DecisionTree.id)).where(*conditions))
    return int(result.scalar() or 0)


async def _fetch_active_roots(db: AsyncSession, user_id: UUID) -> list[DecisionTree]:
    result = await db.execute(
        select(DecisionTree)
        .where(
            DecisionTree.author_id == user_id,
            DecisionTree.is_current.is_(True),
            DecisionTree.is_archived.is_(False),
            DecisionTree.parent_decision_tree_id.is_(None),
        )
        .order_by(DecisionTree.updated_at.desc())
    )
    return list(result.scalars().all())


def clear_subscription_periods(user: User) -> None:
    """Clear local subscription period fields (no payment-provider I/O)."""
    user.subscription_period_start = None
    user.subscription_period_end = None


async def clear_downgrade_state_on_upgrade(db: AsyncSession, user: User) -> None:
    """Re-upgrade: all workflows live again; clear pick / cancel flags."""
    user.subscription_cancel_at_period_end = False
    user.cancellation_explainer_pending = False
    user.cancellation_explainer_acknowledged_at = None
    user.workflow_pick_required = False
    user.live_workflow_root_id = None
    user.free_usage_epoch = None
    await db.execute(
        update(DecisionTree).where(DecisionTree.author_id == user.id).values(billing_dormant=False)
    )
    db.add(user)


async def resolve_subscription_ended(db: AsyncSession, user: User) -> None:
    """Moment B: subscription no longer Pro — pick live workflow or auto-resolve."""
    user.subscription_cancel_at_period_end = False
    user.cancellation_explainer_pending = False
    clear_subscription_periods(user)

    roots = await _fetch_active_roots(db, user.id)
    now = datetime.now(UTC)

    if len(roots) == 0:
        user.workflow_pick_required = False
        user.live_workflow_root_id = None
        user.free_usage_epoch = now
        db.add(user)
        return

    max_live = free_max_workflows()
    if len(roots) <= max_live:
        for root in roots:
            root.billing_dormant = False
            db.add(root)
        user.workflow_pick_required = False
        user.live_workflow_root_id = roots[0].id if len(roots) == 1 else None
        user.free_usage_epoch = now
        db.add(user)
        return

    user.workflow_pick_required = True
    user.live_workflow_root_id = None
    db.add(user)


async def apply_workflow_pick(
    db: AsyncSession,
    user: User,
    chosen_root_ids: list[UUID],
) -> None:
    """User confirmed which workflows stay live on Free; others become dormant."""
    roots = await _fetch_active_roots(db, user.id)
    root_ids = {r.id for r in roots}
    chosen = set(chosen_root_ids)
    if not chosen or not chosen.issubset(root_ids):
        raise HTTPException(status_code=400, detail="Selected decision tree not found.")
    max_live = free_max_workflows()
    if len(chosen) != max_live:
        raise HTTPException(
            status_code=400,
            detail=f"Select exactly {max_live} decision trees to keep live on Free.",
        )

    now = datetime.now(UTC)
    for root in roots:
        root.billing_dormant = root.id not in chosen
        db.add(root)

    user.live_workflow_root_id = next(iter(chosen)) if len(chosen) == 1 else None
    user.workflow_pick_required = False
    user.free_usage_epoch = now
    db.add(user)


def dismiss_cancellation_explainer(user: User) -> None:
    user.cancellation_explainer_pending = False
    user.cancellation_explainer_acknowledged_at = datetime.now(UTC)


def pro_ending_banner_text(user: User, *, active_root_count: int) -> str | None:
    """Pre-expiry scary strip (option C)."""
    from smeme.billing.providers import hosted_quota_enforcement_enabled

    if not hosted_quota_enforcement_enabled():
        return None
    if not user.subscription_cancel_at_period_end or not user.is_premium:
        return None
    end = user.subscription_period_end
    if end is None:
        max_live = free_max_workflows()
        return f"Pro ends soon — renew or choose {max_live} live decision trees on Free."
    end_local = end.astimezone(UTC)
    date_label = end_local.strftime("%b %d")
    max_live = free_max_workflows()
    if active_root_count <= max_live:
        return f"Pro ends {date_label} — renew to keep higher limits."
    return (
        f"Pro ends {date_label} — {active_root_count} decision trees; "
        f"Free allows {max_live} live (others become download-only)."
    )


def billing_lifecycle_context(
    user: User,
    *,
    active_root_count: int,
) -> dict[str, Any]:
    from smeme.billing.providers import hosted_quota_enforcement_enabled

    if not hosted_quota_enforcement_enabled():
        return {
            "show_cancellation_explainer": False,
            "pro_ending_banner": None,
            "workflow_pick_required": False,
            "subscription_period_end_label": None,
        }
    return {
        "show_cancellation_explainer": bool(user.cancellation_explainer_pending),
        "pro_ending_banner": pro_ending_banner_text(user, active_root_count=active_root_count),
        "workflow_pick_required": user.workflow_pick_required,
        "subscription_period_end_label": (
            user.subscription_period_end.astimezone(UTC).strftime("%b %d, %Y")
            if user.subscription_period_end
            else None
        ),
    }


__all__ = [
    "CHOOSE_WORKFLOW_CONFIRM_PHRASE",
    "apply_workflow_pick",
    "billing_lifecycle_context",
    "clear_downgrade_state_on_upgrade",
    "clear_subscription_periods",
    "count_active_root_workflows",
    "count_live_root_workflows",
    "dismiss_cancellation_explainer",
    "free_max_workflows",
    "is_decision_tree_dashboard_grayed",
    "is_decision_tree_live",
    "is_workflow_pick_required",
    "mcp_account_downgrade_pending_response",
    "mcp_workflow_dormant_response",
    "path_allowed_during_workflow_pick",
    "pro_ending_banner_text",
    "raise_if_workflow_edit_denied",
    "resolve_subscription_ended",
]
