"""LangGraph workflow for agentic DecisionTree generation.

Orchestrates the 3-phase workflow with separate conclusion extraction:
- Phase 1: Search + Factor Analysis → User edits factors
- Phase 1.5: Extract Conclusions → User edits conclusions
- Phase 2: Design questionnaire → User edits design → Build + Fix + Save

Uses LangGraph's interrupt() for human-in-the-loop editing.
The return value of interrupt() is the resume value from Command(resume=...).
"""

import logging
import time

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from smeme.decision_tree.generation.agentic.models import AgenticDecisionTreeGenerationState
from smeme.decision_tree.generation.agentic.subgraphs.build import (
    create_build_subgraph,
    extract_build_input,
    merge_build_output,
)
from smeme.decision_tree.generation.agentic.subgraphs.conclusions import (
    create_conclusions_subgraph,
    extract_conclusions_input,
    merge_conclusions_output,
)
from smeme.decision_tree.generation.agentic.subgraphs.design import (
    create_design_subgraph,
    extract_design_input,
    merge_design_output,
)
from smeme.decision_tree.generation.agentic.subgraphs.models import (
    BuildSubgraphOutput,
    ConclusionsSubgraphOutput,
    DesignSubgraphOutput,
    InterruptPayload,
    ResearchSubgraphOutput,
)
from smeme.decision_tree.generation.agentic.subgraphs.research import (
    create_research_subgraph,
    extract_research_input,
    merge_research_output,
)

logger = logging.getLogger("smeme.decision_tree.generation.agentic")


# =============================================================================
# Workflow Version (Sprint 6)
# =============================================================================

# Semantic version for workflow code
# Increment when making changes to workflow structure or logic:
# - MAJOR: Breaking changes (state schema changes, node removals)
# - MINOR: New features (new nodes, new state fields with defaults)
# - PATCH: Bug fixes, performance improvements
WORKFLOW_VERSION = "1.0.0"


# =============================================================================
# Phase Tracker Nodes (Sprint 6)
# =============================================================================
# These lightweight nodes explicitly track phase transitions for observability.
# Benefits:
# - Always know current phase (no inference from node names)
# - Log phase transitions for debugging
# - Track phase duration for analytics
# - Enable phase-based UI progress indicators


def set_research_phase(state: AgenticDecisionTreeGenerationState) -> dict:
    """Transition to research phase.

    Called at workflow start before research subgraph.
    """
    current_time = time.time()
    previous_phase = state.get("current_phase")

    phase_transition = {
        "from": previous_phase,
        "to": "research",
        "timestamp": current_time,
    }

    logger.info(
        "Phase transition: research",
        extra={
            "user_id": state.get("user_id"),
            "from_phase": previous_phase,
            "to_phase": "research",
            "augmentation_count": state.get("augmentation_count", 0),
        },
    )

    return {
        "current_phase": "research",
        "phase_start_time": current_time,
        "phase_history": [phase_transition],
    }


def set_conclusions_phase(state: AgenticDecisionTreeGenerationState) -> dict:
    """Transition to conclusions phase.

    Called after research edit, before conclusions subgraph.
    """
    current_time = time.time()
    previous_phase = state.get("current_phase")
    phase_start = state.get("phase_start_time", current_time)
    phase_duration = current_time - phase_start

    phase_transition = {
        "from": previous_phase,
        "to": "conclusions",
        "timestamp": current_time,
        "previous_phase_duration_seconds": round(phase_duration, 2),
    }

    logger.info(
        "Phase transition: conclusions",
        extra={
            "user_id": state.get("user_id"),
            "from_phase": previous_phase,
            "to_phase": "conclusions",
            "previous_phase_duration": phase_duration,
        },
    )

    return {
        "current_phase": "conclusions",
        "phase_start_time": current_time,
        "phase_history": [phase_transition],
    }


