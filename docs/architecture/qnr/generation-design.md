# QNR Generation Design Decisions

!!! warning "Historical Document"
    This document describes the **simple/prototype QNR generation workflow** which is **no longer actively maintained**. 
    
    **For the production system**, see: **[Agentic Generation](agentic-generation.md)** ⭐
    
    This document is preserved for historical context and to document the design decisions that led to our current architecture (OpenAI SDK + LangGraph).

## Overview

This document analyzes the design choices for implementing a LangGraph workflow to generate QNRs (Questionnaires) from natural language prompts using LLMs.

**Note**: The workflow described here is the **simple 4-node workflow** (prototype). The production system uses a more sophisticated **agentic workflow** with web research and human-in-the-loop editing.

## Goal

Generate a complete `QNRGraph` from a user prompt like:
> "Create a questionnaire to help developers choose the right Python web framework"

Expected output:
- Structured nodes (start, questions, end)
- Conditional edges based on answers
- Question metadata (type, options, help text)
- QNR metadata (title, description, tags)

---


## Decision: OpenAI SDK + LangGraph Validation Workflow

### Why This Approach

1. **Minimal Dependencies**
   - Only add `openai` SDK - no additional frameworks
   - LangGraph handles all orchestration (already in our stack)
   - Keeps complexity low, maintenance burden minimal

2. **LangGraph Does What It's Best At**
   - **Workflow orchestration**: Sequential and conditional node execution
   - **Validation retry logic**: Conditional edges for intelligent retry
   - **State management**: Track validation attempts, errors, feedback
   - **Observability**: LangSmith traces show every retry attempt

3. **Separation of Concerns**
   - **OpenAI SDK**: LLM interaction only
   - **LangGraph nodes**: Validation logic
   - **Pydantic models**: Data structure and basic validation
   - **Custom code**: Graph-specific business rules

4. **Flexibility and Control**
   - Full control over retry logic and conditions
   - Custom validation at each stage
   - Easy to add new validation nodes
   - Clear visibility into the workflow

### Implementation Architecture with OpenAI SDK + LangGraph

```
User Prompt
    ↓
LangGraph Workflow (smeme/qnr/generation/workflow.py)
    ↓
┌─────────────────────────────────────────┐
│ Node 1: Enhance Prompt                  │
│ - Validate user input                   │
│ - Add domain context                    │
│ - Format for LLM                        │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ Node 2: Call OpenAI (Structured Output) │
│ - Use response_format with Pydantic     │
│ - Get JSON matching QNRGraph schema     │
│ - Parse to QNRGraph model               │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ Node 3: Validate Pydantic Schema        │
│ - Check all required fields present     │
│ - Validate field types                  │
│ - Run Pydantic validators               │
│ - Store errors if any                   │
└─────────────────────────────────────────┘
    ↓
    Decision: Valid schema?
    ├─ No ──→ (retry < 3?) ──→ Back to Node 2 with errors
    │
    ↓ Yes
┌─────────────────────────────────────────┐
│ Node 4: Validate Graph Logic            │
│ - Check graph connectivity              │
│ - Validate conditional edges            │
│ - Verify start/end nodes                │
│ - Check reachability                    │
└─────────────────────────────────────────┘
    ↓
    Decision: Valid graph?
    ├─ No ──→ (retry < 2?) ──→ Back to Node 2 with feedback
    │
    ↓ Yes
┌─────────────────────────────────────────┐
│ Node 5: Save to Database                │
│ - Create QNR record                     │
│ - Store graph_data (JSONB)              │
│ - Set status to 'draft'                 │
└─────────────────────────────────────────┘
    ↓
QNR Ready for Review/Publish
```

### Code Structure

```
smeme/
├── core/
│   └── llm.py               # OpenAI client singleton (dependency injection)
├── qnr/
    ├── generation/
    │   ├── __init__.py
    │   ├── workflow.py      # LangGraph workflow with validation nodes
    │   ├── llm_client.py    # OpenAI client wrapper functions
    │   ├── prompts.py       # System prompts for LLM
    │   ├── validation.py    # Graph logic validation functions
    │   └── routes.py        # API routes for generation
    ├── helpers/
    │   └── graph_utils.py   # Graph manipulation utilities
```

