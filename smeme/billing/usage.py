"""Monthly usage aggregates for billing quotas and UI meters."""

from __future__ import annotations

import calendar
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import User
from smeme.mcp.models import McpToolInvocation
from smeme.qnr.generation.agentic.telemetry import WIZARD_SUCCESS_STATUSES
from smeme.qnr.models import WizardGenerationEvent

from .access_policy import count_active_root_workflows, count_live_root_workflows
from .tiers import limits_for_user, tier_display_name, tier_for_user

logger = logging.getLogger(__name__)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc_month_window(
    *,
    at: datetime | None = None,
) -> tuple[datetime, datetime, datetime]:
    """Return (month_start, month_end_exclusive, next_month_start) in UTC.

    Kept as a utility; Free tier now uses ``signup_anniversary_window`` instead.
    """
    now = at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1)
    return month_start, next_month_start, next_month_start


def _anniversary_in_month(year: int, month: int, signup_day: int) -> datetime:
    """Midnight UTC on the anniversary day clamped to the month's actual length.

    Handles months shorter than the signup day (e.g. Jan-31 signup → Feb-28 boundary).
    """
    last_day = calendar.monthrange(year, month)[1]
    return datetime(year, month, min(signup_day, last_day), 0, 0, 0, tzinfo=UTC)


def signup_anniversary_window(
    created_at: datetime,
    *,
    at: datetime | None = None,
) -> tuple[datetime, datetime, datetime]:
    """Return (period_start, period_end_exclusive, resets_at) anchored to the monthly
    anniversary of ``created_at``.

    A user who signed up on the 5th has windows Jun 5 → Jul 5 → Aug 5 … regardless
    of calendar month boundaries.  Days > 28 are clamped to the last day of each
    month so a Jan-31 signup gets Feb-28 as its February boundary.
    """
    now = at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    signup = _ensure_utc(created_at)
    signup_day = signup.day

    this_anniversary = _anniversary_in_month(now.year, now.month, signup_day)

    if now >= this_anniversary:
        # Window started this month; ends next month's anniversary
        period_start = this_anniversary
        next_year = now.year + 1 if now.month == 12 else now.year
        next_month = 1 if now.month == 12 else now.month + 1
        period_end = _anniversary_in_month(next_year, next_month, signup_day)
    else:
        # We haven't reached this month's anniversary yet; window started last month
        prev_year = now.year - 1 if now.month == 1 else now.year
        prev_month = 12 if now.month == 1 else now.month - 1
        period_start = _anniversary_in_month(prev_year, prev_month, signup_day)
        period_end = this_anniversary

    return period_start, period_end, period_end


def stripe_billing_period_current(
    user: User,
    *,
    at: datetime | None = None,
) -> tuple[datetime, datetime] | None:
    """Return (period_start, period_end_exclusive) when Pro Stripe window contains ``at``."""
    if not getattr(user, "is_premium", False):
        return None
    period_start = user.subscription_period_start
    period_end = user.subscription_period_end
    if period_start is None or period_end is None:
        return None
    now = at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    start = _ensure_utc(period_start)
    end = _ensure_utc(period_end)
    if start <= now < end:
        return start, end
    return None


def usage_period_window(
    user: User,
    *,
    at: datetime | None = None,
) -> tuple[datetime, datetime, datetime]:
    """Return (period_start, period_end_exclusive, resets_at) for quota metering.

    Resolution order:
    1. Pro with valid Stripe period → Stripe billing period.
    2. Pro with missing/expired Stripe period → UTC calendar month (Pro limits unchanged).
    3. Free with ``created_at`` → monthly signup-anniversary window.
    4. Fallback (no ``created_at``) → UTC calendar month.
    Post-downgrade ``free_usage_epoch`` floors the start in all Free paths.
    """
    now = at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    stripe_period = stripe_billing_period_current(user, at=now)
    if stripe_period is not None:
        start, end = stripe_period
        return start, end, end

    if getattr(user, "is_premium", False):
        logger.warning(
            "pro_stale_subscription_period",
            extra={
                "user_id": str(getattr(user, "id", "")),
                "stripe_subscription_id": getattr(user, "stripe_subscription_id", None),
            },
        )
        return utc_month_window(at=now)

    created_at = getattr(user, "created_at", None)
    epoch = getattr(user, "free_usage_epoch", None)

    # Hosted pick limbo: no Free metering until the user chooses a live workflow.
    # Core ignores stale hosted billing lifecycle fields while enforcement is off.
    from smeme.billing.providers import hosted_quota_enforcement_enabled

    if hosted_quota_enforcement_enabled() and getattr(user, "workflow_pick_required", False):
        if created_at is not None:
            _, period_end, next_reset = signup_anniversary_window(created_at, at=now)
        else:
            _, period_end, next_reset = utc_month_window(at=now)
        return now, period_end, next_reset

    # Free: anchor to signup date; fall back to UTC month if created_at absent
    if created_at is not None:
        anchor = now
        if epoch is not None:
            epoch_utc = _ensure_utc(epoch)
            anchor = epoch_utc if epoch_utc > now else now
        period_start, period_end, next_reset = signup_anniversary_window(created_at, at=anchor)
    else:
        period_start, period_end, next_reset = utc_month_window(at=now)

    # Post-downgrade: fresh Free quotas start at free_usage_epoch
    if epoch is not None:
        epoch_utc = _ensure_utc(epoch)
        if epoch_utc > period_start:
            period_start = epoch_utc

    return period_start, period_end, next_reset


