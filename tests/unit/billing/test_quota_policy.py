"""Request/task-scoped quota enforcement policy tests."""

from __future__ import annotations

import asyncio

import pytest

from smeme.billing.providers import (
    hosted_quota_enforcement_enabled,
    hosted_quota_enforcement_scope,
)


def test_core_defaults_to_unenforced_quota() -> None:
    assert hosted_quota_enforcement_enabled() is False


def test_hosted_scope_restores_previous_value_after_exception() -> None:
    assert hosted_quota_enforcement_enabled() is False

    with hosted_quota_enforcement_scope():
        assert hosted_quota_enforcement_enabled() is True

        with pytest.raises(RuntimeError, match="test failure"):
            with hosted_quota_enforcement_scope(enabled=False):
                assert hosted_quota_enforcement_enabled() is False
                raise RuntimeError("test failure")

        assert hosted_quota_enforcement_enabled() is True

    assert hosted_quota_enforcement_enabled() is False


@pytest.mark.asyncio
async def test_concurrent_quota_contexts_do_not_leak() -> None:
    async def observe(enabled: bool) -> tuple[bool, bool]:
        with hosted_quota_enforcement_scope(enabled=enabled):
            first = hosted_quota_enforcement_enabled()
            await asyncio.sleep(0)
            second = hosted_quota_enforcement_enabled()
        return first, second

    hosted, core = await asyncio.gather(observe(True), observe(False))

    assert hosted == (True, True)
    assert core == (False, False)
    assert hosted_quota_enforcement_enabled() is False
