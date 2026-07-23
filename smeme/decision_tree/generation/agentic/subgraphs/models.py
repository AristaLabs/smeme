"""Pydantic models for subgraph state contracts.

Use Pydantic BaseModel (not SQLModel or TypedDict) to:
- Enable runtime validation at subgraph boundaries
- Prevent silent type mismatches
- Avoid SQLAlchemy field definition conflicts (Sprint 1 Lesson)
"""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ============================================================================
# Interrupt Payload (Sprint 6: Standardized Interrupts)
# ============================================================================


class InterruptPayload(BaseModel):
    """Standardized interrupt payload for all human-in-the-loop waits.

    Benefits:
    - Makes routing logic resilient (no ad-hoc dict parsing)
    - Enables validation at interrupt boundaries
    - Clear contract for what data is available at each wait
    - Better type hints for route functions
    """

    phase: Literal["research", "conclusions", "design", "build"] = Field(
        ...,
        description="Which phase is interrupting (for routing verification)",
    )
    user_id: str = Field(
        ...,
        description="User who owns this generation (for authorization checks)",
    )
    action_required: str = Field(
        ...,
        description="What user needs to do (e.g., 'Edit research factors', 'Review design')",
    )
    data_to_edit: dict[str, Any] = Field(
        default_factory=dict,
        description="Phase-specific data user can edit (e.g., research_context, design)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context (e.g., augmentation_count, token_usage)",
    )


# ============================================================================
# Research Subgraph Models
# ============================================================================


class ResearchSubgraphInput(BaseModel):
    """Input contract for research subgraph.

    These fields are extracted from parent state and passed to the subgraph.
    """

    user_prompt: str = Field(
        ...,
        description="User's research request",
        max_length=2000,
    )
    user_id: UUID = Field(
        ...,
        description="User who initiated the generation",
    )
    research_corpus: str | None = Field(
        default=None,
        description="Optional pasted text / local corpus to merge with web search results",
    )
    country: str | None = Field(
        default=None,
        description="Optional country code for localized results",
    )
    include_domains: list[str] | None = Field(
        default=None,
        description="Optional trusted domains to prioritize",
    )
    exclude_domains: list[str] = Field(
        default_factory=list,
        description="Domains to exclude from search",
    )
    skip_web_search: bool = Field(
        default=False,
        description="Use only uploaded files and pasted text; skip Tavily web search",
    )
    augmentation_count: int = Field(
        default=0,
        ge=0,
        le=5,
        description="Number of augmentations already performed",
    )
    # Augmentation parameters (present when looping back for additional search)
    research_context: str = Field(
        default="",
        description="Existing research context from previous search (for augmentation)",
    )
    augment_prompt: str | None = Field(
        default=None,
        description="Additional search query for augmentation",
    )
    augment_include_domains: list[str] | None = Field(
        default=None,
        description="Domains to include in augmentation search",
    )
    augment_exclude_domains: list[str] | None = Field(
        default=None,
        description="Domains to exclude in augmentation search",
    )


class ResearchSubgraphOutput(BaseModel):
    """Output contract for research subgraph.

    These fields are returned to parent state after research completes.
    """

    research_context: str = Field(
        ...,
        description="Extracted and summarized research content",
    )
    research_raw: dict[str, Any] | None = Field(
        default=None,
        description="Raw search results for debugging (dict from Tavily API)",
    )
    search_skipped: bool = Field(
        default=False,
        description="Whether web search was skipped",
    )
    search_skip_reason: str | None = Field(
        default=None,
        description="Reason for skipping search (if applicable)",
    )
    research_degraded: bool = Field(
        default=False,
        description="Whether research ran in degraded mode",
    )
    extraction_used: bool = Field(
        default=False,
        description="Whether URL extraction was used instead of search",
    )
    augmentation_count: int = Field(
        default=0,
        description="Final augmentation count after this run",
    )
    research_failure_source: str | None = Field(
        default=None,
        description="Who caused degraded research: openai, tavily, config, etc.",
    )
    openai_failure_kind: str | None = Field(
        default=None,
        description="OpenAI error class when research_failure_source is openai",
    )


