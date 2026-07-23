"""Graph modification operations for the Editor Workflow.

All operations are pure functions that take a graph and return a modified graph.
They do NOT touch the database directly.

Supports both question nodes and conclusion nodes.
"""

import logging
from copy import deepcopy
from typing import Literal

from smeme.qnr.models import ConclusionData, DTGraph, GraphEdge, GraphNode, QuestionData

logger = logging.getLogger(__name__)


# =============================================================================
# Node Operations
# =============================================================================


def create_node(
    graph: DTGraph,
    node_id: str,
    question_text: str,
    question_type: str = "radio",
    options: list[str] | None = None,
    help_text: str | None = None,
    required: bool = True,
) -> DTGraph:
    """
    Create a new question node in the graph (radio-only).

    Args:
        graph: Current graph
        node_id: New node ID
        question_text: Question text
        question_type: Must be ``radio`` (kept for call-site compatibility)
        options: Non-empty list of radio option labels
        help_text: Optional help text
        required: Whether answer is required

    Returns:
        Modified graph with new node

    Raises:
        ValueError: If node_id already exists, type is not radio, or options are empty
    """
    # Check if node already exists
    if any(n.id == node_id for n in graph.nodes):
        msg = f"Node '{node_id}' already exists"
        raise ValueError(msg)

    if question_type != "radio":
        msg = f"Only radio questions are supported, got {question_type!r}"
        raise ValueError(msg)

    opts = [str(o).strip() for o in (options or []) if o is not None and str(o).strip()]
    if not opts:
        msg = "Radio questions require at least one non-empty option"
        raise ValueError(msg)

    logger.info(f"Creating question node: {node_id}")

    # Create new question node
    new_node = GraphNode(
        id=node_id,
        type="question",
        data=QuestionData(
            text=question_text,
            type="radio",
            options=opts,
            help_text=help_text,
            required=required,
        ),
    )

    # Add to graph
    new_graph = deepcopy(graph)
    new_graph.nodes.append(new_node)

    return new_graph


def create_conclusion_node(
    graph: DTGraph,
    node_id: str,
    title: str,
    summary: str,
    recommendations: list[str] | None = None,
    severity: Literal["info", "warning", "critical"] | None = "info",
) -> DTGraph:
    """
    Create a new conclusion node in the graph.

    Conclusion nodes are terminal endpoints that represent the outcome of a
    decision path. They should have no outgoing edges.

    Args:
        graph: Current graph
        node_id: New node ID (e.g., 'conclusion_llc', 'conclusion_1')
        title: Short title for the conclusion
        summary: Explanation of what this conclusion means
        recommendations: Actionable next steps
        severity: Urgency indicator (info, warning, critical)

    Returns:
        Modified graph with new conclusion node

    Raises:
        ValueError: If node_id already exists
    """
    # Check if node already exists
    if any(n.id == node_id for n in graph.nodes):
        msg = f"Node '{node_id}' already exists"
        raise ValueError(msg)

    logger.info(f"Creating conclusion node: {node_id}")

    # Create new conclusion node
    new_node = GraphNode(
        id=node_id,
        type="conclusion",
        data=ConclusionData(
            title=title,
            summary=summary,
            recommendations=recommendations or [],
            severity=severity,
        ),
    )

    # Add to graph
    new_graph = deepcopy(graph)
    new_graph.nodes.append(new_node)

    return new_graph