def set_design_phase(state: AgenticDecisionTreeGenerationState) -> dict:
    """Transition to design phase.

    Called after conclusions edit, before design subgraph.
    """
    current_time = time.time()
    previous_phase = state.get("current_phase")
    phase_start = state.get("phase_start_time", current_time)
    phase_duration = current_time - phase_start

    phase_transition = {
        "from": previous_phase,
        "to": "design",
        "timestamp": current_time,
        "previous_phase_duration_seconds": round(phase_duration, 2),
    }

    logger.info(
        "Phase transition: design",
        extra={
            "user_id": state.get("user_id"),
            "from_phase": previous_phase,
            "to_phase": "design",
            "previous_phase_duration": phase_duration,
        },
    )

    return {
        "current_phase": "design",
        "phase_start_time": current_time,
        "phase_history": [phase_transition],
    }


def set_build_phase(state: AgenticDecisionTreeGenerationState) -> dict:
    """Transition to build phase.

    Called after design edit, before build subgraph.
    """
    current_time = time.time()
    previous_phase = state.get("current_phase")
    phase_start = state.get("phase_start_time", current_time)
    phase_duration = current_time - phase_start

    phase_transition = {
        "from": previous_phase,
        "to": "build",
        "timestamp": current_time,
        "previous_phase_duration_seconds": round(phase_duration, 2),
    }

    logger.info(
        "Phase transition: build",
        extra={
            "user_id": state.get("user_id"),
            "from_phase": previous_phase,
            "to_phase": "build",
            "previous_phase_duration": phase_duration,
        },
    )

    return {
        "current_phase": "build",
        "phase_start_time": current_time,
        "phase_history": [phase_transition],
    }


def set_complete_phase(state: AgenticDecisionTreeGenerationState) -> dict:
    """Transition to complete phase.

    Called after successful save_decision_tree.
    """
    current_time = time.time()
    previous_phase = state.get("current_phase")
    phase_start = state.get("phase_start_time", current_time)
    phase_duration = current_time - phase_start

    phase_transition = {
        "from": previous_phase,
        "to": "complete",
        "timestamp": current_time,
        "previous_phase_duration_seconds": round(phase_duration, 2),
    }

    logger.info(
        "Phase transition: complete",
        extra={
            "user_id": state.get("user_id"),
            "from_phase": previous_phase,
            "to_phase": "complete",
            "previous_phase_duration": phase_duration,
            "decision_tree_id": state.get("decision_tree_id"),
        },
    )

    return {
        "current_phase": "complete",
        "phase_start_time": current_time,
        "phase_history": [phase_transition],
    }


def set_error_phase(state: AgenticDecisionTreeGenerationState) -> dict:
    """Transition to error phase.

    Called when a terminal error occurs.
    """
    current_time = time.time()
    previous_phase = state.get("current_phase")
    phase_start = state.get("phase_start_time", current_time)
    phase_duration = current_time - phase_start

    phase_transition = {
        "from": previous_phase,
        "to": "error",
        "timestamp": current_time,
        "previous_phase_duration_seconds": round(phase_duration, 2),
    }

    logger.error(
        "Phase transition: error",
        extra={
            "user_id": state.get("user_id"),
            "from_phase": previous_phase,
            "to_phase": "error",
            "error_message": state.get("error"),
        },
    )

    return {
        "current_phase": "error",
        "phase_start_time": current_time,
        "phase_history": [phase_transition],
    }


# =============================================================================
# Subgraph Invocation Nodes
# =============================================================================


