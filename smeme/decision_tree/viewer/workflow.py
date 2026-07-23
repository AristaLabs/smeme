"""DecisionTree Viewer Workflow - 3-node read-only pipeline with caching.

This workflow is fast, cacheable, and stateless (except for selection state).
"""

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.decision_tree.helpers.cache import cache_graph, get_cached_graph
from smeme.decision_tree.helpers.db_queries import (
    get_decision_tree_by_id,
    get_decision_tree_research_corpus_row,
    parse_graph_data,
)
from smeme.decision_tree.helpers.validation import (
    build_validation_issue_rows,
    format_validation_results,
    get_node_validation_status,
    validate_graph_for_editing,
)
from smeme.decision_tree.viewer.layout import calculate_layout, ordered_nodes_for_checklist
from smeme.decision_tree.viewer.models import DecisionTreeViewerState
from smeme.reasoning.assistant_tools_row_status import reasoning_tools_row_state_for_decision_tree

logger = logging.getLogger(__name__)


# =============================================================================
# Workflow Nodes
# =============================================================================


async def load_decision_tree_node(
    state: DecisionTreeViewerState, config: RunnableConfig
) -> dict[str, Any]:
    """
    Node 1: Load DecisionTree graph from cache or database.

    This is the only node that touches the database.
    Aggressive caching for fast repeated loads.
    """
    decision_tree_id = state["decision_tree_id"]
    user_id = state["user_id"]
    db: AsyncSession = config["configurable"]["db"]
    editor_view: str = config["configurable"].get("editor_view", "graph")

    logger.info(
        "Loading DecisionTree for viewer", extra={"decision_tree_id": str(decision_tree_id)}
    )

    # Try cache first
    cached_graph = await get_cached_graph(decision_tree_id)
    if cached_graph:
        logger.info(
            "DecisionTree graph loaded from cache",
            extra={
                "decision_tree_id": str(decision_tree_id),
                "node_count": len(cached_graph.nodes),
            },
        )

        # Still need to get status and title from DB (not cached)
        decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
        if not decision_tree:
            return {"error": "DecisionTree not found"}

        corp = await get_decision_tree_research_corpus_row(db, decision_tree_id)
        corp_bytes = len(corp.body_text.encode("utf-8")) if corp and corp.body_text.strip() else 0
        corpus_body = corp.body_text if corp else ""
        tools_row_state = await reasoning_tools_row_state_for_decision_tree(db, decision_tree)
        is_owner = decision_tree.author_id == user_id
        if editor_view == "tools" and not is_owner:
            editor_view = "graph"
        return {
            "graph": cached_graph,
            "decision_tree_title": decision_tree.title,
            "is_public": decision_tree.is_public,
            "was_ever_public": decision_tree.was_ever_public,
            "is_read_only": decision_tree.is_public or decision_tree.was_ever_public,
            "is_owner": is_owner,
            "version_number": decision_tree.version_number,
            "parent_decision_tree": decision_tree.parent if decision_tree.parent else None,
            "intended_audience": decision_tree.intended_audience,
            "use_case": decision_tree.use_case,
            "reasoning_status": decision_tree.reasoning_status,
            "cevi_legal": bool(decision_tree.cevi_legal),
            "research_corpus_present": corp_bytes > 0,
            "research_corpus_bytes": corp_bytes,
            "research_corpus_body": corpus_body,
            "tools_row_state": tools_row_state,
            "editor_view": editor_view,
        }

    # Cache miss - load from database
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        logger.error("DecisionTree not found", extra={"decision_tree_id": str(decision_tree_id)})
        return {"error": "DecisionTree not found"}

    # Parse and validate graph
    graph = parse_graph_data(decision_tree)

    logger.info(
        "DecisionTree graph loaded from database",
        extra={
            "decision_tree_id": str(decision_tree_id),
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
        },
    )

    # Cache for future requests
    await cache_graph(decision_tree_id, graph)

    corp = await get_decision_tree_research_corpus_row(db, decision_tree_id)
    corp_bytes = len(corp.body_text.encode("utf-8")) if corp and corp.body_text.strip() else 0
    corpus_body = corp.body_text if corp else ""
    tools_row_state = await reasoning_tools_row_state_for_decision_tree(db, decision_tree)
    is_owner = decision_tree.author_id == user_id
    if editor_view == "tools" and not is_owner:
        editor_view = "graph"
    return {
        "graph": graph,
        "decision_tree_title": decision_tree.title,
        "is_public": decision_tree.is_public,
        "was_ever_public": decision_tree.was_ever_public,
        "is_read_only": decision_tree.is_public or decision_tree.was_ever_public,
        "is_owner": is_owner,
        "version_number": decision_tree.version_number,
        "parent_decision_tree": decision_tree.parent if decision_tree.parent else None,
        "intended_audience": decision_tree.intended_audience,
        "use_case": decision_tree.use_case,
        "reasoning_status": decision_tree.reasoning_status,
        "cevi_legal": bool(decision_tree.cevi_legal),
        "research_corpus_present": corp_bytes > 0,
        "research_corpus_bytes": corp_bytes,
        "research_corpus_body": corpus_body,
        "tools_row_state": tools_row_state,
        "editor_view": editor_view,
    }