class ResearchSubgraphState(BaseModel):
    """Internal state for research subgraph.

    Combines input + output + intermediate state needed during execution.
    """

    # Input fields (from parent)
    user_prompt: str
    user_id: UUID
    research_corpus: str | None = None
    country: str | None = None
    include_domains: list[str] | None = None
    exclude_domains: list[str] = Field(default_factory=list)
    skip_web_search: bool = False
    augmentation_count: int = 0

    # Output fields (to parent)
    research_context: str = ""
    research_raw: dict[str, Any] | None = None
    search_skipped: bool = False
    search_skip_reason: str | None = None
    research_degraded: bool = False
    extraction_used: bool = False
    research_failure_source: str | None = None
    openai_failure_kind: str | None = None

    # Internal fields (not passed to parent)
    user_action: str | None = None  # User's action: "continue" or "augment"
    augment_prompt: str | None = None  # For augmentation requests
    augment_include_domains: list[str] | None = None
    augment_exclude_domains: list[str] | None = None


# ============================================================================
# Conclusions Subgraph Models
# ============================================================================


class ConclusionsSubgraphInput(BaseModel):
    """Input contract for conclusions subgraph.

    Hybrid Path Support:
    - If user_conclusions provided → use directly (skip LLM)
    - If user_conclusions empty → extract from research_context via LLM
    """

    user_prompt: str = Field(
        ...,
        description="Original user query for context",
    )
    user_id: UUID = Field(
        ...,
        description="User who initiated the generation",
    )
    research_context: str = Field(
        ...,
        description="Research factors extracted in previous phase",
    )
    user_conclusions: str | None = Field(
        default=None,
        description="User-provided conclusions (optional, skips LLM if present)",
    )


class ConclusionsSubgraphOutput(BaseModel):
    """Output contract for conclusions subgraph.

    Always includes conclusions_source to track provenance.
    """

    possible_conclusions: str = Field(
        ...,
        description="Final conclusions (user-provided OR LLM-extracted)",
    )
    conclusions_source: str = Field(
        ...,
        description="Source of conclusions: 'user_provided', 'llm_extracted', or 'llm_failed'",
    )
    conclusions_raw: dict[str, Any] | None = Field(
        default=None,
        description="Raw LLM response for debugging (only if extracted)",
    )


class ConclusionsSubgraphState(BaseModel):
    """Internal state for conclusions subgraph.

    Combines input + output + intermediate state.
    """

    # Input fields (from parent)
    user_prompt: str
    user_id: UUID
    research_context: str
    user_conclusions: str | None = None

    # Output fields (to parent)
    possible_conclusions: str = ""
    conclusions_source: str = ""
    conclusions_raw: dict[str, Any] | None = None

    # Internal fields
    llm_extraction_attempted: bool = False
    llm_extraction_failed: bool = False


# ============================================================================
# Design Subgraph Models
# ============================================================================


class DesignSubgraphInput(BaseModel):
    """Input contract for design subgraph.

    Single-path (no hybrid): Always generates design via LLM.
    """

    user_prompt: str = Field(
        ...,
        description="Original user query for context",
    )
    user_id: UUID = Field(
        ...,
        description="User who initiated the generation",
    )
    research_context_edited: str = Field(
        ...,
        description="User-reviewed research factors from research phase",
    )
    possible_conclusions_edited: str = Field(
        ...,
        description="User-reviewed conclusions from conclusions phase",
    )


class DesignSubgraphOutput(BaseModel):
    """Output contract for design subgraph.

    Includes source tracking and raw response for debugging.
    """

    decision_tree_design: str = Field(
        ...,
        description="Generated questionnaire in markdown format",
    )
    design_source: str = Field(
        ...,
        description="Source: 'llm_generated' or 'llm_failed'",
    )
    design_raw: dict[str, Any] | None = Field(
        default=None,
        description="Raw LLM response for debugging",
    )
    token_usage: dict[str, int] | None = Field(
        default=None,
        description="Token usage stats for optimization tracking",
    )
    allowed_conclusion_ids: list[str] = Field(
        default_factory=list,
        description="Parsed CONCLUSION_N IDs from approved conclusions",
    )
    allowed_conclusions_parse_ok: bool = Field(
        default=False,
        description="Whether CONCLUSION_N blocks were parsed successfully",
    )


class DesignSubgraphState(BaseModel):
    """Internal state for design subgraph.

    Combines input + output + intermediate state.
    """

    # Input fields (from parent)
    user_prompt: str
    user_id: UUID
    research_context_edited: str
    possible_conclusions_edited: str

    # Output fields (to parent)
    decision_tree_design: str = ""
    design_source: str = ""
    design_raw: dict[str, Any] | None = None
    token_usage: dict[str, int] | None = None
    allowed_conclusion_ids: list[str] = Field(default_factory=list)
    allowed_conclusions_parse_ok: bool = False

    # Internal fields
    llm_generation_attempted: bool = False
    llm_generation_failed: bool = False
    optimization_applied: bool = False  # Track if we optimized input


