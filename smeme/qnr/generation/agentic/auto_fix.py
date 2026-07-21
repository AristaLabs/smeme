"""Deterministic auto-fix for QNRGraph validation issues.

Applies rule-based fixes for common structural problems.
Reuses existing operations from smeme/qnr/editor/operations.py.

See docs/AGENTIC_QNR_GENERATION_PLAN.md for fix specifications.

Handles both question and conclusion nodes:
- Conclusion nodes are terminal (no outgoing edges expected)
- Edges to conclusions must be conditional (no defaults)
- Question nodes without outgoing edges should lead to conclusions
"""

import logging
import re
import time
from difflib import get_close_matches

from smeme.qnr.editor.operations import create_edge, delete_edge, delete_node
from smeme.qnr.models import QNRGraph

logger = logging.getLogger("smeme.qnr.generation.agentic")


def auto_fix_graph(
    graph: QNRGraph,
    errors: list[str],
    warnings: list[str],
) -> tuple[QNRGraph, list[str], list[str], list[str]]:
    """
    Apply deterministic fixes to a QNRGraph.

    Fixes are applied in order:
    1. Edge fixes (self-loops, duplicates, multiple defaults, condition typos)
    2. Conclusion-specific fixes (remove outgoing edges from conclusions, fix default edges to conclusions)
    3. Node fixes (orphans, invalid IDs) - but NOT conclusion nodes
    4. Warning fixes (missing default edges) - but NOT to conclusions

    Args:
        graph: The QNRGraph to fix
        errors: List of validation errors
        warnings: List of validation warnings

    Returns:
        Tuple of:
        - Fixed QNRGraph
        - Remaining errors (not fixed)
        - Remaining warnings (not fixed)
        - List of fixes applied (for UI display)
    """
    start_time = time.time()
    fixes_applied: list[str] = []
    remaining_errors: list[str] = []
    remaining_warnings: list[str] = []

    # Get conclusion IDs for special handling
    conclusion_ids = graph.conclusion_ids

    # =========================================================================
    # EDGE FIXES
    # =========================================================================

    for error in errors:
        fixed = False

        # Self-loop: "Self-loop detected on node 'q3'"
        if match := re.search(r"Self-loop detected on node '(\w+)'", error):
            node_id = match.group(1)
            try:
                # Find and remove all self-loop edges for this node
                graph = _remove_self_loops(graph, node_id)
                fixes_applied.append(f"Removed self-loop on '{node_id}'")
                fixed = True
            except ValueError:
                pass

        # Multiple defaults: "Node 'q2' has 2 default edges"
        elif match := re.search(r"Node '(\w+)' has (\d+) default edges", error):
            node_id = match.group(1)
            graph, count = _keep_first_default_edge(graph, node_id)
            if count > 0:
                fixes_applied.append(f"Removed {count} extra default edges from '{node_id}'")
                fixed = True

        # Duplicate edge: "Duplicate edge: q1 → q2"
        elif match := re.search(r"Duplicate edge: (\w+) → (\w+)", error):
            source, target = match.group(1), match.group(2)
            graph, count = _remove_duplicate_edges(graph, source, target)
            if count > 0:
                fixes_applied.append(f"Removed {count} duplicate edges {source} → {target}")
                fixed = True

        # Condition typo: "Condition 'Yess' from 'q1' must match an option"
        elif match := re.search(r"Condition '(.+)' from '(\w+)' must match", error):
            condition, node_id = match.group(1), match.group(2)
            result = _fuzzy_fix_condition(graph, node_id, condition)
            if result:
                graph, corrected = result
                fixes_applied.append(f"Fixed typo '{condition}' → '{corrected}' on '{node_id}'")
                fixed = True

        # Conclusion has outgoing edges: "Conclusion node 'X' cannot have outgoing edges"
        elif match := re.search(r"Conclusion node '(\w+)' cannot have outgoing edges", error):
            node_id = match.group(1)
            graph, count = _remove_outgoing_edges_from_conclusion(graph, node_id)
            if count > 0:
                fixes_applied.append(f"Removed {count} outgoing edges from conclusion '{node_id}'")
                fixed = True

        # Default edge to conclusion: "Edge to conclusion 'X' from 'Y' must be conditional"
        elif match := re.search(
            r"Edge to conclusion '(\w+)' from '(\w+)' must be conditional", error
        ):
            target, source = match.group(1), match.group(2)
            # Can't auto-fix this without knowing what condition to use
            # Just report it - user must fix manually

        if not fixed:
            remaining_errors.append(error)

    # =========================================================================
    # NODE FIXES
    # =========================================================================

    # Find and remove orphan nodes (no incoming or outgoing edges)
    # BUT don't remove conclusion nodes - they're supposed to have no outgoing edges
    graph, orphans_removed = _remove_orphan_nodes(graph, exclude_conclusions=True)
    if orphans_removed:
        fixes_applied.append(f"Removed orphan nodes: {', '.join(orphans_removed)}")

    # =========================================================================
    # WARNING FIXES
    # =========================================================================

    for warning in warnings:
        fixed = False

        # Missing default edge warnings - but NOT if all edges go to conclusions
        if (
            "must have a default edge" in warning.lower()
            or "missing default edge" in warning.lower()
        ) and (match := re.search(r"'(\w+)'", warning)):
            node_id = match.group(1)
            # Check if all edges from this node go to conclusions
            edges_out = graph.get_outgoing_edges(node_id)
            all_to_conclusions = all(e.target in conclusion_ids for e in edges_out)

            if not all_to_conclusions:
                result = _add_default_edge_to_next(graph, node_id, conclusion_ids)
                if result:
                    graph, target = result
                    fixes_applied.append(f"Added default edge {node_id} → {target}")
                    fixed = True

        if not fixed:
            remaining_warnings.append(warning)

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "Auto-fix completed",
        extra={
            "fixes_count": len(fixes_applied),
            "remaining_errors": len(remaining_errors),
            "remaining_warnings": len(remaining_warnings),
            "conclusion_count": len(conclusion_ids),
            "elapsed_ms": round(elapsed_ms, 2),
        },
    )

    return graph, remaining_errors, remaining_warnings, fixes_applied


