"""Generation-path branching quality assessment (Track A).

Structural graph validation lives in ``smeme.qnr.helpers.validation``.
This module detects valid-but-weak topology: funnel trees, fake branching, etc.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from smeme.qnr.models import DTGraph

BRANCHING_QUALITY_PREFIX = "Branching quality:"

EARLY_GATE_NODE_IDS = ("q1", "q2", "q3")
PREFIX_FUNNEL_CHAIN = ("q1", "q2", "q3")


@dataclass(frozen=True)
class BranchingDiagnostic:
    code: str
    severity: Literal["error", "warning"]
    node_id: str | None
    message: str
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BranchingMetrics:
    question_count: int = 0
    conclusion_count: int = 0
    max_path_length: int = 0
    median_path_length: float = 0.0
    early_distinct_target_count: int = 0
    same_target_node_count: int = 0
    collect_only_node_count: int = 0
    reachable_conclusion_count: int = 0
    path_length_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BranchingQualityAssessment:
    diagnostics: list[BranchingDiagnostic] = field(default_factory=list)
    metrics: BranchingMetrics = field(default_factory=BranchingMetrics)

    @property
    def errors(self) -> list[str]:
        return [d.message for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> list[str]:
        return [d.message for d in self.diagnostics if d.severity == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "metrics": self.metrics.to_dict(),
        }


def branching_quality_errors_are_auto_fixable(errors: list[str]) -> bool:
    """True if at least one error might be fixed by deterministic auto-fix."""
    return any(not error.startswith(BRANCHING_QUALITY_PREFIX) for error in errors)


def _is_collect_only(node_id: str, collect_only_question_ids: frozenset[str]) -> bool:
    return node_id in collect_only_question_ids


def _entry_node_id(graph: DTGraph) -> str | None:
    has_incoming = {edge.target for edge in graph.edges}
    has_outgoing = {edge.source for edge in graph.edges}
    candidates = sorted(has_outgoing - has_incoming)
    if "q1" in candidates:
        return "q1"
    return candidates[0] if candidates else None


def _reachable_from_entry(graph: DTGraph, start: str | None) -> set[str]:
    if not start:
        return set()
    reachable: set[str] = {start}
    queue: deque[str] = deque([start])
    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        adjacency.setdefault(edge.source, []).append(edge.target)
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, []):
            if neighbor not in reachable:
                reachable.add(neighbor)
                queue.append(neighbor)
    return reachable


def _path_lengths_to_conclusions(graph: DTGraph) -> list[int]:
    """Count question hops from entry to each conclusion path (edge-count DFS)."""
    entry = _entry_node_id(graph)
    conclusion_ids = graph.conclusion_ids
    if not entry or not conclusion_ids:
        return []

    lengths: list[int] = []

    def dfs(node_id: str, question_hops: int, visited: set[str]) -> None:
        if node_id in conclusion_ids:
            lengths.append(question_hops)
            return
        for edge in graph.get_outgoing_edges(node_id):
            next_id = edge.target
            if next_id in visited:
                continue
            hop_increment = 1 if next_id not in conclusion_ids else 0
            dfs(next_id, question_hops + hop_increment, visited | {node_id})

    dfs(entry, 0, set())
    return lengths


def _compute_metrics(
    graph: DTGraph,
    collect_only_question_ids: frozenset[str],
) -> BranchingMetrics:
    question_nodes = [node for node in graph.nodes if node.type == "question"]
    conclusion_nodes = [node for node in graph.nodes if node.type == "conclusion"]
    path_lengths = _path_lengths_to_conclusions(graph)

    same_target_count = 0
    collect_only_count = 0
    early_distinct = 0

    for node in question_nodes:
        if _is_collect_only(node.id, collect_only_question_ids):
            collect_only_count += 1
        edges_out = graph.get_outgoing_edges(node.id)
        if len(edges_out) >= 2:
            unique_targets = {edge.target for edge in edges_out}
            if len(unique_targets) == 1:
                same_target_count += 1

    for node_id in EARLY_GATE_NODE_IDS:
        node = graph.get_node(node_id)
        if node is None or node.type != "question":
            continue
        edges_out = graph.get_outgoing_edges(node_id)
        if edges_out:
            early_distinct = max(early_distinct, len({edge.target for edge in edges_out}))

    entry = _entry_node_id(graph)
    reachable = _reachable_from_entry(graph, entry)
    reachable_conclusions = len(reachable & graph.conclusion_ids)

    max_path = max(path_lengths) if path_lengths else 0
    median_path = statistics.median(path_lengths) if path_lengths else 0.0
    q_count = len(question_nodes) or 1

    return BranchingMetrics(
        question_count=len(question_nodes),
        conclusion_count=len(conclusion_nodes),
        max_path_length=max_path,
        median_path_length=float(median_path),
        early_distinct_target_count=early_distinct,
        same_target_node_count=same_target_count,
        collect_only_node_count=collect_only_count,
        reachable_conclusion_count=reachable_conclusions,
        path_length_ratio=round(max_path / q_count, 3) if q_count else 0.0,
    )


def _detect_sequential_prefix_funnel(graph: DTGraph) -> BranchingDiagnostic | None:
    """Error when Q1→Q2→Q3→Q4 pass-through with ≥4 questions and no early split."""
    question_count = sum(1 for node in graph.nodes if node.type == "question")
    if question_count < 4:
        return None

    if not all(graph.get_node(node_id) for node_id in PREFIX_FUNNEL_CHAIN):
        return None

    for index, node_id in enumerate(PREFIX_FUNNEL_CHAIN):
        edges_out = graph.get_outgoing_edges(node_id)
        unique_targets = {edge.target for edge in edges_out}
        if len(unique_targets) != 1:
            return None
        expected_next = f"q{index + 2}"
        if next(iter(unique_targets)) != expected_next:
            return None

    return BranchingDiagnostic(
        code="PREFIX_FUNNEL",
        severity="error",
        node_id="q1",
        message=(
            f"{BRANCHING_QUALITY_PREFIX} Q1–Q3 form a sequential pass-through prefix "
            "(Q1→Q2→Q3→Q4) with no effective split before Q4."
        ),
        suggestion=(
            "Add a dispositive branch, skipped factor block, or early conclusion "
            "before the Q4 segment."
        ),
    )


def _detect_early_reconvergence(graph: DTGraph) -> BranchingDiagnostic | None:
    """Warn when Q1 cosmetic fork reconverges within one hop."""
    node = graph.get_node("q1")
    if node is None or node.type != "question":
        return None

    conclusion_ids = graph.conclusion_ids
    edges_out = graph.get_outgoing_edges("q1")
    branch_targets = {edge.target for edge in edges_out if edge.target not in conclusion_ids}
    if len(branch_targets) < 2:
        return None

    next_targets_by_branch: list[set[str]] = []
    for branch_id in sorted(branch_targets):
        branch_edges = graph.get_outgoing_edges(branch_id)
        if not branch_edges:
            return None
        next_targets_by_branch.append({edge.target for edge in branch_edges})

    if len(next_targets_by_branch) < 2:
        return None

    common = set.intersection(*next_targets_by_branch)
    if not common:
        return None

    reconverge = sorted(common)[0]
    return BranchingDiagnostic(
        code="EARLY_RECONVERGENCE",
        severity="warning",
        node_id="q1",
        message=(
            f"{BRANCHING_QUALITY_PREFIX} Early branches from Q1 reconverge at "
            f"'{reconverge}' within one hop — the split may be cosmetic."
        ),
        suggestion=(
            "Ensure branch targets skip different factor groups or reach different "
            "conclusions; Track B route_strategy can encode intent explicitly."
        ),
    )


def _validate_conclusion_allowlist(
    graph: DTGraph,
    allowed_conclusion_ids: frozenset[str],
) -> list[BranchingDiagnostic]:
    from smeme.qnr.generation.agentic.conclusions_parse import graph_conclusion_id_to_allowlist_id

    diagnostics: list[BranchingDiagnostic] = []
    allowed_upper = {conclusion_id.upper() for conclusion_id in allowed_conclusion_ids}
    graph_conclusion_ids = {
        graph_conclusion_id_to_allowlist_id(node.id)
        for node in graph.nodes
        if node.type == "conclusion"
    }

    for blueprint_id in sorted(graph_conclusion_ids - allowed_upper):
        diagnostics.append(
            BranchingDiagnostic(
                code="DISALLOWED_CONCLUSION",
                severity="error",
                node_id=None,
                message=(
                    f"{BRANCHING_QUALITY_PREFIX} Graph references {blueprint_id}, "
                    f"but allowed conclusions are "
                    f"{', '.join(sorted(allowed_upper))}."
                ),
                suggestion="Remove or rename the extra conclusion, or update approved conclusions.",
            )
        )

    missing = allowed_upper - graph_conclusion_ids
    if missing:
        diagnostics.append(
            BranchingDiagnostic(
                code="MISSING_ALLOWED_CONCLUSIONS",
                severity="warning",
                node_id=None,
                message=(
                    f"{BRANCHING_QUALITY_PREFIX} Approved conclusions not present in graph: "
                    f"{', '.join(sorted(missing))}."
                ),
                suggestion="Add routes so each approved conclusion is reachable.",
            )
        )

    return diagnostics


def assess_branching_quality(
    graph: DTGraph,
    *,
    collect_only_question_ids: frozenset[str] | None = None,
    allowed_conclusion_ids: frozenset[str] | None = None,
    allowed_conclusions_parse_ok: bool = True,
) -> BranchingQualityAssessment:
    """Assess branching usefulness with actionable diagnostics and metrics."""
    collect_only_ids = collect_only_question_ids or frozenset()
    assessment = BranchingQualityAssessment(
        metrics=_compute_metrics(graph, collect_only_ids),
    )

    if allowed_conclusions_parse_ok and allowed_conclusion_ids:
        assessment.diagnostics.extend(_validate_conclusion_allowlist(graph, allowed_conclusion_ids))

    prefix_funnel = _detect_sequential_prefix_funnel(graph)
    if prefix_funnel:
        assessment.diagnostics.append(prefix_funnel)

    early_reconvergence = _detect_early_reconvergence(graph)
    if early_reconvergence:
        assessment.diagnostics.append(early_reconvergence)

    for node in graph.nodes:
        if node.type != "question":
            continue

        edges_out = graph.get_outgoing_edges(node.id)
        if len(edges_out) < 2:
            continue

        unique_targets = {edge.target for edge in edges_out}
        if len(unique_targets) != 1:
            continue

        if _is_collect_only(node.id, collect_only_ids):
            continue

        target = next(iter(unique_targets))
        # Q1 intake classifiers may route all options to one next node (warning only).
        if node.id == "q1":
            continue

        assessment.diagnostics.append(
            BranchingDiagnostic(
                code="FAKE_BRANCHING",
                severity="error",
                node_id=node.id,
                message=(
                    f"{BRANCHING_QUALITY_PREFIX} Question '{node.id}' has {len(edges_out)} "
                    f"edges but all route to '{target}'."
                ),
                suggestion=(
                    "Split at least one option to a different question or conclusion, "
                    "merge equivalent options, or mark the question as collect-only "
                    "(Node kind: collect_only) if the answer is needed only for explanation."
                ),
            )
        )

    for node_id in EARLY_GATE_NODE_IDS:
        node = graph.get_node(node_id)
        if node is None or node.type != "question":
            continue

        edges_out = graph.get_outgoing_edges(node_id)
        if not edges_out:
            continue

        unique_targets = {edge.target for edge in edges_out}
        if len(unique_targets) >= 2:
            continue

        only_target = next(iter(unique_targets))
        assessment.diagnostics.append(
            BranchingDiagnostic(
                code="EARLY_SINGLE_TARGET",
                severity="warning",
                node_id=node_id,
                message=(
                    f"{BRANCHING_QUALITY_PREFIX} Early gate '{node_id}' routes all "
                    f"options to '{only_target}' only."
                ),
                suggestion=(
                    "Acceptable for intake/classifier questions if a later gate splits "
                    "routes; otherwise add a second target (skip block or conclusion)."
                ),
            )
        )

    metrics = assessment.metrics
    if metrics.question_count >= 4 and metrics.path_length_ratio > 0.85:
        assessment.diagnostics.append(
            BranchingDiagnostic(
                code="HIGH_PATH_RATIO",
                severity="warning",
                node_id=None,
                message=(
                    f"{BRANCHING_QUALITY_PREFIX} Max path length ({metrics.max_path_length}) "
                    f"is {metrics.path_length_ratio:.0%} of question count "
                    f"({metrics.question_count}) — possible linear funnel."
                ),
                suggestion=(
                    "Review whether mid-tree conclusions or factor-skip branches are "
                    "possible. Sequential domains may legitimately score high here."
                ),
            )
        )

    if metrics.same_target_node_count > 1:
        assessment.diagnostics.append(
            BranchingDiagnostic(
                code="MULTIPLE_SAME_TARGET_NODES",
                severity="warning",
                node_id=None,
                message=(
                    f"{BRANCHING_QUALITY_PREFIX} {metrics.same_target_node_count} questions "
                    "have multiple options routing to the same target."
                ),
                suggestion="Review for fake branching or mark informational nodes collect-only.",
            )
        )

    unreachable = metrics.conclusion_count - metrics.reachable_conclusion_count
    if unreachable > 0:
        assessment.diagnostics.append(
            BranchingDiagnostic(
                code="UNREACHABLE_CONCLUSIONS",
                severity="error",
                node_id=None,
                message=(
                    f"{BRANCHING_QUALITY_PREFIX} {unreachable} conclusion(s) are not "
                    "reachable from the entry node."
                ),
                suggestion="Add conditional routes to orphan conclusions from relevant gates.",
            )
        )

    return assessment


def validate_branching_quality(graph: DTGraph) -> list[str]:
    """Return blocking error messages only (backward-compatible helper)."""
    return assess_branching_quality(graph).errors