async def invoke_research_subgraph(
    state: AgenticDecisionTreeGenerationState,
    config,
) -> dict:
    """Invoke research subgraph and merge results.

    Note: Using Option A approach - simpler conditional routing in parent.
    The subgraph runs to completion for each invocation (initial or augmentation).
    The parent's wait_for_research_edit node handles the interrupt and routing.

    Pattern:
    1. Extract input (validates parent state)
    2. Compile subgraph
    3. Invoke subgraph (inherits checkpointer from config)
    4. Validate output
    5. Merge back to parent state
    """
    logger.info(
        "Invoking research subgraph",
        extra={
            "user_id": str(state["user_id"]),
            "thread_id": config.get("configurable", {}).get("thread_id"),
            "augmentation_count": state.get("augmentation_count", 0),
        },
    )

    # Extract and validate input
    research_input = extract_research_input(state)

    # Compile subgraph (checkpointer inherited from parent config)
    research_subgraph = create_research_subgraph().compile()

    # Invoke subgraph - it will run search (or augment if augment_prompt is set)
    subgraph_result = await research_subgraph.ainvoke(
        research_input.model_dump(),
        config,
    )

    # Validate output
    research_output = ResearchSubgraphOutput(**subgraph_result)

    # Merge back to parent state
    updates = merge_research_output(state, research_output)

    logger.info(
        "Research subgraph completed",
        extra={
            "user_id": str(state["user_id"]),
            "research_length": len(research_output.research_context),
            "augmentation_count": research_output.augmentation_count,
        },
    )

    return updates


async def invoke_conclusions_subgraph(
    state: AgenticDecisionTreeGenerationState,
    config: RunnableConfig,
) -> dict:
    """Invoke conclusions subgraph and merge results.

    Pattern (from Sprint 2):
    1. Extract input (validates parent state)
    2. Compile subgraph
    3. Invoke subgraph
    4. Validate output
    5. Merge back to parent state
    """
    logger.info(
        "Invoking conclusions subgraph",
        extra={
            "user_id": str(state["user_id"]),
            "thread_id": config.get("configurable", {}).get("thread_id"),
            "has_user_conclusions": bool(state.get("user_conclusions")),
        },
    )

    # Step 1: Extract and validate input
    conclusions_input = extract_conclusions_input(state)

    # Step 2: Compile subgraph (checkpointer inherited from parent config)
    conclusions_subgraph = create_conclusions_subgraph().compile()

    # Step 3: Invoke subgraph
    subgraph_result = await conclusions_subgraph.ainvoke(
        conclusions_input.model_dump(),
        config,
    )

    # Step 4: Validate output
    conclusions_output = ConclusionsSubgraphOutput(**subgraph_result)

    # Step 5: Merge back
    updates = merge_conclusions_output(state, conclusions_output)

    logger.info(
        "Conclusions subgraph completed",
        extra={
            "user_id": str(state["user_id"]),
            "conclusions_length": len(conclusions_output.possible_conclusions),
            "conclusions_source": conclusions_output.conclusions_source,
        },
    )

    return updates


async def invoke_design_subgraph(
    state: AgenticDecisionTreeGenerationState,
    config: RunnableConfig,
) -> dict:
    """Invoke design subgraph and merge results.

    Pattern (from Sprints 2 & 3):
    1. Extract input (validates parent state)
    2. Compile subgraph (DON'T FORGET .compile()!)
    3. Invoke subgraph
    4. Validate output
    5. Merge back to parent state
    """
    logger.info(
        "Invoking design subgraph",
        extra={
            "user_id": str(state["user_id"]),
            "thread_id": config.get("configurable", {}).get("thread_id"),
            "research_length": len(state.get("research_context_edited", "")),
            "conclusions_length": len(state.get("possible_conclusions_edited", "")),
        },
    )

    # Step 1: Extract and validate input
    design_input = extract_design_input(state)

    # Step 2: Compile subgraph (checkpointer inherited from parent config)
    design_subgraph = create_design_subgraph().compile()  # ← Don't forget!

    # Step 3: Invoke subgraph
    subgraph_result = await design_subgraph.ainvoke(
        design_input.model_dump(),
        config,
    )

    # Step 4: Validate output
    design_output = DesignSubgraphOutput(**subgraph_result)

    # Step 5: Merge back
    updates = merge_design_output(state, design_output)

    logger.info(
        "Design subgraph completed",
        extra={
            "user_id": str(state["user_id"]),
            "design_length": len(design_output.decision_tree_design),
            "design_source": design_output.design_source,
            "token_usage": design_output.token_usage,
        },
    )

    return updates