def update_node(
    graph: DTGraph,
    node_id: str,
    question_text: str,
    question_type: str,
    options: list[str] | None = None,
    help_text: str | None = None,
    required: bool = True,
) -> DTGraph:
    """
    Update an existing question node's data.

    For updating conclusion nodes, use update_conclusion_node instead.

    Args:
        graph: Current graph
        node_id: Node ID to update
        question_text: Updated question text
        question_type: Updated question type
        options: Updated options
        help_text: Updated help text
        required: Whether answer is required

    Returns:
        Modified graph with updated node

    Raises:
        ValueError: If node not found or node is not a question
    """
    # Find node
    node_index = next((i for i, n in enumerate(graph.nodes) if n.id == node_id), None)
    if node_index is None:
        msg = f"Node '{node_id}' not found"
        raise ValueError(msg)

    existing_node = graph.nodes[node_index]
    if existing_node.type == "conclusion":
        msg = f"Node '{node_id}' is a conclusion node. Use update_conclusion_node instead."
        raise ValueError(msg)

    if question_type != "radio":
        msg = f"Only radio questions are supported, got {question_type!r}"
        raise ValueError(msg)

    opts = [str(o).strip() for o in (options or []) if o is not None and str(o).strip()]
    if not opts:
        msg = "Radio questions require at least one non-empty option"
        raise ValueError(msg)

    logger.info(f"Updating question node: {node_id}")

    # Create updated question node
    updated_node = GraphNode(
        id=node_id,
        type="question",
        data=QuestionData(
            text=question_text,
            type="radio",
            options=opts,
            help_text=help_text,
            required=required,
        ),
    )

    # Update in graph
    new_graph = deepcopy(graph)
    new_graph.nodes[node_index] = updated_node

    return new_graph


def update_conclusion_node(
    graph: DTGraph,
    node_id: str,
    title: str,
    summary: str,
    recommendations: list[str] | None = None,
    severity: Literal["info", "warning", "critical"] | None = "info",
) -> DTGraph:
    """
    Update an existing conclusion node's data.

    Args:
        graph: Current graph
        node_id: Node ID to update
        title: Updated title
        summary: Updated summary
        recommendations: Updated recommendations
        severity: Updated severity

    Returns:
        Modified graph with updated conclusion node

    Raises:
        ValueError: If node not found or node is not a conclusion
    """
    # Find node
    node_index = next((i for i, n in enumerate(graph.nodes) if n.id == node_id), None)
    if node_index is None:
        msg = f"Node '{node_id}' not found"
        raise ValueError(msg)

    existing_node = graph.nodes[node_index]
    if existing_node.type != "conclusion":
        msg = f"Node '{node_id}' is not a conclusion node. Use update_node instead."
        raise ValueError(msg)

    logger.info(f"Updating conclusion node: {node_id}")

    # Create updated conclusion node
    updated_node = GraphNode(
        id=node_id,
        type="conclusion",
        data=ConclusionData(
            title=title,
            summary=summary,
            recommendations=recommendations or [],
            severity=severity,
        ),
    )

    # Update in graph
    new_graph = deepcopy(graph)
    new_graph.nodes[node_index] = updated_node

    return new_graph


def delete_node(graph: DTGraph, node_id: str) -> DTGraph:
    """
    Delete a node and all connected edges.

    Args:
        graph: Current graph
        node_id: Node ID to delete

    Returns:
        Modified graph with node and connected edges removed

    Raises:
        ValueError: If node not found
    """
    # Check if node exists
    if not any(n.id == node_id for n in graph.nodes):
        msg = f"Node '{node_id}' not found"
        raise ValueError(msg)

    logger.info(f"Deleting node: {node_id}")

    # Remove node and all connected edges
    new_graph = deepcopy(graph)
    new_graph.nodes = [n for n in new_graph.nodes if n.id != node_id]
    new_graph.edges = [e for e in new_graph.edges if e.source != node_id and e.target != node_id]

    return new_graph