# ============================================================================
# Build Subgraph Models
# ============================================================================


class BuildSubgraphInput(BaseModel):
    """Input contract for build subgraph.

    Single-path: Always builds via LLM (no hybrid user-provided graph).
    """

    user_prompt: str = Field(
        ...,
        description="Original user query for context",
    )
    user_id: UUID = Field(
        ...,
        description="User who initiated the generation",
    )
    decision_tree_design_edited: str = Field(
        ...,
        description="User-reviewed questionnaire design in markdown",
    )
    possible_conclusions_edited: str = Field(
        default="",
        description="Approved conclusions markdown for allowlist validation",
    )
    allowed_conclusion_ids: list[str] = Field(
        default_factory=list,
        description="Parsed CONCLUSION_N IDs when available from design phase",
    )
    allowed_conclusions_parse_ok: bool = Field(
        default=False,
        description="Whether CONCLUSION_N blocks were parsed successfully",
    )


class BuildSubgraphOutput(BaseModel):
    """Output contract for build subgraph.

    Includes validation results and fix tracking.
    """

    generated_graph: dict[str, Any] = Field(
        ...,
        description="Generated DTGraph as dict (may be invalid if fixes failed)",
    )
    build_source: str = Field(
        ...,
        description="Source: 'llm_generated' or 'llm_failed'",
    )
    build_raw: dict[str, Any] | None = Field(
        default=None,
        description="Raw LLM response for debugging",
    )
    build_token_usage: dict[str, int] | None = Field(
        default=None,
        description="Token usage stats for build LLM call",
    )
    validation_errors: list[str] = Field(
        default_factory=list,
        description="Blocking validation errors (empty if valid)",
    )
    validation_warnings: list[str] = Field(
        default_factory=list,
        description="Non-blocking warnings",
    )
    fix_source: str = Field(
        default="no_fix_needed",
        description="'auto_fixed', 'fix_failed', or 'no_fix_needed'",
    )
    fix_iteration_count: int = Field(
        default=0,
        ge=0,
        le=3,
        description="Number of auto-fix iterations performed (0-3)",
    )
    fixes_applied: list[str] = Field(
        default_factory=list,
        description="Descriptions of fixes applied",
    )
    final_status: str = Field(
        ...,
        description="'valid', 'valid_with_warnings', or 'has_errors'",
    )
    branching_diagnostics: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured branching quality findings",
    )
    branching_metrics: dict[str, Any] | None = Field(
        default=None,
        description="Branching quality metrics snapshot",
    )


class BuildSubgraphState(BaseModel):
    """Internal state for build subgraph.

    Combines input + output + intermediate state for loop.
    """

    # Input fields (from parent)
    user_prompt: str
    user_id: UUID
    decision_tree_design_edited: str
    possible_conclusions_edited: str = ""
    allowed_conclusion_ids: list[str] = Field(default_factory=list)
    allowed_conclusions_parse_ok: bool = False

    # Output fields (to parent)
    generated_graph: dict[str, Any] = {}
    build_source: str = ""
    build_raw: dict[str, Any] | None = None
    build_token_usage: dict[str, int] | None = None
    validation_errors: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    fix_source: str = "no_fix_needed"
    fix_iteration_count: int = 0
    fixes_applied: list[str] = Field(default_factory=list)
    final_status: str = ""

    # Internal fields (loop control)
    llm_build_attempted: bool = False
    llm_build_failed: bool = False
    optimization_applied: bool = False
    validation_performed: bool = False
    auto_fix_attempted: bool = False


# ============================================================================
# Validation Helpers
# ============================================================================


def validate_tavily_prompt(prompt: str) -> tuple[bool, str | None]:
    """Validate prompt meets Tavily API requirements.

    Args:
        prompt: User's search prompt

    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(prompt) > 400:
        return (
            False,
            f"Search prompt too long ({len(prompt)} chars). Tavily API limit is 400 characters.",
        )

    if len(prompt.strip()) < 10:
        return (
            False,
            "Search prompt too short. Please provide at least 10 characters.",
        )

    return (True, None)
