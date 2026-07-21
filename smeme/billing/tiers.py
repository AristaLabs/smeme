"""Canonical subscription tier limits (single source of truth)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from smeme.core.models import User


class BillingTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    TEAMS = "teams"


@dataclass(frozen=True, slots=True)
class TierLimits:
    max_workflows: int
    max_mcp_weighted: float
    max_wizard_completions: int


TIER_LIMITS: dict[BillingTier, TierLimits] = {
    BillingTier.FREE: TierLimits(
        max_workflows=3,
        max_mcp_weighted=150.0,
        max_wizard_completions=3,
    ),
    BillingTier.PRO: TierLimits(
        max_workflows=20,
        max_mcp_weighted=1500.0,
        max_wizard_completions=20,
    ),
    BillingTier.TEAMS: TierLimits(
        max_workflows=50,
        max_mcp_weighted=3000.0,
        max_wizard_completions=50,
    ),
}


def tier_for_user(user: User) -> BillingTier:
    """Resolve billing tier from User row (Business/TEAMS not shipped — Pro via is_premium)."""
    if getattr(user, "is_premium", False):
        return BillingTier.PRO
    return BillingTier.FREE


def limits_for_user(user: User) -> TierLimits:
    return TIER_LIMITS[tier_for_user(user)]


def tier_display_name(tier: BillingTier) -> str:
    if tier == BillingTier.PRO:
        return "Pro"
    if tier == BillingTier.TEAMS:
        return "Business"
    return "Free"


__all__ = [
    "BillingTier",
    "TIER_LIMITS",
    "TierLimits",
    "limits_for_user",
    "tier_display_name",
    "tier_for_user",
]
