"""Graph validation helpers.

Node types in a DTGraph:
- question: Gathers information, can have outgoing edges
- conclusion: Terminal outcome, no outgoing edges

Entry and terminal status is determined by edge connectivity and node type.
Conclusions are always terminal. Questions with no outgoing edges are invalid
(must lead somewhere - either to another question or a conclusion).
"""

import logging
import re
from collections import deque
from collections.abc import Callable
from typing import NotRequired, TypedDict

from smeme.qnr.models import DTGraph, GraphEdge, GraphNode

logger = logging.getLogger(__name__)

# =============================================================================
# Performance Optimizations: Pre-compiled Regexes
# =============================================================================

PROHIBITED_PATTERN = re.compile(r"[\x00-\x1F]")
VALID_ID_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")

# =============================================================================
# Enhanced Type Safety: TypedDict Classes
# =============================================================================


class ValidationResult(TypedDict):
    """Type-safe validation result structure."""

    is_valid: bool
    errors: list[str]
    warnings: list[str]
    suggestions: NotRequired[dict[str, str]]


class ValidationCategories(TypedDict):
    """Type-safe validation message categories."""

    Structure: list[str]
    Nodes: list[str]
    Edges: list[str]
    Content: list[str]
    Metadata: list[str]


class NodeValidationStatus(TypedDict):
    """Type-safe node-specific validation status."""

    errors: list[str]
    warnings: list[str]


class ValidationIssueRow(TypedDict):
    """Flat validation issue for editor jump-to-node UX."""

    severity: str  # ``error`` | ``warning``
    message: str
    node_id: str | None
    suggestion: NotRequired[str | None]


class _ValidationContext:
    """Collects validation messages and programmatic fix hints at the call site."""

    __slots__ = ("errors", "warnings", "suggestions")

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.suggestions: dict[str, str] = {}

    def error(self, message: str, suggestion: str) -> None:
        self.errors.append(message)
        self.suggestions[message] = suggestion

    def warning(self, message: str, suggestion: str) -> None:
        self.warnings.append(message)
        self.suggestions[message] = suggestion

    def to_result(self, *, is_valid: bool) -> ValidationResult:
        return ValidationResult(
            is_valid=is_valid,
            errors=self.errors,
            warnings=self.warnings,
            suggestions=self.suggestions,
        )


