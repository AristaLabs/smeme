"""Unit tests for MCP invocation cost telemetry."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from smeme.mcp.invocation_telemetry import (
    bind_invocation_id,
    bind_mcp_user,
    cache_oauth_client_id_on_request,
    effective_quota_weight_for_outcome,
    estimate_cost_usd_micros,
    internal_cost_units_for_tool,
    mcp_invocation_scope,
    outcome_from_tool_json,
    quota_weight_for_tool,
    request_from_mcp_context,
)


def test_quota_weight_vs_internal_cost_units_for_what_if() -> None:
    assert quota_weight_for_tool("smeme_reasoning_what_if") == 2.0
    assert internal_cost_units_for_tool("smeme_reasoning_what_if") == 2.2
    assert quota_weight_for_tool("smeme_reasoning_evaluate") == 1.0
    assert quota_weight_for_tool("smeme_reasoning_validate_answers") == 1.0
    assert quota_weight_for_tool("smeme_reasoning_how_to_reach") == 2.5
    assert quota_weight_for_tool("smeme_reasoning_list") == 0.0
    assert quota_weight_for_tool("smeme_reasoning_guidance_check") == 0.0
    assert quota_weight_for_tool("smeme_reasoning_guidance_get") == 0.0


def test_effective_quota_weight_hybrid_policy() -> None:
    """A3-C: client mistakes free; server work (incl. stale_theory) bills."""
    assert (
        effective_quota_weight_for_outcome(
            tool_name="smeme_reasoning_evaluate",
            outcome="ok",
        )
        == 1.0
    )
    assert (
        effective_quota_weight_for_outcome(
            tool_name="smeme_reasoning_evaluate",
            outcome="stale_theory",
        )
        == 1.0
    )
    assert (
        effective_quota_weight_for_outcome(
            tool_name="smeme_reasoning_evaluate",
            outcome="invalid_decision_tree_id",
        )
        == 0.0
    )
    assert (
        effective_quota_weight_for_outcome(
            tool_name="smeme_reasoning_validate_answers",
            outcome="ingest_malformed",
        )
        == 0.0
    )


def test_outcome_from_tool_json_ok_and_error() -> None:
    assert outcome_from_tool_json(json.dumps({"report": {}})) == "ok"
    err = outcome_from_tool_json(
        json.dumps({"error": {"code": "stale_theory", "message": "re-publish"}})
    )
    assert err == "stale_theory"


def test_estimate_cost_usd_micros_scales_with_internal_units(monkeypatch: pytest.MonkeyPatch) -> None:
    from smeme.core.config import settings

    monkeypatch.setattr(settings, "mcp_cost_baseline_usd_micros", 1000)
    monkeypatch.setattr(settings, "mcp_cost_usd_micros_per_second", 0)
    evaluate = estimate_cost_usd_micros(
        duration_ms=0,
        reasoning_ms=None,
        tool_name="smeme_reasoning_evaluate",
    )
    what_if = estimate_cost_usd_micros(
        duration_ms=0,
        reasoning_ms=None,
        tool_name="smeme_reasoning_what_if",
    )
    assert what_if > evaluate
    assert what_if == int(1000 * 2.2)


def test_estimate_cost_usd_micros_increases_with_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    from smeme.core.config import settings

    monkeypatch.setattr(settings, "mcp_cost_baseline_usd_micros", 100)
    monkeypatch.setattr(settings, "mcp_cost_usd_micros_per_second", 1000)
    low = estimate_cost_usd_micros(
        duration_ms=50,
        reasoning_ms=None,
        tool_name="smeme_reasoning_evaluate",
    )
    high = estimate_cost_usd_micros(
        duration_ms=500,
        reasoning_ms=200,
        tool_name="smeme_reasoning_evaluate",
    )
    assert high > low


def test_recorder_outcome_from_response() -> None:
    from smeme.mcp.invocation_telemetry import McpInvocationRecorder

    rec = McpInvocationRecorder("smeme_reasoning_evaluate")
    rec.bind_user(SimpleNamespace(id=uuid4()))
    rec.note_json_response(json.dumps({"error": {"code": "not_found", "message": "x"}}))
    assert rec._outcome == "not_found"


def test_oauth_client_id_from_request_state() -> None:
    from smeme.mcp.invocation_telemetry import _oauth_client_id_from_request

    request = MagicMock()
    request.state = SimpleNamespace(mcp_oauth_client_id="oauth_app_123")
    assert _oauth_client_id_from_request(request) == "oauth_app_123"

    empty = MagicMock()
    empty.state = SimpleNamespace()
    assert _oauth_client_id_from_request(empty) is None


def test_request_from_context_uses_request_context() -> None:
    from starlette.requests import Request

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    ctx = MagicMock()
    ctx.request_context.request = request
    assert request_from_mcp_context(ctx) is request
    assert request_from_mcp_context(None) is None

    bare = MagicMock(spec=[])
    assert request_from_mcp_context(bare) is None


def test_cache_oauth_client_id_on_request() -> None:
    request = MagicMock()
    request.state = SimpleNamespace()
    cache_oauth_client_id_on_request(request, {"client_id": "from_jwt"})
    assert request.state.mcp_oauth_client_id == "from_jwt"


@pytest.mark.asyncio
async def test_scope_records_internal_error_when_handler_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from smeme.core.config import settings
    from smeme.mcp import invocation_telemetry as mod

    monkeypatch.setattr(settings, "mcp_invocation_telemetry_enabled", True)
    monkeypatch.setattr(settings, "mcp_invocation_telemetry_persist", False)

    captured: list[dict] = []

    def _capture(_msg: str, *, extra: dict | None = None) -> None:
        if extra:
            captured.append(extra)

    monkeypatch.setattr(mod.logger, "info", _capture)

    ctx = MagicMock()
    ctx.request_context.request = MagicMock()
    ctx.request_context.request.state = SimpleNamespace()

    user_id = uuid4()
    with pytest.raises(RuntimeError, match="boom"):
        async with mcp_invocation_scope("smeme_reasoning_evaluate", ctx) as rec:
            rec.bind_user(SimpleNamespace(id=user_id))
            raise RuntimeError("boom")

    assert captured
    assert captured[-1]["outcome"] == "internal_error"
    assert captured[-1]["user_id"] == str(user_id)


@pytest.mark.asyncio
async def test_scope_skips_flush_when_user_never_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    from smeme.core.config import settings
    from smeme.mcp import invocation_telemetry as mod

    monkeypatch.setattr(settings, "mcp_invocation_telemetry_enabled", True)
    captured: list[dict] = []
    monkeypatch.setattr(mod.logger, "info", lambda _msg, *, extra=None: captured.append(extra or {}))

    ctx = MagicMock()
    async with mcp_invocation_scope("smeme_reasoning_list", ctx):
        pass

    assert captured == []


def test_bind_mcp_user_snapshots_oauth_from_request() -> None:
    from smeme.mcp.invocation_telemetry import McpInvocationRecorder, _active_recorder

    request = MagicMock()
    request.state = SimpleNamespace(mcp_oauth_client_id="cowork_app")
    rec = McpInvocationRecorder("smeme_reasoning_evaluate")
    token = _active_recorder.set(rec)
    try:
        bind_mcp_user(SimpleNamespace(id=uuid4()), request=request)  # type: ignore[arg-type]
        assert rec._oauth_client_id == "cowork_app"
    finally:
        _active_recorder.reset(token)


@pytest.mark.asyncio
async def test_scope_persists_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.requests import Request

    from smeme.core.config import settings
    from smeme.mcp import invocation_telemetry as mod

    monkeypatch.setattr(settings, "mcp_invocation_telemetry_enabled", True)
    monkeypatch.setattr(settings, "mcp_invocation_telemetry_persist", True)
    monkeypatch.setattr(mod.logger, "info", lambda *_a, **_k: None)

    persist = AsyncMock()
    monkeypatch.setattr(mod, "_persist_invocation", persist)

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    request.state.mcp_oauth_client_id = "cowork_app"
    ctx = MagicMock()

    async with mcp_invocation_scope("smeme_reasoning_evaluate", ctx) as rec:
        bind_mcp_user(SimpleNamespace(id=uuid4()), request=request)  # type: ignore[arg-type]
        rec.note_json_response(json.dumps({"report": {}}))

    persist.assert_awaited_once()
    kwargs = persist.await_args.kwargs
    assert kwargs["outcome"] == "ok"
    assert kwargs["oauth_client_id"] == "cowork_app"
    assert kwargs["cost_metadata"]["internal_cost_units"] == 1.0


@pytest.mark.asyncio
async def test_scope_does_not_persist_when_persist_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from smeme.core.config import settings
    from smeme.mcp import invocation_telemetry as mod

    monkeypatch.setattr(settings, "mcp_invocation_telemetry_enabled", True)
    monkeypatch.setattr(settings, "mcp_invocation_telemetry_persist", False)
    monkeypatch.setattr(mod.logger, "info", lambda *_a, **_k: None)

    persist = AsyncMock()
    monkeypatch.setattr(mod, "_persist_invocation", persist)

    ctx = MagicMock()
    ctx.request_context.request = MagicMock()
    ctx.request_context.request.state = SimpleNamespace()

    async with mcp_invocation_scope("smeme_reasoning_evaluate", ctx) as rec:
        rec.bind_user(SimpleNamespace(id=uuid4()))
        rec.note_json_response(json.dumps({"report": {}}))

    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_flush_uses_snapshotted_user_id_after_session_detach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate-style paths rollback/close the auth session before telemetry flush."""
    from sqlalchemy.orm.exc import DetachedInstanceError

    from smeme.core.config import settings
    from smeme.mcp import invocation_telemetry as mod

    monkeypatch.setattr(settings, "mcp_invocation_telemetry_enabled", True)
    monkeypatch.setattr(settings, "mcp_invocation_telemetry_persist", False)
    captured: list[dict] = []
    monkeypatch.setattr(mod.logger, "info", lambda _msg, *, extra=None: captured.append(extra or {}))

    uid = uuid4()

    class DetachingUser:
        def __init__(self) -> None:
            self._detached = False

        @property
        def id(self) -> UUID:
            if self._detached:
                raise DetachedInstanceError("user detached")
            return uid

        def detach(self) -> None:
            self._detached = True

    user = DetachingUser()
    ctx = MagicMock()

    async with mcp_invocation_scope("smeme_reasoning_validate_answers", ctx) as rec:
        rec.bind_user(user)  # type: ignore[arg-type]
        user.detach()
        rec.note_json_response(json.dumps({"status": "ok", "warnings": [], "harness_next": "phase_2_ok"}))

    assert captured
    assert captured[-1]["user_id"] == str(uid)
    assert captured[-1]["outcome"] == "ok"


