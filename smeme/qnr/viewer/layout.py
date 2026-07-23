"""Hierarchical graph layout algorithm using BFS.

This module is VIEWER-ONLY. The Editor never calculates positions.
"""

import logging
from collections import deque

from smeme.qnr.models import DTGraph, GraphNode
from smeme.qnr.viewer.models import GraphVisualization, NodePosition, VisualEdge, VisualNode

logger = logging.getLogger(__name__)


# Layout constants
NODE_WIDTH = 200
NODE_HEIGHT = 80
HORIZONTAL_SPACING = 100
VERTICAL_SPACING = 120
CANVAS_PADDING = 50
VISUAL_LABEL_MAX_LEN = 28


def visual_node_label_text(node: GraphNode) -> str:
    """Full display text for a graph node (question text, conclusion title, or id)."""
    if node.is_question() and isinstance(node.data, object) and getattr(node.data, "text", None):
        text = (node.data.text or "").strip()
        if text:
            return " ".join(text.split())
    if node.is_conclusion() and isinstance(node.data, object) and getattr(node.data, "title", None):
        title = (node.data.title or "").strip()
        if title:
            return " ".join(title.split())
    return node.id


def truncate_visual_label(text: str, max_len: int = VISUAL_LABEL_MAX_LEN) -> str:
    """Truncate label for SVG canvas; append ellipsis when over max_len."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def visual_node_tooltip(node: GraphNode, full_text: str) -> str:
    """Hover tooltip: full text plus technical id when display text differs."""
    if full_text != node.id:
        return f"{full_text} ({node.id})"
    return node.id


def _connectivity_maps(
    graph: DTGraph,
) -> tuple[dict[str, list], dict[str, list]]:
    """Incoming and outgoing adjacency lists (edge list order preserved per source)."""
    incoming = {node.id: [] for node in graph.nodes}
    outgoing = {node.id: [] for node in graph.nodes}
    for edge in graph.edges:
        if edge.source in outgoing:
            outgoing[edge.source].append(edge)
        if edge.target in incoming:
            incoming[edge.target].append(edge)
    return incoming, outgoing


def _bfs_layers_grouped(
    graph: DTGraph,
) -> tuple[list[str], dict[int, list[str]], dict[str, list], dict[str, list]]:
    """
    Entry node ids (layout fallback if none), layer -> node ids in layout order,
    plus outgoing/incoming maps.

    Must stay aligned with ``calculate_layout`` / ``linear_node_ids_for_layout``.
    """
    incoming, outgoing = _connectivity_maps(graph)
    entry_nodes = [node_id for node_id, edges in incoming.items() if not edges]

    if not entry_nodes and graph.nodes:
        logger.warning("No entry points found, using first node")
        entry_nodes = [graph.nodes[0].id]

    node_layers = _assign_layers_bfs(entry_nodes, outgoing)

    layers: dict[int, list[str]] = {}
    for node_id, layer in node_layers.items():
        layers.setdefault(layer, []).append(node_id)

    if len(node_layers) < len(graph.nodes):
        remaining = [n.id for n in graph.nodes if n.id not in node_layers]
        current_max_layer = max(layers.keys()) if layers else 0
        for idx, node_id in enumerate(remaining):
            layer_num = current_max_layer + 1 + idx // 5
            node_layers[node_id] = layer_num
            layers.setdefault(layer_num, []).append(node_id)

    return entry_nodes, layers, outgoing, incoming


def linear_node_ids_for_layout(graph: DTGraph) -> list[str]:
    """
    Flat node id order implied by the same BFS layering as ``calculate_layout``.

    Used for checklist ordering so the linear list matches the graph canvas.
    """
    if not graph.nodes:
        return []
    _entry, layers, _out, _inc = _bfs_layers_grouped(graph)
    max_layer = max(layers.keys()) if layers else 0
    ordered: list[str] = []
    for layer_num in range(max_layer + 1):
        ordered.extend(layers.get(layer_num, []))
    return ordered


def ordered_nodes_for_checklist(graph: DTGraph) -> list[GraphNode]:
    """``GraphNode`` list in ``linear_node_ids_for_layout`` order for templates."""
    id_order = linear_node_ids_for_layout(graph)
    id_to_node = {n.id: n for n in graph.nodes}
    return [id_to_node[nid] for nid in id_order if nid in id_to_node]


def calculate_layout(
    graph: DTGraph,
    selected_node_id: str | None = None,
    node_validation_status: dict[str, dict[str, list[str]]] | None = None,
) -> GraphVisualization:
    """
    Calculate hierarchical layout for DTGraph using BFS.

    Algorithm:
    1. Find entry points (nodes with no incoming edges)
    2. Assign layers using BFS (entry = layer 0)
    3. Calculate positions within each layer
    4. Create VisualNodes and VisualEdges with styling

    Args:
        graph: Semantic DTGraph
        selected_node_id: Optional node to highlight
        node_validation_status: Optional dict mapping node_id -> validation issues

    Returns:
        GraphVisualization with positioned nodes and styled edges
    """
    if node_validation_status is None:
        node_validation_status = {}
    if not graph.nodes:
        logger.warning("Empty graph, returning empty visualization")
        return GraphVisualization(
            nodes=[],
            edges=[],
            width=2 * CANVAS_PADDING,
            height=2 * CANVAS_PADDING,
            selected_node_id=selected_node_id,
        )

    entry_nodes, layers, outgoing, _incoming = _bfs_layers_grouped(graph)

    logger.info(
        f"Calculating layout for {len(graph.nodes)} nodes, {len(graph.edges)} edges",
        extra={
            "entry_count": len(entry_nodes),
            "entry_nodes": entry_nodes,
            "selected": selected_node_id,
        },
    )

    max_layer = max(layers.keys()) if layers else 0
    max_nodes_in_layer = max(len(nodes) for nodes in layers.values()) if layers else 1

    # Calculate canvas size
    canvas_width = max_nodes_in_layer * (NODE_WIDTH + HORIZONTAL_SPACING) + 2 * CANVAS_PADDING
    canvas_height = (max_layer + 1) * (NODE_HEIGHT + VERTICAL_SPACING) + 2 * CANVAS_PADDING

    # Calculate positions for each node (iterate layers in numeric order)
    positions: dict[str, NodePosition] = {}
    for layer_num in range(max_layer + 1):
        node_ids = layers.get(layer_num, [])
        if not node_ids:
            continue
        y = CANVAS_PADDING + layer_num * (NODE_HEIGHT + VERTICAL_SPACING)

        # Center nodes horizontally within the layer
        total_width = len(node_ids) * NODE_WIDTH + (len(node_ids) - 1) * HORIZONTAL_SPACING
        start_x = (canvas_width - total_width) / 2

        for i, node_id in enumerate(node_ids):
            x = start_x + i * (NODE_WIDTH + HORIZONTAL_SPACING)
            positions[node_id] = NodePosition(x=x, y=y, layer=layer_num)

    # Create VisualNodes
    visual_nodes: list[VisualNode] = []
    for node in graph.nodes:
        if node.id not in positions:
            logger.warning(f"Node {node.id} has no position, skipping")
            continue

        full_label = visual_node_label_text(node)
        label = truncate_visual_label(full_label)
        tooltip = visual_node_tooltip(node, full_label)

        # Determine terminal nodes (no outgoing edges)
        is_terminal = len(outgoing.get(node.id, [])) == 0

        # Get validation status for this node
        validation = node_validation_status.get(node.id, {"errors": [], "warnings": []})
        has_errors = len(validation.get("errors", [])) > 0
        has_warnings = len(validation.get("warnings", [])) > 0

        visual_node = VisualNode(
            id=node.id,
            label=label,
            tooltip=tooltip,
            # type defaults to "question" - all nodes are questions
            position=positions[node.id],
            is_selected=(node.id == selected_node_id),
            is_entry=(node.id in entry_nodes),
            is_terminal=is_terminal,
            has_errors=has_errors,
            has_warnings=has_warnings,
        )
        visual_nodes.append(visual_node)

    # Create VisualEdges - group by (source, target) to prevent overlapping labels
    edge_groups: dict[tuple[str, str], list] = {}
    for edge in graph.edges:
        key = (edge.source, edge.target)
        if key not in edge_groups:
            edge_groups[key] = []
        edge_groups[key].append(edge)

    visual_edges: list[VisualEdge] = []
    for (source, target), edges in edge_groups.items():
        is_highlighted = selected_node_id is not None and (
            source == selected_node_id or target == selected_node_id
        )

        # Separate conditional and default edges
        conditional_edges = [e for e in edges if e.condition is not None]
        default_edges = [e for e in edges if e.condition is None]
        has_default = len(default_edges) > 0

        # Collect all conditions
        all_conditions = [e.condition for e in conditional_edges]

        # Determine primary condition for display
        # If only one condition, use it directly; otherwise conditions list will be used
        primary_condition = all_conditions[0] if len(all_conditions) == 1 else None
        if len(all_conditions) == 0 and has_default:
            primary_condition = None  # Default edge, no condition

        visual_edge = VisualEdge(
            source=source,
            target=target,
            condition=primary_condition,
            conditions=all_conditions,  # Store all conditions for tooltip
            is_default=has_default,
            is_highlighted=is_highlighted,
        )
        visual_edges.append(visual_edge)

    logger.info(
        f"Layout calculated: {len(visual_nodes)} nodes, {len(visual_edges)} edges, "
        f"{max_layer + 1} layers",
        extra={"canvas_size": f"{canvas_width}x{canvas_height}"},
    )

    return GraphVisualization(
        nodes=visual_nodes,
        edges=visual_edges,
        width=int(canvas_width),
        height=int(canvas_height),
        selected_node_id=selected_node_id,
    )


def _assign_layers_bfs(entry_nodes: list[str], outgoing: dict[str, list]) -> dict[str, int]:
    """
    Assign layers to nodes using BFS from entry points.

    Args:
        entry_nodes: List of entry point node IDs
        outgoing: Adjacency list mapping node_id -> list of outgoing edges

    Returns:
        Dictionary mapping node_id -> layer_number
    """
    layers: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque()

    # Initialize with entry nodes at layer 0
    for node_id in entry_nodes:
        layers[node_id] = 0
        queue.append((node_id, 0))

    # BFS traversal
    visited = set(entry_nodes)  # Track visited nodes to prevent infinite loops

    while queue:
        current_id, current_layer = queue.popleft()

        for edge in outgoing.get(current_id, []):
            target_id = edge.target

            # Only visit each node once (prevents infinite loops in cyclic graphs)
            if target_id not in visited:
                visited.add(target_id)
                new_layer = current_layer + 1
                layers[target_id] = new_layer
                queue.append((target_id, new_layer))

    return layers
