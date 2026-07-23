"""QNR Viewer Workflow - 3-node read-only pipeline with caching.

This workflow is fast, cacheable, and stateless (except for selection state).
"""

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.qnr.helpers.cache import cache_graph, get_cached_graph
from smeme.qnr.helpers.db_queries import (
    get_qnr_by_id,
    get_qnr_research_corpus_row,
    parse_graph_data,
)
from smeme.qnr.helpers.validation import (
    build_validation_issue_rows,
    format_validation_results,
    get_node_validation_status,
    validate_graph_for_editing,
)
from smeme.qnr.viewer.layout import calculate_layout, ordered_nodes_for_checklist
from smeme.qnr.viewer.models import QNRViewerState
from smeme.reasoning.assistant_tools_row_status import reasoning_tools_row_state_for_qnr

logger = logging.getLogger(__name__)


# =============================================================================
# Workflow Nodes
# =============================================================================


async def load_qnr_node(state: QNRViewerState, config: RunnableConfig) -> dict[str, Any]:
    """
    Node 1: Load DTGraph from cache or database.

    This is the only node that touches the database.
    Aggressive caching for fast repeated loads.
    """
    qnr_id = state["qnr_id"]
    user_id = state["user_id"]
    db: AsyncSession = config["configurable"]["db"]
    editor_view: str = config["configurable"].get("editor_view", "graph")

    logger.info("Loading QNR for viewer", extra={"qnr_id": str(qnr_id)})

    # Try cache first
    cached_graph = await get_cached_graph(qnr_id)
    if cached_graph:
        logger.info(
            "DTGraph loaded from cache",
            extra={"qnr_id": str(qnr_id), "node_count": len(cached_graph.nodes)},
        )

        # Still need to get status and title from DB (not cached)
        qnr = await get_qnr_by_id(db, qnr_id)
        if not qnr:
            return {"error": "QNR not found"}

        corp = await get_qnr_research_corpus_row(db, qnr_id)
        corp_bytes = len(corp.body_text.encode("utf-8")) if corp and corp.body_text.strip() else 0
        corpus_body = corp.body_text if corp else ""
        tools_row_state = await reasoning_tools_row_state_for_qnr(db, qnr)
        is_owner = qnr.author_id == user_id
        if editor_view == "tools" and not is_owner:
            editor_view = "graph"
        return {
            "graph": cached_graph,
            "qnr_title": qnr.title,
            "is_public": qnr.is_public,
            "was_ever_public": qnr.was_ever_public,
            "is_read_only": qnr.is_public or qnr.was_ever_public,
            "is_owner": is_owner,
            "version_number": qnr.version_number,
            "parent_qnr": qnr.parent if qnr.parent else None,
            "intended_audience": qnr.intended_audience,
            "use_case": qnr.use_case,
            "reasoning_status": qnr.reasoning_status,
            "cevi_legal": bool(qnr.cevi_legal),
            "research_corpus_present": corp_bytes > 0,
            "research_corpus_bytes": corp_bytes,
            "research_corpus_body": corpus_body,
            "tools_row_state": tools_row_state,
            "editor_view": editor_view,
        }

    # Cache miss - load from database
    qnr = await get_qnr_by_id(db, qnr_id)
    if not qnr:
        logger.error("QNR not found", extra={"qnr_id": str(qnr_id)})
        return {"error": "QNR not found"}

    # Parse and validate graph
    graph = parse_graph_data(qnr)

    logger.info(
        "DTGraph loaded from database",
        extra={
            "qnr_id": str(qnr_id),
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
        },
    )

    # Cache for future requests
    await cache_graph(qnr_id, graph)

    corp = await get_qnr_research_corpus_row(db, qnr_id)
    corp_bytes = len(corp.body_text.encode("utf-8")) if corp and corp.body_text.strip() else 0
    corpus_body = corp.body_text if corp else ""
    tools_row_state = await reasoning_tools_row_state_for_qnr(db, qnr)
    is_owner = qnr.author_id == user_id
    if editor_view == "tools" and not is_owner:
        editor_view = "graph"
    return {
        "graph": graph,
        "qnr_title": qnr.title,
        "is_public": qnr.is_public,
        "was_ever_public": qnr.was_ever_public,
        "is_read_only": qnr.is_public or qnr.was_ever_public,
        "is_owner": is_owner,
        "version_number": qnr.version_number,
        "parent_qnr": qnr.parent if qnr.parent else None,
        "intended_audience": qnr.intended_audience,
        "use_case": qnr.use_case,
        "reasoning_status": qnr.reasoning_status,
        "cevi_legal": bool(qnr.cevi_legal),
        "research_corpus_present": corp_bytes > 0,
        "research_corpus_bytes": corp_bytes,
        "research_corpus_body": corpus_body,
        "tools_row_state": tools_row_state,
        "editor_view": editor_view,
    }