_VALIDATION_NODE_ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Typed node prefixes (must precede generic "Question 'id'")
    re.compile(
        r"(?:Question node|Conclusion node|Radio question|Optional radio question)"
        r"\s+['\"]([^'\"]+)['\"]",
        re.IGNORECASE,
    ),
    re.compile(r"(?:Question|Node)\s+['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(r"\bfrom\s+['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(r"\bon\s+['\"]([^'\"]+)['\"]\s*→", re.IGNORECASE),
    re.compile(r"\bon node\s+['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(r"Edge source\s+['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(r"Self-loop detected on node\s+['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(r"Conclusion\s+['\"]([^'\"]+)['\"]", re.IGNORECASE),
)

# Structure warnings that reference nodes without quoted ids (cycle paths, comma lists).
_CYCLE_DETECTED_RE = re.compile(r"Cycle detected:\s*(.+)", re.IGNORECASE)
_ORPHANED_NODES_RE = re.compile(r"Orphaned nodes:\s*(.+)", re.IGNORECASE)
_UNREACHABLE_CONCLUSIONS_RE = re.compile(r"Unreachable conclusions:\s*([^.]+)", re.IGNORECASE)
_UNREACHABLE_QUESTIONS_RE = re.compile(r"Unreachable questions:\s*([^.]+)", re.IGNORECASE)


def _strip_warning_prefix(message: str) -> str:
    return message.removeprefix("⚠️ ").strip()


def _parse_comma_separated_node_ids(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def node_ids_for_validation_message(message: str) -> list[str]:
    """Return node ids referenced by a validation message (may be empty or many)."""
    text = _strip_warning_prefix(message)

    cycle_match = _CYCLE_DETECTED_RE.match(text)
    if cycle_match:
        path_part = cycle_match.group(1).strip()
        first = path_part.split("→", 1)[0].strip()
        return [first] if first else []

    for pattern in (_ORPHANED_NODES_RE, _UNREACHABLE_CONCLUSIONS_RE, _UNREACHABLE_QUESTIONS_RE):
        match = pattern.match(text)
        if match:
            return _parse_comma_separated_node_ids(match.group(1))

    single = extract_validation_node_id(message)
    return [single] if single else []


def _issue_rows_for_message(
    message: str,
    severity: str,
    node_for: Callable[[str], str | None],
    *,
    suggestion: str | None = None,
) -> list[ValidationIssueRow]:
    """Build one or more sidebar rows for a validation message."""
    text = _strip_warning_prefix(message)

    def _row(msg: str, node_id: str | None) -> ValidationIssueRow:
        row: ValidationIssueRow = {
            "severity": severity,
            "message": msg,
            "node_id": node_id,
        }
        if suggestion:
            row["suggestion"] = suggestion
        return row

    cycle_match = _CYCLE_DETECTED_RE.match(text)
    if cycle_match:
        node_ids = node_ids_for_validation_message(message)
        return [_row(message, node_ids[0] if node_ids else None)]

    for pattern, label in (
        (_ORPHANED_NODES_RE, "Orphaned node (unreachable from entry)"),
        (_UNREACHABLE_CONCLUSIONS_RE, "Unreachable conclusion"),
        (_UNREACHABLE_QUESTIONS_RE, "Unreachable question"),
    ):
        match = pattern.match(text)
        if match:
            node_ids = _parse_comma_separated_node_ids(match.group(1))
            if len(node_ids) <= 1:
                return [_row(message, node_ids[0] if node_ids else None)]
            return [_row(f"⚠️ {label}: {node_id}", node_id) for node_id in node_ids]

    return [_row(message, node_for(message))]


def _multiple_entry_points_message(graph: DTGraph) -> str | None:
    """Return a blocking error if more than one node has indegree zero."""
    entry_ids = [n.id for n in graph.get_entry_nodes()]
    if len(entry_ids) <= 1:
        return None
    joined = ", ".join(sorted(entry_ids))
    return (
        f"Graph must have exactly one entry node (no incoming edges); "
        f"found {len(entry_ids)}: {joined}"
    )


def bare_create_node_blocked_message(graph: DTGraph) -> str | None:
    """
    Message when POST /create_node would add a question with no incoming edges.

    That always introduces a second entry point once the graph is non-empty.
    Future composite routes should create edges in the same request (predecessors,
    insert-between, or new-start with forward links to the former entry).
    """
    if not graph.nodes:
        return None
    return (
        "Cannot add a standalone question while the graph already has nodes: "
        "it would create a second entry point (exactly one node may have no incoming edges). "
        "Use Add node in the side panel (POST /qnr/editor/create_node_wired), or add an edge from an existing question first."
    )


def validate_graph(graph: DTGraph) -> tuple[bool, str | None]:
    """
    Validate DTGraph structure (strict validation).

    Node types: question and conclusion.
    - Questions gather information and have outgoing edges
    - Conclusions are terminal outcomes with no outgoing edges

    Conclusion Node Rules (per QNR_CONCLUSION_NODES_PLAN.md):
    - At least TWO conclusions required (disjunction principle)
    - Conclusion nodes have NO outgoing edges
    - Edges to conclusions must be CONDITIONAL (no defaults to conclusions)
    - Exactly one entry node (no incoming edges)
    - All conclusions must be reachable from entry
    - Question nodes without outgoing edges are invalid (legacy support: grandfathered)

    Returns:
        (is_valid, error_message)
    """
    if not graph.nodes:
        return False, "Graph must have at least one node"

    node_ids = {node.id for node in graph.nodes}

    # Check for duplicate node IDs
    if len(node_ids) != len(graph.nodes):
        return False, "Duplicate node IDs found"

    # Validate edges reference existing nodes
    for edge in graph.edges:
        if edge.source not in node_ids:
            return False, f"Edge source '{edge.source}' not found in nodes"
        if edge.target not in node_ids:
            return False, f"Edge target '{edge.target}' not found in nodes"

    # Separate question and conclusion nodes
    question_nodes = graph.get_question_nodes()
    conclusion_nodes = graph.get_conclusion_nodes()
    conclusion_ids = graph.conclusion_ids

    # Validate node data based on type
    for node in graph.nodes:
        if not node.data:
            return False, f"Node '{node.id}' missing data"

        if node.type == "question":
            qdata = node.question_data
            if not qdata:
                return False, f"Question node '{node.id}' has invalid data type"
            if not qdata.text:
                return False, f"Question node '{node.id}' missing question text"
        elif node.type == "conclusion":
            cdata = node.conclusion_data
            if not cdata:
                return False, f"Conclusion node '{node.id}' has invalid data type"
            if not cdata.title:
                return False, f"Conclusion node '{node.id}' missing title"
            if not cdata.summary:
                return False, f"Conclusion node '{node.id}' missing summary"

    # Helper functions for edge lookup
    def get_incoming(node_id: str) -> list[GraphEdge]:
        return [e for e in graph.edges if e.target == node_id]

    def get_outgoing(node_id: str) -> list[GraphEdge]:
        return [e for e in graph.edges if e.source == node_id]

    # Entry point requirement: exactly one node with no incoming edges
    first_candidates = [n.id for n in graph.nodes if len(get_incoming(n.id)) == 0]
    if not first_candidates:
        return False, "There must be a node with no incoming edges (entry point)"

    multi = _multiple_entry_points_message(graph)
    if multi:
        return False, multi

    # Entry point must be a question, not a conclusion
    entry_conclusions = [n for n in first_candidates if n in conclusion_ids]
    if entry_conclusions:
        return False, f"Conclusion node(s) cannot be entry points: {', '.join(entry_conclusions)}"

    # =========================================================================
    # CONCLUSION NODE VALIDATION RULES
    # =========================================================================

    # If graph has conclusions, enforce conclusion-specific rules
    if conclusion_nodes:
        # Rule: At least TWO conclusions (disjunction principle)
        if len(conclusion_nodes) < 2:
            return False, (
                "Workflow must have at least 2 conclusion nodes to provide meaningful "
                "discrimination. Add another conclusion or remove existing one."
            )

        # Rule: Conclusion nodes have NO outgoing edges
        for node in conclusion_nodes:
            outgoing = get_outgoing(node.id)
            if outgoing:
                targets = [e.target for e in outgoing]
                return False, (
                    f"Conclusion node '{node.id}' cannot have outgoing edges. "
                    f"Remove edges to: {', '.join(targets)}"
                )

        # Rule: Edges to conclusions must be CONDITIONAL (no defaults)
        for edge in graph.edges:
            if edge.target in conclusion_ids:
                if edge.condition is None or not edge.condition.strip():
                    return False, (
                        f"Edge to conclusion '{edge.target}' from '{edge.source}' must be "
                        "conditional, not default. Conclusions can only be reached by "
                        "explicit answers, not fallbacks."
                    )

    # Terminal requirement: at least one node with no outgoing edges
    terminal_nodes = [n.id for n in graph.nodes if len(get_outgoing(n.id)) == 0]
    if not terminal_nodes:
        return False, "There must be at least one terminal node with no outgoing edges"

    # Validate conditional edges and defaults for question nodes
    for node in question_nodes:
        edges_out = get_outgoing(node.id)
        if not edges_out:
            # If graph has conclusions, question nodes without edges are invalid
            # (grandfathered for legacy QNRs without conclusions)
            if conclusion_nodes:
                return False, (
                    f"Question node '{node.id}' has no outgoing edges. "
                    "All questions must lead to another question or a conclusion."
                )
            continue

        has_default = any(e.condition is None or not e.condition.strip() for e in edges_out)
        qdata = node.question_data

        # Basic type/option sanity (radio-only)
        if qdata:
            if not qdata.options or len(qdata.options) == 0:
                return False, f"Radio question '{node.id}' must have options"

        # Default edge requirements (required-aware)
        if qdata:
            conds = {e.condition.strip() for e in edges_out if e.condition}
            options_set = set(qdata.options or [])

            if conds != options_set:
                missing = options_set - conds
                if qdata.required:
                    if not has_default:
                        return False, (
                            f"Radio question '{node.id}' has partial "
                            f"conditional coverage. Add a default edge or add conditions "
                            f"for: {', '.join(sorted(missing))}"
                        )
                else:
                    return False, (
                        f"Optional radio question '{node.id}' missing conditional "
                        f"edges for: {', '.join(sorted(missing))}. All options must have "
                        "edges when question is optional."
                    )

            if not qdata.required and not has_default:
                return False, (
                    f"Optional radio question '{node.id}' must have a default edge "
                    "to handle when the user skips it"
                )

        for edge in edges_out:
            if edge.condition is None or not edge.condition.strip():
                continue

            cond = edge.condition.strip()
            if PROHIBITED_PATTERN.search(cond):
                return False, (
                    f"Condition on '{node.id}' -> '{edge.target}' must be a simple"
                    " literal without operators"
                )

            if qdata:
                if not qdata.options or cond not in qdata.options:
                    return False, (
                        f"Condition '{cond}' from '{node.id}' must match an option label"
                    )

    # Metadata requirements
    if graph.metadata is None:
        return False, "Graph metadata is required"
    if not graph.metadata.title:
        return False, "Graph metadata.title is required"

    return True, None


def get_node_by_id(graph: DTGraph, node_id: str) -> GraphNode | None:
    """Get node by ID from graph. Uses graph's built-in method."""
    return graph.get_node(node_id)


def get_outgoing_edges(graph: DTGraph, node_id: str) -> list[GraphEdge]:
    """Get all edges originating from a node. Uses graph's built-in method."""
    return graph.get_outgoing_edges(node_id)


def get_incoming_edges(graph: DTGraph, node_id: str) -> list[GraphEdge]:
    """Get all edges targeting a node. Uses graph's built-in method."""
    return graph.get_incoming_edges(node_id)


def has_conditional_edges(graph: DTGraph, node_id: str) -> bool:
    """Check if node has any conditional outgoing edges. Uses graph's built-in method."""
    return graph.has_conditional_edges(node_id)


def get_first_question_id(graph: DTGraph) -> str | None:
    """Get ID of the entry node (the unique node with no incoming edges when valid)."""
    return graph.entry_node_id


def get_reachable_questions(graph: DTGraph, responses: dict[str, str]) -> set[str]:
    """
    Traverse the graph from start following the path determined by current responses.

    This function simulates the user's navigation path through the questionnaire
    to determine which questions are actually reachable given their current answers.

    Algorithm:
    1. Start at the entry point (first node with no incoming edges)
    2. For each node in the path:
       - Mark it as reachable
       - If answered: follow matching conditional edge OR default edge
       - If NOT answered but has default edge: follow it (optional question)
       - If NOT answered and only has conditional edges: STOP (path blocked)
    3. Continue until we reach the end or path is blocked

    Args:
        graph: The DTGraph structure
        responses: Current user responses (question_id -> answer)

    Returns:
        Set of question IDs that are reachable given current response state
    """
    reachable: set[str] = set()
    visited: set[str] = set()

    # Start at entry point
    current_id = graph.entry_node_id
    if not current_id:
        logger.warning("No entry point found in graph")
        return reachable

    logger.debug(f"Starting reachability traversal from: {current_id}")

    while current_id:
        # Cycle detection
        if current_id in visited:
            logger.warning(f"Cycle detected at node {current_id}, stopping traversal")
            break
        visited.add(current_id)

        # All nodes are questions - mark as reachable
        current_node = graph.get_node(current_id)
        if current_node:
            reachable.add(current_id)
            logger.debug(f"Node {current_id} is reachable")

        # Get outgoing edges
        edges_out = graph.get_outgoing_edges(current_id)
        if not edges_out:
            logger.debug(f"No outgoing edges from {current_id}, end of path")
            break

        # Determine next node based on current state
        next_id: str | None = None

        if current_id in responses:
            user_answer = responses[current_id]
            logger.debug(f"Node {current_id} answered: {user_answer}")

            # Try to match conditional edge (radio-only: exact option label match, case-insensitive)
            for edge in edges_out:
                if edge.condition and edge.condition.strip():
                    condition = edge.condition.strip()
                    ua = user_answer.strip()
                    if condition.lower() == ua.lower():
                        next_id = edge.target
                        logger.debug(
                            f"Matched conditional edge: {current_id} -> {next_id} "
                            f"(condition: {condition})"
                        )
                        break

            # If no conditional match, try default edge
            if not next_id:
                default_edge = graph.get_default_edge(current_id)
                if default_edge:
                    next_id = default_edge.target
                    logger.debug(f"Using default edge: {current_id} -> {next_id}")
                else:
                    logger.warning(f"No matching edge for answer '{user_answer}' at {current_id}")
                    break

        else:
            # Not answered - only follow if default edge exists
            logger.debug(f"Node {current_id} not answered")

            default_edge = graph.get_default_edge(current_id)
            if default_edge:
                next_id = default_edge.target
                logger.debug(
                    f"Following default edge from unanswered optional node: "
                    f"{current_id} -> {next_id}"
                )
            else:
                logger.debug(
                    f"Node {current_id} unanswered and only has conditional edges, "
                    f"stopping traversal"
                )
                break

        current_id = next_id

    logger.info(f"Reachable nodes: {sorted(reachable)}")
    return reachable


# =============================================================================
# Performance Helpers: Pre-computed Data Structures
# =============================================================================


def build_node_maps(graph: DTGraph) -> tuple[dict[str, GraphNode], dict[str, list[str]]]:
    """
    Build optimized node and adjacency maps for graph traversal.

    Returns:
        (node_map, adjacency_list) tuple for efficient lookups
    """
    node_map = graph.node_map
    adjacency: dict[str, list[str]] = {node.id: [] for node in graph.nodes}
    for edge in graph.edges:
        adjacency.setdefault(edge.source, []).append(edge.target)
    return node_map, adjacency


def get_question_nodes(graph: DTGraph) -> list[GraphNode]:
    """Get all question nodes from graph (excludes conclusion nodes)."""
    return graph.get_question_nodes()


def get_outgoing_edges_map(graph: DTGraph) -> dict[str, list[GraphEdge]]:
    """Build map of node_id -> outgoing edges for efficient lookup."""
    edges_map: dict[str, list[GraphEdge]] = {}
    for edge in graph.edges:
        edges_map.setdefault(edge.source, []).append(edge)
    return edges_map


def _validate_question_nodes(nodes: list[GraphNode], ctx: _ValidationContext) -> None:
    """Validate node content and structure for both question and conclusion nodes."""
    if not nodes:
        ctx.error(
            "Graph must have at least one node",
            "Add a question or conclusion node to start building your workflow.",
        )
        return

    for node in nodes:
        if not node.data:
            ctx.error(
                f"Node '{node.id}' missing data",
                "Open the node and fill in its required fields, or delete and recreate it.",
            )
            continue

        if node.type == "question":
            qdata = node.question_data
            if not qdata:
                ctx.error(
                    f"Question node '{node.id}' has invalid data type",
                    "Open the node editor and re-save the question, or recreate the node.",
                )
                continue
            if not qdata.text:
                ctx.error(
                    f"Question node '{node.id}' missing question text",
                    "Select the node and enter the question text in the side panel.",
                )
            else:
                MAX_QUESTION_LENGTH = 500
                if len(qdata.text) > MAX_QUESTION_LENGTH:
                    ctx.warning(
                        f"⚠️ Question '{node.id}' has very long text "
                        f"({len(qdata.text)} characters). "
                        f"Consider breaking into multiple questions.",
                        "Split this into two or more shorter questions so users can answer step by step.",
                    )
        elif node.type == "conclusion":
            cdata = node.conclusion_data
            if not cdata:
                ctx.error(
                    f"Conclusion node '{node.id}' has invalid data type",
                    "Open the conclusion and re-save its title and summary, or recreate the node.",
                )
                continue
            if not cdata.title:
                ctx.error(
                    f"Conclusion node '{node.id}' missing title",
                    "Select the conclusion and add a short title in the side panel.",
                )
            if not cdata.summary:
                ctx.error(
                    f"Conclusion node '{node.id}' missing summary",
                    "Select the conclusion and add a summary describing the outcome.",
                )
            # Validate recommendations is a list
            if cdata.recommendations is not None and not isinstance(cdata.recommendations, list):
                ctx.error(
                    f"Conclusion node '{node.id}' recommendations must be a list",
                    "Format recommendations as a list of bullet points, not a single string.",
                )


def _validate_question_options(nodes: list[GraphNode], ctx: _ValidationContext) -> None:
    """Validate question options and type-specific requirements.

    Only applies to question nodes. Conclusion nodes are skipped.
    """
    for node in nodes:
        # Skip conclusion nodes - they don't have question-style options
        if node.type == "conclusion":
            continue

        qdata = node.question_data
        if not qdata:
            continue

        if qdata.type == "radio":
            if not qdata.options or len(qdata.options) == 0:
                ctx.error(
                    f"Radio question '{node.id}' must have options",
                    "Open the node and add at least one answer choice under Options.",
                )
            else:
                # BLOCK: Empty option labels
                for i, opt in enumerate(qdata.options):
                    if not opt or not opt.strip():
                        ctx.error(
                            f"Question '{node.id}' has empty option at position {i + 1}",
                            "Remove the blank option or enter label text for every choice.",
                        )

                # BLOCK: Duplicate option labels
                option_counts: dict[str, int] = {}
                for opt in qdata.options:
                    if opt:
                        option_counts[opt] = option_counts.get(opt, 0) + 1

                duplicates = [opt for opt, count in option_counts.items() if count > 1]
                if duplicates:
                    ctx.error(
                        f"Question '{node.id}' has duplicate options: {', '.join(duplicates)}",
                        "Rename or merge duplicate choices so each option label is unique.",
                    )

                # WARN: Too many options
                MAX_OPTIONS = 15
                if len(qdata.options) > MAX_OPTIONS:
                    ctx.warning(
                        f"⚠️ Question '{node.id}' has {len(qdata.options)} options. "
                        f"Consider grouping options for better UX.",
                        "Group related choices or split into a follow-up question.",
                    )


def _validate_edge_conditions(
    nodes: list[GraphNode], graph: DTGraph, ctx: _ValidationContext
) -> None:
    """Validate edge conditions for all nodes.

    - Question nodes: validate conditions match options
    - Conclusion nodes: should have no outgoing edges (validated elsewhere)
    - Edges TO conclusions: must be conditional (no defaults)
    """
    conclusion_ids = graph.conclusion_ids

    for node in nodes:
        # Conclusion nodes shouldn't have outgoing edges
        if node.type == "conclusion":
            continue

        qdata = node.question_data
        if not qdata:
            continue

        edges_out = graph.get_outgoing_edges(node.id)

        for edge in edges_out:
            # Check: edges to conclusions must be conditional
            if edge.target in conclusion_ids:
                if edge.condition is None or not edge.condition.strip():
                    ctx.error(
                        f"Edge to conclusion '{edge.target}' from '{node.id}' must be "
                        "conditional. Conclusions can only be reached by explicit answers.",
                        "Edit the edge and set its condition to a specific answer option "
                        "instead of leaving it as a default.",
                    )

            if edge.condition is None or not edge.condition.strip():
                continue

            cond = edge.condition.strip()

            if PROHIBITED_PATTERN.search(cond):
                ctx.error(
                    f"Condition on '{node.id}' → '{edge.target}' must be a simple "
                    "literal without operators",
                    "Use an exact option label as the condition; remove operators or expressions.",
                )

            if qdata.type == "radio":
                if not qdata.options or cond not in qdata.options:
                    ctx.error(
                        f"Condition '{cond}' from '{node.id}' must match an option label",
                        "Change the edge condition to match one of this question's option labels exactly.",
                    )


def _validate_graph_structure(
    graph: DTGraph, nodes: list[GraphNode], ctx: _ValidationContext
) -> None:
    """Validate graph structure and add warnings for potential issues.

    Handles both question and conclusion nodes with appropriate rules.
    """
    conclusion_ids = graph.conclusion_ids
    question_nodes = graph.get_question_nodes()
    conclusion_nodes = graph.get_conclusion_nodes()

    # WARN: Cycles
    cycle_detected, cycle_desc = has_cycle(graph)
    if cycle_detected and cycle_desc:
        ctx.warning(
            f"⚠️ {cycle_desc}",
            "Break the loop by removing or retargeting one edge in the cycle.",
        )

    # WARN: Orphaned nodes
    orphans = find_orphaned_nodes(graph)
    if orphans:
        ctx.warning(
            f"⚠️ Orphaned nodes: {', '.join(orphans)}",
            "Connect each orphaned node from the entry question, or delete it if unused.",
        )

    # WARN: Unreachable nodes from entry point
    entry_nodes = graph.get_entry_nodes()
    if entry_nodes:
        reachable = set()
        queue = [n.id for n in entry_nodes]

        while queue:
            current = queue.pop(0)
            if current in reachable:
                continue
            reachable.add(current)

            outgoing = [e.target for e in graph.edges if e.source == current]
            queue.extend(outgoing)

        unreachable = [n.id for n in graph.nodes if n.id not in reachable]
        if unreachable:
            # Distinguish between unreachable questions and conclusions
            unreachable_conclusions = [n for n in unreachable if n in conclusion_ids]
            unreachable_questions = [n for n in unreachable if n not in conclusion_ids]

            if unreachable_conclusions:
                ctx.warning(
                    f"⚠️ Unreachable conclusions: {', '.join(unreachable_conclusions)}. "
                    f"These conclusions can never be reached from the workflow.",
                    "Add conditional edges from earlier questions so each conclusion can be reached.",
                )
            if unreachable_questions:
                ctx.warning(
                    f"⚠️ Unreachable questions: {', '.join(unreachable_questions)}. "
                    f"These questions cannot be reached from the start.",
                    "Add edges from upstream questions so users can reach this question.",
                )

    # WARN: No entry point
    if not entry_nodes:
        ctx.warning(
            "⚠️ No entry point (all nodes have incoming edges)",
            "Ensure exactly one node has no incoming edges — that node is where users start.",
        )

    # WARN: Entry point is a conclusion (should be a question)
    for entry in entry_nodes:
        if entry.type == "conclusion":
            ctx.warning(
                f"⚠️ Entry node '{entry.id}' is a conclusion. "
                f"Entry point should be a question, not a conclusion.",
                "Add an incoming edge to this conclusion, or make a question the entry node.",
            )

    # WARN: Edges pointing to entry nodes
    entry_node_ids = {n.id for n in entry_nodes}
    edges_to_entry = [e for e in graph.edges if e.target in entry_node_ids]
    if edges_to_entry:
        for edge in edges_to_entry:
            ctx.warning(
                f"⚠️ Edge {edge.source} → {edge.target} points to entry node. "
                f"Entry nodes typically should not have incoming edges.",
                "Remove this incoming edge or choose a different entry node.",
            )

    # WARN: No terminal nodes
    terminal_nodes = graph.get_terminal_nodes()
    if not terminal_nodes:
        ctx.warning(
            "⚠️ No terminal nodes (all nodes have outgoing edges)",
            "Add a conclusion or end the path so at least one node has no outgoing edges.",
        )

    # =========================================================================
    # CONCLUSION-SPECIFIC WARNINGS
    # =========================================================================

    if conclusion_nodes:
        # WARN: Only one conclusion (need at least 2 for meaningful discrimination)
        if len(conclusion_nodes) == 1:
            ctx.warning(
                "⚠️ Only 1 conclusion node found. Workflows should have at least 2 conclusions "
                "to provide meaningful discrimination between outcomes.",
                "Add another conclusion representing a different outcome, or merge outcomes.",
            )

        # WARN: Conclusion has outgoing edges
        for node in conclusion_nodes:
            edges_out = graph.get_outgoing_edges(node.id)
            if edges_out:
                ctx.warning(
                    f"⚠️ Conclusion '{node.id}' has outgoing edges. "
                    f"Conclusions should be terminal (no outgoing edges).",
                    "Delete outgoing edges from this conclusion — conclusions are end states.",
                )

        # WARN: Default edge to conclusion
        for edge in graph.edges:
            if edge.target in conclusion_ids:
                if edge.condition is None or not edge.condition.strip():
                    ctx.warning(
                        f"⚠️ Default edge to conclusion '{edge.target}' from '{edge.source}'. "
                        f"Conclusions should only be reached by explicit conditional edges.",
                        "Set a specific answer condition on this edge instead of leaving it as default.",
                    )

        # WARN: Question node with no outgoing edges (should lead to conclusion or question)
        for node in question_nodes:
            edges_out = graph.get_outgoing_edges(node.id)
            if not edges_out:
                ctx.warning(
                    f"⚠️ Question '{node.id}' has no outgoing edges. "
                    f"All questions should lead to another question or a conclusion.",
                    "Add an outgoing edge to the next question or a conclusion.",
                )

    # WARN: Missing default edges (required-aware) - only for question nodes
    for node in question_nodes:
        qdata = node.question_data
        if not qdata:
            continue

        edges_out = graph.get_outgoing_edges(node.id)
        if not edges_out:
            continue

        has_default = any(e.condition is None or not e.condition.strip() for e in edges_out)

        # Check if all edges go to conclusions (special case: no default allowed)
        all_to_conclusions = all(e.target in conclusion_ids for e in edges_out)

        conds = {e.condition.strip() for e in edges_out if e.condition}
        options_set = set(qdata.options or [])

        if conds != options_set:
            missing = sorted(options_set - conds)
            if qdata.required:
                # If all edges go to conclusions, we can't add a default
                if not has_default and not all_to_conclusions:
                    ctx.warning(
                        f"⚠️ Radio question '{node.id}' has "
                        f"partial conditional coverage (missing: {', '.join(missing)}). "
                        "Add a default edge or add conditions for missing options.",
                        "Add conditional edges for each missing option, or add one default edge "
                        "for uncovered answers.",
                    )
                elif all_to_conclusions and missing:
                    ctx.warning(
                        f"⚠️ Radio question '{node.id}' leads only to conclusions but "
                        f"missing conditions for: {', '.join(missing)}. "
                        "Add conditional edges for all options.",
                        "Create a conditional edge for each listed option so every answer "
                        "reaches a conclusion.",
                    )
            else:
                ctx.warning(
                    f"⚠️ Optional radio question '{node.id}' missing "
                    f"conditional edges for: {', '.join(missing)}. "
                    "All options must have edges when question is optional.",
                    "Add a conditional edge for every option on this optional question.",
                )

        if not qdata.required and not has_default and not all_to_conclusions:
            ctx.warning(
                f"⚠️ Optional radio question '{node.id}' must have a "
                "default edge to handle when the user skips it",
                "Add one default (unconditioned) outgoing edge for when the user skips this question.",
            )

    # WARN: Radio questions with insufficient branching - only for question nodes
    for node in question_nodes:
        qdata = node.question_data
        if not qdata:
            continue

        edges_out = graph.get_outgoing_edges(node.id)

        if len(edges_out) < 2:
            ctx.warning(
                f"⚠️ {qdata.type.capitalize()} question '{node.id}' has only {len(edges_out)} "
                f"outgoing edge(s). Consider at least 2 edges to create meaningful branching logic.",
                "Add another outgoing edge so different answers can lead to different paths.",
            )

        if len(edges_out) >= 2:
            unique_targets = {e.target for e in edges_out}
            if len(unique_targets) == 1:
                ctx.warning(
                    f"⚠️ {qdata.type.capitalize()} question '{node.id}' has {len(edges_out)} "
                    f"edges but they all lead to the same node ('{list(unique_targets)[0]}'). "
                    f"No actual branching is occurring.",
                    "Route at least one option to a different question or conclusion, "
                    "or merge duplicate edges.",
                )

    # WARN: Metadata
    if graph.metadata is None:
        ctx.warning(
            "⚠️ Graph metadata is missing",
            "Open workflow settings and add a title and description.",
        )
    elif not graph.metadata.title:
        ctx.warning(
            "⚠️ Graph metadata.title is missing",
            "Open workflow settings and enter a title.",
        )


# =============================================================================
# Three-Tier Validation System
# =============================================================================


def has_cycle(graph: DTGraph) -> tuple[bool, str | None]:
    """
    Detect cycles in the graph using DFS with path tracking.

    Returns:
        (has_cycle, cycle_description)
    """
    if not graph.nodes:
        return False, None

    adjacency: dict[str, list[str]] = {node.id: [] for node in graph.nodes}
    for edge in graph.edges:
        adjacency.setdefault(edge.source, []).append(edge.target)

    visited: set[str] = set()
    rec_stack: set[str] = set()
    parent: dict[str, str] = {}

    def dfs(node_id: str) -> str | None:
        visited.add(node_id)
        rec_stack.add(node_id)

        for neighbor in adjacency.get(node_id, []):
            if neighbor not in visited:
                parent[neighbor] = node_id
                cycle_node = dfs(neighbor)
                if cycle_node:
                    return cycle_node
            elif neighbor in rec_stack:
                parent[neighbor] = node_id
                return neighbor

        rec_stack.remove(node_id)
        return None

    for node in graph.nodes:
        if node.id not in visited:
            cycle_node = dfs(node.id)
            if cycle_node:
                path = [cycle_node]
                current = parent.get(cycle_node)
                while current and current != cycle_node:
                    path.append(current)
                    current = parent.get(current)
                path.reverse()
                path.append(cycle_node)

                cycle_str = " → ".join(path)
                return True, f"Cycle detected: {cycle_str}"

    return False, None


def find_orphaned_nodes(graph: DTGraph) -> list[str]:
    """
    Find nodes that are unreachable from any entry point using BFS.

    Returns:
        List of orphaned node IDs
    """
    if not graph.nodes:
        return []

    node_ids = {node.id for node in graph.nodes}
    has_incoming = {edge.target for edge in graph.edges}
    entry_points = node_ids - has_incoming

    if not entry_points:
        return list(node_ids)

    reachable: set[str] = set()
    queue: deque[str] = deque(entry_points)
    reachable.update(entry_points)

    adjacency: dict[str, list[str]] = {node.id: [] for node in graph.nodes}
    for edge in graph.edges:
        adjacency.setdefault(edge.source, []).append(edge.target)

    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, []):
            if neighbor not in reachable:
                reachable.add(neighbor)
                queue.append(neighbor)

    orphaned = node_ids - reachable
    return sorted(orphaned)


def _validate_basic_structure(graph: DTGraph, ctx: _ValidationContext) -> bool:
    """Validate basic graph structure. Returns True if valid, False if critical errors."""
    if not graph.nodes:
        ctx.error(
            "Graph must have at least one node",
            "Add a question or conclusion node to start building your workflow.",
        )
        return False
    return True


def _validate_node_integrity(graph: DTGraph, ctx: _ValidationContext) -> None:
    """Validate node-level integrity issues."""
    node_ids = {node.id for node in graph.nodes}

    for node in graph.nodes:
        if not node.id or not node.id.strip():
            ctx.error(
                "Node has empty ID",
                "Each node needs a non-empty ID; delete corrupted nodes and recreate them.",
            )
        elif not VALID_ID_PATTERN.match(node.id):
            ctx.error(
                f"Node ID '{node.id}' is invalid. Must start with a letter and "
                f"contain only letters, numbers, underscores, or hyphens.",
                "Rename the node so the ID starts with a letter and uses only letters, "
                "numbers, underscores, or hyphens.",
            )

    if len(node_ids) != len(graph.nodes):
        ctx.error(
            "Duplicate node IDs found",
            "Rename one of the duplicate nodes so every ID is unique.",
        )


def _validate_edge_integrity(graph: DTGraph, ctx: _ValidationContext) -> None:
    """Validate edge-level integrity issues."""
    node_ids = graph.node_ids

    for edge in graph.edges:
        if edge.source not in node_ids:
            ctx.error(
                f"Edge source '{edge.source}' not found in nodes",
                "Delete the broken edge or reconnect it to an existing node.",
            )
        if edge.target not in node_ids:
            ctx.error(
                f"Edge target '{edge.target}' not found in nodes",
                "Delete the broken edge or reconnect it to an existing node.",
            )

    # BLOCK: Self-loops
    for edge in graph.edges:
        if edge.source == edge.target:
            ctx.error(
                f"Self-loop detected on node '{edge.source}'",
                "Remove the edge that points from this node back to itself, "
                "or retarget it to a different node.",
            )

    # BLOCK: Duplicate edges
    edge_signatures = set()
    for edge in graph.edges:
        sig = (edge.source, edge.target, edge.condition)
        if sig in edge_signatures:
            cond_str = f" (condition: {edge.condition})" if edge.condition else ""
            ctx.error(
                f"Duplicate edge: {edge.source} → {edge.target}{cond_str}",
                "Delete one of the duplicate connections in the edge panel.",
            )
        edge_signatures.add(sig)

    # BLOCK: Multiple default edges from same node
    node_default_edges: dict[str, int] = {}
    for edge in graph.edges:
        if edge.condition is None or not edge.condition.strip():
            node_default_edges[edge.source] = node_default_edges.get(edge.source, 0) + 1

    for node_id, count in node_default_edges.items():
        if count > 1:
            ctx.error(
                f"Node '{node_id}' has {count} default edges (edges without conditions). "
                f"Only one default edge is allowed per node.",
                "Keep only one default (unconditioned) outgoing edge from this node.",
            )


def validate_graph_for_generation(
    graph: DTGraph,
    *,
    collect_only_question_ids: frozenset[str] | None = None,
    allowed_conclusion_ids: frozenset[str] | None = None,
    allowed_conclusions_parse_ok: bool = True,
) -> ValidationResult:
    """Tier-2 validation plus branching quality gates for agentic build."""
    from smeme.qnr.generation.agentic.branching_quality import assess_branching_quality

    result = validate_graph_for_editing(graph)
    if not result["is_valid"]:
        return result

    assessment = assess_branching_quality(
        graph,
        collect_only_question_ids=collect_only_question_ids,
        allowed_conclusion_ids=allowed_conclusion_ids,
        allowed_conclusions_parse_ok=allowed_conclusions_parse_ok,
    )
    branching_errors = assessment.errors
    branching_warnings = assessment.warnings

    if branching_errors:
        merged_suggestions = {
            **result.get("suggestions", {}),
            **{d.message: d.suggestion for d in assessment.diagnostics},
        }
        return ValidationResult(
            is_valid=False,
            errors=[*result["errors"], *branching_errors],
            warnings=[*result["warnings"], *branching_warnings],
            suggestions=merged_suggestions,
        )

    if branching_warnings:
        merged_suggestions = {
            **result.get("suggestions", {}),
            **{d.message: d.suggestion for d in assessment.diagnostics},
        }
        return ValidationResult(
            is_valid=True,
            errors=result["errors"],
            warnings=[*result["warnings"], *branching_warnings],
            suggestions=merged_suggestions,
        )

    return result


def validate_graph_for_editing(graph: DTGraph) -> ValidationResult:
    """
    Tier-2 validation: Lenient validation for draft editing.

    Blocks:
    - More than one entry node (no incoming edges)
    - Self-loops
    - Duplicate edges
    - Invalid edge conditions (operators, mismatched options)

    Warns:
    - Cycles
    - Orphaned nodes
    - No entry point
    - No terminal nodes
    - Missing default edges

    Returns:
        ValidationResult with is_valid, errors, warnings, and suggestions
    """
    ctx = _ValidationContext()

    if not _validate_basic_structure(graph, ctx):
        return ctx.to_result(is_valid=False)

    multi_err = _multiple_entry_points_message(graph)
    if multi_err:
        ctx.error(
            multi_err,
            "Only one node should have no incoming edges. Remove the extra entry "
            "or connect it with an incoming edge from another question.",
        )

    # All nodes are questions
    nodes = list(graph.nodes)

    _validate_node_integrity(graph, ctx)
    _validate_edge_integrity(graph, ctx)
    _validate_question_nodes(nodes, ctx)
    _validate_question_options(nodes, ctx)
    _validate_edge_conditions(nodes, graph, ctx)

    if ctx.errors:
        return ctx.to_result(is_valid=False)

    _validate_graph_structure(graph, nodes, ctx)

    return ctx.to_result(is_valid=True)


def validate_graph_for_publication(graph: DTGraph) -> tuple[bool, list[str]]:
    """
    Tier-3 validation: Strict validation before preview/publish.

    All Tier-2 warnings become blocking errors.
    Reasoning authoring contract runs after tier-3 (strict graph + acyclicity for compile).

    Returns:
        (is_valid, errors)
    """
    result = validate_graph_for_editing(graph)

    if not result["is_valid"]:
        return False, result["errors"]

    if result["warnings"]:
        all_errors = result["errors"] + [w.replace("⚠️ ", "❌ ") for w in result["warnings"]]
        return False, all_errors

    from smeme.reasoning.contract import enforce_reasoning_authoring_contract

    reasoning_errors = enforce_reasoning_authoring_contract(graph)
    if reasoning_errors:
        return False, reasoning_errors

    return True, []


def extract_validation_node_id(message: str) -> str | None:
    """Parse node id from a validation message when present."""
    for pattern in _VALIDATION_NODE_ID_PATTERNS:
        match = pattern.search(message)
        if match:
            return match.group(1)
    return None


def build_validation_issue_rows(
    errors: list[str],
    warnings: list[str],
    *,
    graph: DTGraph | None = None,
    suggestions: dict[str, str] | None = None,
) -> list[ValidationIssueRow]:
    """Flat issue list for sidebar jump-to-node (errors first, then warnings)."""
    node_by_message: dict[str, str] = {}
    if graph is not None:
        for node_id, status in get_node_validation_status(graph).items():
            for msg in status["errors"] + status["warnings"]:
                node_by_message[msg] = node_id

    hint_by_message = suggestions or {}
    rows: list[ValidationIssueRow] = []

    def _node_for(message: str) -> str | None:
        return node_by_message.get(message) or extract_validation_node_id(message)

    for message in errors:
        rows.extend(
            _issue_rows_for_message(
                message,
                "error",
                _node_for,
                suggestion=hint_by_message.get(message),
            )
        )
    for message in warnings:
        rows.extend(
            _issue_rows_for_message(
                message,
                "warning",
                _node_for,
                suggestion=hint_by_message.get(message),
            )
        )
    return rows


def get_node_validation_status(graph: DTGraph) -> dict[str, NodeValidationStatus]:
    """
    Extract node-specific validation issues from graph validation.

    Returns a mapping of node_id -> {"errors": [...], "warnings": [...]}
    """
    result = validate_graph_for_editing(graph)

    node_status: dict[str, NodeValidationStatus] = {}

    for error in result["errors"]:
        for node_id in node_ids_for_validation_message(error):
            if node_id not in node_status:
                node_status[node_id] = {"errors": [], "warnings": []}
            node_status[node_id]["errors"].append(error)

    for warning in result["warnings"]:
        for node_id in node_ids_for_validation_message(warning):
            if node_id not in node_status:
                node_status[node_id] = {"errors": [], "warnings": []}
            node_status[node_id]["warnings"].append(warning)

    return node_status


def categorize_validation_messages(messages: list[str]) -> dict[str, list[str]]:
    """Categorize validation messages by type for better organization."""
    categories: dict[str, list[str]] = {
        "Structure": [],
        "Nodes": [],
        "Edges": [],
        "Content": [],
        "Metadata": [],
    }

    for msg in messages:
        msg_lower = msg.lower()

        if any(
            keyword in msg_lower
            for keyword in ["cycle", "orphan", "unreachable", "entry point", "terminal"]
        ):
            categories["Structure"].append(msg)
        elif any(
            keyword in msg_lower
            for keyword in ["edge", "condition", "default", "branch", "outgoing", "incoming"]
        ):
            categories["Edges"].append(msg)
        elif any(
            keyword in msg_lower for keyword in ["long text", "too many", "very long", "consider"]
        ):
            categories["Content"].append(msg)
        elif "metadata" in msg_lower:
            categories["Metadata"].append(msg)
        else:
            categories["Nodes"].append(msg)

    return {k: v for k, v in categories.items() if v}


def format_validation_results(
    errors: list[str],
    warnings: list[str],
) -> dict[str, dict[str, list[str]]]:
    """Format validation results for template rendering."""
    return {
        "errors": categorize_validation_messages(errors),
        "warnings": categorize_validation_messages(warnings),
        "error_count": len(errors),
        "warning_count": len(warnings),
    }
