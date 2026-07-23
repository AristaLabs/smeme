"""Structured logging for reasoning ingest hard rejects (M0 / D018).

Operators can aggregate on ``reasoning_metric`` + ``ingest_error_code`` in log pipelines.
There is **no** ``reasoning_evaluation_runs`` row for these failures.

**Logical metric name (document for dashboards):** ``smeme_reasoning_ingest_reject_total``
(label dimensions: ``ingest_error_code``, optionally ``decision_tree_id``).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

# Stable identifier for log/metric routing (T5).
REASONING_INGEST_REJECT_LOG_METRIC = "smeme_reasoning_ingest_reject_total"


def log_reasoning_ingest_hard_reject(
    logger: logging.Logger,
    *,
    code: str,
    message: str,
    decision_tree_id: UUID | str | None = None,
    caller_user_id: UUID | str | None = None,
    transport: str = "unknown",
    **extra: Any,
) -> None:
    """Emit one structured warning log line per hard reject (parse + ingest gate)."""
    payload: dict[str, Any] = {
        "reasoning_metric": REASONING_INGEST_REJECT_LOG_METRIC,
        "ingest_error_code": code,
        "error_message": message,
        "transport": transport,
    }
    if decision_tree_id is not None:
        payload["decision_tree_id"] = str(decision_tree_id)
    if caller_user_id is not None:
        payload["caller_user_id"] = str(caller_user_id)
    payload.update(extra)
    logger.warning("reasoning_ingest_hard_reject", extra=payload)


__all__ = [
    "REASONING_INGEST_REJECT_LOG_METRIC",
    "log_reasoning_ingest_hard_reject",
]