@pytest.mark.asyncio
async def test_flush_never_raises_into_tool_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Telemetry must not turn a successful tool return into internal_error."""
    from smeme.core.config import settings
    from smeme.mcp import invocation_telemetry as mod

    monkeypatch.setattr(settings, "mcp_invocation_telemetry_enabled", True)
    monkeypatch.setattr(settings, "mcp_invocation_telemetry_persist", False)

    def _boom(_msg: str, *, extra: dict | None = None) -> None:
        raise RuntimeError("structured log sink failed")

    monkeypatch.setattr(mod.logger, "info", _boom)

    ctx = MagicMock()
    result: str | None = None
    async with mcp_invocation_scope("smeme_reasoning_validate_answers", ctx) as rec:
        rec.bind_user(SimpleNamespace(id=uuid4()))
        rec.note_json_response(json.dumps({"status": "ok"}))
        result = "tool_ok"

    assert result == "tool_ok"


# ---------------------------------------------------------------------------
# bind_invocation_id — UPDATE flush path (A1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bind_invocation_id_triggers_update_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    """When invocation_id is bound, flush calls _update_invocation not _persist_invocation."""
    from unittest.mock import AsyncMock, patch
    from uuid import uuid4

    from smeme.core.config import settings
    from smeme.mcp import invocation_telemetry as mod

    monkeypatch.setattr(settings, "mcp_invocation_telemetry_enabled", True)
    monkeypatch.setattr(settings, "mcp_invocation_telemetry_persist", True)

    invocation_id = uuid4()

    with (
        patch.object(mod, "_update_invocation", new_callable=AsyncMock) as mock_update,
        patch.object(mod, "_persist_invocation", new_callable=AsyncMock) as mock_insert,
        patch.object(mod, "AsyncSessionLocal"),
    ):
        ctx = MagicMock()
        async with mcp_invocation_scope("smeme_reasoning_evaluate", ctx) as rec:
            rec.bind_user(SimpleNamespace(id=uuid4()))
            bind_invocation_id(invocation_id)
            rec.note_json_response(json.dumps({"report": {}}))

    mock_update.assert_awaited_once()
    mock_insert.assert_not_awaited()
    args = mock_update.call_args
    assert args[0][1] == invocation_id


@pytest.mark.asyncio
async def test_no_invocation_id_uses_insert_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without bind_invocation_id, flush falls back to INSERT (zero-weight tools)."""
    from unittest.mock import AsyncMock, patch
    from uuid import uuid4

    from smeme.core.config import settings
    from smeme.mcp import invocation_telemetry as mod

    monkeypatch.setattr(settings, "mcp_invocation_telemetry_enabled", True)
    monkeypatch.setattr(settings, "mcp_invocation_telemetry_persist", True)

    with (
        patch.object(mod, "_update_invocation", new_callable=AsyncMock) as mock_update,
        patch.object(mod, "_persist_invocation", new_callable=AsyncMock) as mock_insert,
        patch.object(mod, "AsyncSessionLocal"),
    ):
        ctx = MagicMock()
        async with mcp_invocation_scope("smeme_reasoning_list", ctx) as rec:
            rec.bind_user(SimpleNamespace(id=uuid4()))
            # No bind_invocation_id call
            rec.note_json_response(json.dumps({"decision_trees": []}))

    mock_insert.assert_awaited_once()
    mock_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_flush_zeroes_quota_weight_for_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock, patch
    from uuid import uuid4

    from smeme.core.config import settings
    from smeme.mcp import invocation_telemetry as mod

    monkeypatch.setattr(settings, "mcp_invocation_telemetry_enabled", True)
    monkeypatch.setattr(settings, "mcp_invocation_telemetry_persist", True)

    with (
        patch.object(mod, "_update_invocation", new_callable=AsyncMock) as mock_update,
        patch.object(mod, "AsyncSessionLocal"),
    ):
        ctx = MagicMock()
        async with mcp_invocation_scope("smeme_reasoning_evaluate", ctx) as rec:
            rec.bind_user(SimpleNamespace(id=uuid4()))
            bind_invocation_id(uuid4())
            rec.note_json_response(
                json.dumps({"error": {"code": "invalid_decision_tree_id", "message": "bad"}})
            )

    kwargs = mock_update.await_args.kwargs
    assert kwargs["outcome"] == "invalid_decision_tree_id"
    assert kwargs["quota_weight"] == 0.0