async def generate_visualization_node(
    state: DecisionTreeViewerState, config: RunnableConfig
) -> dict[str, Any]:
    """
    Node 2: Generate visualization with layout and styling.

    Pure transformation - no I/O, fast.
    """
    graph = state.get("graph")
    if not graph:
        logger.error("No graph in state")
        return {"error": "No graph data"}

    selected_node_id = state.get("selected_node_id")
    decision_tree_id = state["decision_tree_id"]

    logger.info(
        "Generating visualization",
        extra={
            "decision_tree_id": str(decision_tree_id),
            "selected_node": selected_node_id,
            "node_count": len(graph.nodes),
        },
    )

    # If draft status, run lenient validation for warnings
    warnings: list[str] = []
    node_validation_status: dict[str, dict[str, list[str]]] = {}
    is_public = state.get("is_public", False)

    # Always initialize validation_data with proper structure
    validation_data: dict[str, Any] = {
        "errors": {},
        "warnings": {},
        "error_count": 0,
        "warning_count": 0,
    }
    validation_issue_rows: list[dict[str, Any]] = []

    if not is_public:
        validation_result = validate_graph_for_editing(graph)
        is_valid, errors, validation_warnings = (
            validation_result["is_valid"],
            validation_result["errors"],
            validation_result["warnings"],
        )
        # Keep original warnings for backward compat
        warnings = validation_warnings
        # Get node-specific validation status for visual indicators
        node_validation_status = get_node_validation_status(graph)
        # Format validation results for improved template rendering
        validation_data = format_validation_results(
            errors if not is_valid else [], validation_warnings
        )
        validation_issue_rows = build_validation_issue_rows(
            list(errors) if not is_valid else [],
            list(validation_warnings),
            graph=graph,
            suggestions=validation_result.get("suggestions"),
        )

    # Calculate layout (BFS-based hierarchical positioning)
    visualization = calculate_layout(graph, selected_node_id, node_validation_status)

    logger.info(
        "Visualization generated",
        extra={
            "decision_tree_id": str(decision_tree_id),
            "canvas_size": f"{visualization.width}x{visualization.height}",
            "warnings": len(warnings),
        },
    )

    return {
        "visualization": visualization,
        "warnings": warnings if warnings else [],  # Keep for backward compat
        "validation_data": validation_data,  # New structured format
        "validation_issue_rows": validation_issue_rows,
        "node_validation_status": node_validation_status,  # Node-specific validation
    }