def _remove_outgoing_edges_from_conclusion(graph: QNRGraph, node_id: str) -> tuple[QNRGraph, int]:
    """
    Remove all outgoing edges from a conclusion node.

    Conclusions are terminal - they shouldn't have outgoing edges.
    Returns the modified graph and count of edges removed.
    """
    removed = 0
    for edge in list(graph.edges):
        if edge.source == node_id:
            try:
                graph = delete_edge(
                    graph, source=node_id, target=edge.target, condition=edge.condition
                )
                removed += 1
            except ValueError:
                pass
    return graph, removed


def _remove_self_loops(graph: QNRGraph, node_id: str) -> QNRGraph:
    """Remove all edges where source == target for a given node."""
    for edge in list(graph.edges):
        if edge.source == node_id and edge.target == node_id:
            try:
                graph = delete_edge(graph, source=node_id, target=node_id, condition=edge.condition)
            except ValueError:
                pass  # Edge might have already been removed
    return graph


def _keep_first_default_edge(graph: QNRGraph, node_id: str) -> tuple[QNRGraph, int]:
    """
    Keep only the first default edge (condition=None) from a node.

    Returns the modified graph and count of edges removed.
    """
    default_edges = [
        e for e in graph.edges if e.source == node_id and (e.condition is None or e.condition == "")
    ]

    if len(default_edges) <= 1:
        return graph, 0

    # Keep first, remove rest
    removed = 0
    for edge in default_edges[1:]:
        try:
            graph = delete_edge(graph, source=node_id, target=edge.target, condition=edge.condition)
            removed += 1
        except ValueError:
            pass

    return graph, removed


def _remove_duplicate_edges(graph: QNRGraph, source: str, target: str) -> tuple[QNRGraph, int]:
    """
    Remove duplicate edges between source and target.

    Keeps the first occurrence of each (source, target, condition) tuple.
    Returns the modified graph and count of edges removed.
    """
    seen: set[tuple[str, str, str | None]] = set()
    removed = 0

    for edge in list(graph.edges):
        if edge.source == source and edge.target == target:
            key = (edge.source, edge.target, edge.condition)
            if key in seen:
                try:
                    graph = delete_edge(
                        graph, source=edge.source, target=edge.target, condition=edge.condition
                    )
                    removed += 1
                except ValueError:
                    pass
            else:
                seen.add(key)

    return graph, removed


def _fuzzy_fix_condition(
    graph: QNRGraph, node_id: str, bad_condition: str
) -> tuple[QNRGraph, str] | None:
    """
    Try to fix a condition typo by fuzzy matching to valid options.

    Returns tuple of (modified graph, corrected condition) or None if no match found.
    """
    # Find the node
    node = next((n for n in graph.nodes if n.id == node_id), None)
    if not node or node.data is None:
        return None

    # Get valid options
    options = node.data.options or []
    if not options:
        return None

    # Try fuzzy match
    matches = get_close_matches(bad_condition, options, n=1, cutoff=0.6)
    if not matches:
        return None

    corrected = matches[0]

    # Find and update the edge with the bad condition
    for i, edge in enumerate(graph.edges):
        if edge.source == node_id and edge.condition == bad_condition:
            # Update the condition
            from copy import deepcopy

            from smeme.qnr.models import GraphEdge

            new_graph = deepcopy(graph)
            new_graph.edges[i] = GraphEdge(
                source=edge.source,
                target=edge.target,
                condition=corrected,
            )
            return new_graph, corrected

    return None