### Detailed Implementation

#### 1. OpenAI Client Setup

**A. Singleton Client with `@lru_cache` (`smeme/core/llm.py`)**

```python
"""OpenAI client configuration."""

from functools import lru_cache
from openai import AsyncOpenAI
from smeme.core.config import settings


@lru_cache(maxsize=1)
def get_openai_client() -> AsyncOpenAI:
    """
    Get OpenAI client (cached singleton).
    
    Why singleton?
    - OpenAI client is thread-safe and can be reused
    - Connection pooling built into httpx (underlying library)
    - Creating per-request is wasteful
    
    Why lru_cache?
    - FastAPI best practice for singleton dependencies
    - Can be overridden in tests via app.dependency_overrides
    - Only creates one instance across entire application
    
    Official guidance:
    - FastAPI: Use @lru_cache for singleton dependencies
    - OpenAI SDK: Client is thread-safe, reuse across requests
    - LangGraph: Pass runtime dependencies via config["configurable"]
    """
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=30.0,
        max_retries=3,
    )
```

**B. LLM Client Wrapper (`smeme/qnr/generation/llm_client.py`)**

```python
"""OpenAI client wrapper for QNR generation."""

from openai import AsyncOpenAI
from smeme.qnr.models import QNRGraph


async def generate_qnr_with_llm(
    client: AsyncOpenAI,  # Passed from node via config
    system_prompt: str,
    user_prompt: str,
    validation_feedback: str | None = None,
    model: str = "gpt-4o",  # Configurable at call time
    temperature: float = 0.7,
) -> dict:
    """
    Call OpenAI to generate QNR graph structure.
    
    Args:
        client: AsyncOpenAI client instance (injected)
        system_prompt: Instructions for the LLM
        user_prompt: User's description of desired questionnaire
        validation_feedback: Previous validation errors (for retry)
        model: Model to use (default: gpt-4o, can escalate/downgrade)
        temperature: Sampling temperature (0-2, higher = more creative)
    
    Returns:
        Parsed QNRGraph from OpenAI
    
    Raises:
        OpenAIError: If API call fails
    
    Design Note:
        Nodes can override model/temperature based on runtime context:
        - Use gpt-4o-mini for initial attempts (cheaper)
        - Escalate to gpt-4o on retries (better quality)
        - Adjust temperature based on complexity
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    # Add validation feedback for retry attempts
    if validation_feedback:
        messages.append({
            "role": "user",
            "content": f"Previous attempt had these errors:\n{validation_feedback}\n\nPlease fix these issues."
        })
    
    # Use structured outputs with Pydantic schema
    response = await client.beta.chat.completions.parse(
        model=model,  # Runtime configurable
        temperature=temperature,
        messages=messages,
        response_format=QNRGraph,
    )
    
    return response.choices[0].message.parsed
```

#### 2. System Prompt (`smeme/qnr/generation/generation_prompts.py`)

```python
"""System prompts for QNR generation."""

SYSTEM_PROMPT = """You are an expert questionnaire designer. Your task is to create 
well-structured, logical questionnaires based on user descriptions.

## Questionnaire Structure Requirements:

1. **Nodes:**
   - ALWAYS start with a "start" node (type: "start", id: "start")
   - Include question nodes (type: "question", unique ids like "q1", "q2")
   - ALWAYS end with an "end" node (type: "end", id: "end")

2. **Questions:**
   - Use appropriate question types: "text", "number", "radio", "checkbox"
   - For radio/checkbox: MUST provide options list
   - Set required=true for critical questions
   - Include helpful help_text to guide users

3. **Edges:**
   - Connect start → first question → ... → end
   - Use conditional edges for branching logic based on answers
   - Example: If user selects "Python", go to Python-specific questions
   - Conditional edges have "condition" field matching expected answer

4. **Metadata:**
   - Provide clear title and description
   - Set appropriate category
   - Estimate completion time in minutes
   - Add relevant tags for searchability

## Graph Design Best Practices:

- Keep questionnaires focused (5-15 questions ideal)
- Use conditional logic to reduce irrelevant questions
- Group related questions together
- Ensure all paths eventually reach the end node
- Make required questions truly necessary

## Example Question Types:

```
Text: "What programming languages do you use?" (type: "text")
Radio: "What's your primary framework?" (type: "radio", options: ["Django", "Flask", "FastAPI"])
Number: "Years of experience?" (type: "number")
Checkbox: "Which features do you need?" (type: "checkbox", options: [...])
```

Generate a complete, valid QNRGraph structure based on the user's request.
"""


ENHANCEMENT_PROMPT = """Enhance this user prompt with domain-specific context:

Original: {prompt}

Add:
1. Clarify the target audience
2. Suggest appropriate question types
3. Identify potential branching logic
4. Recommend metadata (category, tags)

Enhanced prompt:"""
```

