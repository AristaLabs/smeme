"""Design subgraph for agentic DecisionTree generation.

Handles questionnaire design generation from research and conclusions.
Includes token optimization and retry mechanism.

Pattern: Sprint 4
- Single-path subgraph (no hybrid, no loops)
- Token optimization for input context
- Retry-friendly error handling
- Source tracking for debugging
"""

import logging
import time
from typing import Any

import httpx
from langgraph.graph import END, START, StateGraph
from openai import AsyncOpenAI

from smeme.core.openai_models import OPENAI_MODEL_HEAVY
from smeme.decision_tree.generation.agentic.conclusions_parse import parse_allowed_conclusions
from smeme.decision_tree.generation.agentic.design_context import format_structured_design_context
from smeme.decision_tree.generation.agentic.prompts import DESIGN_DECISION_TREE_PROMPT
from smeme.decision_tree.generation.agentic.subgraphs.models import (
    DesignSubgraphInput,
    DesignSubgraphOutput,
    DesignSubgraphState,
)

logger = logging.getLogger("smeme.decision_tree.generation.agentic")

MODEL_DESIGN = OPENAI_MODEL_HEAVY

# Context limits for design LLM input (Track A: preserve routing/threshold detail)
MAX_RESEARCH_CONTEXT_CHARS = 12_000
MAX_CONCLUSIONS_CHARS = 6_000
MAX_FACTORS_WHEN_SPLIT = 20


# ============================================================================
# Helper Functions
# ============================================================================


def optimize_context_for_design(
    research_context: str,
    conclusions: str,
) -> tuple[str, str, bool]:
    """Optimize research context and conclusions to reduce token usage.

    Strategy:
    1. Truncate research factors if > MAX_RESEARCH_CONTEXT_CHARS
    2. Truncate conclusions if > MAX_CONCLUSIONS_CHARS
    3. Preserve factor numbering and structure

    Args:
        research_context: Full research factors text
        conclusions: Full conclusions text

    Returns:
        (optimized_research, optimized_conclusions, was_optimized)
    """
    optimized = False
    optimized_research = research_context
    optimized_conclusions = conclusions

    # Optimize research context
    if len(research_context) > MAX_RESEARCH_CONTEXT_CHARS:
        # Split by factor (assumes "Factor N:" format)
        factors = research_context.split("Factor ")

        # Keep first N factors + header
        if len(factors) > MAX_FACTORS_WHEN_SPLIT + 1:
            kept_factors = factors[: MAX_FACTORS_WHEN_SPLIT + 1]
            optimized_research = "Factor ".join(kept_factors)
            optimized_research += "\n\n[...additional factors truncated for token efficiency...]"
            optimized = True
        else:
            # Just truncate at character limit
            optimized_research = research_context[:MAX_RESEARCH_CONTEXT_CHARS]
            optimized_research += "\n[...truncated...]"
            optimized = True

    # Optimize conclusions
    if len(conclusions) > MAX_CONCLUSIONS_CHARS:
        optimized_conclusions = conclusions[:MAX_CONCLUSIONS_CHARS]
        optimized_conclusions += "\n[...truncated...]"
        optimized = True

    if optimized:
        original_chars = len(research_context) + len(conclusions)
        optimized_chars = len(optimized_research) + len(optimized_conclusions)
        token_reduction_estimate = (original_chars - optimized_chars) // 4

        logger.info(
            "Optimized design input context",
            extra={
                "original_research_chars": len(research_context),
                "optimized_research_chars": len(optimized_research),
                "original_conclusions_chars": len(conclusions),
                "optimized_conclusions_chars": len(optimized_conclusions),
                "token_reduction_estimate": token_reduction_estimate,
                "reduction_percentage": round(
                    ((original_chars - optimized_chars) / original_chars) * 100, 1
                ),
            },
        )

    return optimized_research, optimized_conclusions, optimized


# ============================================================================
# Subgraph Nodes
# ============================================================================


