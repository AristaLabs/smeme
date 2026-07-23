"""DecisionTree Editor Workflow - 5-node write operation pipeline.

This workflow handles all graph modification operations with validation and cache invalidation.
"""

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes

from smeme.decision_tree.editor.models import DecisionTreeEditorState
from smeme.decision_tree.editor.operations import apply_operation
from smeme.decision_tree.helpers.cache import invalidate_graph_cache
from smeme.decision_tree.helpers.db_queries import get_decision_tree_by_id, parse_graph_data
from smeme.decision_tree.helpers.validation import validate_graph_for_editing

logger = logging.getLogger(__name__)


# =============================================================================
# Workflow Nodes
# =============================================================================


async def load_decision_tree_node(
    state: DecisionTreeEditorState, config: RunnableConfig
) -> dict[str, Any]:
    """
    Node 1: Load DecisionTree graph from database (no cache).

    Editor workflow ALWAYS loads fresh data from the database to ensure
    concurrency safety and authoritative source.
    """
    decision_tree_id = state["decision_tree_id"]
    db: AsyncSession = config["configurable"]["db"]

    logger.info(
        "Loading DecisionTree for editor (no cache)",
        extra={"decision_tree_id": str(decision_tree_id)},
    )

    # Load from database (skip cache for editor)
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        logger.error("DecisionTree not found", extra={"decision_tree_id": str(decision_tree_id)})
        return {
            "success": False,
            "error_message": "DecisionTree not found",
        }

    # Parse graph data
    graph = parse_graph_data(decision_tree)

    logger.info(
        "DecisionTree loaded from database",
        extra={
            "decision_tree_id": str(decision_tree_id),
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
        },
    )

    return {
        "graph": graph,
        "decision_tree_title": decision_tree.title,
        "is_public": decision_tree.is_public,
        "success": True,
    }


async def apply_operation_node(
    state: DecisionTreeEditorState, config: RunnableConfig
) -> dict[str, Any]:
    """
    Node 2: Apply the requested operation to the graph.

    This is a pure function that modifies the graph in memory.
    No database writes happen here.
    """
    graph = state.get("graph")
    if not graph:
        logger.error("No graph in state")
        return {"success": False, "error_message": "No graph data"}

    operation = state["operation"]
    operation_data = state.get("operation_data", {})  # Get operation data from state
    decision_tree_id = state["decision_tree_id"]

    logger.info(
        f"Applying operation: {operation}",
        extra={
            "decision_tree_id": str(decision_tree_id),
            "operation": operation,
            "operation_data": operation_data,
        },
    )

    try:
        # Apply operation (returns modified graph)
        modified_graph = apply_operation(graph, operation, operation_data)

        # Ensure we have a DTGraph instance
        from smeme.decision_tree.models import DTGraph

        if not isinstance(modified_graph, DTGraph):
            modified_graph = DTGraph.model_validate(modified_graph)

        logger.info(
            "Operation applied successfully",
            extra={
                "decision_tree_id": str(decision_tree_id),
                "operation": operation,
            },
        )

        return {
            **state,
            "graph": modified_graph,
            "success": True,
        }

    except ValueError as e:
        logger.warning(
            f"Operation failed: {e}",
            extra={
                "decision_tree_id": str(decision_tree_id),
                "operation": operation,
                "error": str(e),
            },
        )
        return {
            "success": False,
            "error_message": str(e),
        }


async def validate_graph_node(
    state: DecisionTreeEditorState, config: RunnableConfig
) -> dict[str, Any]:
    """
    Node 3: Validate the modified graph using lenient validation.

    Uses Tier-2 validation (validate_graph_for_editing):
    - Records errors and warnings but does NOT block save
    - Validation results are passed through for UI display
    - Blocking is done at publish time, not edit time

    This allows authors to fix one error at a time without being locked out.
    """
    graph = state.get("graph")
    if not graph:
        return {"success": False, "error_message": "No graph data"}

    decision_tree_id = state["decision_tree_id"]

    logger.info("Validating modified graph", extra={"decision_tree_id": str(decision_tree_id)})

    # Run lenient validation
    validation_result = validate_graph_for_editing(graph)
    is_valid, errors, warnings = (
        validation_result["is_valid"],
        validation_result["errors"],
        validation_result["warnings"],
    )

    if not is_valid:
        # Log validation issues but DO NOT block save
        logger.info(
            "Graph has validation errors (will save anyway for incremental fixing)",
            extra={
                "decision_tree_id": str(decision_tree_id),
                "error_count": len(errors),
                "errors": errors,
            },
        )
    else:
        logger.info(
            "Graph validation passed",
            extra={
                "decision_tree_id": str(decision_tree_id),
                "warning_count": len(warnings),
            },
        )

    # Always return success=True to allow save
    # Pass validation results for UI display
    return {
        **state,
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "success": True,  # Always proceed to save
    }