#### 3. LangGraph Workflow with Validation Retry (`smeme/qnr/generation/workflow.py`)

```python
"""LangGraph workflow for QNR generation with validation retry."""

from datetime import UTC, datetime
from typing import TypedDict, Literal
from uuid import UUID

from langgraph.graph import StateGraph, END
from langgraph.types import RunnableConfig
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import ValidationError

from smeme.core.models import QNR
from smeme.qnr.models import QNRGraph
from smeme.qnr.generation.llm_client import generate_qnr_with_llm
from smeme.qnr.generation.generation_prompts import GENERATE_QUESTIONNAIRE_PROMPT
from smeme.qnr.generation.validation import validate_graph_logic


class GenerationState(TypedDict, total=False):
    """State for QNR generation workflow."""
    
    # Input
    user_prompt: str
    user_id: int
    
    # Processing
    enhanced_prompt: str
    llm_response: dict | None
    generated_graph: QNRGraph | None
    pydantic_errors: list[str]
    graph_errors: list[str]
    retry_count: int
    validation_retry_count: int
    
    # Output
    qnr_id: UUID
    error: str | None


async def enhance_prompt_node(
    state: GenerationState,
    config: RunnableConfig
) -> GenerationState:
    """Enhance user prompt with domain context."""
    return {
        "enhanced_prompt": state["user_prompt"],
        "retry_count": 0,
        "validation_retry_count": 0
    }


async def call_llm_node(
    state: GenerationState,
    config: RunnableConfig
) -> GenerationState:
    """
    Call OpenAI to generate QNR structure.
    
    Uses smart model selection:
    - First attempt: gpt-4o-mini (cheaper, faster)
    - Retry 1: gpt-4o (better quality)
    - Retry 2+: gpt-4o with higher temperature (more creative)
    """
    import logging
    import time
    
    logger = logging.getLogger("smeme.qnr.generation.workflow")
    start_time = time.time()
    
    try:
        # Extract dependencies from config
        openai_client: AsyncOpenAI = config["configurable"]["openai_client"]
        user_id: int = config["configurable"]["user_id"]
        
        # Build validation feedback if this is a retry
        feedback = None
        if state.get("pydantic_errors"):
            feedback = "Pydantic validation errors:\n" + "\n".join(state["pydantic_errors"])
        elif state.get("graph_errors"):
            feedback = "Graph structure errors:\n" + "\n".join(state["graph_errors"])
        
        # Smart model selection based on retry count
        retry_count = state.get("retry_count", 0)
        
        if retry_count >= 2:
            # Multiple retries: use best model with high creativity
            model = "gpt-4o"
            temperature = 0.9
        elif retry_count == 1:
            # First retry: escalate to better model
            model = "gpt-4o"
            temperature = 0.7
        else:
            # Initial attempt: use cheaper model
            model = "gpt-4o-mini"
            temperature = 0.5
        
        # Log LLM call with context
        logger.info(
            "Calling LLM for QNR generation",
            extra={
                "user_id": user_id,
                "node": "call_llm",
                "model": model,
                "temperature": temperature,
                "retry_count": retry_count,
                "has_feedback": feedback is not None,
            },
        )
        
        # Call OpenAI with context-aware parameters
        llm_response = await generate_qnr_with_llm(
            client=openai_client,  # Injected client
            system_prompt=SYSTEM_PROMPT,
            user_prompt=state["enhanced_prompt"],
            validation_feedback=feedback,
            model=model,  # Decided at runtime
            temperature=temperature,
        )
        
        # Log success
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "LLM call completed",
            extra={
                "user_id": user_id,
                "node": "call_llm",
                "model": model,
                "node_count": len(llm_response.nodes),
                "edge_count": len(llm_response.edges),
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )
        
        return {
            "llm_response": llm_response,
            "retry_count": retry_count + 1,  # Increment for next attempt
            "error": None
        }
    
    except Exception as e:
        logger.error(
            "LLM call failed",
            extra={
                "user_id": user_id,
                "node": "call_llm",
                "error": str(e),
                "retry_count": retry_count,
            },
            exc_info=True,
        )
        return {"error": f"LLM call failed: {str(e)}"}


async def validate_pydantic_node(
    state: GenerationState,
    config: RunnableConfig
) -> GenerationState:
    """Validate LLM response against Pydantic schema."""
    import logging
    
    logger = logging.getLogger("smeme.qnr.generation.workflow")
    user_id: int = config["configurable"]["user_id"]
    
    if state.get("error"):
        return state
    
    try:
        # Parse LLM response to QNRGraph model
        qnr_graph = QNRGraph.model_validate(state["llm_response"])
        
        logger.info(
            "Pydantic validation passed",
            extra={
                "user_id": user_id,
                "node": "validate_pydantic",
            },
        )
        
        return {
            "generated_graph": qnr_graph,
            "pydantic_errors": [],
            "error": None
        }
    
    except ValidationError as e:
        errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        
        logger.warning(
            "Pydantic validation failed",
            extra={
                "user_id": user_id,
                "node": "validate_pydantic",
                "error_count": len(errors),
                "errors": errors[:3],  # First 3 errors
            },
        )
        
        return {
            "pydantic_errors": errors,
            "generated_graph": None
        }


async def validate_graph_logic_node(
    state: GenerationState,
    config: RunnableConfig
) -> GenerationState:
    """Validate graph connectivity and business rules."""
    import logging
    
    logger = logging.getLogger("smeme.qnr.generation.workflow")
    user_id: int = config["configurable"]["user_id"]
    
    if state.get("error") or not state.get("generated_graph"):
        return state
    
    errors = validate_graph_logic(state["generated_graph"])
    
    if errors:
        logger.warning(
            "Graph validation failed",
            extra={
                "user_id": user_id,
                "node": "validate_graph_logic",
                "error_count": len(errors),
                "errors": errors[:3],  # First 3 errors
            },
        )
    else:
        logger.info(
            "Graph validation passed",
            extra={
                "user_id": user_id,
                "node": "validate_graph_logic",
            },
        )
    
    return {"graph_errors": errors}


async def save_qnr_node(
    state: GenerationState,
    config: RunnableConfig
) -> GenerationState:
    """Save validated QNR to database."""
    if state.get("error") or not state.get("generated_graph"):
        return state
    
    db: AsyncSession = config["configurable"]["db"]
    user_id: int = config["configurable"]["user_id"]
    
    graph = state["generated_graph"]
    
    qnr = QNR(
        title=graph.metadata.title,
        description=graph.metadata.description,
        author_id=user_id,
        graph_data=graph.model_dump(),
        is_published=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC)
    )
    
    db.add(qnr)
    await db.commit()
    await db.refresh(qnr)
    
    return {
        "qnr_id": qnr.id,
        "error": None
    }


def should_retry_pydantic(state: GenerationState) -> Literal["retry", "continue", "fail"]:
    """Decide whether to retry after Pydantic validation."""
    if state.get("pydantic_errors"):
        retry_count = state.get("retry_count", 0)
        if retry_count < 3:
            return "retry"
        return "fail"
    return "continue"


def should_retry_graph(state: GenerationState) -> Literal["retry", "continue", "fail"]:
    """Decide whether to retry after graph validation."""
    if state.get("graph_errors"):
        retry_count = state.get("validation_retry_count", 0)
        if retry_count < 2:
            return "retry"
        return "fail"
    return "continue"


def build_generation_workflow() -> StateGraph:
    """Build workflow with conditional retry logic."""
    workflow = StateGraph(GenerationState)
    
    # Add nodes
    workflow.add_node("enhance_prompt", enhance_prompt_node)
    workflow.add_node("call_llm", call_llm_node)
    workflow.add_node("validate_pydantic", validate_pydantic_node)
    workflow.add_node("validate_graph", validate_graph_logic_node)
    workflow.add_node("save_qnr", save_qnr_node)
    
    # Linear flow with conditional branches
    workflow.set_entry_point("enhance_prompt")
    workflow.add_edge("enhance_prompt", "call_llm")
    workflow.add_edge("call_llm", "validate_pydantic")
    
    # Conditional: Retry or continue after Pydantic validation
    workflow.add_conditional_edges(
        "validate_pydantic",
        should_retry_pydantic,
        {
            "retry": "call_llm",  # Loop back with feedback
            "continue": "validate_graph",
            "fail": END  # Give up after max retries
        }
    )
    
    # Conditional: Retry or continue after graph validation
    workflow.add_conditional_edges(
        "validate_graph",
        should_retry_graph,
        {
            "retry": "call_llm",  # Loop back with feedback
            "continue": "save_qnr",
            "fail": END  # Give up after max retries
        }
    )
    
    workflow.add_edge("save_qnr", END)
    
    return workflow.compile()
```

