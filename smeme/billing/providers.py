"""Injectable billing side-effects for Core (default: no-op).

SaaS / ``smeme-cloud`` registers Stripe-backed implementations via
``register_billing_providers`` from ``smeme.saas_overlay``. Core must never
import Stripe adapters directly.

Hosted Free/Pro **quota enforcement** is activated per request by Cloud
middleware (default off in Core — metering stays on). See D022.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import User

type EnsureProBillingPeriodFn = Callable[[AsyncSession, User], Awaitable[None]]
type CancelSubscriptionFn = Callable[[User], Awaitable[bool]]

CORE_QUOTA_POLICY = "unlimited_metered"
HOSTED_QUOTA_POLICY = "hosted_free_pro"


async def _noop_ensure_pro_billing_period(_db: AsyncSession, _user: User) -> None:
    return None


async def _noop_cancel_subscription_if_needed(_user: User) -> bool:
    return False


_ensure_pro_billing_period: EnsureProBillingPeriodFn = _noop_ensure_pro_billing_period
_cancel_subscription_if_needed: CancelSubscriptionFn = _noop_cancel_subscription_if_needed
_hosted_quota_enforcement: ContextVar[bool] = ContextVar(
    "hosted_quota_enforcement",
    default=False,
)


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


@contextmanager
def hosted_quota_enforcement_scope(*, enabled: bool = True) -> Iterator[None]:
    """Set hosted Free/Pro enforcement for the current request/task context.

    The ContextVar keeps Core and Cloud app instances isolated when embedding
    code creates both in one process. Core defaults to enforcement off with
    metering on; Cloud middleware enters this scope for each hosted request.
    """
    token = _hosted_quota_enforcement.set(enabled)
    try:
        yield
    finally:
        _hosted_quota_enforcement.reset(token)


def hosted_quota_enforcement_enabled() -> bool:
    """True when hosted Free/Pro Mode B caps are active in this context."""
    return _hosted_quota_enforcement.get()


def reset_billing_providers_for_tests() -> None:
    """Restore no-op billing side-effect providers (unit tests)."""
    global _ensure_pro_billing_period, _cancel_subscription_if_needed
    _ensure_pro_billing_period = _noop_ensure_pro_billing_period
    _cancel_subscription_if_needed = _noop_cancel_subscription_if_needed


async def ensure_pro_billing_period(db: AsyncSession, user: User) -> None:
    """Refresh paid billing windows when a provider is registered; else no-op."""
    await _ensure_pro_billing_period(db, user)


async def cancel_subscription_if_needed(user: User) -> bool:
    """Cancel remote subscription on account delete when a provider is registered."""
    return await _cancel_subscription_if_needed(user)


__all__ = [
    "CORE_QUOTA_POLICY",
    "HOSTED_QUOTA_POLICY",
    "cancel_subscription_if_needed",
    "ensure_pro_billing_period",
    "hosted_quota_enforcement_enabled",
    "hosted_quota_enforcement_scope",
    "register_billing_providers",
    "reset_billing_providers_for_tests",
]