async def invoke_build_subgraph(
    state: AgenticDecisionTreeGenerationState,
    config: RunnableConfig,
) -> dict:
    """Invoke build subgraph and merge results.

    Pattern (from Sprints 2-4):
    1. Extract input (validates parent state)
    2. Compile subgraph (DON'T FORGET .compile()!)
    3. Invoke subgraph (runs internal validation loop)
    4. Validate output
    5. Merge back to parent state
    """
    logger.info(
        "Invoking build subgraph",
        extra={
            "user_id": str(state["user_id"]),
            "thread_id": config.get("configurable", {}).get("thread_id"),
            "design_length": len(state.get("decision_tree_design_edited", "")),
        },
    )

    # Step 1: Extract and validate input
    build_input = extract_build_input(state)

    # Step 2: Compile subgraph (checkpointer inherited from parent config)
    build_subgraph = create_build_subgraph().compile()  # ← Don't forget!

    # Step 3: Invoke subgraph (runs internal validation loop)
    subgraph_result = await build_subgraph.ainvoke(
        build_input.model_dump(),
        config,
    )

    # Step 4: Validate output
    build_output = BuildSubgraphOutput(**subgraph_result)

    # Step 5: Merge back
    updates = merge_build_output(state, build_output)

    logger.info(
        "Build subgraph completed",
        extra={
            "user_id": str(state["user_id"]),
            "final_status": build_output.final_status,
            "error_count": len(build_output.validation_errors),
            "warning_count": len(build_output.validation_warnings),
            "fix_iterations": build_output.fix_iteration_count,
            "token_usage": build_output.build_token_usage,
        },
    )

    return updates


# =============================================================================
# DecisionTree Persistence Node (Sprint 6: Moved from nodes/build.py)
# =============================================================================


async def save_decision_tree_node(
    state: AgenticDecisionTreeGenerationState,
    config: RunnableConfig,
) -> dict:
    """
    Save DTGraph to database.

    Always saves, even if there are remaining errors (user can fix in editor).
    Moved from nodes/build.py during Sprint 6 cleanup.
    """
    from typing import Literal
    from uuid import UUID

    from sqlmodel.ext.asyncio.session import AsyncSession

    from smeme.core.models import DecisionTree, DecisionTreeResearchCorpus
    from smeme.reasoning.cevi.corpus_normalize import (
        normalize_corpus_text,
        truncate_corpus_to_max_bytes,
    )
    from smeme.reasoning.cevi.generation_corpus import (
        build_research_corpus_text_from_generation_state,
    )

    # Check for fatal errors or missing graph
    if state.get("error") or not state.get("generated_graph"):
        return {}

    user_id: UUID = config["configurable"]["user_id"]
    db: AsyncSession = config["configurable"]["db"]
    user_prompt = state["user_prompt"]

    errors = state.get("validation_errors", [])
    warnings = state.get("validation_warnings", [])

    logger.info(
        "Saving DecisionTree to database",
        extra={
            "user_id": str(user_id),
            "has_errors": bool(errors),
            "has_warnings": bool(warnings),
            "node": "save_decision_tree",
            "phase": "complete",
        },
    )

    try:
        graph_dict = state["generated_graph"]

        # Determine final status
        if errors:
            final_status: Literal["valid", "valid_with_warnings", "has_errors"] = "has_errors"
        elif warnings:
            final_status = "valid_with_warnings"
        else:
            final_status = "valid"

        # Use brief title as source of truth; fallback to graph metadata or goal
        brief_title = state.get("title")
        if brief_title and brief_title.strip():
            decision_tree_title = brief_title.strip()[:200]
        else:
            decision_tree_title = graph_dict.get("metadata", {}).get(
                "title", f"Decision tree: {user_prompt[:50]}..."
            )

        # Create DecisionTree record (DecisionTree has title; description lives in graph_data.metadata)
        decision_tree = DecisionTree(
            title=decision_tree_title,
            author_id=user_id,
            graph_data=graph_dict,
            is_published=False,  # Draft by default
        )

        db.add(decision_tree)
        await db.flush()

        merged_corpus = build_research_corpus_text_from_generation_state(dict(state))
        normalized_corpus = truncate_corpus_to_max_bytes(normalize_corpus_text(merged_corpus))
        if normalized_corpus:
            db.add(
                DecisionTreeResearchCorpus(
                    decision_tree_id=decision_tree.id, body_text=normalized_corpus
                )
            )

        await db.commit()
        await db.refresh(decision_tree)

        logger.info(
            "DecisionTree saved successfully",
            extra={
                "user_id": str(user_id),
                "decision_tree_id": str(decision_tree.id),
                "final_status": final_status,
                "node": "save_decision_tree",
                "phase": "complete",
            },
        )

        return {
            "decision_tree_id": str(decision_tree.id),
            "final_status": final_status,
            "remaining_issues": errors + warnings,
        }

    except Exception as e:
        logger.error(
            "Failed to save decision tree",
            extra={
                "user_id": str(user_id),
                "error": str(e),
                "node": "save_decision_tree",
            },
            exc_info=True,
        )
        return {
            "error": f"Failed to save decision tree: {str(e)}",
            "error_recoverable": True,
        }