#### 4. Graph Validation Functions (`smeme/qnr/generation/validation.py`)

```python
"""Graph logic validation for generated QNRs."""

from smeme.qnr.models import QNRGraph


def validate_graph_logic(graph: QNRGraph) -> list[str]:
    """
    Validate graph structure and logic.
    
    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    
    # Check for start and end nodes
    node_ids = {node.id for node in graph.nodes}
    node_types = {node.id: node.type for node in graph.nodes}
    
    if "start" not in node_ids:
        errors.append("Missing 'start' node")
    
    if "end" not in node_ids:
        errors.append("Missing 'end' node")
    
    # Check start node has type "start"
    if "start" in node_types and node_types["start"] != "start":
        errors.append("Node 'start' must have type 'start'")
    
    # Check end node has type "end"
    if "end" in node_types and node_types["end"] != "end":
        errors.append("Node 'end' must have type 'end'")
    
    # Validate edges reference existing nodes
    for edge in graph.edges:
        if edge.source not in node_ids:
            errors.append(f"Edge references non-existent source node: {edge.source}")
        
        if edge.target not in node_ids:
            errors.append(f"Edge references non-existent target node: {edge.target}")
    
    # Check connectivity: all nodes should be reachable from start
    if not errors:  # Only if basic structure is valid
        reachable = get_reachable_nodes(graph)
        unreachable = node_ids - reachable
        if unreachable:
            errors.append(f"Unreachable nodes: {', '.join(unreachable)}")
    
    # Validate question nodes have question data
    for node in graph.nodes:
        if node.type == "question" and not node.data:
            errors.append(f"Question node '{node.id}' missing question data")
        
        # Validate radio/checkbox have options
        if node.type == "question" and node.data:
            if node.data.type in ["radio", "checkbox"]:
                if not node.data.options or len(node.data.options) == 0:
                    errors.append(
                        f"Question '{node.id}' type '{node.data.type}' must have options"
                    )
    
    return errors


def get_reachable_nodes(graph: QNRGraph) -> set[str]:
    """Get all nodes reachable from start node."""
    # Build adjacency list
    adjacency = {}
    for edge in graph.edges:
        if edge.source not in adjacency:
            adjacency[edge.source] = []
        adjacency[edge.source].append(edge.target)
    
    # BFS from start
    reachable = set()
    queue = ["start"]
    
    while queue:
        current = queue.pop(0)
        if current in reachable:
            continue
        
        reachable.add(current)
        
        for neighbor in adjacency.get(current, []):
            if neighbor not in reachable:
                queue.append(neighbor)
    
    return reachable
```

