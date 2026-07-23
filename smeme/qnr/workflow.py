"""LangGraph workflow for QNR questionnaire navigation.

Supports both question nodes and conclusion nodes.
Conclusion nodes are terminal endpoints that represent the outcome of a decision path.
"""

import logging
import time
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from jinja2 import Environment, FileSystemLoader
from langgraph.graph import END, StateGraph
from langgraph.types import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.callout_html import render_callout_html
from smeme.qnr.helpers.cache import cache_graph, get_cached_graph
from smeme.qnr.helpers.db_queries import (
    get_qnr_by_id,
    parse_graph_data,
    save_session,
)
from smeme.qnr.helpers.validation import (
    get_first_question_id,
    get_incoming_edges,
    get_node_by_id,
    get_outgoing_edges,
    get_reachable_questions,
    has_conditional_edges,
    validate_graph,
)
from smeme.qnr.models import DTGraph
from smeme.qnr.workflow_state import QNRSessionState, SessionStateUpdate

# Per-workflow structured logger
logger = logging.getLogger("smeme.qnr.workflow")

# Initialize Jinja2 template environment
jinja_env = Environment(loader=FileSystemLoader("smeme/templates"))


# ============================================================================
# Workflow Nodes (inline functions returning partial state updates)
# ============================================================================


async def load_qnr_node(state: QNRSessionState, config: RunnableConfig) -> SessionStateUpdate:
    """
    Load DTGraph from database or cache.

    Returns:
        Partial state with 'graph' field
    """
    start_time = time.time()

    # Extract runtime context
    db: AsyncSession = config["configurable"]["db"]
    user_id: int = config["configurable"].get("user_id")

    qnr_id = UUID(state["qnr_id"])
    session_id = str(state["session"].id)

    logger.info(
        "Loading QNR",
        extra={
            "qnr_id": str(qnr_id),
            "session_id": session_id,
            "user_id": user_id,
            "node": "load_qnr",
        },
    )

    # Try cache first
    graph = await get_cached_graph(qnr_id)
    if graph:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "QNR loaded from cache",
            extra={
                "qnr_id": str(qnr_id),
                "session_id": session_id,
                "cache_hit": True,
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "load_qnr",
            },
        )
        return {"graph": graph}

    # Load from database
    qnr = await get_qnr_by_id(db, qnr_id)
    if not qnr:
        logger.warning(
            "QNR not found",
            extra={
                "qnr_id": str(qnr_id),
                "session_id": session_id,
                "user_id": user_id,
                "node": "load_qnr",
            },
        )
        return {
            "error_message": f"QNR {qnr_id} not found",
            "rendered_output": "<p>Error: QNR not found</p>",
        }

    try:
        graph = parse_graph_data(qnr)

        # Validate graph
        is_valid, error = validate_graph(graph)
        if not is_valid:
            logger.error(
                "Invalid graph structure",
                extra={
                    "qnr_id": str(qnr_id),
                    "session_id": session_id,
                    "validation_error": error,
                    "node": "load_qnr",
                },
            )
            return {
                "error_message": f"Invalid graph: {error}",
                "rendered_output": f"<p>Error: {error}</p>",
            }

        # Cache for future requests
        await cache_graph(qnr_id, graph)

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "QNR loaded from database and cached",
            extra={
                "qnr_id": str(qnr_id),
                "session_id": session_id,
                "cache_hit": False,
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "load_qnr",
            },
        )

        return {"graph": graph}

    except Exception as e:
        logger.error(
            "Failed to parse graph",
            extra={
                "qnr_id": str(qnr_id),
                "session_id": session_id,
                "error": str(e),
                "node": "load_qnr",
            },
            exc_info=True,
        )
        return {
            "error_message": str(e),
            "rendered_output": f"<p>Error loading QNR: {e}</p>",
        }


