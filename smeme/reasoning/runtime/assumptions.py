"""Shared reachability assumptions φ for evaluate / what_if / how_to_reach.

Product vocabulary uses IR node ids (worksheet / list_conclusions). Internally
this is force/forbid ``reach(n)`` over the compiled theory — see ALGEBRA.md §18.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from z3 import BoolRef, Not

from smeme.reasoning.ir.types import IR

MAX_ASSUMPTION_NODE_IDS = 32


class AssumptionsError(Exception):
    """Domain failure with stable MCP ``error.code``."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


@dataclass(frozen=True)
class ReasoningAssumptions:
    """Quantifier-free reach constraints layered on ``T ∧ E``."""

    force_reachable: frozenset[str] = frozenset()
    force_unreachable: frozenset[str] = frozenset()

    def is_empty(self) -> bool:
        return not self.force_reachable and not self.force_unreachable

    def to_wire(self) -> dict[str, list[str]] | None:
        if self.is_empty():
            return None
        return {
            "force_reachable_ids": sorted(self.force_reachable),
            "force_unreachable_ids": sorted(self.force_unreachable),
        }


EMPTY_ASSUMPTIONS = ReasoningAssumptions()


def assumptions_from_lists(
    force_reachable_ids: list[str] | None = None,
    force_unreachable_ids: list[str] | None = None,
) -> ReasoningAssumptions:
    """Build assumptions from MCP list parameters (empty / None → identity)."""
    fr = frozenset(_normalize_id_list(force_reachable_ids))
    fu = frozenset(_normalize_id_list(force_unreachable_ids))
    if not fr and not fu:
        return EMPTY_ASSUMPTIONS
    return ReasoningAssumptions(force_reachable=fr, force_unreachable=fu)


def _normalize_id_list(ids: list[str] | None) -> list[str]:
    if not ids:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in ids:
        if raw is None:
            continue
        nid = str(raw).strip()
        if not nid or nid in seen:
            continue
        seen.add(nid)
        out.append(nid)
    return out


def validate_assumptions(ir: IR, assumptions: ReasoningAssumptions) -> None:
    """Raise ``AssumptionsError`` if ids are unknown, conflicting, or over cap."""
    if assumptions.is_empty():
        return

    total = len(assumptions.force_reachable) + len(assumptions.force_unreachable)
    if total > MAX_ASSUMPTION_NODE_IDS:
        raise AssumptionsError(
            "assumptions_cap_exceeded",
            f"At most {MAX_ASSUMPTION_NODE_IDS} assumption node ids are allowed "
            f"(got {total}). Narrow force_reachable_ids / force_unreachable_ids.",
            max_ids=MAX_ASSUMPTION_NODE_IDS,
            got=total,
        )

    conflict = assumptions.force_reachable & assumptions.force_unreachable
    if conflict:
        sample = sorted(conflict)[0]
        raise AssumptionsError(
            "conflicting_assumptions",
            f'Node id "{sample}" appears in both force_reachable_ids and '
            "force_unreachable_ids. Remove it from one list.",
            conflicting_ids=sorted(conflict),
        )

    known = {n.id for n in ir.nodes}
    for nid in sorted(assumptions.force_reachable | assumptions.force_unreachable):
        if nid not in known:
            raise AssumptionsError(
                "invalid_assumption_node_id",
                f'Assumption node id "{nid}" is not on this published workflow. '
                "Use question ids from smeme_reasoning_template_get or conclusion ids "
                "from smeme_reasoning_list_conclusions.",
                node_id=nid,
            )


def apply_assumptions_to_solver(
    solver: Any,
    reach: dict[str, BoolRef],
    assumptions: ReasoningAssumptions,
) -> None:
    """Assert force/forbid reach literals on an already-compiled solver."""
    if assumptions.is_empty():
        return
    for nid in sorted(assumptions.force_reachable):
        solver.add(reach[nid])
    for nid in sorted(assumptions.force_unreachable):
        solver.add(Not(reach[nid]))


__all__ = [
    "EMPTY_ASSUMPTIONS",
    "MAX_ASSUMPTION_NODE_IDS",
    "AssumptionsError",
    "ReasoningAssumptions",
    "apply_assumptions_to_solver",
    "assumptions_from_lists",
    "validate_assumptions",
]