#### 5. API Routes (`smeme/qnr/generation/routes.py`)

```python
"""API routes for QNR generation."""

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from smeme.auth.models import User
from smeme.auth.users import current_active_user
from smeme.core.dependencies import get_async_session
from smeme.core.llm import get_openai_client
from smeme.qnr.generation.workflow import build_generation_workflow, GenerationState


router = APIRouter(prefix="/qnr/generate", tags=["qnr-generation"])


class GenerateRequest(BaseModel):
    """Request to generate a QNR from a prompt."""
    
    prompt: str = Field(..., min_length=10, max_length=2000)


class GenerateResponse(BaseModel):
    """Response from QNR generation."""
    
    qnr_id: str
    message: str


@router.post("/", response_model=GenerateResponse)
async def generate_qnr(
    request: GenerateRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
    openai_client: AsyncOpenAI = Depends(get_openai_client),  # Inject OpenAI client
):
    """
    Generate a new QNR from a natural language prompt.
    
    Example prompts:
    - "Create a questionnaire to help developers choose a Python web framework"
    - "Make a survey about user experience with our product"
    - "Build a diagnostic tool for troubleshooting network issues"
    
    Dependencies:
    - user: Authenticated user (FastAPI-Users)
    - db: Database session (per-request)
    - openai_client: OpenAI client (singleton, cached via @lru_cache)
    """
    # Build workflow
    workflow = build_generation_workflow()
    
    # Initial state
    initial_state: GenerationState = {
        "user_prompt": request.prompt,
        "user_id": user.id,
    }
    
    # Execute workflow with dependencies passed via config
    result = await workflow.ainvoke(
        initial_state,
        config={
            "configurable": {
                "db": db,
                "openai_client": openai_client,  # Pass to workflow nodes
                "user_id": user.id
            }
        }
    )
    
    # Check for errors
    if result.get("error"):
        raise HTTPException(
            status_code=500,
            detail=result["error"]
        )
    
    return GenerateResponse(
        qnr_id=str(result["qnr_id"]),
        message=f"Successfully generated QNR: {result['generated_graph'].metadata.title}"
    )
```