async def save_to_db_node(state: DecisionTreeEditorState, config: RunnableConfig) -> dict[str, Any]:
    """
    Node 4: Save the modified graph to the database.

    This is the only node that writes to the database.
    """
    graph = state.get("graph")
    if not graph:
        return {"success": False, "error_message": "No graph data"}

    decision_tree_id = state["decision_tree_id"]
    db: AsyncSession = config["configurable"]["db"]

    logger.info(
        "Saving modified graph to database", extra={"decision_tree_id": str(decision_tree_id)}
    )

    try:
        # Load DecisionTree record
        decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
        if not decision_tree:
            return {"success": False, "error_message": "DecisionTree not found"}

        # Update graph_data
        # Ensure saving dict form
        from smeme.decision_tree.models import DTGraph

        graph_dict = graph.model_dump() if isinstance(graph, DTGraph) else graph
        decision_tree.graph_data = graph_dict

        # Mark JSONB field as modified (SQLAlchemy requirement)
        attributes.flag_modified(decision_tree, "graph_data")

        # Commit to database
        db.add(decision_tree)
        await db.commit()
        await db.refresh(decision_tree)

        logger.info(
            "Graph saved to database",
            extra={
                "decision_tree_id": str(decision_tree_id),
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
            },
        )

        return {"success": True}

    except Exception as e:
        logger.error(
            f"Failed to save graph: {e}",
            extra={"decision_tree_id": str(decision_tree_id)},
            exc_info=True,
        )
        await db.rollback()
        return {**state, "success": False, "error_message": f"Failed to save: {str(e)}"}


async def invalidate_cache_node(
    state: DecisionTreeEditorState, config: RunnableConfig
) -> dict[str, Any]:
    """
    Node 5: Invalidate the DecisionTree cache so viewer loads fresh data.

    This ensures the viewer workflow will see the updated graph.
    """
    decision_tree_id = state["decision_tree_id"]

    logger.info(
        "Invalidating DecisionTree cache", extra={"decision_tree_id": str(decision_tree_id)}
    )

    try:
        await invalidate_graph_cache(decision_tree_id)

        logger.info("Cache invalidated", extra={"decision_tree_id": str(decision_tree_id)})

        return {**state, "success": True}

    except Exception as e:
        logger.error(
            f"Failed to invalidate cache: {e}",
            extra={"decision_tree_id": str(decision_tree_id)},
            exc_info=True,
        )
        # Don't fail the whole operation if cache invalidation fails
        # The database is the source of truth
        return {**state, "success": True}


# =============================================================================
# Workflow Construction
# =============================================================================


def build_editor_workflow() -> StateGraph:
    """
    Build the 5-node DecisionTree Editor Workflow.

    Flow:
    1. load_decision_tree_node (no cache) → graph, title, status
    2. apply_operation_node → modified graph
    3. validate_graph_node → validation results (lenient)
    4. save_to_db_node → persist changes
    5. invalidate_cache_node → clear cache

    Early exit on any failure (validation, save errors).

    Returns:
        Compiled LangGraph workflow
    """
    workflow = StateGraph(DecisionTreeEditorState)

    # Add nodes
    workflow.add_node("load_decision_tree", load_decision_tree_node)
    workflow.add_node("apply_operation", apply_operation_node)
    workflow.add_node("validate_graph", validate_graph_node)
    workflow.add_node("save_to_db", save_to_db_node)
    workflow.add_node("invalidate_cache", invalidate_cache_node)

    # Define linear flow (with early exits handled by conditional edges)
    from langgraph.graph import START

    workflow.set_entry_point("load_decision_tree")
    workflow.add_edge(START, "load_decision_tree")

    # Conditional: Only proceed if load succeeded
    workflow.add_conditional_edges(
        "load_decision_tree",
        lambda state: "apply_operation" if state.get("success", False) else END,
        {
            "apply_operation": "apply_operation",
            END: END,
        },
    )

    # Conditional: Only proceed if operation succeeded
    workflow.add_conditional_edges(
        "apply_operation",
        lambda state: "validate_graph" if state.get("success", False) else END,
        {
            "validate_graph": "validate_graph",
            END: END,
        },
    )

    # Conditional: Only proceed if validation passed
    workflow.add_conditional_edges(
        "validate_graph",
        lambda state: "save_to_db" if state.get("success", False) else END,
        {
            "save_to_db": "save_to_db",
            END: END,
        },
    )

    # Conditional: Only proceed if save succeeded
    workflow.add_conditional_edges(
        "save_to_db",
        lambda state: "invalidate_cache" if state.get("success", False) else END,
        {
            "invalidate_cache": "invalidate_cache",
            END: END,
        },
    )

    # Final node exits
    workflow.add_edge("invalidate_cache", END)

    logger.info("DecisionTree Editor Workflow built (5 nodes with conditional flow)")

    return workflow.compile()
