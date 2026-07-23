"""Quota enforcement helpers.

Core default: **enforcement off**, metering on (D022). Hosted Free/Pro Mode B
caps are activated per request by Cloud middleware via
``hosted_quota_enforcement_scope``. Do not early-return from
``reserve_mcp_quota`` when enforcement is off — that path still inserts the
``reserved`` telemetry row and UUID used by flush.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import User
from smeme.mcp.invocation_telemetry import quota_weight_for_tool
from smeme.mcp.tool_contract import tool_error_json

from .tiers import BillingTier, limits_for_user, tier_display_name, tier_for_user
from .usage import (
    count_active_root_workflows,
    count_live_root_workflows_for_user,
    count_wizard_completions_month,
    resets_at_iso,
    sum_mcp_weighted_month,
)


class QuotaDimension(str, Enum):
    DECISION_TREES = "decision_trees"
    MCP_WEIGHTED = "mcp_weighted"
    WIZARD_COMPLETIONS = "wizard_completions"


@dataclass(frozen=True, slots=True)
class QuotaCheckResult:
    allowed: bool
    used: float
    limit: float | None
    remaining: float | None
    enforced: bool
    dimension: QuotaDimension
    tier: BillingTier
    message: str
    resets_at_iso: str


def _tier_plan_label(tier: BillingTier) -> str:
    name = tier_display_name(tier)
    return f"{name} plan"


def _exceeded_message(
    *,
    tier: BillingTier,
    dimension: QuotaDimension,
    limit: float,
) -> str:
    plan = _tier_plan_label(tier)
    if dimension == QuotaDimension.DECISION_TREES:
        n = int(limit)
        return (
            f"{plan} allows {n} active decision tree{'s' if n != 1 else ''}. "
            "Permanently delete a decision tree, or upgrade to Pro for higher limits."
        )
    if dimension == QuotaDimension.WIZARD_COMPLETIONS:
        n = int(limit)
        return (
            f"{plan} allows {n} AI-assisted decision-tree build{'s' if n != 1 else ''} per month. "
            "Upgrade to Pro for more builds, or wait until your allowance resets."
        )
    return (
        f"{plan} allows {limit:g} MCP tool calls per month. "
        "Upgrade to Pro for a higher allowance, or wait until your allowance resets."
    )


async def check_quota(
    db: AsyncSession,
    user: User,
    dimension: QuotaDimension,
    *,
    projected_add: float = 0.0,
) -> QuotaCheckResult:
    """Return whether ``used + projected_add`` is within the tier cap.

    When hosted Free/Pro enforcement is off (Core default), always allow.
    """
    from smeme.billing.providers import (
        ensure_pro_billing_period,
        hosted_quota_enforcement_enabled,
    )

    enforced = hosted_quota_enforcement_enabled()
    tier = tier_for_user(user)
    resets = resets_at_iso(user=user)

    if enforced:
        await ensure_pro_billing_period(db, user)
    limits = limits_for_user(user) if enforced else None

    if dimension == QuotaDimension.DECISION_TREES:
        if enforced and tier == BillingTier.FREE:
            used = float(await count_live_root_workflows_for_user(db, user))
        else:
            used = float(await count_active_root_workflows(db, user.id))
        limit = float(limits.max_workflows) if limits is not None else None
    elif dimension == QuotaDimension.MCP_WEIGHTED:
        used = await sum_mcp_weighted_month(db, user)
        limit = limits.max_mcp_weighted if limits is not None else None
    elif dimension == QuotaDimension.WIZARD_COMPLETIONS:
        used = float(await count_wizard_completions_month(db, user))
        limit = float(limits.max_wizard_completions) if limits is not None else None
    else:
        msg = f"Unknown quota dimension: {dimension}"
        raise ValueError(msg)

    if limit is None:
        return QuotaCheckResult(
            allowed=True,
            used=used,
            limit=None,
            remaining=None,
            enforced=False,
            dimension=dimension,
            tier=tier,
            message="",
            resets_at_iso=resets,
        )

    projected = used + projected_add
    remaining = max(0.0, limit - used)
    allowed = projected <= limit
    message = "" if allowed else _exceeded_message(tier=tier, dimension=dimension, limit=limit)

    return QuotaCheckResult(
        allowed=allowed,
        used=used,
        limit=limit,
        remaining=remaining,
        enforced=True,
        dimension=dimension,
        tier=tier,
        message=message,
        resets_at_iso=resets,
    )


@dataclass(frozen=True, slots=True)
class WizardStartBlock:
    """Why a new agentic wizard cannot be started."""

    reason: str  # pick_required | in_progress | workflow_cap | wizard_monthly
    title: str
    message: str
    dashboard_href: str
    show_upgrade: bool


async def check_wizard_start_block(
    db: AsyncSession,
    user: User,
    *,
    in_progress_count: int,
) -> WizardStartBlock | None:
    """Return structured block info when a new wizard may not start, else ``None``."""
    from smeme.billing.access_policy import is_workflow_pick_required
    from smeme.billing.providers import hosted_quota_enforcement_enabled

    tier = tier_for_user(user)
    show_upgrade = (
        hosted_quota_enforcement_enabled()
        and tier == BillingTier.FREE
        and not getattr(user, "is_premium", False)
    )

    if is_workflow_pick_required(user):
        return WizardStartBlock(
            reason="pick_required",
            title="Choose a live decision tree first",
            message=(
                "Your Pro subscription ended with multiple decision trees. "
                "Choose which decision tree to keep live before starting a new AI-assisted build."
            ),
            dashboard_href="/billing/choose-workflow",
            show_upgrade=show_upgrade,
        )

    if not hosted_quota_enforcement_enabled():
        return None

    if tier == BillingTier.FREE and in_progress_count >= 1:
        return WizardStartBlock(
            reason="in_progress",
            title="Finish your current build first",
            message=(
                "Your Free plan includes one decision tree at a time. "
                "Resume or abandon the in-progress build on your dashboard before starting another."
            ),
            dashboard_href="/decision-trees/dashboard#in-progress",
            show_upgrade=show_upgrade,
        )

    workflow_quota = await check_quota(db, user, QuotaDimension.DECISION_TREES, projected_add=1.0)
    if not workflow_quota.allowed:
        return WizardStartBlock(
            reason="workflow_cap",
            title="Decision tree limit reached",
            message=workflow_quota.message,
            dashboard_href="/decision-trees/dashboard",
            show_upgrade=show_upgrade,
        )

    wizard_quota = await check_quota(db, user, QuotaDimension.WIZARD_COMPLETIONS, projected_add=1.0)
    if not wizard_quota.allowed:
        from smeme.billing.usage import resets_at_label

        return WizardStartBlock(
            reason="wizard_monthly",
            title="Monthly AI build limit reached",
            message=f"{wizard_quota.message} {resets_at_label(user=user)}.",
            dashboard_href="/decision-trees/dashboard",
            show_upgrade=show_upgrade,
        )

    return None


async def wizard_start_blocked_message(
    db: AsyncSession,
    user: User,
    *,
    in_progress_count: int,
) -> str | None:
    """Return a user-facing message when a new wizard may not be started, else ``None``."""
    block = await check_wizard_start_block(db, user, in_progress_count=in_progress_count)
    return block.message if block else None


async def mcp_quota_denied_response(
    db: AsyncSession,
    user: User,
    tool_name: str,
) -> str | None:
    """If this MCP call would exceed the monthly weighted cap, return tool error JSON."""
    from smeme.billing.access_policy import (
        is_workflow_pick_required,
        mcp_account_downgrade_pending_response,
    )

    if is_workflow_pick_required(user):
        return mcp_account_downgrade_pending_response(user=user)

    weight = quota_weight_for_tool(tool_name)
    if weight <= 0:
        return None
    check = await check_quota(
        db,
        user,
        QuotaDimension.MCP_WEIGHTED,
        projected_add=weight,
    )
    if check.allowed:
        return None
    return tool_error_json(
        "quota_exceeded",
        check.message,
        remaining=check.remaining,
        limit=check.limit,
        resets_at=check.resets_at_iso,
    )


async def reserve_mcp_quota(
    db: AsyncSession,
    user: User,
    tool_name: str,
    *,
    oauth_client_id: str | None = None,
) -> UUID | str:
    """Reserve one quota slot atomically: lock → re-check → INSERT outcome='reserved' → commit.

    Returns the new invocation UUID on success, or tool_error_json on failure.
    Store the UUID on McpInvocationRecorder via ``bind_invocation_id`` so flush()
    UPDATEs the reserved row with real outcome and timing instead of blind INSERT.

    Lock failure returns ``concurrency_limit``, not ``quota_exceeded`` — the user's
    plan allowance is not involved when another call is simply mid-transaction.

    When hosted enforcement is off, cap denial is skipped but the reserved row
    (metering) is still inserted.
    """
    from smeme.billing.access_policy import (
        is_workflow_pick_required,
        mcp_account_downgrade_pending_response,
    )
    from smeme.billing.providers import hosted_quota_enforcement_enabled
    from smeme.mcp.models import McpToolInvocation

    if is_workflow_pick_required(user):
        return mcp_account_downgrade_pending_response(user=user)

    weight = quota_weight_for_tool(tool_name)

    # 1. Try per-user advisory lock (transaction-scoped, non-blocking).
    #    Released automatically at db.commit() / rollback() — no leaked locks.
    lock_key = f"mcp:quota:{user.id}"
    lock_result = await db.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
        {"key": lock_key},
    )
    if not lock_result.scalar():
        # Another MCP call is mid-transaction for this user.  The window is
        # milliseconds; this is not a billing-plan cap hit.
        return tool_error_json(
            "concurrency_limit",
            "Another MCP tool call is being processed for your account. Please retry in a moment.",
        )

    # 2. Re-check quota while holding the lock — skipped when Core enforcement
    #    is off (metering still continues below).
    if hosted_quota_enforcement_enabled():
        check = await check_quota(db, user, QuotaDimension.MCP_WEIGHTED, projected_add=weight)
        if not check.allowed:
            return tool_error_json(
                "quota_exceeded",
                check.message,
                remaining=check.remaining,
                limit=check.limit,
                resets_at=check.resets_at_iso,
            )

    # 3. INSERT reserved row — lock still held.  Row is visible to concurrent
    #    sum() queries after commit, so the slot is counted even if the handler
    #    crashes before flush runs.
    invocation_id = uuid4()
    db.add(
        McpToolInvocation(
            id=invocation_id,
            user_id=user.id,
            tool_name=tool_name,
            outcome="reserved",
            quota_weight=weight,
            oauth_client_id=oauth_client_id,
            duration_ms=0,  # placeholder; flush UPDATE sets the real value
        )
    )
    await db.commit()  # lock released here
    return invocation_id


__all__ = [
    "QuotaCheckResult",
    "QuotaDimension",
    "WizardStartBlock",
    "check_quota",
    "check_wizard_start_block",
    "mcp_quota_denied_response",
    "reserve_mcp_quota",
    "wizard_start_blocked_message",
]