---

## Supporting Multiple LLM Providers (Future)

The architecture supports swapping providers without changing workflow code:

```python
# smeme/core/llm.py - Provider abstraction
from functools import lru_cache
from smeme.core.config import settings

@lru_cache(maxsize=1)
def get_llm_client():
    """Get LLM client based on configuration."""
    if settings.llm_provider == "openai":
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=settings.openai_api_key, ...)
    elif settings.llm_provider == "anthropic":
        from anthropic import AsyncAnthropic
        return AsyncAnthropic(api_key=settings.anthropic_api_key, ...)
    # etc.

# smeme/qnr/generation/llm_client.py - Provider-agnostic wrapper
async def generate_qnr_with_llm(client, system_prompt, user_prompt, model, ...):
    """
    Provider-agnostic LLM call.
    
    Works with OpenAI, Anthropic, or any provider that supports
    structured outputs. Implementation adapts based on client type.
    """
    if hasattr(client, "beta"):  # OpenAI
        response = await client.beta.chat.completions.parse(
            model=model,
            messages=[...],
            response_format=QNRGraph,
        )
        return response.choices[0].message.parsed
    elif hasattr(client, "messages"):  # Anthropic
        # Different API but same result
        ...
```

**Key Insight:** Single client instance, swappable provider. Nodes don't need to change.

**For MVP**: Start with OpenAI only. Add providers as needed based on user requirements.

---

## Implementation Checklist

### Phase 1: Basic Generation (MVP)
- [ ] Add dependency to pyproject.toml (`openai>=1.50.0`)
- [ ] Add OpenAI API key to settings (`smeme/core/config.py`)
- [ ] Create `smeme/core/llm.py` with `@lru_cache` singleton client
- [ ] Create `smeme/qnr/generation/` directory structure
- [ ] Implement `llm_client.py` with OpenAI client wrapper functions
- [ ] Write `prompts.py` with system prompt
- [ ] Create `validation.py` with graph logic validation functions
- [ ] Implement `workflow.py` with LangGraph nodes and conditional retry
- [ ] Create `routes.py` with API endpoint (inject client via `Depends()`)
- [ ] Register routes in `main.py`
- [ ] Test generation with retry scenarios
- [ ] Test dependency injection and mocking