# =============================================================================
# Human Input Nodes (receive edited content from user)
# =============================================================================


async def wait_for_research_edit_node(state: AgenticDecisionTreeGenerationState) -> dict:
    """
    Pause for user to review/edit research factors.

    Sprint 6: Uses InterruptPayload for standardized interrupt format.

    Flow:
    1. Build InterruptPayload with phase, user_id, action_required, data_to_edit, metadata
    2. interrupt(payload.model_dump()) pauses workflow
    3. Route handler receives payload, validates it, shows edit form
    4. User submits, route calls Command(resume=result_dict)
    5. interrupt() returns result_dict
    6. Node returns result_dict to update state
    """
    research_context = state.get("research_context", "")
    augmentation_count = state.get("augmentation_count", 0)

    logger.info(
        "Waiting for research edit",
        extra={
            "user_id": state["user_id"],
            "research_length": len(research_context),
            "augmentation_count": augmentation_count,
            "phase": "research",
        },
    )

    # Build standardized interrupt payload (Sprint 6)
    payload = InterruptPayload(
        phase="research",
        user_id=state["user_id"],
        action_required="Edit research factors and decide whether to continue or augment",
        data_to_edit={"research_context": research_context},
        metadata={
            "augmentation_count": augmentation_count,
            "search_skipped": state.get("search_skipped", False),
            "search_skip_reason": state.get("search_skip_reason"),
            "extraction_used": state.get("extraction_used", False),
        },
    )

    # Interrupt with payload
    result = interrupt(payload.model_dump())

    logger.info(
        "Resumed from research edit",
        extra={
            "user_id": state["user_id"],
            "result_type": type(result).__name__,
            "has_user_action": "user_action" in result if isinstance(result, dict) else False,
        },
    )

    # Result is a dict from Command(resume=...) with user edits
    # Could contain: research_context_edited, augment_prompt, user_action, etc.
    return result if isinstance(result, dict) else {}


async def wait_for_conclusions_edit_node(state: AgenticDecisionTreeGenerationState) -> dict:
    """
    Pause for user to review/edit extracted conclusions.

    Sprint 6: Uses InterruptPayload for standardized interrupt format.

    Flow:
    1. Build InterruptPayload with conclusions data
    2. interrupt(payload.model_dump()) pauses workflow
    3. Route handler validates payload, shows edit form
    4. User edits and submits
    5. Route calls Command(resume=result_dict)
    6. interrupt() returns result_dict
    7. Node returns result_dict to update state
    """
    possible_conclusions = state.get("possible_conclusions", "")
    conclusions_source = state.get("conclusions_source", "unknown")

    logger.info(
        "Waiting for conclusions edit",
        extra={
            "conclusions_length": len(possible_conclusions),
            "has_conclusions": bool(possible_conclusions),
            "conclusions_source": conclusions_source,
            "phase": "conclusions",
        },
    )

    # Build standardized interrupt payload (Sprint 6)
    payload = InterruptPayload(
        phase="conclusions",
        user_id=state["user_id"],
        action_required="Review and edit possible conclusions",
        data_to_edit={"possible_conclusions": possible_conclusions},
        metadata={
            "conclusions_source": conclusions_source,
            "research_context_available": bool(state.get("research_context_edited")),
        },
    )

    # Interrupt with payload
    result = interrupt(payload.model_dump())

    logger.info(
        "Received edited conclusions",
        extra={
            "result_type": type(result).__name__,
            "is_dict": isinstance(result, dict),
            "has_edited_field": "possible_conclusions_edited" in result
            if isinstance(result, dict)
            else False,
        },
    )

    # Handle different result formats
    if isinstance(result, dict):
        # If result contains edited conclusions, return as-is
        if "possible_conclusions_edited" in result:
            return result
        # If result is empty dict, preserve original
        if not result:
            return {"possible_conclusions_edited": possible_conclusions}

    # Legacy format: result is the edited text directly (backward compat)
    if isinstance(result, str):
        if not result:  # Empty string, use original
            return {"possible_conclusions_edited": possible_conclusions}
        return {"possible_conclusions_edited": result}

    # Default: preserve original
    return {"possible_conclusions_edited": possible_conclusions}