async def determine_next_question_node(
    state: QNRSessionState, config: RunnableConfig
) -> SessionStateUpdate:
    """
    Determine which node (question or conclusion) to show next.

    Handles:
    - First load (no current_node_id)
    - "next" navigation
    - "previous" navigation
    - "skip" navigation
    - "finish" navigation
    - "review" navigation
    - Conditional edges
    - Required question validation
    - Conclusion node detection

    Returns:
        Partial state with:
        - 'next_question_id' (node ID to show)
        - 'is_conclusion' (True if next node is a conclusion)
        - 'is_complete' (True if questionnaire finished)
        - 'navigation_warning' (error message if navigation blocked)
    """
    start_time = time.time()

    # Extract runtime context
    user_id: int = config["configurable"].get("user_id")

    graph = cast(DTGraph, state.get("graph"))
    session = state["session"]
    session_id = str(session.id)
    current_id = session.current_node_id
    responses = session.user_responses or {}
    direction = state.get(
        "navigation_intent", "next"
    )  # if navigation_intent is not provided, default to "next"

    # Get conclusion node IDs for quick lookup
    conclusion_ids = graph.conclusion_ids

    logger.info(
        "Determining next node",
        extra={
            "session_id": session_id,
            "user_id": user_id,
            "current_node": current_id,
            "direction": direction,
            "answered_count": len(responses),
            "conclusion_count": len(conclusion_ids),
            "node": "determine_next_question",
        },
    )

    # --- Handle "finish" intent ---
    # Make sure all REACHABLE required questions are answered
    if direction == "finish":
        # Get questions that are reachable given current response path
        reachable = get_reachable_questions(graph, responses)

        # Only check required questions (not conclusions) that are actually reachable
        required_questions = [
            n.id
            for n in graph.nodes
            if n.type == "question"
            and n.question_data
            and n.question_data.required
            and n.id in reachable
        ]
        unanswered = [q for q in required_questions if q not in responses]

        if unanswered:
            count = len(unanswered)
            warning = f"Please answer {count} remaining required question{'s' if count > 1 else ''} before finishing."
            logger.info(
                "Finish blocked - unanswered required questions",
                extra={
                    "session_id": session_id,
                    "user_id": user_id,
                    "reachable_count": len(reachable),
                    "required_count": len(required_questions),
                    "unanswered_count": count,
                    "unanswered_questions": unanswered,
                    "node": "determine_next_question",
                },
            )
            return {
                "navigation_warning": warning,
                "next_question_id": current_id,  # Stay on current
            }

        # All reachable required questions answered - mark complete
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Finish approved - questionnaire complete",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "total_answers": len(responses),
                "required_answered": len(required_questions),
                "reachable_count": len(reachable),
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "determine_next_question",
            },
        )
        completed_at_iso = datetime.now(UTC).isoformat()
        return {
            "is_complete": True,
            "completed_at": completed_at_iso,
            "next_question_id": None,
        }

    # --- Handle "review" intent (reopen completed QNR) ---
    if direction == "review":
        if responses:
            next_id = list(responses.keys())[-1]  # Last answered
        else:
            next_id = get_first_question_id(graph)

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Review mode - reopening questionnaire",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "starting_question": next_id,
                "total_answers": len(responses),
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "determine_next_question",
            },
        )
        return {
            "is_complete": False,
            "next_question_id": next_id,
            "is_conclusion": next_id in conclusion_ids if next_id else False,
        }

    # --- First load (no current node) ---
    if not current_id:
        first_id = get_first_question_id(graph)
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "First load - starting questionnaire",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "first_question": first_id,
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "determine_next_question",
            },
        )
        return {
            "next_question_id": first_id,
            "is_conclusion": first_id in conclusion_ids if first_id else False,
        }

    # --- Check if current node is a conclusion (shouldn't navigate away) ---
    if current_id in conclusion_ids and direction in ("next", "skip"):
        # Already at a conclusion - this is the end
        logger.info(
            "At conclusion node - no forward navigation",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "conclusion_id": current_id,
                "node": "determine_next_question",
            },
        )
        return {
            "next_question_id": current_id,
            "is_conclusion": True,
        }

    # --- Handle "previous" navigation ---
    if direction == "previous":
        incoming = get_incoming_edges(graph, current_id)
        if not incoming:
            logger.info(
                "Already at first question",
                extra={
                    "session_id": session_id,
                    "user_id": user_id,
                    "current_question": current_id,
                    "node": "determine_next_question",
                },
            )
            return {
                "navigation_warning": "Already at the first question",
                "next_question_id": current_id,
                "is_conclusion": current_id in conclusion_ids,
            }

        source_ids = [e.source for e in incoming]
        answered_sources = [s for s in source_ids if s in responses]

        # if len(answered_sources) ge 1,then take the most recent one
        if answered_sources:
            prev_id = answered_sources[-1]
        # if none of the source nodes have been answered, then take the first listed source node. Would this be the closest or furthest?
        else:
            prev_id = source_ids[0]

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Navigating to previous node",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "from_node": current_id,
                "to_node": prev_id,
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "determine_next_question",
            },
        )
        return {
            "next_question_id": prev_id,
            "is_conclusion": prev_id in conclusion_ids,
        }

    # --- Handle "next" and "skip" navigation ---
    is_skip = direction == "skip"

    # Check if current question is answered (unless skipping)
    # Only applies to question nodes, not conclusions
    if not is_skip and current_id not in responses and current_id not in conclusion_ids:
        current_node = get_node_by_id(graph, current_id)
        if current_node and current_node.question_data and current_node.question_data.required:
            logger.info(
                "Cannot advance - required question unanswered",
                extra={
                    "session_id": session_id,
                    "user_id": user_id,
                    "question_id": current_id,
                    "node": "determine_next_question",
                },
            )
            return {
                "navigation_warning": "Please answer this question before continuing",
                "next_question_id": current_id,
                "is_conclusion": False,
            }

    # Get outgoing edges
    edges_out = get_outgoing_edges(graph, current_id)

    if not edges_out:
        # No outgoing edges = terminal node
        # If it's a conclusion, that's expected
        # If it's a question (legacy), stay here for explicit finish
        logger.info(
            "At terminal node - no outgoing edges",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "node_id": current_id,
                "is_conclusion": current_id in conclusion_ids,
                "node": "determine_next_question",
            },
        )
        return {
            "next_question_id": current_id,
            "is_conclusion": current_id in conclusion_ids,
        }

    # Check if current question has conditionals
    has_conditionals = has_conditional_edges(graph, current_id)

    # Block "skip" on conditional questions
    if is_skip and has_conditionals:
        logger.info(
            "Skip blocked - question has conditional edges",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "question_id": current_id,
                "node": "determine_next_question",
            },
        )
        return {
            "navigation_warning": "Cannot skip: next question depends on your answer",
            "next_question_id": current_id,
            "is_conclusion": False,
        }

    # Determine next edge
    next_id: str | None = None

    if has_conditionals and current_id in responses:
        # Match answer to conditional edge (radio-only: exact label, case-insensitive)
        user_answer = responses[current_id]
        ua = user_answer.strip().lower()
        matched_edge = next(
            (e for e in edges_out if e.condition and e.condition.strip().lower() == ua),
            None,
        )

        if matched_edge:
            next_id = matched_edge.target
            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                "Conditional edge matched",
                extra={
                    "session_id": session_id,
                    "user_id": user_id,
                    "from_node": current_id,
                    "to_node": next_id,
                    "answer": user_answer[:50],  # Truncate long answers
                    "condition": matched_edge.condition,
                    "is_conclusion": next_id in conclusion_ids,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "node": "determine_next_question",
                },
            )
            return {
                "next_question_id": next_id,
                "is_conclusion": next_id in conclusion_ids,
            }

        # No match - try default edge (no condition)
        default_edge = next((e for e in edges_out if not e.condition), None)
        if default_edge:
            next_id = default_edge.target
            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                "Using default edge - no condition matched",
                extra={
                    "session_id": session_id,
                    "user_id": user_id,
                    "from_node": current_id,
                    "to_node": next_id,
                    "answer": user_answer[:50],
                    "is_conclusion": next_id in conclusion_ids,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "node": "determine_next_question",
                },
            )
            return {
                "next_question_id": next_id,
                "is_conclusion": next_id in conclusion_ids,
            }

        logger.warning(
            "No matching edge for answer",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "question_id": current_id,
                "answer": user_answer[:50],
                "available_conditions": [e.condition for e in edges_out if e.condition],
                "node": "determine_next_question",
            },
        )
        return {
            "navigation_warning": "Unexpected answer - cannot determine next question",
            "next_question_id": current_id,
            "is_conclusion": False,
        }

    # Use first available edge (default or skip)
    next_id = edges_out[0].target

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "Next node determined",
        extra={
            "session_id": session_id,
            "user_id": user_id,
            "from_node": current_id,
            "to_node": next_id,
            "direction": direction,
            "is_conclusion": next_id in conclusion_ids,
            "elapsed_ms": round(elapsed_ms, 2),
            "node": "determine_next_question",
        },
    )
    return {
        "next_question_id": next_id,
        "is_conclusion": next_id in conclusion_ids,
    }