async def generate_design_node(
    state: DesignSubgraphState,
    config,
) -> dict[str, Any]:
    """Generate questionnaire design using LLM.

    Applies token optimization before calling LLM.
    Includes retry-friendly error handling.
    """
    start_time = time.time()

    openai_client: AsyncOpenAI = config["configurable"]["openai_client"]

    logger.info(
        "Generating questionnaire design",
        extra={
            "user_id": str(state.user_id),
            "research_length": len(state.research_context_edited),
            "conclusions_length": len(state.possible_conclusions_edited),
        },
    )

    # Step 1: Optimize input context for token efficiency
    optimized_research, optimized_conclusions, was_optimized = optimize_context_for_design(
        state.research_context_edited,
        state.possible_conclusions_edited,
    )

    allowed = parse_allowed_conclusions(optimized_conclusions)
    if not allowed.parse_ok:
        logger.warning(
            "Could not parse CONCLUSION_N IDs from approved conclusions",
            extra={"user_id": str(state.user_id)},
        )

    combined_context = format_structured_design_context(
        research_context=optimized_research,
        conclusions=optimized_conclusions,
        allowed_conclusions_block=allowed.formatted_block,
        conclusions_parse_ok=allowed.parse_ok,
    )

    try:
        system_prompt = DESIGN_DECISION_TREE_PROMPT.format(
            user_prompt=state.user_prompt,
            research_context_edited=combined_context,
            allowed_conclusions=allowed.formatted_block,
        )

        input_chars = len(system_prompt) + len("Design the complete questionnaire now.")
        input_tokens_estimate = (len(system_prompt) + 100) // 4

        logger.info(
            "Calling OpenAI for design generation",
            extra={
                "user_id": str(state.user_id),
                "input_chars": input_chars,
                "input_tokens_estimate": input_tokens_estimate,
                "optimization_applied": was_optimized,
            },
        )

        response = await openai_client.chat.completions.create(
            model=MODEL_DESIGN,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Design the complete questionnaire now."},
            ],
            max_completion_tokens=10000,
        )

        decision_tree_design = response.choices[0].message.content or ""

        # Extract token usage
        token_usage = None
        if response.usage:
            token_usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        elapsed_ms = (time.time() - start_time) * 1000

        logger.info(
            "Design generation completed",
            extra={
                "user_id": str(state.user_id),
                "design_length": len(decision_tree_design),
                "elapsed_ms": round(elapsed_ms, 2),
                "token_usage": token_usage,
                "optimization_applied": was_optimized,
            },
        )

        return {
            "decision_tree_design": decision_tree_design,
            "design_source": "llm_generated",
            "design_raw": {
                "model": response.model,
                "finish_reason": response.choices[0].finish_reason,
                "usage": token_usage,
            },
            "token_usage": token_usage,
            "allowed_conclusion_ids": list(allowed.ids),
            "allowed_conclusions_parse_ok": allowed.parse_ok,
            "llm_generation_attempted": True,
            "llm_generation_failed": False,
            "optimization_applied": was_optimized,
        }

    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.error(
            "Design generation failed (network)",
            extra={
                "user_id": str(state.user_id),
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )

        # Return graceful failure (enables retry)
        return {
            "decision_tree_design": "",
            "design_source": "llm_failed",
            "design_raw": {
                "error": str(e),
                "error_type": type(e).__name__,
            },
            "llm_generation_attempted": True,
            "llm_generation_failed": True,
        }

    except Exception as e:
        logger.error(
            "Design generation failed",
            extra={
                "user_id": str(state.user_id),
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )

        return {
            "decision_tree_design": "",
            "design_source": "llm_failed",
            "design_raw": {
                "error": str(e),
                "error_type": type(e).__name__,
            },
            "llm_generation_attempted": True,
            "llm_generation_failed": True,
        }


# ============================================================================
# Subgraph Builder
# ============================================================================


def create_design_subgraph() -> StateGraph:
    """Create the design subgraph.

    Flow:
        START → generate_design_node → END

    Single path (no routing), but supports retry via parent workflow.

    Returns:
        StateGraph ready to compile
    """
    workflow = StateGraph(DesignSubgraphState)

    # Add single node
    workflow.add_node("generate_design", generate_design_node)

    # Simple linear flow
    workflow.add_edge(START, "generate_design")
    workflow.add_edge("generate_design", END)

    return workflow


# ============================================================================
# Integration Helpers
# ============================================================================


def extract_design_input(parent_state: dict) -> DesignSubgraphInput:
    """Extract design input from parent workflow state.

    Args:
        parent_state: Parent workflow state dict

    Returns:
        Validated DesignSubgraphInput

    Raises:
        ValidationError: If required fields missing or invalid
    """
    return DesignSubgraphInput(
        user_prompt=parent_state["user_prompt"],
        user_id=parent_state["user_id"],
        research_context_edited=parent_state.get("research_context_edited")
        or parent_state.get("research_context", ""),
        possible_conclusions_edited=parent_state.get("possible_conclusions_edited")
        or parent_state.get("possible_conclusions", ""),
    )


def merge_design_output(
    parent_state: dict,
    design_output: DesignSubgraphOutput,
) -> dict:
    """Merge design subgraph output back into parent state.

    Args:
        parent_state: Parent workflow state dict
        design_output: Validated design subgraph output

    Returns:
        State updates to merge into parent
    """
    return {
        "decision_tree_design": design_output.decision_tree_design,
        "design_source": design_output.design_source,
        "design_raw": design_output.design_raw,
        "design_token_usage": design_output.token_usage,
        "allowed_conclusion_ids": design_output.allowed_conclusion_ids,
        "allowed_conclusions_parse_ok": design_output.allowed_conclusions_parse_ok,
    }