def resets_on_stripe_period(user: User, *, at: datetime | None = None) -> bool:
    return stripe_billing_period_current(user, at=at) is not None


def resets_at_iso(*, user: User, at: datetime | None = None) -> str:
    """ISO timestamp when monthly quotas reset for this user."""
    _, _, resets = usage_period_window(user, at=at)
    return resets.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_month_day(value: datetime) -> str:
    return f"{value.strftime('%b')} {value.day}"


def resets_at_label(*, user: User, at: datetime | None = None) -> str:
    """Human label, e.g. ``Resets on Jul 11 (30 days)``."""
    now = at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    _, _, resets = usage_period_window(user, at=at)
    days = max(0, (resets.date() - now.date()).days)
    return f"Resets on {_format_month_day(resets)} ({days} days)"


async def count_live_root_workflows_for_user(db: AsyncSession, user: User) -> int:
    return await count_live_root_workflows(db, user)


async def sum_mcp_weighted_month(
    db: AsyncSession,
    user: User,
    *,
    at: datetime | None = None,
) -> float:
    period_start, period_end, _ = usage_period_window(user, at=at)
    result = await db.execute(
        select(func.coalesce(func.sum(McpToolInvocation.quota_weight), 0)).where(
            McpToolInvocation.user_id == user.id,
            McpToolInvocation.created_at >= period_start,
            McpToolInvocation.created_at < period_end,
        )
    )
    return float(result.scalar() or 0)


async def mcp_weighted_by_qnr_month(
    db: AsyncSession,
    user: User,
    *,
    at: datetime | None = None,
) -> dict[UUID, float]:
    period_start, period_end, _ = usage_period_window(user, at=at)
    result = await db.execute(
        select(
            McpToolInvocation.qnr_id,
            func.coalesce(func.sum(McpToolInvocation.quota_weight), 0),
        )
        .where(
            McpToolInvocation.user_id == user.id,
            McpToolInvocation.qnr_id.is_not(None),
            McpToolInvocation.created_at >= period_start,
            McpToolInvocation.created_at < period_end,
        )
        .group_by(McpToolInvocation.qnr_id)
    )
    out: dict[UUID, float] = {}
    for qnr_id, total in result.all():
        if qnr_id is not None:
            out[qnr_id] = float(total or 0)
    return out


def _wizard_complete_counts_toward_quota_clause():
    """Only successful builds consume wizard credits (see sprint wizard telemetry contract)."""
    status = WizardGenerationEvent.event_metadata["final_status"].astext
    return or_(
        ~WizardGenerationEvent.event_metadata.has_key("final_status"),
        status.in_(tuple(WIZARD_SUCCESS_STATUSES)),
    )


async def count_wizard_completions_month(
    db: AsyncSession,
    user: User,
    *,
    at: datetime | None = None,
) -> int:
    period_start, period_end, _ = usage_period_window(user, at=at)
    result = await db.execute(
        select(func.count(func.distinct(WizardGenerationEvent.generation_id))).where(
            WizardGenerationEvent.user_id == user.id,
            WizardGenerationEvent.event_type == "wizard.complete",
            WizardGenerationEvent.generation_id.is_not(None),
            WizardGenerationEvent.created_at >= period_start,
            WizardGenerationEvent.created_at < period_end,
            _wizard_complete_counts_toward_quota_clause(),
        )
    )
    return int(result.scalar() or 0)


def _usage_pct(used: float, limit: float) -> float:
    if limit <= 0:
        return 0.0
    return min(100.0, (used / limit) * 100.0)


async def build_usage_summary(db: AsyncSession, user: User) -> dict[str, Any]:
    """Compact usage dict for Profile and Dashboard templates."""
    from smeme.billing.providers import ensure_pro_billing_period

    await ensure_pro_billing_period(db, user)
    tier = tier_for_user(user)
    limits = limits_for_user(user)
    if user.is_premium:
        workflows_used = await count_active_root_workflows(db, user.id)
    else:
        workflows_used = await count_live_root_workflows_for_user(db, user)
    mcp_used = await sum_mcp_weighted_month(db, user)
    wizard_used = await count_wizard_completions_month(db, user)

    def _dim(used: float, limit: float) -> dict[str, Any]:
        remaining = max(0.0, limit - used)
        pct = _usage_pct(used, limit)
        return {
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "pct": pct,
            "at_warning": pct >= 80.0,
            "at_cap": used >= limit,
        }

    return {
        "tier": tier.value,
        "tier_name": tier_display_name(tier),
        "resets_at": resets_at_iso(user=user),
        "resets_label": resets_at_label(user=user),
        "resets_on_stripe_period": resets_on_stripe_period(user),
        "workflows": _dim(float(workflows_used), float(limits.max_workflows)),
        "mcp_weighted": _dim(mcp_used, limits.max_mcp_weighted),
        "wizard_completions": _dim(float(wizard_used), float(limits.max_wizard_completions)),
    }


__all__ = [
    "build_usage_summary",
    "count_active_root_workflows",
    "count_live_root_workflows_for_user",
    "count_wizard_completions_month",
    "mcp_weighted_by_qnr_month",
    "resets_at_iso",
    "resets_at_label",
    "resets_on_stripe_period",
    "stripe_billing_period_current",
    "signup_anniversary_window",
    "sum_mcp_weighted_month",
    "usage_period_window",
    "utc_month_window",
]
