"""Build subgraph for agentic decision-tree generation.

Handles graph building, validation, and auto-fix loop.
Most complex subgraph with internal validation → fix → validation loop (up to 3 iterations).

Pattern: Sprint 5
- Internal loop (validate → auto_fix → validate)
- Token optimization for input design
- Retry-friendly error handling
- Source tracking for builds and fixes
"""

import logging
import time
from typing import Any, Literal

import httpx
from langgraph.graph import END, START, StateGraph
from openai import AsyncOpenAI
from pydantic import ValidationError

from smeme.core.openai_models import OPENAI_MODEL_HEAVY
from smeme.qnr.generation.agentic.auto_fix import auto_fix_graph
from smeme.qnr.generation.agentic.branching_quality import (
    assess_branching_quality,
    branching_quality_errors_are_auto_fixable,
)
from smeme.qnr.generation.agentic.conclusions_parse import parse_allowed_conclusions
from smeme.qnr.generation.agentic.design_parse import parse_collect_only_question_ids
from smeme.qnr.generation.agentic.prompts import BUILD_GRAPH_PROMPT
from smeme.qnr.generation.agentic.subgraphs.models import (
    BuildSubgraphInput,
    BuildSubgraphOutput,
    BuildSubgraphState,
)
from smeme.qnr.helpers.validation import validate_graph_for_generation
from smeme.qnr.models import DTGraph

logger = logging.getLogger("smeme.qnr.generation.agentic")

MODEL_BUILD = OPENAI_MODEL_HEAVY

# Token optimization targets
MAX_DESIGN_CHARS = 8000  # ~2000 tokens

# Fix iteration limits
MAX_FIX_ITERATIONS = 3


# ============================================================================
# Helper Functions
# ============================================================================


def optimize_design_for_build(questionnaire_design: str) -> tuple[str, bool]:
    """Optimize questionnaire design to reduce token usage.

    Strategy:
    1. Truncate design if > MAX_DESIGN_CHARS
    2. Preserve question structure

    Args:
        questionnaire_design: Full design markdown

    Returns:
        (optimized_design, was_optimized)
    """
    optimized = False
    optimized_design = questionnaire_design

    if len(questionnaire_design) > MAX_DESIGN_CHARS:
        # Split by questions (assumes "#### Q" format)
        questions = questionnaire_design.split("#### Q")

        # Keep first 15 questions + header
        if len(questions) > 16:  # [0] is header, [1-15] are questions
            kept_questions = questions[:16]
            optimized_design = "#### Q".join(kept_questions)
            optimized_design += "\n\n[...additional questions truncated for token efficiency...]"
            optimized = True
        else:
            # Just truncate at character limit
            optimized_design = questionnaire_design[:MAX_DESIGN_CHARS]
            optimized_design += "\n[...truncated...]"
            optimized = True

        token_reduction_estimate = (len(questionnaire_design) - len(optimized_design)) // 4

        logger.info(
            "Optimized build input design",
            extra={
                "original_chars": len(questionnaire_design),
                "optimized_chars": len(optimized_design),
                "token_reduction_estimate": token_reduction_estimate,
                "reduction_percentage": round(
                    (
                        (len(questionnaire_design) - len(optimized_design))
                        / len(questionnaire_design)
                    )
                    * 100,
                    1,
                ),
            },
        )

    return optimized_design, optimized


# ============================================================================
# Subgraph Nodes
# ============================================================================


