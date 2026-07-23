"""MCP tool invocation metering and cost telemetry.

Persists one row per authenticated MCP tool call (after ``get_mcp_user``) and emits a
structured log line for aggregation in Render/Datadog/etc.

**Operator guide:** ``docs/guides/mcp-cost-telemetry.md``
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from smeme.core.config import settings
from smeme.core.database import AsyncSessionLocal
from smeme.core.logging import get_logger
from smeme.core.models import User
from smeme.mcp.bearer_auth import oauth_client_id_from_clerk_access_payload
from smeme.mcp.models import McpToolInvocation
from smeme.reasoning.runtime.ingest_codes import IngestErrorCode

logger = get_logger(__name__)

# Stable logical metric for log routers (dashboards: smeme_mcp_tool_invocation_total).
MCP_TOOL_INVOCATION_LOG_METRIC = "smeme_mcp_tool_invocation_total"

# Customer-facing plan allowance weights. See docs/guides/mcp-cost-telemetry.md.
DEFAULT_QUOTA_WEIGHT_BY_TOOL: dict[str, float] = {
    "smeme_reasoning_capabilities": 0.0,
    "smeme_reasoning_list": 0.0,
    "smeme_reasoning_validate_answers": 1.0,
    "smeme_reasoning_evaluate": 1.0,
    "smeme_reasoning_what_if": 2.0,
    "smeme_reasoning_how_to_reach": 2.5,
    "smeme_reasoning_decisive_support": 2.0,
    "smeme_reasoning_edit_affects_path": 2.0,
    "smeme_reasoning_list_conclusions": 0.0,
    "smeme_reasoning_template_check": 0.0,
    "smeme_reasoning_template_get": 0.0,
    "smeme_reasoning_guidance_check": 0.0,
    "smeme_reasoning_guidance_get": 0.0,
    "smeme_authoring_design_guidance": 0.0,
    "smeme_authoring_validate_graph": 0.0,
    "smeme_authoring_create_draft": 0.0,
}

# Internal COGS unit multipliers (ops / margin analysis — not shown on landing).
# ``what_if`` ≈ two evaluates + diff overhead → 2.2; quota is rounded to 2.0.
INTERNAL_COST_UNITS_BY_TOOL: dict[str, float] = {
    "smeme_reasoning_capabilities": 0.0,
    "smeme_reasoning_list": 0.0,
    "smeme_reasoning_validate_answers": 0.3,
    "smeme_reasoning_evaluate": 1.0,
    "smeme_reasoning_what_if": 2.2,
    "smeme_reasoning_how_to_reach": 3.0,
    "smeme_reasoning_decisive_support": 2.2,
    "smeme_reasoning_edit_affects_path": 2.0,
    "smeme_reasoning_list_conclusions": 0.2,
    "smeme_reasoning_template_check": 0.0,
    "smeme_reasoning_template_get": 0.0,
    "smeme_reasoning_guidance_check": 0.0,
    "smeme_reasoning_guidance_get": 0.0,
    "smeme_authoring_design_guidance": 0.0,
    "smeme_authoring_validate_graph": 0.0,
    "smeme_authoring_create_draft": 0.1,
}

_active_recorder: ContextVar[McpInvocationRecorder | None] = ContextVar(
    "mcp_invocation_recorder", default=None
)

# Hybrid outcome policy (A3-C): bill server work; client mistakes free.
# Rows still persist for ops; ``quota_weight`` is zeroed on flush for these outcomes.
MCP_CLIENT_ERROR_OUTCOMES: frozenset[str] = frozenset(
    {
        "invalid_decision_tree_id",
        "invalid_answers_json",
        "invalid_evidence_blob_json",
        "not_found",
        "not_discoverable",
        "no_reasoning_artifact",
        "no_compiled_theory",
        "account_downgrade_pending",
        "payload_too_large",
        *(code.value for code in IngestErrorCode),
    }
)


def quota_weight_for_tool(tool_name: str) -> float:
    """Billable units for one invocation (0 = metered for ops but not against allowance).

    Unknown tool names return 0.0 and emit a warning (A0-d).  Returning 1.0 for unknown
    tools could silently over-bill users; 0.0 is safe-for-users while making the gap visible
    in the ``unknown_mcp_tool_for_quota`` log metric.
    """
    weight = DEFAULT_QUOTA_WEIGHT_BY_TOOL.get(tool_name)
    if weight is None:
        logger.warning(
            "unknown_mcp_tool_for_quota",
            extra={"tool_name": tool_name, "quota_weight": 0.0},
        )
        return 0.0
    return float(weight)


def effective_quota_weight_for_outcome(*, tool_name: str, outcome: str) -> float:
    """Customer-facing allowance units after hybrid outcome policy (A3-C)."""
    base = quota_weight_for_tool(tool_name)
    if base <= 0:
        return 0.0
    if outcome in MCP_CLIENT_ERROR_OUTCOMES:
        return 0.0
    return base


def internal_cost_units_for_tool(tool_name: str) -> float:
    """Server-side COGS multiplier for margin analysis (may differ from quota_weight)."""
    return float(INTERNAL_COST_UNITS_BY_TOOL.get(tool_name, 1.0))


def estimate_cost_usd_micros(
    *,
    duration_ms: int,
    reasoning_ms: int | None,
    tool_name: str,
) -> int:
    """Rough internal COGS estimate in micro-dollars (1 USD = 1_000_000 micros).

    Calibrate ``mcp_cost_baseline_usd_micros`` and ``mcp_cost_usd_micros_per_second`` from
    production p50 wall time once telemetry has ~2 weeks of data. Scaled by
    :func:`internal_cost_units_for_tool` so ``what_if`` (~2.2× evaluate work) is visible
    in ops dashboards even when quota_weight is 2.0.
    """
    baseline = settings.mcp_cost_baseline_usd_micros
    per_second = settings.mcp_cost_usd_micros_per_second
    wall_seconds = max(duration_ms, 0) / 1000.0
    kernel_seconds = max(reasoning_ms or 0, 0) / 1000.0
    # Weight kernel slightly higher (Z3 CPU) than non-reasoning handler work.
    raw = baseline + (wall_seconds * per_second) + (kernel_seconds * per_second * 0.5)
    return int(raw * internal_cost_units_for_tool(tool_name))


def outcome_from_tool_json(response: str) -> str:
    """Parse tool JSON string; return ``ok`` or ``error.code``."""
    try:
        payload = json.loads(response)
    except json.JSONDecodeError:
        return "invalid_tool_json"
    if not isinstance(payload, dict):
        return "invalid_tool_json"
    err = payload.get("error")
    if isinstance(err, dict):
        code = err.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip()
    return "ok"


class McpInvocationRecorder:
    """Per-request collector; attach via :func:`mcp_invocation_scope`."""

    __slots__ = (
        "_invocation_id",
        "_oauth_client_id",
        "_outcome",
        "_decision_tree_id",
        "_reasoning_ms",
        "_size",
        "_start",
        "_user_id",
        "cost_metadata",
        "tool_name",
    )

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        self._start = time.perf_counter()
        self._user_id: UUID | None = None
        self._invocation_id: UUID | None = None
        self._oauth_client_id: str | None = None
        self._decision_tree_id: UUID | None = None
        self._outcome: str | None = None
        self._reasoning_ms: int | None = None
        self._size: dict[str, int] = {}
        self.cost_metadata: dict[str, Any] = {}

    @property
    def duration_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)

    def bind_user(self, user: User) -> None:
        # Snapshot id now: tool bodies may ``rollback()``/close the auth session before flush.
        self._user_id = user.id

    def bind_invocation_id(self, invocation_id: UUID) -> None:
        """Store the reserved row UUID so flush() UPDATEs instead of INSERTs."""
        self._invocation_id = invocation_id

    def note_oauth_client_id(self, oauth_client_id: str | None) -> None:
        if oauth_client_id and oauth_client_id.strip():
            self._oauth_client_id = oauth_client_id.strip()

    def note_decision_tree_id(self, decision_tree_id: UUID | str | None) -> None:
        if decision_tree_id is None:
            return
        try:
            self._decision_tree_id = decision_tree_id if isinstance(decision_tree_id, UUID) else UUID(str(decision_tree_id))
        except (TypeError, ValueError):
            return

    def note_ir_shape(
        self,
        *,
        question_count: int | None = None,
        edge_count: int | None = None,
        answered_count: int | None = None,
    ) -> None:
        if question_count is not None:
            self._size["question_count"] = question_count
        if edge_count is not None:
            self._size["edge_count"] = edge_count
        if answered_count is not None:
            self._size["answered_count"] = answered_count

    def note_reasoning_ms(self, reasoning_ms: int) -> None:
        self._reasoning_ms = max(reasoning_ms, 0)

    def note_sat_calls(self, sat_calls: int) -> None:
        if sat_calls >= 0:
            self.cost_metadata["sat_calls"] = sat_calls

    def note_json_response(self, response: str) -> None:
        self._outcome = outcome_from_tool_json(response)

    def note_outcome(self, outcome: str) -> None:
        self._outcome = outcome

    async def flush(self, ctx: Context | None) -> None:
        """Emit structured log + optional DB row. Must never raise into tool handlers."""
        if self._user_id is None:
            return
        if not settings.mcp_invocation_telemetry_enabled:
            return
        try:
            if self._outcome is None:
                logger.warning(
                    "MCP invocation telemetry missing outcome; using unknown",
                    extra={"tool_name": self.tool_name, "user_id": str(self._user_id)},
                )
            outcome = self._outcome or "unknown"
            quota_weight = effective_quota_weight_for_outcome(
                tool_name=self.tool_name,
                outcome=outcome,
            )
            internal_cost_units = internal_cost_units_for_tool(self.tool_name)
            duration_ms = self.duration_ms
            reasoning_ms = self._reasoning_ms
            cost_metadata = dict(self.cost_metadata)
            cost_metadata.setdefault("internal_cost_units", internal_cost_units)
            cost_micros = estimate_cost_usd_micros(
                duration_ms=duration_ms,
                reasoning_ms=reasoning_ms,
                tool_name=self.tool_name,
            )
            oauth_client_id = self._oauth_client_id
            if oauth_client_id is None and ctx is not None:
                oauth_client_id = _oauth_client_id_from_request(request_from_mcp_context(ctx))

            row_kwargs: dict[str, Any] = {
                "user_id": self._user_id,
                "tool_name": self.tool_name,
                "outcome": outcome,
                "decision_tree_id": self._decision_tree_id,
                "oauth_client_id": oauth_client_id,
                "duration_ms": duration_ms,
                "reasoning_ms": reasoning_ms,
                "question_count": self._size.get("question_count"),
                "edge_count": self._size.get("edge_count"),
                "answered_count": self._size.get("answered_count"),
                "sat_calls": self.cost_metadata.get("sat_calls"),
                "quota_weight": quota_weight,
                "estimated_cost_usd_micros": cost_micros,
                "cost_metadata": cost_metadata,
            }

            log_payload = {
                "reasoning_metric": MCP_TOOL_INVOCATION_LOG_METRIC,
                "tool_name": self.tool_name,
                "outcome": outcome,
                "user_id": str(self._user_id),
                "decision_tree_id": str(self._decision_tree_id) if self._decision_tree_id else None,
                "duration_ms": duration_ms,
                "reasoning_ms": reasoning_ms,
                "quota_weight": quota_weight,
                "internal_cost_units": internal_cost_units,
                "estimated_cost_usd_micros": cost_micros,
                "oauth_client_id": oauth_client_id,
                **self._size,
            }
            logger.info("mcp_tool_invocation", extra=log_payload)

            if not settings.mcp_invocation_telemetry_persist:
                return

            try:
                async with AsyncSessionLocal() as db:
                    if self._invocation_id is not None:
                        await _update_invocation(db, self._invocation_id, **row_kwargs)
                    else:
                        await _persist_invocation(db, **row_kwargs)
            except Exception:
                # Stable metric key for log routers / alerting (A0-e).
                logger.warning(
                    "mcp_invocation_persist_failed_total",
                    extra={"tool_name": self.tool_name, "user_id": str(self._user_id)},
                    exc_info=True,
                )
        except Exception:
            logger.warning(
                "MCP invocation telemetry flush failed",
                extra={"tool_name": self.tool_name, "user_id": str(self._user_id)},
                exc_info=True,
            )


def get_active_mcp_recorder() -> McpInvocationRecorder | None:
    return _active_recorder.get()


def bind_invocation_id(invocation_id: UUID) -> None:
    """Store the reserved row UUID on the active recorder so flush() UPDATEs it."""
    rec = _active_recorder.get()
    if rec is not None:
        rec.bind_invocation_id(invocation_id)


def bind_mcp_user(
    user: User,
    *,
    oauth_client_id: str | None = None,
    request: Request | None = None,
) -> None:
    """Call after ``get_mcp_user`` inside a tool body to attach identity for flush.

    Snapshots ``user.id`` and (when available) OAuth client id while the auth session
    is still open — tool bodies may close/rollback the session before telemetry flush.
    """
    rec = _active_recorder.get()
    if rec is None:
        return
    rec.bind_user(user)
    if oauth_client_id:
        rec.note_oauth_client_id(oauth_client_id)
    elif request is not None:
        rec.note_oauth_client_id(_oauth_client_id_from_request(request))


@asynccontextmanager
async def mcp_invocation_scope(
    tool_name: str, ctx: Context
) -> AsyncIterator[McpInvocationRecorder]:
    """Wrap an MCP tool handler; records telemetry when ``bind_mcp_user`` was called."""
    rec = McpInvocationRecorder(tool_name)
    token = _active_recorder.set(rec)
    try:
        yield rec
    except Exception:
        # Outer tool wrappers convert this to ``internal_error`` JSON after the scope exits;
        # record the stable code here so flush does not emit ``unknown``.
        if rec._outcome is None:
            rec.note_outcome("internal_error")
        raise
    finally:
        _active_recorder.reset(token)
        await rec.flush(ctx)


async def _persist_invocation(db: AsyncSession, **kwargs: Any) -> None:
    row = McpToolInvocation(**kwargs)
    db.add(row)
    await db.commit()


async def _update_invocation(db: AsyncSession, invocation_id: UUID, **kwargs: Any) -> None:
    """UPDATE the reserved row written by reserve_mcp_quota with real outcome + timing."""
    # Drop fields that were already set correctly at reserve time and must not change.
    kwargs.pop("user_id", None)
    kwargs.pop("tool_name", None)
    # ``quota_weight`` may be zeroed on flush for client-error outcomes (A3-C).
    await db.execute(
        update(McpToolInvocation).where(McpToolInvocation.id == invocation_id).values(**kwargs)
    )
    await db.commit()


def request_from_mcp_context(ctx: Context | None) -> Request | None:
    """Starlette request from FastMCP ``Context`` (``request_context.request``, not ``ctx.request``)."""
    if ctx is None:
        return None
    request_context = getattr(ctx, "request_context", None)
    if request_context is None:
        return None
    request = getattr(request_context, "request", None)
    return request if isinstance(request, Request) else None


def _oauth_client_id_from_request(request: Request | None) -> str | None:
    """Read OAuth app id cached by :func:`cache_oauth_client_id_on_request` in ``get_mcp_user``."""
    if request is None:
        return None
    state = getattr(request, "state", None)
    if state is None:
        return None
    cached = getattr(state, "mcp_oauth_client_id", None)
    if isinstance(cached, str) and cached.strip():
        return cached.strip()
    return None


def cache_oauth_client_id_on_request(request: Request, payload: dict[str, Any]) -> None:
    """Store resolved OAuth client id on request.state for telemetry (no second JWT parse)."""
    cid = oauth_client_id_from_clerk_access_payload(payload)
    if cid:
        request.state.mcp_oauth_client_id = cid


__all__ = [
    "DEFAULT_QUOTA_WEIGHT_BY_TOOL",
    "INTERNAL_COST_UNITS_BY_TOOL",
    "MCP_CLIENT_ERROR_OUTCOMES",
    "MCP_TOOL_INVOCATION_LOG_METRIC",
    "McpInvocationRecorder",
    "bind_invocation_id",
    "bind_mcp_user",
    "cache_oauth_client_id_on_request",
    "effective_quota_weight_for_outcome",
    "estimate_cost_usd_micros",
    "get_active_mcp_recorder",
    "internal_cost_units_for_tool",
    "mcp_invocation_scope",
    "outcome_from_tool_json",
    "quota_weight_for_tool",
    "request_from_mcp_context",
]