async def render_question_node(
    state: QNRSessionState, config: RunnableConfig
) -> SessionStateUpdate:
    """
    Render the current node as HTML (question or conclusion).

    Updates session.current_node_id and persists to database.
    For conclusions, also sets session.conclusion_reached.

    Returns:
        Partial state with 'rendered_output'
    """
    start_time = time.time()

    # Extract runtime context
    db: AsyncSession = config["configurable"]["db"]
    user_id: int = config["configurable"].get("user_id")

    graph = cast(DTGraph, state.get("graph"))
    session = state["session"]
    session_id = str(session.id)
    node_id = state.get("next_question_id")
    is_conclusion = state.get("is_conclusion", False)

    if not node_id:
        logger.error(
            "No node_id to render",
            extra={"session_id": session_id, "user_id": user_id, "node": "render_question"},
        )
        return {"rendered_output": "<p>Error: No question to display</p>"}

    # Get node (question or conclusion)
    node = get_node_by_id(graph, node_id)
    if not node or not node.data:
        logger.error(
            "Invalid node",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "node_id": node_id,
                "node": "render_question",
            },
        )
        return {"rendered_output": f"<p>Error: Node {node_id} not found</p>"}

    # Update session.current_node_id
    session.current_node_id = node_id

    # Handle conclusion nodes differently
    if is_conclusion or node.type == "conclusion":
        return await _render_conclusion_node(
            graph, node, session, db, user_id, start_time, state.get("navigation_warning")
        )

    # Get question data
    qdata = node.question_data
    if not qdata:
        logger.error(
            "Question node missing question data",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "node_id": node_id,
                "node": "render_question",
            },
        )
        return {"rendered_output": f"<p>Error: Invalid question node {node_id}</p>"}

    # Determine navigation context
    responses = session.user_responses or {}
    incoming = get_incoming_edges(graph, node_id)
    outgoing = get_outgoing_edges(graph, node_id)

    can_go_previous = len(incoming) > 0
    is_last_question = len(outgoing) == 0
    can_skip = not has_conditional_edges(graph, node_id) and not qdata.required

    # Get previous answer if exists
    previous_answer = responses.get(node_id, "")

    # Render question template
    template = jinja_env.get_template("qnr/_question.html")
    html = template.render(
        q=qdata,
        question_node_id=node_id,
        session_id=str(session.id),
        previous_answer=previous_answer,
        can_go_previous=can_go_previous,
        is_last_question=is_last_question,
        can_skip=can_skip,
        navigation_warning=state.get("navigation_warning"),
    )

    # Persist session changes
    await save_session(db, session)

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "Question rendered",
        extra={
            "session_id": session_id,
            "user_id": user_id,
            "question_id": node_id,
            "question_type": qdata.type,
            "is_required": qdata.required,
            "can_skip": can_skip,
            "is_last": is_last_question,
            "html_length": len(html),
            "elapsed_ms": round(elapsed_ms, 2),
            "node": "render_question",
        },
    )
    return {"rendered_output": html, "current_node_id": node_id}