async def wait_for_design_edit_node(state: AgenticDecisionTreeGenerationState) -> dict:
    """
    Pause for user to review/edit questionnaire design.

    Sprint 6: Uses InterruptPayload for standardized interrupt format.

    Flow:
    1. Build InterruptPayload with design data
    2. interrupt(payload.model_dump()) pauses workflow
    3. Route handler validates payload, shows edit form
    4. User edits and submits
    5. Route calls Command(resume=result_dict)
    6. interrupt() returns result_dict
    7. Node returns result_dict to update state
    """
    decision_tree_design = state.get("decision_tree_design", "")
    design_source = state.get("design_source", "unknown")

    logger.info(
        "Waiting for design edit",
        extra={
            "decision_tree_design_length": len(decision_tree_design),
            "design_source": design_source,
            "phase": "design",
        },
    )

    # Build standardized interrupt payload (Sprint 6)
    payload = InterruptPayload(
        phase="design",
        user_id=state["user_id"],
        action_required="Review and edit questionnaire design",
        data_to_edit={"decision_tree_design": decision_tree_design},
        metadata={
            "design_source": design_source,
            "token_usage": state.get("design_token_usage"),
        },
    )

    # Interrupt with payload
    result = interrupt(payload.model_dump())

    logger.info(
        "Received edited design",
        extra={
            "result_type": type(result).__name__,
            "is_dict": isinstance(result, dict),
            "has_edited_field": "decision_tree_design_edited" in result
            if isinstance(result, dict)
            else False,
        },
    )

    # Handle different result formats
    if isinstance(result, dict):
        # If result contains edited design, return as-is
        if "decision_tree_design_edited" in result:
            return result
        # If result is empty dict, preserve original
        if not result:
            return {"decision_tree_design_edited": decision_tree_design}

    # Legacy format: result is the edited text directly (backward compat)
    if isinstance(result, str):
        if not result:  # Empty string, use original
            return {"decision_tree_design_edited": decision_tree_design}
        return {"decision_tree_design_edited": result}

    # Default: preserve original
    return {"decision_tree_design_edited": decision_tree_design}


# =============================================================================
# Conditional Routing
# =============================================================================


def should_continue_after_error(state: AgenticDecisionTreeGenerationState) -> str:
    """Check if workflow should continue or end due to error."""
    if state.get("error"):
        return "end"
    return "continue"


def route_after_build_subgraph(state: AgenticDecisionTreeGenerationState) -> str:
    """Route after build subgraph completes.

    Always routes to save_decision_tree - we save even questionnaires with errors
    so users can fix them manually in the editor.

    Routes to:
    - save_decision_tree: Always (users can fix errors in editor)
    - end: Only if build completely failed (no graph generated)
    """
    final_status = state.get("final_status", "has_errors")
    has_graph = bool(state.get("generated_graph"))

    logger.info(
        "Routing after build subgraph",
        extra={
            "final_status": final_status,
            "has_graph": has_graph,
            "error_count": len(state.get("validation_errors", [])),
            "warning_count": len(state.get("validation_warnings", [])),
            "fix_iterations": state.get("fix_iteration_count", 0),
        },
    )

    # Only skip saving if build completely failed (no graph at all)
    if not has_graph:
        logger.warning("Routing to end (no graph generated)")
        return "end"

    logger.info("Routing to save_decision_tree (will save even with errors)")
    return "save_decision_tree"