def create_node_wired(graph: DTGraph, operation_data: dict) -> DTGraph:
    """
    Create a question or conclusion node and required edges in one atomic graph edit.

    ``operation_data`` keys:

    - ``kind``: ``"question"`` | ``"conclusion"``
    - ``node_id``: new node id (required, caller allocates uniqueness)

    Question:
    - ``question_text``, ``question_type``, ``options``, ``help_text``, ``required``
    - ``question_wiring``: ``"none"`` (first/only node), ``"incoming"``, ``"new_start"``
    - ``predecessor_ids``: list[str] (required for ``incoming``)
    - ``incoming_edge_condition``: optional str (same condition for each predecessor→new edge)

    Conclusion:
    - ``title``, ``summary``, ``recommendations``, ``severity``
    - ``conclusion_edges``: list[dict] with ``source``, ``condition`` (non-empty; edges to conclusions)

    Raises:
        ValueError: invalid wiring, missing fields, or graph rules violated
    """
    kind = operation_data.get("kind")
    if kind not in ("question", "conclusion"):
        msg = f"kind must be 'question' or 'conclusion', got {kind!r}"
        raise ValueError(msg)

    node_id = operation_data.get("node_id")
    if not node_id or not str(node_id).strip():
        msg = "node_id is required"
        raise ValueError(msg)
    node_id = str(node_id).strip()

    if kind == "question":
        return _create_node_wired_question(graph, node_id, operation_data)

    return _create_node_wired_conclusion(graph, node_id, operation_data)


def _require_question_source(graph: DTGraph, source_id: str) -> None:
    node = graph.get_node(source_id)
    if not node:
        msg = f"Source node '{source_id}' not found"
        raise ValueError(msg)
    if not node.is_question():
        msg = f"Edges must originate from a question; '{source_id}' is not a question"
        raise ValueError(msg)


def _create_node_wired_question(graph: DTGraph, node_id: str, operation_data: dict) -> DTGraph:
    question_text = operation_data.get("question_text") or ""
    question_text = question_text.strip()
    if not question_text:
        raise ValueError("Question text is required")

    question_type = operation_data.get("question_type") or "radio"
    options = operation_data.get("options")
    help_text = operation_data.get("help_text")
    required = bool(operation_data.get("required", True))

    wiring = operation_data.get("question_wiring")
    if not graph.nodes:
        wiring = "none"
    else:
        if wiring is None or (isinstance(wiring, str) and not wiring.strip()):
            raise ValueError(
                "Choose how to connect the question: 'incoming' (from existing question(s)) "
                "or 'new_start' (new entry with a default link to the current start)."
            )
        wiring = str(wiring).strip()

    g = create_node(
        graph,
        node_id=node_id,
        question_text=question_text,
        question_type=question_type,
        options=options,
        help_text=help_text,
        required=required,
    )

    if wiring == "none":
        if graph.nodes:
            msg = "question_wiring 'none' is only valid for the first node on an empty graph"
            raise ValueError(msg)
        return g

    if wiring == "incoming":
        preds = operation_data.get("predecessor_ids") or []
        if not preds:
            raise ValueError("Select at least one predecessor question (incoming wiring).")
        inc_cond = operation_data.get("incoming_edge_condition")
        if isinstance(inc_cond, str):
            inc_cond = inc_cond.strip() or None
        else:
            inc_cond = None
        for p in preds:
            _require_question_source(graph, p)
            g = create_edge(g, p, node_id, inc_cond)
        return g

    if wiring == "new_start":
        entries = graph.get_entry_nodes()
        if len(entries) != 1:
            n = len(entries)
            msg = (
                "Replacing the entry requires exactly one current entry node; "
                f"found {n}. Fix the graph or use incoming wiring instead."
            )
            raise ValueError(msg)
        entry_id = entries[0].id
        if entry_id == node_id:
            raise ValueError("Invalid entry target")
        if not graph.get_node(entry_id).is_question():
            raise ValueError("Current entry must be a question to chain a new start before it")
        return create_edge(g, node_id, entry_id, None)

    msg = f"Unknown question_wiring: {wiring!r}"
    raise ValueError(msg)


