"""Agentic QNR generation workflow.

This module implements a web-search-augmented QNR generation workflow
using Tavily for research and GPT-5.1/GPT-5-mini for design and building.

Flow:
    Phase 1: Relevant Factors Research
        - Tavily search for key factors
        - Small LLM analysis
        - Author review/edit

    Phase 2: Decision Patterns & Freeform Design
        - Tavily search for decision patterns
        - Large LLM freeform questionnaire design
        - Author review/edit

    Phase 3: Build + Deterministic Fix
        - Build QNRGraph from edited markdown
        - Validate and auto-fix structural issues
        - Save to database
"""

from smeme.qnr.generation.agentic.models import AgenticQNRGenerationState
from smeme.qnr.generation.agentic.routes import router
from smeme.qnr.generation.agentic.workflow import build_agentic_generation_workflow

__all__ = [
    "AgenticQNRGenerationState",
    "build_agentic_generation_workflow",
    "router",
]
