"""Publish gate: DecisionTree validation → IR compile → validate_ir → conclusion SAT enumeration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from smeme.decision_tree.helpers.validation import validate_graph_for_publication
from smeme.decision_tree.models import DTGraph
from smeme.reasoning.dt_graph_bridge import compile_dt_graph_to_ir
from smeme.reasoning.graph_hash import canonical_graph_hash
from smeme.reasoning.ir.serialize import ir_to_json
from smeme.reasoning.ir.types import IR
from smeme.reasoning.ir.validate import validate_ir
from smeme.reasoning.runtime.analyze import (
    ConclusionSatQueryEnumeration,
    enumerate_conclusion_sat_queries,
)


@dataclass(frozen=True, slots=True)
class PreflightIssue:
    """Single user-facing preflight blocker."""

    code: str
    message: str


@dataclass
class PublishReadiness:
    """Result of pre-publish checks (no DB writes)."""

    ready: bool
    validation_errors: list[str] = field(default_factory=list)
    compile_error: str | None = None
    ir: IR | None = None
    ir_json: dict | None = None
    graph_hash: str | None = None
    enumeration: ConclusionSatQueryEnumeration | None = None
    preflight_issues: list[PreflightIssue] = field(default_factory=list)

    @property
    def structural_issues(self) -> list[PreflightIssue]:
        """Deprecated template alias; use ``preflight_issues``."""
        return self.preflight_issues


def assess_publish_readiness_sync(graph: DTGraph) -> PublishReadiness:
    """Run the publish gate synchronously (CPU-bound; prefer :func:`assess_publish_readiness` in async code)."""
    ok, errors = validate_graph_for_publication(graph)
    if not ok:
        return PublishReadiness(ready=False, validation_errors=list(errors))

    try:
        ir = compile_dt_graph_to_ir(graph)
    except ValueError:
        return PublishReadiness(
            ready=False,
            compile_error=(
                "Your workflow has a configuration issue that prevented deployment. "
                "Fix any errors shown above, then try again."
            ),
        )

    report = validate_ir(ir)
    if not report.valid:
        return PublishReadiness(
            ready=False,
            compile_error=(
                "One or more workflow rules could not be verified. "
                "Check that all questions and answers are configured correctly."
            ),
        )

    gh = canonical_graph_hash(graph)
    ir_json = ir_to_json(ir)

    enumeration = enumerate_conclusion_sat_queries(ir, validate=False)
    issues: list[PreflightIssue] = []

    if not enumeration.is_theory_satisfiable:
        issues.append(
            PreflightIssue(
                code="THEORY_UNSAT",
                message="The decision tree’s branching rules cannot all be satisfied together.",
            )
        )

    dead: list[str] = []
    for cid, reachable in enumeration.conclusion_reachable.items():
        if not reachable:
            dead.append(cid)
            issues.append(
                PreflightIssue(
                    code="DEAD_CONCLUSION",
                    message=f"Conclusion {cid!r} cannot be reached under the published rules.",
                )
            )

    ready = enumeration.is_theory_satisfiable and len(dead) == 0

    return PublishReadiness(
        ready=ready,
        ir=ir,
        ir_json=ir_json,
        graph_hash=gh,
        enumeration=enumeration,
        preflight_issues=issues,
    )


async def assess_publish_readiness(graph: DTGraph) -> PublishReadiness:
    """Async wrapper (Z3 work runs off the event loop)."""
    return await asyncio.to_thread(assess_publish_readiness_sync, graph)
