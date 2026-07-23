"""Wizard generation funnel telemetry (Spike 1).

Persists structured events for drop-off analysis. Events are append-only;
recording failures are logged and never block the wizard.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.logging import get_logger
from smeme.decision_tree.models import WizardGenerationEvent

logger = get_logger(__name__)

WizardEventType = Literal[
    "wizard.phase.enter",
    "wizard.phase.submit",
    "wizard.phase.error",
    "wizard.abandon",
    "wizard.complete",
]

WizardPhase = Literal["brief", "research", "conclusions", "design", "build"]

WIZARD_SUCCESS_STATUSES = frozenset({"valid", "valid_with_warnings"})

SPIKE2_MIN_COMPLETIONS = 50
SPIKE2_MIN_DAYS = 7


class WizardPhaseTimer:
    """Wall-clock timer for route handler latency."""

    __slots__ = ("_start",)

    def __init__(self) -> None:
        self._start = time.perf_counter()

    @property
    def duration_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)


async def record_wizard_event(
    db: AsyncSession,
    *,
    user_id: UUID,
    event_type: WizardEventType,
    phase: WizardPhase | Literal["complete"],
    thread_id: str | None = None,
    generation_id: UUID | None = None,
    duration_ms: int | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist one wizard telemetry event (best-effort, independent commit)."""
    event_metadata = dict(metadata or {})
    if error_message:
        event_metadata["error_message"] = error_message[:500]

    event = WizardGenerationEvent(
        user_id=user_id,
        thread_id=thread_id,
        generation_id=generation_id,
        event_type=event_type,
        phase=phase,
        duration_ms=duration_ms,
        event_metadata=event_metadata,
    )

    try:
        db.add(event)
        await db.commit()
        logger.info(
            "wizard telemetry",
            extra={
                "event_type": event_type,
                "phase": phase,
                "user_id": str(user_id),
                "thread_id": thread_id,
                "duration_ms": duration_ms,
            },
        )
    except Exception:
        await db.rollback()
        logger.warning(
            "Failed to record wizard telemetry event",
            extra={
                "event_type": event_type,
                "phase": phase,
                "user_id": str(user_id),
                "thread_id": thread_id,
            },
            exc_info=True,
        )


async def track_phase_enter(
    db: AsyncSession,
    *,
    user_id: UUID,
    phase: WizardPhase,
    thread_id: str | None = None,
    generation_id: UUID | None = None,
    **metadata: Any,
) -> None:
    await record_wizard_event(
        db,
        user_id=user_id,
        event_type="wizard.phase.enter",
        phase=phase,
        thread_id=thread_id,
        generation_id=generation_id,
        metadata=metadata or None,
    )


async def track_phase_submit(
    db: AsyncSession,
    *,
    user_id: UUID,
    phase: WizardPhase,
    thread_id: str,
    duration_ms: int,
    generation_id: UUID | None = None,
    **metadata: Any,
) -> None:
    await record_wizard_event(
        db,
        user_id=user_id,
        event_type="wizard.phase.submit",
        phase=phase,
        thread_id=thread_id,
        generation_id=generation_id,
        duration_ms=duration_ms,
        metadata=metadata or None,
    )


async def track_phase_error(
    db: AsyncSession,
    *,
    user_id: UUID,
    phase: WizardPhase,
    thread_id: str | None,
    duration_ms: int | None = None,
    error_message: str | None = None,
    generation_id: UUID | None = None,
    **metadata: Any,
) -> None:
    await record_wizard_event(
        db,
        user_id=user_id,
        event_type="wizard.phase.error",
        phase=phase,
        thread_id=thread_id,
        generation_id=generation_id,
        duration_ms=duration_ms,
        error_message=error_message,
        metadata=metadata or None,
    )


def wizard_completion_counts_toward_quota(metadata: dict[str, Any] | None) -> bool:
    """Return whether a ``wizard.complete`` row should consume a monthly build credit."""
    meta = metadata or {}
    final_status = meta.get("final_status")
    if final_status is None:
        return True
    return final_status in WIZARD_SUCCESS_STATUSES


async def track_wizard_complete(
    db: AsyncSession,
    *,
    user_id: UUID,
    thread_id: str,
    duration_ms: int | None = None,
    decision_tree_id: str | None = None,
    generation_id: UUID | None = None,
    **metadata: Any,
) -> None:
    meta = dict(metadata or {})
    if decision_tree_id:
        meta["decision_tree_id"] = decision_tree_id
    if not wizard_completion_counts_toward_quota(meta):
        return
    await record_wizard_event(
        db,
        user_id=user_id,
        event_type="wizard.complete",
        phase="complete",
        thread_id=thread_id,
        generation_id=generation_id,
        duration_ms=duration_ms,
        metadata=meta,
    )


