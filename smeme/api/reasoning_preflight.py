"""JSON API: reasoning preflight (publish gate — IR + SAT enumeration)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.auth.users import current_active_user
from smeme.core.database import get_db
from smeme.core.models import QNR, User
from smeme.qnr.helpers.db_queries import parse_graph_data
from smeme.reasoning.ir.types import IR_FORMAT_VERSION
from smeme.reasoning.publish_readiness import assess_publish_readiness
from smeme.reasoning.version import REASONING_COMPILER_VERSION

router = APIRouter(prefix="/qnr", tags=["reasoning-preflight"])


def _envelope_ok(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "ok",
        "code": "OK",
        "message": "Preflight completed.",
        "warnings": [],
        "errors": [],
        "summary": summary,
        "artifacts": {},
    }


def _issues_to_errors(readiness) -> list[dict[str, str]]:
    return [{"code": i.code, "message": i.message} for i in readiness.preflight_issues]


@router.get("/{qnr_id}/reasoning/preflight", summary="Reasoning preflight (publish gate)")
@router.post("/{qnr_id}/reasoning/preflight", summary="Reasoning preflight (POST)")
async def reasoning_preflight(
    qnr_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(QNR).where(QNR.id == qnr_id))
    qnr = result.scalar_one_or_none()
    if not qnr or qnr.author_id != user.id:
        raise HTTPException(status_code=404, detail="QNR not found")

    try:
        graph = parse_graph_data(qnr)
    except ValidationError as e:
        return {
            "status": "failed",
            "code": "QNR_VALIDATION_FAILED",
            "message": "Graph failed schema validation.",
            "warnings": [],
            "errors": e.errors(),
            "summary": {},
            "artifacts": {},
        }

    readiness = await assess_publish_readiness(graph)

    dead: list[str] = []
    if readiness.enumeration:
        dead = [cid for cid, ok in readiness.enumeration.conclusion_reachable.items() if not ok]
    if readiness.enumeration:
        pairs = [
            {"a": a, "b": b}
            for (a, b), ok in readiness.enumeration.conclusion_pairs_co_reachable.items()
            if ok
        ]
    else:
        pairs = []

    summary = {
        "is_publishable": readiness.ready,
        "is_theory_satisfiable": (
            readiness.enumeration.is_theory_satisfiable if readiness.enumeration else False
        ),
        "dead_conclusion_ids": dead,
        "co_reachable_pairs": pairs,
        "compiler_version": REASONING_COMPILER_VERSION,
        "ir_format_version": IR_FORMAT_VERSION,
        "graph_hash": readiness.graph_hash,
    }

    if readiness.validation_errors:
        return {
            "status": "failed",
            "code": "QNR_VALIDATION_FAILED",
            "message": "Graph validation failed.",
            "warnings": [],
            "errors": readiness.validation_errors,
            "summary": summary,
            "artifacts": {},
        }

    if readiness.compile_error:
        code = (
            "IR_VALIDATION_FAILED"
            if "IR validation" in (readiness.compile_error or "")
            else "REASONING_EVALUATION_FAILED"
        )
        return {
            "status": "failed",
            "code": code,
            "message": readiness.compile_error,
            "warnings": [],
            "errors": [],
            "summary": summary,
            "artifacts": {},
        }

    if not readiness.ready:
        codes: list[str] = []
        if readiness.enumeration and not readiness.enumeration.is_theory_satisfiable:
            codes.append("THEORY_UNSAT")
        if dead:
            codes.append("DEAD_CONCLUSIONS_PRESENT")
        err_code = codes[0] if codes else "REASONING_EVALUATION_FAILED"
        return {
            "status": "failed",
            "code": err_code,
            "message": "Publish preflight checks failed.",
            "warnings": [],
            "errors": _issues_to_errors(readiness),
            "summary": summary,
            "artifacts": {},
        }

    return _envelope_ok(summary)
