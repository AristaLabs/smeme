"""State models for agentic decision-tree generation workflow.

TypedDict state for LangGraph workflows following project patterns
from LANGGRAPH_INTEGRATION_GUIDE.md.

CRITICAL: TypedDict is a SILENT DATA FILTER - any field not declared
here will be dropped between nodes. Always add fields before using them!
"""

from operator import add
from typing import Annotated, Literal, NotRequired, TypedDict

# ============================================================================
# Phase Tracking Types
# ============================================================================

QNRGenerationPhase = Literal[
    "research",  # Phase 1: Research + factor analysis + augmentation
    "conclusions",  # Phase 1.5: Conclusion extraction
    "design",  # Phase 2: Questionnaire design
    "build",  # Phase 3: Graph building + validation + auto-fix
    "complete",  # Phase 4: Successfully saved
    "error",  # Terminal error state
]


class AugmentationRecord(TypedDict):
    """Record of a single augmentation operation."""

    augmentation_number: int
    prompt: str
    include_domains: list[str]
    exclude_domains: list[str]
    result_count: int
    factors_added: bool  # True if new factors were extracted, False if only confirmed existing
    timestamp: str  # ISO format timestamp


class AgenticQNRGenerationState(TypedDict, total=False):
    """
    LangGraph workflow state for agentic decision-tree generation.

    Following project patterns (per LANGGRAPH_INTEGRATION_GUIDE.md):
    - All fields must be serializable (no AsyncSession, no complex objects)
    - UUIDs stored as strings in state, actual UUIDs in config
    - Use NotRequired[] for optional fields
    - TypedDict is a SILENT DATA FILTER - any field not declared is dropped!

    Nodes return ONLY delta updates - no need to repeat unchanged fields.

    3-phase flow with separate conclusion extraction:
    - Phase 1: Search + factor analysis → user edits factors
    - Phase 1.5: Extract conclusions from factors → user edits conclusions
    - Phase 2: Design questionnaire from factors + conclusions → user edits → build
    """

    # === Input (from generate dialogue / brief form) ===
    title: NotRequired[str]  # User-provided QNR name (required from brief; used at save)
    user_prompt: Annotated[str, lambda x, y: x or y]  # Goal from brief; drives research
    user_id: Annotated[str, lambda x, y: x or y]
    country: NotRequired[str]  # ISO country code for Tavily (e.g., "us", "gb")
    # Pasted text from brief (concatenated into research; no local_sources yet in Phase A)
    research_corpus: NotRequired[str]  # Optional pasted/text corpus merged with Tavily results

    # === Research Parameters ===
    include_domains: NotRequired[list[str]]  # Initial URLs for Extract API (user-provided)
    exclude_domains: NotRequired[list[str]]  # Domains to exclude from search
    skip_web_search: NotRequired[bool]  # Use only uploaded files + pasted text; no Tavily

    # === Phase 1: Research (factors only) ===
    research_raw: NotRequired[dict]  # Tavily search result (JSON)
    research_context: NotRequired[str]  # Factor analysis (LLM output)
    research_context_edited: NotRequired[str]  # User-edited factors
    extraction_used: NotRequired[bool]  # True if initial research used Extract API

    # === Augmentation Control ===
    user_action: NotRequired[str]  # "continue" | "augment" (from research edit interrupt)
    augment_prompt: NotRequired[str]  # Search query for this augmentation
    augment_include_domains: NotRequired[list[str]]  # Domains to prioritize for augmentation
    augment_exclude_domains: NotRequired[list[str]]  # Domains to exclude for augmentation
    augmentation_count: NotRequired[int]  # Number of augmentations performed (max 5)
    augmentation_history: Annotated[NotRequired[list[AugmentationRecord]], add]

    # === Phase 1.5: Conclusions (separate step) ===
    user_conclusions: NotRequired[str]  # User-provided conclusions at start (optional)
    possible_conclusions: NotRequired[str]  # LLM-generated or formatted conclusions (markdown)
    possible_conclusions_edited: NotRequired[str]  # User-edited conclusions (markdown)
    conclusions_source: NotRequired[str]  # Track source: "user_provided" or "llm_extracted"
    allowed_conclusion_ids: NotRequired[list[str]]  # Parsed CONCLUSION_N allowlist
    allowed_conclusions_parse_ok: NotRequired[bool]  # False when parser found no IDs

    # === Phase 2: Design ===
    questionnaire_design: NotRequired[str]  # LLM-generated design (markdown)
    questionnaire_design_edited: NotRequired[str]  # Author-edited markdown
    design_source: NotRequired[str]  # Track source: "llm_generated" or "llm_failed"
    design_raw: NotRequired[dict]  # Raw LLM response for debugging
    design_token_usage: NotRequired[dict]  # Token usage stats (prompt/completion/total)

    # === Phase 3: Build + Validate + Fix (Subgraph) ===
    generated_graph: NotRequired[dict]  # DTGraph as dict (Pydantic model_dump)
    build_source: NotRequired[str]  # Track source: "llm_generated" or "llm_failed"
    build_raw: NotRequired[dict]  # Full build response for debugging
    build_token_usage: NotRequired[dict]  # Token stats for build call
    validation_errors: NotRequired[list[str]]  # Blocking validation errors
    validation_warnings: NotRequired[list[str]]  # Non-blocking warnings
    branching_diagnostics: NotRequired[list[dict]]  # Structured branching quality findings
    branching_metrics: NotRequired[dict]  # BranchingQuality metrics snapshot
    fix_source: NotRequired[str]  # "auto_fixed" | "fix_failed" | "no_fix_needed"
    fix_iteration_count: NotRequired[int]  # Number of auto-fix iterations (0-3)
    fixes_applied: NotRequired[list[str]]  # List of fixes applied (for UI display)
    auto_fix_applied: NotRequired[bool]  # True if auto-fix was attempted (backward compat)

    # === Output ===
    qnr_id: NotRequired[str]  # UUID as string (saved QNR)
    final_status: NotRequired[Literal["valid", "valid_with_warnings", "has_errors"]]
    remaining_issues: NotRequired[list[str]]  # Shown to user if has_errors

    # === Error Handling & Degradation ===
    error: NotRequired[str]  # Fatal error message (stops flow, shows error page)
    error_recoverable: NotRequired[bool]  # True = show retry button
    search_skipped: NotRequired[bool]  # True = Tavily failed, using LLM only
    search_skip_reason: NotRequired[str]  # User-facing explanation
    research_degraded: NotRequired[bool]  # True = research from LLM only (no Tavily)
    research_failure_source: NotRequired[str]  # openai | tavily | config (degraded research)
    openai_failure_kind: NotRequired[str]  # quota | rate_limit | timeout | other

    # === UI Rendering ===
    rendered_html: NotRequired[str]  # HTML fragment to return to HTMX

    # === Phase Tracking (Sprint 6) ===
    current_phase: NotRequired[QNRGenerationPhase]  # Explicit current phase (no inference needed)
    phase_start_time: NotRequired[
        float
    ]  # Timestamp when current phase started (for duration tracking)
    phase_history: Annotated[NotRequired[list[dict]], add]  # Full audit trail of phase transitions


# Type alias for node return values (partial state updates)
AgenticNodeResult = dict
