"""Conclusions subgraph for extracting or accepting user-provided conclusions.

This subgraph handles:
- Hybrid path: user-provided conclusions OR LLM extraction
- Graceful degradation if LLM extraction fails
- Source tracking for transparency

Exit Contract:
    Returns ConclusionsSubgraphOutput with possible_conclusions and source.
    Parent workflow receives complete conclusions with provenance.
"""

from typing import Any, Literal

import httpx
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from openai import AsyncOpenAI

from smeme.core.logging import get_logger
from smeme.core.openai_models import OPENAI_MAX_COMPLETION_CONCLUSIONS, OPENAI_MODEL_HEAVY
from smeme.decision_tree.generation.agentic.conclusions_sanitize import (
    sanitize_extracted_conclusions,
)
from smeme.decision_tree.generation.agentic.prompts import EXTRACT_CONCLUSIONS_PROMPT
from smeme.decision_tree.generation.agentic.subgraphs.models import (
    ConclusionsSubgraphInput,
    ConclusionsSubgraphOutput,
    ConclusionsSubgraphState,
)

logger = get_logger(__name__)

MODEL_CONCLUSIONS = OPENAI_MODEL_HEAVY


# ============================================================================
# Node Functions
# ============================================================================


async def user_provided_conclusions_node(
    state: ConclusionsSubgraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Use user-provided conclusions directly (no LLM call).

    This path is taken when user entered conclusions in the initial form.
    """
    logger.info(
        "Using user-provided conclusions",
        extra={
            "user_id": str(state.user_id),
            "conclusions_length": len(state.user_conclusions or ""),
            "node": "user_provided_conclusions",
        },
    )

    return {
        "possible_conclusions": state.user_conclusions or "",
        "conclusions_source": "user_provided",
        "conclusions_raw": None,  # No LLM call
    }


async def extract_conclusions_node(
    state: ConclusionsSubgraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Extract conclusions from research context using LLM.

    Called when user did NOT provide conclusions upfront.
    Uses GPT-4o to analyze research factors and derive conclusions.
    """
    logger.info(
        "Extracting conclusions via LLM",
        extra={
            "user_id": str(state.user_id),
            "research_length": len(state.research_context),
            "node": "extract_conclusions",
        },
    )

    # Get OpenAI client from config
    openai_client: AsyncOpenAI | None = config.get("configurable", {}).get("openai_client")
    if not openai_client:
        logger.error(
            "OpenAI client not provided in config",
            extra={"user_id": str(state.user_id), "node": "extract_conclusions"},
        )
        return {
            "possible_conclusions": (
                "⚠️ LLM unavailable\n\nPlease provide conclusions manually in the edit form."
            ),
            "conclusions_source": "llm_failed",
            "llm_extraction_attempted": True,
            "llm_extraction_failed": True,
        }

    try:
        # Build extraction prompt using existing template
        system_prompt = EXTRACT_CONCLUSIONS_PROMPT.format(
            user_prompt=state.user_prompt,
            research_context_edited=state.research_context,
        )

        logger.info(
            "Calling OpenAI for conclusions extraction",
            extra={
                "user_id": str(state.user_id),
                "prompt_length": len(system_prompt),
                "node": "extract_conclusions",
            },
        )

        # Call LLM
        response = await openai_client.chat.completions.create(
            model=MODEL_CONCLUSIONS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the possible conclusions now."},
            ],
            max_completion_tokens=OPENAI_MAX_COMPLETION_CONCLUSIONS,
        )

        raw_text = response.choices[0].message.content or ""
        conclusions_text = sanitize_extracted_conclusions(raw_text)

        logger.info(
            "LLM conclusions extracted",
            extra={
                "user_id": str(state.user_id),
                "conclusions_length": len(conclusions_text),
                "conclusions_preview": conclusions_text[:200],
                "sanitized_chars_removed": len(raw_text) - len(conclusions_text),
                "node": "extract_conclusions",
            },
        )

        return {
            "possible_conclusions": conclusions_text,
            "conclusions_source": "llm_extracted",
            "conclusions_raw": {
                "model": MODEL_CONCLUSIONS,
                "prompt_length": len(system_prompt),
                "response_length": len(conclusions_text),
                "response_preview": conclusions_text[:500],
            },
            "llm_extraction_attempted": True,
            "llm_extraction_failed": False,
        }

    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.error(
            "OpenAI API failed (network)",
            extra={
                "user_id": str(state.user_id),
                "error": str(e),
                "error_type": type(e).__name__,
                "node": "extract_conclusions",
            },
            exc_info=True,
        )

        # Graceful degradation
        return {
            "possible_conclusions": (
                "⚠️ AI service temporarily unavailable (network issue)\n\n"
                "Please provide conclusions manually in the edit form, "
                "or try the retry button."
            ),
            "conclusions_source": "llm_failed",
            "llm_extraction_attempted": True,
            "llm_extraction_failed": True,
        }

    except Exception as e:
        logger.error(
            "Failed to extract conclusions",
            extra={
                "user_id": str(state.user_id),
                "error": str(e),
                "error_type": type(e).__name__,
                "node": "extract_conclusions",
            },
            exc_info=True,
        )

        # Graceful degradation
        return {
            "possible_conclusions": (
                f"⚠️ Conclusion extraction failed: {str(e)}\n\n"
                "Please provide conclusions manually in the edit form, "
                "or try the retry button."
            ),
            "conclusions_source": "llm_failed",
            "llm_extraction_attempted": True,
            "llm_extraction_failed": True,
        }


