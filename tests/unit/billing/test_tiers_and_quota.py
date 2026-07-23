"""Unit tests for billing tiers, usage aggregates, and quota enforcement."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from smeme.billing.access_policy import (
    billing_lifecycle_context,
    is_decision_tree_dashboard_grayed,
    is_decision_tree_live,
    is_workflow_pick_required,
)
from smeme.billing.providers import (
    hosted_quota_enforcement_enabled,
    hosted_quota_enforcement_scope,
    reset_billing_providers_for_tests,
)
from smeme.billing.quota import (
    QuotaDimension,
    check_quota,
    check_wizard_start_block,
    mcp_quota_denied_response,
    reserve_mcp_quota,
    wizard_start_blocked_message,
)
from smeme.billing.tiers import (
    TIER_LIMITS,
    BillingTier,
    limits_for_user,
    tier_display_name,
    tier_for_user,
)
from smeme.billing.usage import (
    count_active_root_workflows,
    count_wizard_completions_month,
    resets_at_label,
    resets_on_stripe_period,
    signup_anniversary_window,
    stripe_billing_period_current,
    sum_mcp_weighted_month,
    usage_period_window,
    utc_month_window,
)
from smeme.core.models import DecisionTree, User
from smeme.mcp.invocation_telemetry import outcome_from_tool_json
from smeme.mcp.models import McpToolInvocation
from smeme.decision_tree.models import InProgressDecisionTreeGeneration, WizardGenerationEvent


@pytest_asyncio.fixture
async def billing_user(test_session_factory):
    uid = uuid4().hex[:8]
    async with test_session_factory() as session:
        user = User(
            email=f"billing_{uid}@example.com",
            hashed_password="unused",
            is_active=True,
            is_verified=True,
            username=f"billing_{uid}",
            is_premium=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    yield user
    async with test_session_factory() as session:
        await session.execute(delete(WizardGenerationEvent).where(WizardGenerationEvent.user_id == user.id))
        await session.execute(delete(McpToolInvocation).where(McpToolInvocation.user_id == user.id))
        await session.execute(
            delete(InProgressDecisionTreeGeneration).where(InProgressDecisionTreeGeneration.user_id == user.id)
        )
        await session.execute(delete(DecisionTree).where(DecisionTree.author_id == user.id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


@pytest.fixture(autouse=True)
def _hosted_quota_enforcement_for_mode_b_tests():
    """Quota denial tests exercise hosted Free/Pro Mode B (SaaS registration)."""
    with hosted_quota_enforcement_scope():
        yield
    reset_billing_providers_for_tests()


def test_tier_for_user_free_and_pro() -> None:
    free = User(email="a@b.com", hashed_password="x", is_premium=False)
    pro = User(email="c@d.com", hashed_password="x", is_premium=True)
    assert tier_for_user(free) == BillingTier.FREE
    assert tier_for_user(pro) == BillingTier.PRO
    assert tier_display_name(BillingTier.PRO) == "Pro"


def test_tier_limits_matrix() -> None:
    free = TIER_LIMITS[BillingTier.FREE]
    pro = TIER_LIMITS[BillingTier.PRO]
    assert free.max_workflows == 3
    assert pro.max_workflows == 20
    assert free.max_mcp_weighted == 150.0
    assert pro.max_mcp_weighted == 1500.0
    assert free.max_wizard_completions == 3
    assert pro.max_wizard_completions == 20


def test_utc_month_window() -> None:
    mid_june = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    start, end, next_start = utc_month_window(at=mid_june)
    assert start == datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
    assert next_start == end


def test_signup_anniversary_window_mid_month() -> None:
    """User signed up on the 5th; mid-June falls inside the Jun 5–Jul 5 window."""
    created_at = datetime(2026, 5, 5, 14, 30, 0, tzinfo=UTC)
    now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    start, end, resets = signup_anniversary_window(created_at, at=now)
    assert start == datetime(2026, 6, 5, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 7, 5, 0, 0, 0, tzinfo=UTC)
    assert resets == end


def test_signup_anniversary_window_before_anniversary_this_month() -> None:
    """Before the anniversary day: window started last month."""
    created_at = datetime(2026, 3, 20, 0, 0, 0, tzinfo=UTC)
    now = datetime(2026, 6, 15, 0, 0, 0, tzinfo=UTC)  # Jun 15 < Jun 20
    start, end, resets = signup_anniversary_window(created_at, at=now)
    assert start == datetime(2026, 5, 20, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 6, 20, 0, 0, 0, tzinfo=UTC)


def test_signup_anniversary_window_on_anniversary_day() -> None:
    """Exactly on the anniversary (midnight): window flips to new period."""
    created_at = datetime(2026, 1, 15, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 6, 15, 0, 0, 0, tzinfo=UTC)  # exactly at anniversary
    start, end, _ = signup_anniversary_window(created_at, at=now)
    assert start == datetime(2026, 6, 15, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 7, 15, 0, 0, 0, tzinfo=UTC)


def test_signup_anniversary_window_month_end_clamp() -> None:
    """Jan-31 signup: Feb boundary clamps to Feb 28 (2026 is not a leap year)."""
    created_at = datetime(2026, 1, 31, 0, 0, 0, tzinfo=UTC)
    now = datetime(2026, 2, 10, 0, 0, 0, tzinfo=UTC)
    start, end, _ = signup_anniversary_window(created_at, at=now)
    assert start == datetime(2026, 1, 31, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 2, 28, 0, 0, 0, tzinfo=UTC)


def test_signup_anniversary_window_year_boundary() -> None:
    """Dec signup; window spans Dec → Jan of next year."""
    created_at = datetime(2025, 12, 10, 0, 0, 0, tzinfo=UTC)
    now = datetime(2025, 12, 20, 0, 0, 0, tzinfo=UTC)
    start, end, _ = signup_anniversary_window(created_at, at=now)
    assert start == datetime(2025, 12, 10, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 1, 10, 0, 0, 0, tzinfo=UTC)


def test_usage_period_window_free_uses_signup_anniversary() -> None:
    """Free tier: window anchors to signup day, not the 1st of the month."""
    created_at = datetime(2026, 5, 5, 14, 30, 0, tzinfo=UTC)
    now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    user = User(
        email="free@example.com",
        hashed_password="x",
        is_premium=False,
        created_at=created_at,
    )
    start, end, _ = usage_period_window(user, at=now)
    assert start == datetime(2026, 6, 5, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 7, 5, 0, 0, 0, tzinfo=UTC)


def test_usage_period_window_uses_stripe_period_for_pro() -> None:
    now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
    user = User(
        email="pro@example.com",
        hashed_password="x",
        is_premium=True,
        subscription_period_start=datetime(2026, 6, 11, 0, 0, 0, tzinfo=UTC),
        subscription_period_end=datetime(2026, 7, 11, 0, 0, 0, tzinfo=UTC),
    )
    start, end, resets = usage_period_window(user, at=now)
    assert start == datetime(2026, 6, 11, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 7, 11, 0, 0, 0, tzinfo=UTC)
    assert resets == end


def test_resets_at_label_stripe_period() -> None:
    now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
    user = User(
        email="pro@example.com",
        hashed_password="x",
        is_premium=True,
        subscription_period_start=datetime(2026, 6, 11, 0, 0, 0, tzinfo=UTC),
        subscription_period_end=datetime(2026, 7, 11, 0, 0, 0, tzinfo=UTC),
    )
    assert resets_at_label(user=user, at=now) == "Resets on Jul 11 (29 days)"


def test_usage_period_window_pro_missing_periods_uses_utc_month() -> None:
    """Pro without Stripe periods must not inherit Free signup-anniversary windows."""
    now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    created_at = datetime(2025, 1, 5, 0, 0, 0, tzinfo=UTC)
    user = User(
        email="pro@example.com",
        hashed_password="x",
        is_premium=True,
        created_at=created_at,
    )
    expected = utc_month_window(at=now)
    start, end, resets = usage_period_window(user, at=now)
    assert (start, end, resets) == expected
    assert limits_for_user(user).max_mcp_weighted == TIER_LIMITS[BillingTier.PRO].max_mcp_weighted


def test_usage_period_window_pro_expired_periods_uses_utc_month() -> None:
    now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    user = User(
        email="pro@example.com",
        hashed_password="x",
        is_premium=True,
        created_at=datetime(2025, 1, 5, 0, 0, 0, tzinfo=UTC),
        subscription_period_start=datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC),
        subscription_period_end=datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC),
    )
    assert stripe_billing_period_current(user, at=now) is None
    assert resets_on_stripe_period(user, at=now) is False
    start, end, _ = usage_period_window(user, at=now)
    month_start, month_end, _ = utc_month_window(at=now)
    assert start == month_start
    assert end == month_end


def test_usage_period_window_pro_stale_period_logs(caplog: pytest.LogCaptureFixture) -> None:
    now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    user = User(
        email="pro@example.com",
        hashed_password="x",
        is_premium=True,
        stripe_subscription_id="sub_stale_test",
    )
    with caplog.at_level("WARNING"):
        usage_period_window(user, at=now)
    assert any(r.message == "pro_stale_subscription_period" for r in caplog.records)


@pytest.mark.asyncio(loop_scope="session")
async def test_workflow_quota_blocks_fourth_root(test_session_factory, billing_user) -> None:
    async with test_session_factory() as session:
        for i in range(3):
            session.add(
                DecisionTree(
                    author_id=billing_user.id,
                    title=f"Workflow {i + 1}",
                    graph_data={"nodes": [], "edges": []},
                    is_current=True,
                    is_archived=False,
                )
            )
        await session.commit()

        check = await check_quota(session, billing_user, QuotaDimension.DECISION_TREES, projected_add=1.0)
        assert check.allowed is False
        assert check.used == 3.0
        assert check.limit == 3.0


@pytest.mark.asyncio(loop_scope="session")
async def test_mcp_quota_denies_when_sum_plus_weight_exceeds(test_session_factory, billing_user) -> None:
    async with test_session_factory() as session:
        session.add(
            McpToolInvocation(
                user_id=billing_user.id,
                tool_name="smeme_reasoning_evaluate",
                outcome="ok",
                duration_ms=10,
                quota_weight=Decimal("149.00"),
                estimated_cost_usd_micros=100,
            )
        )
        await session.commit()

        check = await check_quota(
            session,
            billing_user,
            QuotaDimension.MCP_WEIGHTED,
            projected_add=2.0,
        )
        assert check.allowed is False
        assert check.used == 149.0


@pytest.mark.asyncio(loop_scope="session")
async def test_wizard_quota_counts_distinct_generation_id(test_session_factory, billing_user) -> None:
    async with test_session_factory() as session:
        for i in range(3):
            session.add(
                WizardGenerationEvent(
                    user_id=billing_user.id,
                    event_type="wizard.complete",
                    phase="complete",
                    generation_id=uuid4(),
                    thread_id=f"thread-{i}",
                )
            )
        await session.commit()

        count = await count_wizard_completions_month(session, billing_user)
        assert count == 3

        check = await check_quota(
            session,
            billing_user,
            QuotaDimension.WIZARD_COMPLETIONS,
            projected_add=1.0,
        )
        assert check.allowed is False


@pytest.mark.asyncio(loop_scope="session")
async def test_wizard_quota_ignores_failed_build_completions(test_session_factory, billing_user) -> None:
    gen_id = uuid4()
    async with test_session_factory() as session:
        session.add(
            WizardGenerationEvent(
                user_id=billing_user.id,
                event_type="wizard.complete",
                phase="complete",
                generation_id=gen_id,
                thread_id="thread-failed",
                event_metadata={"final_status": "has_errors"},
            )
        )
        await session.commit()

        count = await count_wizard_completions_month(session, billing_user)
        assert count == 0

        check = await check_quota(
            session,
            billing_user,
            QuotaDimension.WIZARD_COMPLETIONS,
            projected_add=1.0,
        )
        assert check.allowed is True


@pytest.mark.asyncio(loop_scope="session")
async def test_wizard_start_blocked_when_monthly_cap_reached(test_session_factory, billing_user) -> None:
    async with test_session_factory() as session:
        for i in range(3):
            session.add(
                WizardGenerationEvent(
                    user_id=billing_user.id,
                    event_type="wizard.complete",
                    phase="complete",
                    generation_id=uuid4(),
                    thread_id=f"thread-done-{i}",
                    event_metadata={"final_status": "valid"},
                )
            )
        await session.commit()

        block = await check_wizard_start_block(session, billing_user, in_progress_count=0)
        assert block is not None
        assert block.reason == "wizard_monthly"
        assert block.title == "Monthly AI build limit reached"


@pytest.mark.asyncio(loop_scope="session")
async def test_wizard_start_blocked_when_free_has_in_progress(test_session_factory, billing_user) -> None:
    async with test_session_factory() as session:
        session.add(
            InProgressDecisionTreeGeneration(
                user_id=billing_user.id,
                langgraph_thread_id=str(uuid4()),
                user_prompt_preview="Existing build",
                graph_version="v2",
                current_phase="design",
            )
        )
        await session.commit()

        block = await check_wizard_start_block(session, billing_user, in_progress_count=1)
        assert block is not None
        assert block.reason == "in_progress"


@pytest.mark.asyncio(loop_scope="session")
async def test_wizard_start_allowed_when_pro_has_in_progress(test_session_factory, billing_user) -> None:
    billing_user.is_premium = True
    async with test_session_factory() as session:
        msg = await wizard_start_blocked_message(session, billing_user, in_progress_count=2)
        assert msg is None


@pytest.mark.asyncio(loop_scope="session")
async def test_active_root_workflow_count_excludes_archived(test_session_factory, billing_user) -> None:
    async with test_session_factory() as session:
        session.add(
            DecisionTree(
                author_id=billing_user.id,
                title="Archived",
                graph_data={"nodes": [], "edges": []},
                is_current=True,
                is_archived=True,
            )
        )
        await session.commit()
        assert await count_active_root_workflows(session, billing_user.id) == 0


@pytest.mark.asyncio(loop_scope="session")
async def test_sum_mcp_weighted_month(test_session_factory, billing_user) -> None:
    async with test_session_factory() as session:
        session.add_all(
            [
                McpToolInvocation(
                    user_id=billing_user.id,
                    tool_name="smeme_reasoning_evaluate",
                    outcome="ok",
                    duration_ms=5,
                    quota_weight=Decimal("1.00"),
                    estimated_cost_usd_micros=100,
                ),
                McpToolInvocation(
                    user_id=billing_user.id,
                    tool_name="smeme_reasoning_validate_answers",
                    outcome="ok",
                    duration_ms=5,
                    quota_weight=Decimal("1.00"),
                    estimated_cost_usd_micros=50,
                ),
            ]
        )
        await session.commit()
        total = await sum_mcp_weighted_month(session, billing_user)
        assert total == pytest.approx(2.0)


@pytest.mark.asyncio(loop_scope="session")
async def test_sum_mcp_weighted_month_excludes_zero_weight_rows(
    test_session_factory, billing_user
) -> None:
    async with test_session_factory() as session:
        session.add_all(
            [
                McpToolInvocation(
                    user_id=billing_user.id,
                    tool_name="smeme_reasoning_evaluate",
                    outcome="ok",
                    duration_ms=5,
                    quota_weight=Decimal("1.00"),
                    estimated_cost_usd_micros=100,
                ),
                McpToolInvocation(
                    user_id=billing_user.id,
                    tool_name="smeme_reasoning_evaluate",
                    outcome="invalid_decision_tree_id",
                    duration_ms=1,
                    quota_weight=Decimal("0.00"),
                    estimated_cost_usd_micros=1,
                ),
            ]
        )
        await session.commit()
        total = await sum_mcp_weighted_month(session, billing_user)
        assert total == pytest.approx(1.0)


@pytest.mark.asyncio(loop_scope="session")
async def test_mcp_quota_denied_response_includes_reset_fields(
    test_session_factory, billing_user
) -> None:
    async with test_session_factory() as session:
        session.add(
            McpToolInvocation(
                user_id=billing_user.id,
                tool_name="smeme_reasoning_evaluate",
                outcome="ok",
                duration_ms=1,
                quota_weight=Decimal("149.00"),
                estimated_cost_usd_micros=1,
            )
        )
        await session.commit()

        denied = await mcp_quota_denied_response(
            session, billing_user, "smeme_reasoning_what_if"
        )
        assert denied is not None
        assert outcome_from_tool_json(denied) == "quota_exceeded"
        payload = json.loads(denied)
        assert payload["error"]["remaining"] == 1.0
        assert payload["error"]["limit"] == 150.0
        assert "resets_at" in payload["error"]


# ---------------------------------------------------------------------------
# Advisory-lock gate: start_new_generation locked re-check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_start_new_generation_raises_when_free_user_already_in_progress(
    test_session_factory, billing_user
) -> None:
    """Locked re-check inside start_new_generation raises WizardStartBlockedError.

    Simulates the two-tab race: a Free user already has one in-progress build
    (written by 'Tab A'), then 'Tab B' calls start_new_generation.  Even though
    Tab B passed the fast-path pre-check before Tab A's row was committed, the
    advisory lock + locked quota re-check inside start_new_generation catches
    it and raises WizardStartBlockedError(reason='in_progress').
    """
    from smeme.decision_tree.generation.agentic.services import (
        WizardStartBlockedError,
        checkpoint_manager,
    )

    # Set up: insert the in-progress row that 'Tab A' would have created.
    async with test_session_factory() as setup_session:
        setup_session.add(
            InProgressDecisionTreeGeneration(
                user_id=billing_user.id,
                langgraph_thread_id=str(uuid4()),
                user_prompt_preview="Tab A build (already running)",
                graph_version="v2",
                current_phase="research",
            )
        )
        await setup_session.commit()

    # Act: 'Tab B' tries to start a new generation in its own session.
    async with test_session_factory() as session:
        with pytest.raises(WizardStartBlockedError) as exc_info:
            await checkpoint_manager.start_new_generation(
                db=session,
                user=billing_user,
                user_prompt="Tab B build attempt",
            )

    assert exc_info.value.block.reason == "in_progress"


@pytest.mark.asyncio(loop_scope="session")
async def test_start_new_generation_succeeds_when_no_in_progress(
    test_session_factory, billing_user
) -> None:
    """start_new_generation inserts a row and returns it when the user has no
    in-progress builds and is within all quota limits."""
    from smeme.decision_tree.generation.agentic.services import checkpoint_manager

    async with test_session_factory() as session:
        gen = await checkpoint_manager.start_new_generation(
            db=session,
            user=billing_user,
            user_prompt="First build for this user",
        )

    assert gen.user_id == billing_user.id
    assert gen.current_phase == "research"
    assert gen.langgraph_thread_id  # non-empty UUID string

    # Cleanup: remove the row so the billing_user fixture teardown is clean.
    async with test_session_factory() as cleanup:
        await cleanup.execute(
            delete(InProgressDecisionTreeGeneration).where(
                InProgressDecisionTreeGeneration.id == gen.id
            )
        )
        await cleanup.commit()


# ---------------------------------------------------------------------------
# reserve_mcp_quota — atomic lock + check + INSERT (A1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_reserve_mcp_quota_inserts_reserved_row(
    test_session_factory, billing_user
) -> None:
    """Happy path: under cap → reserved row committed, returns UUID."""
    from uuid import UUID


    async with test_session_factory() as session:
        result = await reserve_mcp_quota(session, billing_user, "smeme_reasoning_evaluate")

    assert isinstance(result, UUID), f"expected UUID, got: {result!r}"

    async with test_session_factory() as session:
        row = await session.get(McpToolInvocation, result)
        assert row is not None
        assert row.outcome == "reserved"
        assert float(row.quota_weight) == 1.0
        assert row.tool_name == "smeme_reasoning_evaluate"
        assert row.user_id == billing_user.id

    # Cleanup
    async with test_session_factory() as session:
        await session.execute(
            delete(McpToolInvocation).where(McpToolInvocation.id == result)
        )
        await session.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_reserve_mcp_quota_denies_at_cap(
    test_session_factory, billing_user
) -> None:
    """At cap: reserve returns quota_exceeded tool_error_json, no new row."""
    import json

    row_id = uuid4()
    async with test_session_factory() as session:
        session.add(
            McpToolInvocation(
                id=row_id,
                user_id=billing_user.id,
                tool_name="smeme_reasoning_evaluate",
                outcome="ok",
                duration_ms=1,
                quota_weight=Decimal("150.00"),
                estimated_cost_usd_micros=1,
            )
        )
        await session.commit()

    async with test_session_factory() as session:
        result = await reserve_mcp_quota(session, billing_user, "smeme_reasoning_evaluate")

    assert isinstance(result, str)
    assert json.loads(result)["error"]["code"] == "quota_exceeded"

    async with test_session_factory() as session:
        count_result = await session.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(
                __import__("sqlalchemy", fromlist=["func"]).func.count()
            ).where(
                McpToolInvocation.user_id == billing_user.id,
                McpToolInvocation.outcome == "reserved",
            )
        )
        assert count_result.scalar() == 0

    # Cleanup
    async with test_session_factory() as session:
        await session.execute(
            delete(McpToolInvocation).where(McpToolInvocation.id == row_id)
        )
        await session.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_reserve_mcp_quota_concurrency_limit_on_lock_fail(
    test_session_factory, billing_user, monkeypatch
) -> None:
    """When pg_try_advisory_xact_lock returns False → concurrency_limit, no row."""
    import json
    from unittest.mock import AsyncMock, MagicMock

    mock_scalar = MagicMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalar = mock_scalar

    async with test_session_factory() as session:
        monkeypatch.setattr(session, "execute", AsyncMock(return_value=mock_result))
        result = await reserve_mcp_quota(session, billing_user, "smeme_reasoning_evaluate")

    assert isinstance(result, str)
    assert json.loads(result)["error"]["code"] == "concurrency_limit"


# ---------------------------------------------------------------------------
# Core enforcement off (metering on)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_check_quota_allows_when_enforcement_off(
    test_session_factory, billing_user
) -> None:
    """Core default: no Free/Pro hard deny even when usage would exceed Free caps."""
    with hosted_quota_enforcement_scope(enabled=False):
        assert hosted_quota_enforcement_enabled() is False
        async with test_session_factory() as session:
            for i in range(5):
                session.add(
                    DecisionTree(
                        author_id=billing_user.id,
                        title=f"wf-{i}",
                        graph_data={"nodes": [], "edges": []},
                        is_current=True,
                        is_archived=False,
                    )
                )
            await session.commit()
            check = await check_quota(
                session,
                billing_user,
                QuotaDimension.DECISION_TREES,
                projected_add=1.0,
            )
    assert check.allowed is True
    assert check.enforced is False
    assert check.used == 5.0
    assert check.limit is None
    assert check.remaining is None


@pytest.mark.asyncio(loop_scope="session")
async def test_reserve_mcp_quota_meters_when_enforcement_off(
    test_session_factory, billing_user
) -> None:
    """Enforcement off still inserts reserved telemetry row (no early-return)."""
    from uuid import UUID

    row_id = uuid4()
    async with test_session_factory() as session:
        session.add(
            McpToolInvocation(
                id=row_id,
                user_id=billing_user.id,
                tool_name="smeme_reasoning_evaluate",
                outcome="ok",
                duration_ms=1,
                quota_weight=Decimal("150.00"),
                estimated_cost_usd_micros=1,
            )
        )
        await session.commit()

    with hosted_quota_enforcement_scope(enabled=False):
        async with test_session_factory() as session:
            result = await reserve_mcp_quota(
                session,
                billing_user,
                "smeme_reasoning_evaluate",
            )

    assert isinstance(result, UUID), f"expected UUID when enforcement off, got: {result!r}"

    async with test_session_factory() as session:
        row = await session.get(McpToolInvocation, result)
        assert row is not None
        assert row.outcome == "reserved"
        await session.execute(delete(McpToolInvocation).where(McpToolInvocation.id == result))
        await session.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_wizard_start_unblocked_when_enforcement_off(
    test_session_factory, billing_user
) -> None:
    with hosted_quota_enforcement_scope(enabled=False):
        async with test_session_factory() as session:
            block = await check_wizard_start_block(
                session,
                billing_user,
                in_progress_count=2,
            )
    assert block is None


@pytest.mark.asyncio(loop_scope="session")
async def test_core_ignores_stale_hosted_downgrade_state(billing_user) -> None:
    billing_user.workflow_pick_required = True
    decision_tree = DecisionTree(
        author_id=billing_user.id,
        title="Previously dormant",
        graph_data={"nodes": [], "edges": []},
        is_current=True,
        is_archived=False,
        billing_dormant=True,
    )

    with hosted_quota_enforcement_scope(enabled=False):
        assert is_workflow_pick_required(billing_user) is False
        assert is_decision_tree_live(billing_user, decision_tree) is True
        assert is_decision_tree_dashboard_grayed(billing_user, decision_tree) is False
        assert billing_lifecycle_context(billing_user, active_root_count=5) == {
            "show_cancellation_explainer": False,
            "pro_ending_banner": None,
            "workflow_pick_required": False,
            "subscription_period_end_label": None,
        }