### Phase 2: Enhanced Generation
- [ ] Add prompt enhancement node (using another LLM call)
- [ ] Implement graph optimization (remove redundant edges, simplify paths)
- [ ] Add preview/edit capability before saving
- [ ] Implement versioning for generated QNRs
- [ ] Add UI for generation (prompt input, preview, publish)
- [ ] Add cost tracking and rate limiting

### Phase 3: Advanced Features
- [ ] Support for iterative refinement (user feedback loop)
- [ ] Multi-step generation (outline → questions → refinement)
- [ ] Template-based generation (industry-specific templates)
- [ ] AI-assisted question improvement for existing QNRs
- [ ] A/B testing support for generated variants
- [ ] Analytics on generated QNR performance

---

## Security & Safety Considerations

1. **Prompt Injection Protection**
   - Sanitize user inputs
   - Use structured outputs (reduces injection risk)
   - Validate generated content

2. **Content Moderation**
   - Use OpenAI's moderation endpoint
   - Filter inappropriate questions
   - Log all generations for review

3. **Rate Limiting**
   - Implement per-user rate limits
   - Prevent abuse of generation API
   - Monitor costs

4. **Data Privacy**
   - Don't include sensitive data in prompts
   - Use OpenAI's zero-retention API tier if needed
   - Comply with data regulations

---

## Cost Estimation

**OpenAI Pricing (as of 2024):**
- GPT-4o: $2.50 / 1M input tokens, $10.00 / 1M output tokens
- GPT-4o-mini: $0.15 / 1M input tokens, $0.60 / 1M output tokens

**Estimated per QNR Generation:**
- Input: ~500 tokens (system prompt + user prompt)
- Output: ~2000 tokens (QNR graph with 10 questions)

**Using GPT-4o-mini (recommended for this task):**
- Input cost: 500 tokens × $0.15 / 1M = $0.000075
- Output cost: 2000 tokens × $0.60 / 1M = $0.0012
- **Total per generation: ~$0.0013 (~0.13 cents)**

**Monthly cost for 1000 QNR generations: ~$1.30**

---

## Conclusion

**Use OpenAI SDK + LangGraph Validation Workflow:**

✅ **Minimal Dependencies** - Only add OpenAI SDK, use LangGraph we already have  
✅ **LangGraph Does What It's Best At** - Orchestration, conditional routing, retry logic  
✅ **Full Control** - Custom validation logic at each stage  
✅ **Observable** - Every retry attempt visible in LangSmith traces  
✅ **Type-safe** - Pydantic V2 throughout (models, validation)  
✅ **Flexible** - Easy to add new validation stages or conditions  

**Why This Approach:**
- ✅ LangGraph already handles complex workflows with conditional routing
- ✅ Separation of concerns: OpenAI for LLM, LangGraph for orchestration, Pydantic for validation
- ✅ No additional framework dependencies (PydanticAI, Instructor, LangChain)
- ✅ Clear visibility into retry logic via workflow visualization

**Follows Our Principles:**
- ✅ **No Technical Debt** - Clean, maintainable code
- ✅ **PostgreSQL First** - Store in JSONB
- ✅ **HTMX/Jinja First** - Server-side rendering, no JavaScript frameworks
- ✅ **Type Safe** - Pydantic V2 throughout
- ✅ **LangGraph Idiomatic** - Nodes for stages, conditional edges for retry
- ✅ **Minimal Dependencies** - Only add `openai`
- ✅ **Observable** - LangSmith traces + structured logging with timing/context
- ✅ **Code Quality** - Strict Ruff/MyPy configuration enforced

**Architecture Summary:**

```
User Prompt 
  → LangGraph Workflow
    ├─ OpenAI (structured output)
    ├─ Pydantic Validation Node
    ├─ Graph Logic Validation Node
    ├─ Conditional Retry Edges
    └─ PostgreSQL (JSONB)
```

This approach gives us **maximum control and observability** while keeping dependencies minimal and using LangGraph for what it does best.