def _create_node_wired_conclusion(graph: DTGraph, node_id: str, operation_data: dict) -> DTGraph:
    if not graph.nodes:
        raise ValueError("Add at least one question before adding a conclusion.")

    title = (operation_data.get("title") or "").strip()
    summary = (operation_data.get("summary") or "").strip()
    if not title:
        raise ValueError("Conclusion title is required")
    if not summary:
        raise ValueError("Conclusion summary is required")

    recommendations = operation_data.get("recommendations") or []
    severity = operation_data.get("severity") or "info"

    raw_edges = operation_data.get("conclusion_edges")
    if not raw_edges:
        raise ValueError("Add at least one incoming edge (source question + condition).")

    g = create_conclusion_node(
        graph,
        node_id=node_id,
        title=title,
        summary=summary,
        recommendations=recommendations,
        severity=severity,
    )

    for item in raw_edges:
        if not isinstance(item, dict):
            raise ValueError("Each conclusion edge must be a JSON object")
        src = (item.get("source") or "").strip()
        cond = (item.get("condition") or "").strip()
        if not src:
            raise ValueError("Each conclusion edge needs a source question id")
        if not cond:
            raise ValueError(
                "Each edge to a conclusion must have a non-empty condition (no default edges)."
            )
        _require_question_source(graph, src)
        g = create_edge(g, src, node_id, cond)

    return g


# =============================================================================
# Edge Operations
# =============================================================================


def create_edge(graph: DTGraph, source: str, target: str, condition: str | None = None) -> DTGraph:
    """
    Create a new edge between two nodes.

    Args:
        graph: Current graph
        source: Source node ID
        target: Target node ID
        condition: Optional condition

    Returns:
        Modified graph with new edge

    Raises:
        ValueError: If nodes don't exist or edge already exists
    """
    # Check nodes exist
    node_ids = {n.id for n in graph.nodes}
    if source not in node_ids:
        msg = f"Source node '{source}' not found"
        raise ValueError(msg)
    if target not in node_ids:
        msg = f"Target node '{target}' not found"
        raise ValueError(msg)

    # Check for duplicate edge
    for edge in graph.edges:
        if edge.source == source and edge.target == target and edge.condition == condition:
            msg = f"Edge from '{source}' to '{target}' with condition '{condition}' already exists"
            raise ValueError(msg)

    logger.info(f"Creating edge: {source} -> {target} (condition: {condition})")

    # Create new edge
    new_edge = GraphEdge(source=source, target=target, condition=condition)

    # Add to graph
    new_graph = deepcopy(graph)
    new_graph.edges.append(new_edge)

    return new_graph


def update_edge(
    graph: DTGraph,
    source: str,
    old_target: str,
    new_target: str,
    old_condition: str | None = None,
    condition: str | None = None,
) -> DTGraph:
    """
    Update an existing edge's target and/or condition.

    Args:
        graph: Current graph
        source: Source node ID
        old_target: Current target node ID
        new_target: New target node ID
        old_condition: Current condition (to identify the specific edge)
        condition: Updated condition

    Returns:
        Modified graph with updated edge

    Raises:
        ValueError: If edge not found or new target doesn't exist
    """
    # Normalize conditions (treat empty string as None)
    normalized_old_condition = (
        old_condition.strip() if old_condition and old_condition.strip() else None
    )
    normalized_new_condition = condition.strip() if condition and condition.strip() else None

    # Find edge to update (match on source, target, AND normalized condition)
    def edge_matches(e: GraphEdge) -> bool:
        e_condition = e.condition.strip() if e.condition and e.condition.strip() else None
        return (
            e.source == source
            and e.target == old_target
            and e_condition == normalized_old_condition
        )

    edge_index = next(
        (i for i, e in enumerate(graph.edges) if edge_matches(e)),
        None,
    )
    if edge_index is None:
        msg = f"Edge from '{source}' to '{old_target}' with condition '{old_condition}' not found"
        raise ValueError(msg)

    # Check new target exists
    node_ids = {n.id for n in graph.nodes}
    if new_target not in node_ids:
        msg = f"Target node '{new_target}' not found"
        raise ValueError(msg)

    logger.info(
        f"Updating edge: {source} -> {old_target} (condition: {normalized_old_condition}) => "
        f"{source} -> {new_target} (condition: {normalized_new_condition})"
    )

    # Create updated edge with normalized condition
    updated_edge = GraphEdge(source=source, target=new_target, condition=normalized_new_condition)

    # Update in graph
    new_graph = deepcopy(graph)
    new_graph.edges[edge_index] = updated_edge

    return new_graph