def _remove_orphan_nodes(
    graph: QNRGraph, exclude_conclusions: bool = False
) -> tuple[QNRGraph, list[str]]:
    """
    Remove nodes with no incoming or outgoing edges (except entry node).

    Entry node is identified as the node with no incoming edges but has outgoing.

    Args:
        graph: The QNRGraph to fix
        exclude_conclusions: If True, don't remove conclusion nodes even if orphaned.
            Conclusions are terminal by design - they have no outgoing edges.

    Returns the modified graph and list of removed node IDs.
    """
    removed: list[str] = []
    conclusion_ids = graph.conclusion_ids if exclude_conclusions else set()

    # Find nodes with edges
    has_outgoing = {e.source for e in graph.edges}
    has_incoming = {e.target for e in graph.edges}

    # Entry node: no incoming but has outgoing
    entry_candidates = has_outgoing - has_incoming
    entry_node = next(iter(entry_candidates), None)

    for node in list(graph.nodes):
        # Skip conclusion nodes if exclude_conclusions is True
        # Conclusions are terminal - no outgoing edges expected
        if exclude_conclusions and node.id in conclusion_ids:
            continue

        # Check if orphan (no edges in either direction, not entry)
        is_orphan = (
            node.id not in has_outgoing and node.id not in has_incoming and node.id != entry_node
        )

        if is_orphan:
            try:
                graph = delete_node(graph, node.id)
                removed.append(node.id)
            except ValueError:
                pass

    return graph, removed


def _add_default_edge_to_next(
    graph: QNRGraph, node_id: str, conclusion_ids: set[str] | None = None
) -> tuple[QNRGraph, str] | None:
    """
    Add a default edge from a node to the "next" node.

    The "next" node is determined by:
    1. If the node has existing edges to questions (not conclusions), use one
    2. Otherwise, find the node with the next sequential ID (q1 → q2)
    3. If no next node found, skip

    IMPORTANT: Default edges cannot go to conclusions.
    Conclusions must be reached via conditional edges only.

    Args:
        graph: The QNRGraph to fix
        node_id: The node to add a default edge from
        conclusion_ids: Set of conclusion node IDs to avoid

    Returns tuple of (modified graph, target node) or None if no suitable target.
    """
    if conclusion_ids is None:
        conclusion_ids = graph.conclusion_ids

    # Check if already has a default edge
    has_default = any(
        e.source == node_id and (e.condition is None or e.condition == "") for e in graph.edges
    )
    if has_default:
        return None

    # Try to find a target (but NOT a conclusion)
    # First: look at existing edges from this node that go to questions
    existing_question_targets = [
        e.target for e in graph.edges if e.source == node_id and e.target not in conclusion_ids
    ]
    if existing_question_targets:
        target = existing_question_targets[0]
    else:
        # Try to find "next" question node by ID pattern (q1 → q2, question_1 → question_2)
        target = _find_next_node_id(graph, node_id, conclusion_ids)

    if not target:
        return None

    # Double-check we're not adding a default edge to a conclusion
    if target in conclusion_ids:
        return None

    try:
        graph = create_edge(graph, source=node_id, target=target, condition=None)
        return graph, target
    except ValueError:
        return None


def _find_next_node_id(
    graph: QNRGraph, current_id: str, conclusion_ids: set[str] | None = None
) -> str | None:
    """
    Find the next sequential question node ID.

    Handles patterns like:
    - q1 → q2
    - question_1 → question_2
    - node1 → node2

    Will NOT return conclusion nodes - only questions.

    Args:
        graph: The QNRGraph
        current_id: Current node ID
        conclusion_ids: Set of conclusion node IDs to exclude
    """
    if conclusion_ids is None:
        conclusion_ids = graph.conclusion_ids

    # Extract numeric suffix
    match = re.match(r"^(.+?)(\d+)$", current_id)
    if not match:
        return None

    prefix, num_str = match.groups()
    next_num = int(num_str) + 1
    next_id = f"{prefix}{next_num}"

    # Check if that node exists and is NOT a conclusion
    node_ids = {n.id for n in graph.nodes}
    if next_id in node_ids and next_id not in conclusion_ids:
        return next_id

    return None