async def track_wizard_abandon(
    db: AsyncSession,
    *,
    user_id: UUID,
    thread_id: str,
    phase: str,
    reason: str,
    generation_id: UUID | None = None,
) -> None:
    wizard_phase: WizardPhase | Literal["complete"]
    if phase in ("research", "conclusions", "design", "build", "brief"):
        wizard_phase = phase  # type: ignore[assignment]
    else:
        wizard_phase = "research"
    await record_wizard_event(
        db,
        user_id=user_id,
        event_type="wizard.abandon",
        phase=wizard_phase,
        thread_id=thread_id,
        generation_id=generation_id,
        metadata={"reason": reason, "last_phase": phase},
    )


async def delete_wizard_events_older_than(db: AsyncSession, *, days: int = 90) -> int:
    """Delete wizard telemetry rows older than ``days`` (default 90).

    Cutoff is computed in Python and bound as timestamptz — do not interpolate
    interval literals into SQL.
    """
    if not isinstance(days, int) or days <= 0:
        msg = f"days must be a positive integer, got {days!r}"
        raise ValueError(msg)

    cutoff_at = datetime.now(UTC) - timedelta(days=days)
    stmt = delete(WizardGenerationEvent).where(WizardGenerationEvent.created_at < cutoff_at)
    result = await db.execute(stmt)
    await db.commit()
    deleted = result.rowcount or 0

    if deleted > 0:
        logger.info(
            "Deleted old wizard telemetry events",
            extra={"wizard_events_deleted": deleted, "cutoff_at": cutoff_at.isoformat()},
        )
    return deleted


async def get_drop_off_report(db: AsyncSession) -> dict[str, Any]:
    """Aggregate funnel metrics for operator review."""
    now = datetime.now(UTC)

    counts_stmt = (
        select(
            WizardGenerationEvent.event_type,
            WizardGenerationEvent.phase,
            func.count().label("count"),
        )
        .group_by(WizardGenerationEvent.event_type, WizardGenerationEvent.phase)
        .order_by(WizardGenerationEvent.phase, WizardGenerationEvent.event_type)
    )
    counts_result = await db.execute(counts_stmt)
    event_counts = [
        {"event_type": row.event_type, "phase": row.phase, "count": row.count}
        for row in counts_result.all()
    ]

    phases: list[WizardPhase] = ["brief", "research", "conclusions", "design", "build"]
    funnel: list[dict[str, Any]] = []
    for phase in phases:
        enter = _count_for(event_counts, "wizard.phase.enter", phase)
        submit = _count_for(event_counts, "wizard.phase.submit", phase)
        errors = _count_for(event_counts, "wizard.phase.error", phase)
        drop_off = max(0, enter - submit) if enter else 0
        drop_off_pct = round(100.0 * drop_off / enter, 1) if enter else 0.0
        funnel.append(
            {
                "phase": phase,
                "enters": enter,
                "submits": submit,
                "errors": errors,
                "drop_off": drop_off,
                "drop_off_pct": drop_off_pct,
            }
        )

    completions = _count_for(event_counts, "wizard.complete", "complete")
    abandons = sum(row["count"] for row in event_counts if row["event_type"] == "wizard.abandon")

    first_event_stmt = select(func.min(WizardGenerationEvent.created_at))
    first_event = (await db.execute(first_event_stmt)).scalar_one_or_none()
    days_collecting = (now - first_event).days if first_event else 0

    spike2_ready = completions >= SPIKE2_MIN_COMPLETIONS or days_collecting >= SPIKE2_MIN_DAYS

    latency_stmt = (
        select(
            WizardGenerationEvent.phase,
            func.avg(WizardGenerationEvent.duration_ms).label("avg_ms"),
            func.max(WizardGenerationEvent.duration_ms).label("max_ms"),
            func.count(WizardGenerationEvent.duration_ms).label("samples"),
        )
        .where(
            WizardGenerationEvent.event_type == "wizard.phase.submit",
            WizardGenerationEvent.duration_ms.is_not(None),
        )
        .group_by(WizardGenerationEvent.phase)
    )
    latency_rows = (await db.execute(latency_stmt)).all()
    latency_by_phase = [
        {
            "phase": row.phase,
            "avg_ms": int(row.avg_ms) if row.avg_ms is not None else None,
            "max_ms": row.max_ms,
            "samples": row.samples,
        }
        for row in latency_rows
    ]

    return {
        "generated_at": now.isoformat(),
        "event_counts": event_counts,
        "funnel_by_phase": funnel,
        "completions": completions,
        "abandons": abandons,
        "days_collecting": days_collecting,
        "spike2_gate": {
            "ready_to_re_rank": spike2_ready,
            "min_completions": SPIKE2_MIN_COMPLETIONS,
            "min_days": SPIKE2_MIN_DAYS,
            "completions": completions,
            "days_collecting": days_collecting,
        },
        "submit_latency_by_phase": latency_by_phase,
    }


def _count_for(
    rows: list[dict[str, Any]],
    event_type: str,
    phase: str,
) -> int:
    for row in rows:
        if row["event_type"] == event_type and row["phase"] == phase:
            return int(row["count"])
    return 0
