"""Injectable billing side-effects for Core (default: no-op).

SaaS / ``smeme-cloud`` registers Stripe-backed implementations via
``register_billing_providers`` from ``smeme.saas_overlay``. Core must never
import Stripe adapters directly.

Hosted Free/Pro **quota enforcement** is also registered by the SaaS overlay
(default off in Core — metering stays on). See D022.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import User

type EnsureProBillingPeriodFn = Callable[[AsyncSession, User], Awaitable[None]]
type CancelSubscriptionFn = Callable[[User], Awaitable[bool]]


async def _noop_ensure_pro_billing_period(_db: AsyncSession, _user: User) -> None:
    return None


async def _noop_cancel_subscription_if_needed(_user: User) -> bool:
    return False


_ensure_pro_billing_period: EnsureProBillingPeriodFn = _noop_ensure_pro_billing_period
_cancel_subscription_if_needed: CancelSubscriptionFn = _noop_cancel_subscription_if_needed
_hosted_quota_enforcement: bool = False


def register_billing_providers(
    *,
    ensure_pro_billing_period: EnsureProBillingPeriodFn | None = None,
    cancel_subscription_if_needed: CancelSubscriptionFn | None = None,
) -> None:
    """Wire SaaS payment-provider adapters (called from the private overlay)."""
    global _ensure_pro_billing_period, _cancel_subscription_if_needed
    if ensure_pro_billing_period is not None:
        _ensure_pro_billing_period = ensure_pro_billing_period
    if cancel_subscription_if_needed is not None:
        _cancel_subscription_if_needed = cancel_subscription_if_needed


def register_hosted_quota_enforcement(*, enabled: bool = True) -> None:
    """Enable hosted Free/Pro hard caps (SaaS overlay only).

    Core default is enforcement **off** with metering still on. There is no
    self-host switch that reuses SaaS Free/Pro tiers.
    """
    global _hosted_quota_enforcement
    _hosted_quota_enforcement = enabled


def hosted_quota_enforcement_enabled() -> bool:
    """True when hosted Free/Pro Mode B caps are active (SaaS)."""
    return _hosted_quota_enforcement


def require_hosted_quota_enforcement() -> None:
    """Fail closed for SaaS boots missing hosted quota registration."""
    if not _hosted_quota_enforcement:
        msg = (
            "SaaS overlay requires hosted Free/Pro quota enforcement. "
            "Call register_hosted_quota_enforcement() from mount_saas_overlay."
        )
        raise RuntimeError(msg)


def reset_billing_providers_for_tests() -> None:
    """Restore no-op providers and Core quota defaults (unit tests)."""
    global _ensure_pro_billing_period, _cancel_subscription_if_needed, _hosted_quota_enforcement
    _ensure_pro_billing_period = _noop_ensure_pro_billing_period
    _cancel_subscription_if_needed = _noop_cancel_subscription_if_needed
    _hosted_quota_enforcement = False


async def ensure_pro_billing_period(db: AsyncSession, user: User) -> None:
    """Refresh paid billing windows when a provider is registered; else no-op."""
    await _ensure_pro_billing_period(db, user)


async def cancel_subscription_if_needed(user: User) -> bool:
    """Cancel remote subscription on account delete when a provider is registered."""
    return await _cancel_subscription_if_needed(user)


__all__ = [
    "cancel_subscription_if_needed",
    "ensure_pro_billing_period",
    "hosted_quota_enforcement_enabled",
    "register_billing_providers",
    "register_hosted_quota_enforcement",
    "require_hosted_quota_enforcement",
    "reset_billing_providers_for_tests",
]