async def _render_conclusion_node(
    graph: DTGraph,
    node,
    session,
    db: AsyncSession,
    user_id: int,
    start_time: float,
    navigation_warning: str | None,
) -> SessionStateUpdate:
    """
    Render a conclusion node as HTML.

    Conclusions are terminal endpoints representing the outcome of a decision path.
    Marks the session as complete and stores which conclusion was reached.
    """
    session_id = str(session.id)
    conclusion_id = node.id
    cdata = node.conclusion_data

    if not cdata:
        logger.error(
            "Conclusion node missing conclusion data",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "conclusion_id": conclusion_id,
                "node": "render_conclusion",
            },
        )
        return {"rendered_output": f"<p>Error: Invalid conclusion node {conclusion_id}</p>"}

    # Update session with conclusion
    session.current_node_id = conclusion_id
    session.conclusion_reached = conclusion_id
    session.completed_at = datetime.now(UTC)

    # Determine navigation context (can go back but not forward)
    incoming = get_incoming_edges(graph, conclusion_id)
    can_go_previous = len(incoming) > 0

    # Render conclusion template
    template = jinja_env.get_template("qnr/_conclusion.html")
    html = template.render(
        conclusion=cdata,
        conclusion_id=conclusion_id,
        session_id=str(session.id),
        can_go_previous=can_go_previous,
        navigation_warning=navigation_warning,
    )

    # Persist session changes
    await save_session(db, session)

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "Conclusion rendered",
        extra={
            "session_id": session_id,
            "user_id": user_id,
            "conclusion_id": conclusion_id,
            "conclusion_title": cdata.title,
            "severity": cdata.severity,
            "html_length": len(html),
            "elapsed_ms": round(elapsed_ms, 2),
            "node": "render_conclusion",
        },
    )
    return {
        "rendered_output": html,
        "current_node_id": conclusion_id,
        "is_complete": True,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }


async def render_completion_node(
    state: QNRSessionState, config: RunnableConfig
) -> SessionStateUpdate:
    """
    Render completion screen.

    Returns:
        Partial state with 'rendered_output'
    """
    start_time = time.time()

    # Extract runtime context
    db: AsyncSession = config["configurable"]["db"]
    user_id: int = config["configurable"].get("user_id")

    session = state["session"]
    session_id = str(session.id)
    responses = session.user_responses or {}

    # Persist completion timestamp
    if state.get("completed_at"):
        from datetime import datetime

        session.completed_at = datetime.fromisoformat(state["completed_at"])
        await save_session(db, session)

    logger.info(
        "Rendering completion screen",
        extra={
            "session_id": session_id,
            "user_id": user_id,
            "total_answers": len(responses),
            "completed_at": state.get("completed_at"),
            "node": "render_completion",
        },
    )

    completion_html = f"""
    <div class="max-w-2xl mx-auto p-6">
        {
        render_callout_html(
            title="Assessment Complete!",
            body=(
                '<p class="mb-4">Thank you for completing the assessment. Your responses have been saved.</p>'
                f'<div class="mt-6 flex items-center gap-3">'
                f'<button type="button" hx-post="/qnr/navigate" '
                f'hx-vals=\'{{"session_id": "{session_id}", "direction": "review"}}\' '
                f'hx-target="#main-content" hx-swap="innerHTML" '
                f'class="bg-ui-surface-hover hover:bg-ui-line text-ui-ink-secondary font-medium py-2 px-4 rounded-lg transition">'
                f"← Review Answers</button>"
                f'<div class="mt-4"><a href="/qnr/dashboard" class="text-brand-600 hover:underline text-sm">'
                f"Return to Dashboard</a></div>"
            ),
            type="success",
        )
    }
    </div>
    """

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "Completion screen rendered",
        extra={
            "session_id": session_id,
            "user_id": user_id,
            "elapsed_ms": round(elapsed_ms, 2),
            "node": "render_completion",
        },
    )

    return {"rendered_output": completion_html}


# ============================================================================
# Conditional routing
# ============================================================================


def route_after_determination(state: QNRSessionState) -> str:
    """Route to render_question or render_completion based on state.

    - is_complete=True AND no next_question_id -> render_completion (legacy finish flow)
    - is_conclusion=True -> render_question (which handles conclusion rendering)
    - Otherwise -> render_question
    """
    if state.get("is_complete", False) and not state.get("next_question_id"):
        return "render_completion"
    # Both questions and conclusions are rendered by render_question
    # The function handles both types internally
    return "render_question"


# ============================================================================
# Build and compile workflow
# ============================================================================


def build_qnr_workflow() -> StateGraph:
    """
    Build the QNR workflow graph.

    Workflow:
        load_qnr -> determine_next_question -> [render_question | render_completion] -> END

    Note: Database session is passed via config at runtime, not during graph construction.
    """
    # Create workflow
    workflow = StateGraph(QNRSessionState)

    # Add nodes (they will receive db via runtime config)
    workflow.add_node("load_qnr", load_qnr_node)
    workflow.add_node("determine_next_question", determine_next_question_node)
    workflow.add_node("render_question", render_question_node)
    workflow.add_node("render_completion", render_completion_node)

    # Define edges
    workflow.set_entry_point("load_qnr")
    workflow.add_edge("load_qnr", "determine_next_question")
    workflow.add_conditional_edges(
        "determine_next_question",
        route_after_determination,
        {
            "render_question": "render_question",
            "render_completion": "render_completion",
        },
    )
    workflow.add_edge("render_question", END)
    workflow.add_edge("render_completion", END)

    return workflow.compile()