# ============================================================================
# Routing Functions
# ============================================================================


def route_entry(
    state: ConclusionsSubgraphState,
) -> Literal["user_provided", "extract_conclusions"]:
    """Route based on whether user provided conclusions upfront.

    Decision Logic:
    - If user_conclusions present and non-empty → use directly
    - Otherwise → extract from research via LLM
    """
    if state.user_conclusions and state.user_conclusions.strip():
        logger.info(
            "Routing to user-provided conclusions (hybrid path)",
            extra={"user_id": str(state.user_id), "node": "route_entry"},
        )
        return "user_provided"

    logger.info(
        "Routing to LLM extraction (no user conclusions provided)",
        extra={"user_id": str(state.user_id), "node": "route_entry"},
    )
    return "extract_conclusions"


# ============================================================================
# Subgraph Builder
# ============================================================================


def create_conclusions_subgraph() -> StateGraph:
    """Create and compile the conclusions subgraph.

    Flow (entry routing):
        START → [route] → user_provided → END
                       └→ extract_conclusions → END

    Returns:
        StateGraph ready for parent workflow integration
    """
    workflow = StateGraph(ConclusionsSubgraphState)

    # Add nodes
    workflow.add_node("user_provided", user_provided_conclusions_node)
    workflow.add_node("extract_conclusions", extract_conclusions_node)

    # Entry routing based on user_conclusions presence
    workflow.add_conditional_edges(
        START,
        route_entry,
        {
            "user_provided": "user_provided",
            "extract_conclusions": "extract_conclusions",
        },
    )

    # Both paths go directly to END
    workflow.add_edge("user_provided", END)
    workflow.add_edge("extract_conclusions", END)

    return workflow


# ============================================================================
# Integration Helpers
# ============================================================================


def extract_conclusions_input(parent_state: dict) -> ConclusionsSubgraphInput:
    """Extract conclusions input from parent workflow state.

    Validates that parent state has all required fields.

    Args:
        parent_state: Parent workflow state dict

    Returns:
        Validated ConclusionsSubgraphInput

    Raises:
        ValidationError: If required fields missing or invalid
    """
    return ConclusionsSubgraphInput(
        user_prompt=parent_state["user_prompt"],
        user_id=parent_state["user_id"],
        research_context=parent_state.get("research_context", ""),
        user_conclusions=parent_state.get("user_conclusions"),
    )


def merge_conclusions_output(
    parent_state: dict,
    subgraph_output: ConclusionsSubgraphOutput,
) -> dict[str, Any]:
    """Merge conclusions subgraph output back into parent state.

    Args:
        parent_state: Parent workflow state dict
        subgraph_output: Validated conclusions results

    Returns:
        Dict of updates to merge into parent state
    """
    return {
        "possible_conclusions": subgraph_output.possible_conclusions,
        "conclusions_source": subgraph_output.conclusions_source,
        "conclusions_raw": subgraph_output.conclusions_raw,
    }