async def generate_visualization_node(
    state: QNRViewerState, config: RunnableConfig
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
    qnr_id = state["qnr_id"]

    logger.info(
        "Generating visualization",
        extra={
            "qnr_id": str(qnr_id),
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
            "qnr_id": str(qnr_id),
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


async def render_viewer_node(state: QNRViewerState, config: RunnableConfig) -> dict[str, Any]:
    """
    Node 3: Render final HTML output using Jinja2 templates.

    Renders the complete editor interface with graph visualization and side panel.
    """
    visualization = state.get("visualization")
    graph = state.get("graph")
    warnings = state.get("warnings", [])
    selected_node_id = state.get("selected_node_id")
    qnr_id = state["qnr_id"]
    qnr_title = state.get("qnr_title", "Untitled QNR")
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
            "qnr_id": str(qnr_id),
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
        template_name = "qnr/editor.html"
    elif is_node_selection:
        template_name = "qnr/_side_panel_content.html"
        logger.info(f"Rendering side panel content for selected node: {selected_node_id}")
    else:
        template_name = "qnr/_side_panel_content.html"
        logger.info("Rendering side panel content (no node selection)")

    from smeme.core.theme import theme_template_context

    # Prepare template context
    # Note: TemplateResponse doesn't need "request" for partial templates that don't use it
    context = {
        "qnr_id": str(qnr_id),
        "qnr_title": qnr_title,
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
        "parent_qnr": state.get("parent_qnr"),
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
                "qnr_id": str(qnr_id),
                "html_length": len(rendered_html),
            },
        )

        return {"rendered_html": rendered_html, "editor_view": editor_view}

    except Exception as e:
        logger.error(
            f"Failed to render template: {e}",
            extra={"qnr_id": str(qnr_id)},
            exc_info=True,
        )
        return {"rendered_html": f"<p>Error rendering editor: {str(e)}</p>"}


# =============================================================================
# Workflow Construction
# =============================================================================


def build_viewer_workflow() -> StateGraph:
    """
    Build the 3-node QNR Viewer Workflow.

    Flow:
    1. load_qnr_node (cached) → graph, title, status
    2. generate_visualization_node → visualization, warnings
    3. render_viewer_node → rendered_html

    Returns:
        Compiled LangGraph workflow
    """
    workflow = StateGraph(QNRViewerState)

    # Add nodes
    workflow.add_node("load_qnr", load_qnr_node)
    workflow.add_node("generate_visualization", generate_visualization_node)
    workflow.add_node("render_viewer", render_viewer_node)

    # Define edges (linear flow)
    workflow.set_entry_point("load_qnr")
    workflow.add_edge("load_qnr", "generate_visualization")
    workflow.add_edge("generate_visualization", "render_viewer")
    workflow.set_finish_point("render_viewer")

    logger.info("QNR Viewer Workflow built (3 nodes)")

    return workflow.compile()