async def render_viewer_node(
    state: DecisionTreeViewerState, config: RunnableConfig
) -> dict[str, Any]:
    """
    Node 3: Render final HTML output using Jinja2 templates.

    Renders the complete editor interface with graph visualization and side panel.
    """
    visualization = state.get("visualization")
    graph = state.get("graph")
    warnings = state.get("warnings", [])
    selected_node_id = state.get("selected_node_id")
    decision_tree_id = state["decision_tree_id"]
    decision_tree_title = state.get("decision_tree_title", "Untitled decision tree")
    is_public = state.get("is_public", False)
    was_ever_public = state.get("was_ever_public", False)
    is_read_only = state.get("is_read_only", False)
    is_owner = state.get("is_owner", False)

    if not visualization or not graph:
        logger.error("Missing visualization or graph data")
        return {"rendered_html": "<p>Error rendering visualization</p>"}

    logger.info(
        "Rendering viewer output with Jinja2 templates",
        extra={
            "decision_tree_id": str(decision_tree_id),
            "selected_node": selected_node_id,
            "warnings": len(warnings),
        },
    )

    # Get templates from config
    from starlette.templating import Jinja2Templates

    templates: Jinja2Templates = config["configurable"]["templates"]

    # Determine whether to render full page (with base layout) or just inner content
    # The calling route can set configurable["full_page"] = True to get a complete
    # document on the initial GET request. Subsequent HTMX requests should keep
    # this flag False (default) so that only the inner editor content is swapped.
    full_page: bool = config["configurable"].get("full_page", False)
    editor_view = state.get("editor_view") or config["configurable"].get("editor_view", "graph")

    # Check if we're rendering for a node selection (HTMX swap of side panel only)
    # When a node is selected, we only want to update the side panel content, not the entire editor
    is_node_selection: bool = selected_node_id is not None and not full_page

    # Pick template accordingly
    if full_page:
        template_name = "decision_tree/editor.html"
    elif is_node_selection:
        template_name = "decision_tree/_side_panel_content.html"
        logger.info(f"Rendering side panel content for selected node: {selected_node_id}")
    else:
        template_name = "decision_tree/_side_panel_content.html"
        logger.info("Rendering side panel content (no node selection)")

    from smeme.core.theme import theme_template_context

    # Prepare template context
    # Note: TemplateResponse doesn't need "request" for partial templates that don't use it
    context = {
        "decision_tree_id": str(decision_tree_id),
        "decision_tree_title": decision_tree_title,
        "is_public": is_public,
        "was_ever_public": was_ever_public,
        "is_read_only": is_read_only,
        "is_owner": is_owner,
        "visualization": visualization,
        "graph": graph,
        "checklist_ordered_nodes": ordered_nodes_for_checklist(graph),
        "warnings": warnings,  # Legacy flat list
        "validation_data": state.get("validation_data", {}),  # New structured format
        "validation_issue_rows": state.get("validation_issue_rows", []),
        "node_validation_status": state.get("node_validation_status", {}),  # Node-specific issues
        "selected_node_id": selected_node_id,
        "version_number": state.get("version_number", 1),
        "parent_decision_tree": state.get("parent_decision_tree"),
        "intended_audience": state.get("intended_audience"),
        "use_case": state.get("use_case"),
        "reasoning_status": state.get("reasoning_status"),
        "cevi_legal": state.get("cevi_legal", False),
        "research_corpus_present": state.get("research_corpus_present", False),
        "research_corpus_bytes": state.get("research_corpus_bytes", 0),
        "research_corpus_body": state.get("research_corpus_body", ""),
        "editor_view": editor_view,
        "editor_sidebar_width": config["configurable"].get("editor_sidebar_width", 384),
        "tools_row_state": state.get("tools_row_state", "not_built"),
    }
    # Full page needs user + active_page for base layout nav (match dashboard, gallery, etc.)
    if full_page:
        context["user"] = config["configurable"].get("user")
        context["request"] = config["configurable"].get("request")
        context["active_page"] = "dashboard"
        context["show_deploy_success"] = config["configurable"].get("show_deploy_success", False)
        context.update(theme_template_context(context.get("request")))

    # Render template directly using env (not TemplateResponse which expects Request)
    try:
        template = templates.env.get_template(template_name)
        rendered_html = template.render(context)

        logger.info(
            "Viewer output rendered via Jinja2",
            extra={
                "decision_tree_id": str(decision_tree_id),
                "html_length": len(rendered_html),
            },
        )

        return {"rendered_html": rendered_html, "editor_view": editor_view}

    except Exception as e:
        logger.error(
            f"Failed to render template: {e}",
            extra={"decision_tree_id": str(decision_tree_id)},
            exc_info=True,
        )
        return {"rendered_html": f"<p>Error rendering editor: {str(e)}</p>"}


# =============================================================================
# Workflow Construction
# =============================================================================


def build_viewer_workflow() -> StateGraph:
    """
    Build the 3-node DecisionTree Viewer Workflow.

    Flow:
    1. load_decision_tree_node (cached) → graph, title, status
    2. generate_visualization_node → visualization, warnings
    3. render_viewer_node → rendered_html

    Returns:
        Compiled LangGraph workflow
    """
    workflow = StateGraph(DecisionTreeViewerState)

    # Add nodes
    workflow.add_node("load_decision_tree", load_decision_tree_node)
    workflow.add_node("generate_visualization", generate_visualization_node)
    workflow.add_node("render_viewer", render_viewer_node)

    # Define edges (linear flow)
    workflow.set_entry_point("load_decision_tree")
    workflow.add_edge("load_decision_tree", "generate_visualization")
    workflow.add_edge("generate_visualization", "render_viewer")
    workflow.set_finish_point("render_viewer")

    logger.info("DecisionTree Viewer Workflow built (3 nodes)")

    return workflow.compile()