def route_after_research_edit(state: AgenticDecisionTreeGenerationState) -> str:
    """Route after user edits research factors.

    Routes to:
    - research_subgraph: If user requested augmentation (loop back)
    - conclusions_subgraph: If user clicked "Continue" (proceed forward)
    """
    user_action = state.get("user_action", "continue")
    augment_prompt = state.get("augment_prompt")
    augmentation_count = state.get("augmentation_count", 0)

    logger.info(
        "Routing after research edit",
        extra={
            "user_action": user_action,
            "has_augment_prompt": bool(augment_prompt),
            "augmentation_count": augmentation_count,
        },
    )

    # Check if augmentation was requested
    if user_action == "augment" and augment_prompt:
        # Enforce max 5 augmentations
        if augmentation_count >= 5:
            logger.warning(
                "Max augmentations reached, proceeding to conclusions",
                extra={"augmentation_count": augmentation_count},
            )
            return "conclusions_subgraph"

        logger.info("Routing back to research_subgraph for augmentation")
        return "research_subgraph"

    logger.info("No augmentation requested, proceeding to conclusions")
    return "conclusions_subgraph"


# =============================================================================
# Build Workflow
# =============================================================================


def build_agentic_generation_workflow() -> StateGraph:
    """
    Build and compile the agentic DecisionTree generation workflow with subgraph architecture.

    3-Phase Flow with Research Subgraph (Option A - Conditional Routing):
        START
          ↓
        Phase 1: research_subgraph (isolated subgraph)
          ├─ If augment_prompt set: augment → END
          └─ Otherwise: search → END
          ↓
        [INTERRUPT: wait_for_research_edit] ← User edits factors
          ├─ If "augment": Loop back to research_subgraph (max 5x)
          └─ If "continue": Proceed to conclusions
          ↓
        Phase 1.5: extract_conclusions (LLM generates conclusions)
          ↓
        [INTERRUPT: wait_for_conclusions_edit] ← User edits conclusions
          ↓
        Phase 2: design_questionnaire (uses edited factors + conclusions)
          ↓
        [INTERRUPT: wait_for_design_edit] ← User edits design
          ↓
        Phase 3: build_graph → validate_graph ←→ auto_fix (loop) → save_decision_tree
          ↓
        END

    Research Subgraph (Sprint 2B - Option A):
    - Isolated subgraph with own state model (Pydantic validation)
    - Runs ONCE per invocation (search OR augment, not both)
    - Parent workflow handles interrupt and augmentation loop
    - Returns research_context and metadata to parent workflow
    - Checkpointer inherited from parent for seamless persistence

    Human-in-the-loop uses interrupt() inside wait_for_*_edit nodes:
    1. Node calls interrupt(current_value), workflow pauses
    2. Route handler catches GraphInterrupt, renders edit form
    3. User edits and submits
    4. Route handler resumes with Command(resume=response_dict)
    5. interrupt() returns response_dict, node saves it to state

    Returns:
        Uncompiled StateGraph (compiled at runtime with persistent checkpointer)
    """
    workflow = StateGraph(AgenticDecisionTreeGenerationState)

    # =========================================================================
    # Add Nodes
    # =========================================================================

    # Phase Trackers (Sprint 6)
    workflow.add_node("set_research_phase", set_research_phase)
    workflow.add_node("set_conclusions_phase", set_conclusions_phase)
    workflow.add_node("set_design_phase", set_design_phase)
    workflow.add_node("set_build_phase", set_build_phase)
    workflow.add_node("set_complete_phase", set_complete_phase)

    # Phase 1: Research (now a subgraph)
    workflow.add_node("research_subgraph", invoke_research_subgraph)
    workflow.add_node("wait_for_research_edit", wait_for_research_edit_node)

    # Phase 1.5: Conclusions (now a subgraph)
    workflow.add_node("conclusions_subgraph", invoke_conclusions_subgraph)
    workflow.add_node("wait_for_conclusions_edit", wait_for_conclusions_edit_node)

    # Phase 2: Design (Subgraph)
    workflow.add_node("design_subgraph", invoke_design_subgraph)
    workflow.add_node("wait_for_design_edit", wait_for_design_edit_node)

    # Phase 3: Build + Validate + Fix (Subgraph) + Save
    workflow.add_node("build_subgraph", invoke_build_subgraph)
    workflow.add_node("save_decision_tree", save_decision_tree_node)

    # =========================================================================
    # Add Edges (Sprint 6: Phase trackers added before each major phase)
    # =========================================================================

    # Start → Set Research Phase → Research Subgraph
    workflow.add_edge(START, "set_research_phase")
    workflow.add_edge("set_research_phase", "research_subgraph")

    # After research subgraph → Wait for user to edit research
    workflow.add_edge("research_subgraph", "wait_for_research_edit")

    # After research edit → Conditional routing (augment OR continue to conclusions)
    workflow.add_conditional_edges(
        "wait_for_research_edit",
        route_after_research_edit,
        {
            "research_subgraph": "research_subgraph",  # Loop back for augmentation (no phase change)
            "conclusions_subgraph": "set_conclusions_phase",  # Proceed forward (set phase first)
        },
    )

    # Set Conclusions Phase → Conclusions Subgraph
    workflow.add_edge("set_conclusions_phase", "conclusions_subgraph")

    # Phase 1.5 conclusion extraction → Phase 1.5 human input
    workflow.add_conditional_edges(
        "conclusions_subgraph",
        should_continue_after_error,
        {
            "continue": "wait_for_conclusions_edit",
            "end": END,
        },
    )

    # Phase 1.5 human input → Set Design Phase → Design Subgraph
    workflow.add_edge("wait_for_conclusions_edit", "set_design_phase")
    workflow.add_edge("set_design_phase", "design_subgraph")

    # After design, check for errors then go to human input
    workflow.add_conditional_edges(
        "design_subgraph",
        should_continue_after_error,
        {
            "continue": "wait_for_design_edit",
            "end": END,
        },
    )

    # Phase 2 human input → Set Build Phase → Build Subgraph
    workflow.add_edge("wait_for_design_edit", "set_build_phase")
    workflow.add_edge("set_build_phase", "build_subgraph")

    # After build subgraph → Route based on validation result
    workflow.add_conditional_edges(
        "build_subgraph",
        route_after_build_subgraph,
        {
            "save_decision_tree": "set_complete_phase",  # Set complete phase before save
            "end": END,  # Enables retry via route
        },
    )

    # Set Complete Phase → Save DecisionTree → END
    workflow.add_edge("set_complete_phase", "save_decision_tree")
    workflow.add_edge("save_decision_tree", END)

    # Return uncompiled workflow
    # Will be compiled at runtime with persistent checkpointer
    return workflow


# Build workflow (not compiled yet)
_agentic_generation_workflow = build_agentic_generation_workflow()


async def get_compiled_workflow():
    """Get the compiled workflow with persistent PostgreSQL checkpointer.

    This function is called at runtime to get a workflow instance with
    the persistent checkpointer. The checkpointer must be initialized
    during application startup.

    Returns:
        Compiled StateGraph with PostgreSQL checkpointer for persistence

    Raises:
        RuntimeError: If checkpointer not initialized
    """
    from smeme.decision_tree.generation.agentic.checkpointer import checkpointer_manager

    checkpointer = await checkpointer_manager.get_checkpointer()
    return _agentic_generation_workflow.compile(checkpointer=checkpointer)


# Legacy name for backwards compatibility
# TODO: Update all usages to call get_compiled_workflow() instead
agentic_generation_workflow = _agentic_generation_workflow