def delete_edge(graph: DTGraph, source: str, target: str, condition: str | None = None) -> DTGraph:
    """
    Delete an edge between two nodes.

    Args:
        graph: Current graph
        source: Source node ID
        target: Target node ID
        condition: Edge condition (None for default edge)

    Returns:
        Modified graph with edge removed

    Raises:
        ValueError: If edge not found
    """
    # Normalize condition (treat empty string as None)
    normalized_condition = condition.strip() if condition and condition.strip() else None

    # Check edge exists with specific condition
    edge_exists = any(
        e.source == source
        and e.target == target
        and (e.condition.strip() if e.condition and e.condition.strip() else None)
        == normalized_condition
        for e in graph.edges
    )
    if not edge_exists:
        cond_str = f" (condition: {condition})" if condition else " (default)"
        msg = f"Edge from '{source}' to '{target}'{cond_str} not found"
        raise ValueError(msg)

    cond_log = f" (condition: {condition})" if condition else " (default)"
    logger.info(f"Deleting edge: {source} -> {target}{cond_log}")

    # Remove specific edge (match on source, target, AND condition)
    new_graph = deepcopy(graph)
    new_graph.edges = [
        e
        for e in new_graph.edges
        if not (
            e.source == source
            and e.target == target
            and (e.condition.strip() if e.condition and e.condition.strip() else None)
            == normalized_condition
        )
    ]

    return new_graph


# =============================================================================
# Operation Dispatcher
# =============================================================================


def apply_operation(graph: DTGraph, operation: str, operation_data: dict) -> DTGraph:
    """
    Apply an operation to the graph.

    This is the main entry point used by the Editor Workflow.

    Args:
        graph: Current graph
        operation: Operation name
        operation_data: Operation-specific data with canonical field names

    Returns:
        Modified graph

    Raises:
        ValueError: If operation is invalid or operation fails
    """
    logger.info(f"Applying operation: {operation}", extra={"data": operation_data})

    if operation == "create_node_wired":
        return create_node_wired(graph, operation_data)

    if operation == "create_node":
        return create_node(
            graph,
            node_id=operation_data["node_id"],
            question_text=operation_data["question_text"],
            question_type=operation_data["question_type"],
            options=operation_data.get("options"),
            help_text=operation_data.get("help_text"),
            required=operation_data.get("required", True),
        )

    if operation == "create_conclusion_node":
        return create_conclusion_node(
            graph,
            node_id=operation_data["node_id"],
            title=operation_data["title"],
            summary=operation_data["summary"],
            recommendations=operation_data.get("recommendations"),
            severity=operation_data.get("severity", "info"),
        )

    if operation == "update_node":
        return update_node(
            graph,
            node_id=operation_data["node_id"],
            question_text=operation_data["question_text"],
            question_type=operation_data["question_type"],
            options=operation_data.get("options"),
            help_text=operation_data.get("help_text"),
            required=operation_data.get("required", True),
        )

    if operation == "update_conclusion_node":
        return update_conclusion_node(
            graph,
            node_id=operation_data["node_id"],
            title=operation_data["title"],
            summary=operation_data["summary"],
            recommendations=operation_data.get("recommendations"),
            severity=operation_data.get("severity", "info"),
        )

    if operation == "delete_node":
        return delete_node(graph, node_id=operation_data["node_id"])

    if operation == "create_edge":
        return create_edge(
            graph,
            source=operation_data["source"],
            target=operation_data["target"],
            condition=operation_data.get("condition"),
        )

    if operation == "update_edge":
        return update_edge(
            graph,
            source=operation_data["source"],
            old_target=operation_data["old_target"],
            new_target=operation_data["new_target"],
            old_condition=operation_data.get("old_condition"),
            condition=operation_data.get("new_condition"),
        )

    if operation == "delete_edge":
        return delete_edge(
            graph,
            source=operation_data["source"],
            target=operation_data["target"],
            condition=operation_data.get("condition"),
        )

    msg = f"Unknown operation: {operation}"
    raise ValueError(msg)