async def build_graph_node(
    state: BuildSubgraphState,
    config,
) -> dict[str, Any]:
    """Build DTGraph from markdown design using LLM.

    Applies token optimization before calling LLM.
    Includes retry-friendly error handling.
    """
    start_time = time.time()

    openai_client: AsyncOpenAI = config["configurable"]["openai_client"]

    logger.info(
        "Building graph from design",
        extra={
            "user_id": str(state.user_id),
            "design_length": len(state.questionnaire_design_edited),
        },
    )

    # Step 1: Optimize input design for token efficiency
    optimized_design, was_optimized = optimize_design_for_build(state.questionnaire_design_edited)

    try:
        system_prompt = BUILD_GRAPH_PROMPT.format(questionnaire_design_edited=optimized_design)

        input_tokens_estimate = len(system_prompt) // 4

        logger.info(
            "Calling OpenAI for graph build",
            extra={
                "user_id": str(state.user_id),
                "input_tokens_estimate": input_tokens_estimate,
                "optimization_applied": was_optimized,
            },
        )

        # Import LLM models from helpers (Sprint 6 cleanup)
        from smeme.qnr.generation.agentic.helpers import (
            LLMSimpleGraph,
            convert_simple_graph_to_dt_graph,
        )

        response = await openai_client.beta.chat.completions.parse(
            model=MODEL_BUILD,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the complete DTGraph JSON now."},
            ],
            response_format=LLMSimpleGraph,
            max_completion_tokens=16000,
        )

        parsed_graph = response.choices[0].message.parsed

        # Convert to full DTGraph
        dt_graph = convert_simple_graph_to_dt_graph(parsed_graph)
        generated_graph_dict = dt_graph.model_dump()

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
            "Graph build completed",
            extra={
                "user_id": str(state.user_id),
                "node_count": len(generated_graph_dict.get("nodes", [])),
                "edge_count": len(generated_graph_dict.get("edges", [])),
                "elapsed_ms": round(elapsed_ms, 2),
                "token_usage": token_usage,
                "optimization_applied": was_optimized,
            },
        )

        return {
            "generated_graph": generated_graph_dict,
            "build_source": "llm_generated",
            "build_raw": {
                "model": response.model,
                "finish_reason": response.choices[0].finish_reason,
                "usage": token_usage,
            },
            "build_token_usage": token_usage,
            "llm_build_attempted": True,
            "llm_build_failed": False,
            "optimization_applied": was_optimized,
        }

    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.error(
            "Graph build failed (network)",
            extra={
                "user_id": str(state.user_id),
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )

        # Return graceful failure (enables retry)
        return {
            "generated_graph": {},
            "build_source": "llm_failed",
            "build_raw": {
                "error": str(e),
                "error_type": type(e).__name__,
            },
            "llm_build_attempted": True,
            "llm_build_failed": True,
            "final_status": "has_errors",
            "validation_errors": [f"Build failed: {str(e)}"],
        }

    except Exception as e:
        logger.error(
            "Graph build failed",
            extra={
                "user_id": str(state.user_id),
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )

        return {
            "generated_graph": {},
            "build_source": "llm_failed",
            "build_raw": {
                "error": str(e),
                "error_type": type(e).__name__,
            },
            "llm_build_attempted": True,
            "llm_build_failed": True,
            "final_status": "has_errors",
            "validation_errors": [f"Build failed: {str(e)}"],
        }


async def validate_graph_node(
    state: BuildSubgraphState,
    config,
) -> dict[str, Any]:
    """Validate the generated graph.

    Uses existing validation logic from helpers.
    """
    logger.info(
        "Validating graph",
        extra={
            "user_id": str(state.user_id),
            "fix_iteration": state.fix_iteration_count,
        },
    )

    # If build failed, skip validation
    if state.llm_build_failed:
        return {
            "validation_performed": True,
            "final_status": "has_errors",
        }

    try:
        # Reconstruct DTGraph from dict
        dt_graph = DTGraph(**state.generated_graph)

        # Validate: structural tier-2 + generation branching quality gates
        collect_only_ids = parse_collect_only_question_ids(state.questionnaire_design_edited)

        allowed_ids = state.allowed_conclusion_ids
        parse_ok = state.allowed_conclusions_parse_ok
        if not allowed_ids and state.possible_conclusions_edited:
            parsed = parse_allowed_conclusions(state.possible_conclusions_edited)
            allowed_ids = list(parsed.ids)
            parse_ok = parsed.parse_ok

        allowed_frozen = frozenset(allowed_ids) if allowed_ids else None

        validation_result = validate_graph_for_generation(
            dt_graph,
            collect_only_question_ids=collect_only_ids,
            allowed_conclusion_ids=allowed_frozen,
            allowed_conclusions_parse_ok=parse_ok,
        )
        errors = validation_result["errors"]
        warnings = validation_result["warnings"]

        branching_assessment = assess_branching_quality(
            dt_graph,
            collect_only_question_ids=collect_only_ids,
            allowed_conclusion_ids=allowed_frozen,
            allowed_conclusions_parse_ok=parse_ok,
        )

        # Determine final status
        if errors:
            final_status = "has_errors"
        elif warnings:
            final_status = "valid_with_warnings"
        else:
            final_status = "valid"

        logger.info(
            "Validation completed",
            extra={
                "user_id": str(state.user_id),
                "final_status": final_status,
                "error_count": len(errors),
                "warning_count": len(warnings),
                "branching_metrics": (
                    branching_assessment.metrics.to_dict() if branching_assessment else None
                ),
            },
        )

        result: dict[str, Any] = {
            "validation_errors": errors,
            "validation_warnings": warnings,
            "final_status": final_status,
            "validation_performed": True,
        }
        if branching_assessment:
            result["branching_diagnostics"] = [
                d.to_dict() for d in branching_assessment.diagnostics
            ]
            result["branching_metrics"] = branching_assessment.metrics.to_dict()
        return result

    except ValidationError as e:
        logger.error(
            "Graph validation failed (invalid structure)",
            extra={
                "user_id": str(state.user_id),
                "error": str(e),
            },
            exc_info=True,
        )

        return {
            "validation_errors": [f"Invalid graph structure: {str(e)}"],
            "validation_warnings": [],
            "final_status": "has_errors",
            "validation_performed": True,
        }


async def auto_fix_node(
    state: BuildSubgraphState,
    config,
) -> dict[str, Any]:
    """Attempt to auto-fix validation errors.

    Uses existing auto_fix logic.
    """
    logger.info(
        "Attempting auto-fix",
        extra={
            "user_id": str(state.user_id),
            "error_count": len(state.validation_errors),
            "iteration": state.fix_iteration_count + 1,
        },
    )

    try:
        # Reconstruct DTGraph from dict
        dt_graph = DTGraph(**state.generated_graph)

        # Apply auto-fix (structural errors only; branching quality is not auto-fixable)
        fixed_graph, _, _, fixes_applied = auto_fix_graph(
            dt_graph,
            state.validation_errors,
            state.validation_warnings or [],
        )

        new_iteration_count = state.fix_iteration_count + 1

        if fixes_applied:
            logger.info(
                "Auto-fix applied fixes",
                extra={
                    "user_id": str(state.user_id),
                    "fixes_count": len(fixes_applied),
                    "iteration": new_iteration_count,
                },
            )

            return {
                "generated_graph": fixed_graph.model_dump(),
                "fix_source": "auto_fixed",
                "fix_iteration_count": new_iteration_count,
                "fixes_applied": state.fixes_applied + fixes_applied,
                "auto_fix_attempted": True,
            }
        logger.warning(
            "Auto-fix could not fix errors",
            extra={
                "user_id": str(state.user_id),
                "iteration": new_iteration_count,
            },
        )

        return {
            "fix_source": "fix_failed",
            "fix_iteration_count": new_iteration_count,
            "auto_fix_attempted": True,
        }

    except Exception as e:
        logger.error(
            "Auto-fix failed",
            extra={
                "user_id": str(state.user_id),
                "error": str(e),
            },
            exc_info=True,
        )

        return {
            "fix_source": "fix_failed",
            "fix_iteration_count": state.fix_iteration_count + 1,
            "auto_fix_attempted": True,
        }


# ============================================================================
# Routing Functions
# ============================================================================


def route_after_validation(state: BuildSubgraphState) -> Literal["auto_fix", "end"]:
    """Route after validation based on errors and iteration count.

    Routes to:
    - auto_fix: If has errors AND iteration < MAX_FIX_ITERATIONS
    - end: If valid OR max iterations reached
    """
    has_errors = bool(state.validation_errors)
    can_retry = state.fix_iteration_count < MAX_FIX_ITERATIONS
    auto_fixable = branching_quality_errors_are_auto_fixable(state.validation_errors or [])

    logger.info(
        "Routing after validation",
        extra={
            "has_errors": has_errors,
            "error_count": len(state.validation_errors),
            "iteration": state.fix_iteration_count,
            "can_retry": can_retry,
            "auto_fixable": auto_fixable,
            "final_status": state.final_status,
        },
    )

    if has_errors and can_retry and auto_fixable:
        logger.info("Routing to auto_fix")
        return "auto_fix"

    logger.info("Routing to end")
    return "end"


# ============================================================================
# Subgraph Builder
# ============================================================================


def create_build_subgraph() -> StateGraph:
    """Create the build subgraph with internal validation loop.

    Flow:
        START → build_graph → validate → [route]
                                           ├─ auto_fix → validate → [route]
                                           └─ END (if valid or max iterations)

    Internal loop (up to 3 iterations) before returning to parent.

    Returns:
        StateGraph ready to compile
    """
    workflow = StateGraph(BuildSubgraphState)

    # Add nodes
    workflow.add_node("build_graph", build_graph_node)
    workflow.add_node("validate", validate_graph_node)
    workflow.add_node("auto_fix", auto_fix_node)

    # Define edges
    workflow.add_edge(START, "build_graph")
    workflow.add_edge("build_graph", "validate")

    # Conditional routing after validation
    workflow.add_conditional_edges(
        "validate",
        route_after_validation,
        {
            "auto_fix": "auto_fix",
            "end": END,
        },
    )

    # Auto-fix loops back to validation
    workflow.add_edge("auto_fix", "validate")

    return workflow


# ============================================================================
# Integration Helpers
# ============================================================================


def extract_build_input(parent_state: dict) -> BuildSubgraphInput:
    """Extract build input from parent workflow state.

    Args:
        parent_state: Parent workflow state dict

    Returns:
        Validated BuildSubgraphInput

    Raises:
        ValidationError: If required fields missing or invalid
    """
    from smeme.qnr.generation.agentic.conclusions_parse import parse_allowed_conclusions

    conclusions_text = parent_state.get("possible_conclusions_edited") or parent_state.get(
        "possible_conclusions", ""
    )
    allowed_ids = parent_state.get("allowed_conclusion_ids") or []
    parse_ok = parent_state.get("allowed_conclusions_parse_ok", False)
    if not allowed_ids and conclusions_text:
        parsed = parse_allowed_conclusions(conclusions_text)
        allowed_ids = list(parsed.ids)
        parse_ok = parsed.parse_ok

    return BuildSubgraphInput(
        user_prompt=parent_state["user_prompt"],
        user_id=parent_state["user_id"],
        questionnaire_design_edited=parent_state.get("questionnaire_design_edited")
        or parent_state.get("questionnaire_design", ""),
        possible_conclusions_edited=conclusions_text,
        allowed_conclusion_ids=allowed_ids,
        allowed_conclusions_parse_ok=parse_ok,
    )


def merge_build_output(
    parent_state: dict,
    build_output: BuildSubgraphOutput,
) -> dict:
    """Merge build subgraph output back into parent state.

    Args:
        parent_state: Parent workflow state dict
        build_output: Validated build subgraph output

    Returns:
        State updates to merge into parent
    """
    return {
        "generated_graph": build_output.generated_graph,
        "build_source": build_output.build_source,
        "build_raw": build_output.build_raw,
        "build_token_usage": build_output.build_token_usage,
        "validation_errors": build_output.validation_errors,
        "validation_warnings": build_output.validation_warnings,
        "fix_source": build_output.fix_source,
        "fix_iteration_count": build_output.fix_iteration_count,
        "fixes_applied": build_output.fixes_applied,
        "final_status": build_output.final_status,
        "auto_fix_applied": bool(build_output.fixes_applied),  # For backward compat
        "branching_diagnostics": build_output.branching_diagnostics,
        "branching_metrics": build_output.branching_metrics,
    }
