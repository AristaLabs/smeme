# LangGraph Orchestration for QNR Generation

## Overview

This document details the LangGraph workflow orchestration for AI-powered QNR generation. LangGraph serves as the workflow engine that coordinates PydanticAI (LLM interaction), validation, and database persistence.

---

## Why LangGraph for Orchestration?

### Separation of Concerns

```
┌─────────────────────────────────────────────────────────────┐
│                      LangGraph Layer                        │
│  (Workflow orchestration, state management, routing)        │
│                                                             │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────┐       │
│  │   Prompt    │ → │  OpenAI SDK  │ → │ Validation  │ → DB  │
│  │ Enhancement │   │   (LLM)      │   │   Logic     │       │
│  └─────────────┘   └──────────────┘   └─────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

**LangGraph handles:**
- Workflow state management
- Node sequencing and conditional routing
- Validation retry logic (via conditional edges)
- Error propagation and feedback loops
- Database session management (via `RunnableConfig`)
- Observability (LangSmith tracing)

**OpenAI SDK handles:**
- LLM interaction
- Structured output generation (response_format with Pydantic)

**Pydantic handles:**
- Data model definition (QNRGraph)
- Schema validation
- Type safety

**Result:** Clean separation, each tool does what it's best at. No additional frameworks needed.

---

## Workflow State Machine

### State Definition

```python
class GenerationState(TypedDict, total=False):
    """
    State flows through the entire workflow.
    Each node reads and updates relevant fields.
    """
    
    # ===== INPUT (provided by route) =====
    user_prompt: str              # Original user prompt
    user_id: int                  # SME creating the QNR
    
    # ===== PROCESSING (intermediate) =====
    enhanced_prompt: str          # Enriched with context
    generated_graph: QNRGraph     # Output from PydanticAI
    validation_errors: list[str]  # Graph logic issues
    
    # ===== OUTPUT (result) =====
    qnr_id: UUID                  # Created QNR ID
    error: str | None             # Any errors encountered
```

**Key Design Decisions:**

1. **`total=False`** - All fields except input are optional
   - Nodes only update fields they're responsible for
   - Missing fields don't cause TypeErrors

2. **No Database Session** - Never in state (not serializable)
   - Passed via `RunnableConfig` instead
   - Follows our established pattern

3. **Error Field** - Centralized error handling
   - Any node can set error
   - Downstream nodes check for errors
   - Enables early exit on failure

---

## Node-by-Node Breakdown

### Node 1: Enhance Prompt

```python
async def enhance_prompt_node(
    state: GenerationState,
    config: RunnableConfig
) -> GenerationState:
    """
    Transform user prompt into a more detailed specification.
    
    Why: User prompts can be vague. Enhancement adds:
    - Domain context
    - Suggested question types
    - Branching logic hints
    - Metadata recommendations
    """
```

**Current Implementation (Phase 1 MVP):**
```python
# Simple pass-through for MVP
return {
    **state,
    "enhanced_prompt": state["user_prompt"]
}
```

**Future Enhancement (Phase 2):**
```python
# Use PydanticAI to enhance the prompt
enhancement_agent = Agent(
    model='gpt-4o-mini',  # Cheaper model for simple task
    result_type=str,
    system_prompt=ENHANCEMENT_PROMPT
)

result = await enhancement_agent.run(
    f"Enhance this QNR prompt: {state['user_prompt']}"
)

return {
    **state,
    "enhanced_prompt": result.data
}
```

**Why This Node Exists:**
- Improves LLM output quality
- Can add user preferences (question style, complexity)
- Future: Can check against existing QNRs to avoid duplicates
- Can inject domain-specific templates

**Example Enhancement:**

```
User Prompt:
"Create a questionnaire about Python web frameworks"

Enhanced Prompt:
"Create a technical questionnaire for developers evaluating Python web frameworks.
Include:
- Experience level question (beginner/intermediate/advanced)
- Use radio buttons for framework selection (Django, Flask, FastAPI, etc.)
- Conditional questions based on selected framework
- Questions about project requirements (async, REST API, admin panel)
- Target completion time: 5-7 minutes
- Tags: python, web-development, frameworks"
```

---

### Node 2: Call OpenAI LLM

```python
async def call_llm_node(
    state: GenerationState,
    config: RunnableConfig
) -> GenerationState:
    """
    Call OpenAI to generate QNR structure.
    
    This is the core AI generation step.
    Uses OpenAI's structured output with Pydantic schema.
    """
    try:
        # Extract OpenAI client from config (injected by route)
        openai_client: AsyncOpenAI = config["configurable"]["openai_client"]
        
        # Build validation feedback if this is a retry
        feedback = None
        if state.get("pydantic_errors"):
            feedback = "Pydantic validation errors:\n" + "\n".join(state["pydantic_errors"])
        elif state.get("graph_errors"):
            feedback = "Graph structure errors:\n" + "\n".join(state["graph_errors"])
        
        # Call OpenAI with structured output
        llm_response = await generate_qnr_with_llm(
            client=openai_client,  # Pass injected client
            system_prompt=SYSTEM_PROMPT,
            user_prompt=state["enhanced_prompt"],
            validation_feedback=feedback
        )
        
        return {
            "llm_response": llm_response,
            "error": None
        }
    
    except Exception as e:
        return {"error": f"LLM call failed: {str(e)}"}
```

**What Happens Inside `generate_qnr_with_llm()`:**

```python
# In smeme/qnr/generation/llm_client.py
async def generate_qnr_with_llm(
    client: AsyncOpenAI,  # Injected client
    system_prompt: str,
    user_prompt: str,
    validation_feedback: str | None = None
):
    """
    Call OpenAI to generate QNR graph structure.
    
    Args:
        client: AsyncOpenAI client instance (injected via config)
        system_prompt: Instructions for the LLM
        user_prompt: User's description
        validation_feedback: Previous errors (for retry)
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    # Add validation feedback for retry
    if validation_feedback:
        messages.append({
            "role": "user",
            "content": f"Previous attempt had errors:\n{validation_feedback}\nPlease fix."
        })
    
    # Use OpenAI structured outputs with Pydantic schema
    response = await client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=messages,
        response_format=QNRGraph,  # Pydantic model
    )
    
    return response.choices[0].message.parsed
```

**Dependency Injection Pattern:**

```python
# smeme/core/llm.py - Single singleton client with @lru_cache
from functools import lru_cache
from openai import AsyncOpenAI
from smeme.core.config import settings

@lru_cache(maxsize=1)
def get_openai_client() -> AsyncOpenAI:
    """
    Cached singleton OpenAI client.
    
    Why singleton?
    - OpenAI client is thread-safe and reusable
    - Connection pooling built-in (httpx)
    - Creating per-request is wasteful
    
    Why single client?
    - Model/temperature configured at CALL time, not client creation
    - Nodes decide parameters based on runtime context
    - More flexible than multiple client instances
    """
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=30.0,
        max_retries=3,
    )

# In routes - inject via FastAPI Depends()
from smeme.core.llm import get_openai_client

@router.post("/generate")
async def generate_qnr(
    request: GenerateRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
    openai_client: AsyncOpenAI = Depends(get_openai_client),  # Singleton
):
    result = await workflow.ainvoke(
        initial_state,
        config={
            "configurable": {
                "db": db,
                "openai_client": openai_client,  # Pass to nodes
                "user_id": user.id,
                "user_tier": user.subscription_tier,  # Nodes can use this
            }
        }
    )
```

**Runtime Parameter Configuration:**

Nodes decide model/parameters based on context:

```python
async def call_llm_node(state, config):
    client = config["configurable"]["openai_client"]
    
    # Smart model selection based on state
    retry_count = state.get("retry_count", 0)
    user_tier = config["configurable"].get("user_tier", "free")
    
    # Escalate model quality on retries
    if retry_count >= 2:
        model = "gpt-4o"
        temperature = 0.9  # More creative
    elif user_tier == "premium":
        model = "gpt-4o"  # Always use best for premium
        temperature = 0.7
    else:
        model = "gpt-4o-mini"  # Cheaper for free tier / first attempt
        temperature = 0.5
    
    response = await client.beta.chat.completions.parse(
        model=model,  # Decided at runtime
        temperature=temperature,
        messages=[...],
        response_format=QNRGraph,
    )
```

**Why This Node Is Separate:**
- Isolates LLM interaction from other concerns
- Easy to swap LLM providers (change `generate_qnr_with_llm()` implementation)
- Error handling in one place
- Can add caching here later
- Can log LLM calls for debugging

**Error Handling:**
- If LLM call fails → set `error` field
- Downstream nodes check `error` and skip processing
- User gets clear error message

---

### Node 3: Validate Pydantic Schema

```python
async def validate_pydantic_node(
    state: GenerationState,
    config: RunnableConfig
) -> GenerationState:
    """Validate LLM response against Pydantic schema."""
    if state.get("error"):
        return state
    
    try:
        # Parse LLM response to QNRGraph model
        qnr_graph = QNRGraph.model_validate(state["llm_response"])
        
        return {
            "generated_graph": qnr_graph,
            "pydantic_errors": [],
            "error": None
        }
    
    except ValidationError as e:
        errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        return {
            "pydantic_errors": errors,
            "generated_graph": None
        }
```

**What Gets Validated:**
- All required fields present
- Field types correct (str, int, list, etc.)
- Pydantic field validators pass
- Nested model validation (QuestionData, GraphNode, etc.)

**LangGraph's Validation Retry Pattern:**

```
┌──────────────────────────┐
│ Node: Call OpenAI        │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Node: Validate Pydantic  │
└────────────┬─────────────┘
             │
      ┌──────┴──────┐
      │ Conditional │
      │   Routing   │
      └──────┬──────┘
             │
    ┌────────┼────────┐
    │        │        │
    ▼        ▼        ▼
 Valid   Invalid   Retry
         (fail)   Count?
                     │
              ┌──────┴──────┐
              │             │
              ▼             ▼
           < 3?          >= 3?
     ┌──────┘             │
     │                    ▼
     │                  FAIL
     │
     └──→ Loop back to "Call OpenAI"
          with error feedback
```

**Key Insight:** LangGraph's conditional edges handle the retry logic that PydanticAI would have done automatically. We have more control and visibility.

---

### Node 4: Validate Graph Logic

```python
async def validate_graph_node(
    state: GenerationState,
    config: RunnableConfig
) -> GenerationState:
    """
    Validate graph structure beyond Pydantic schema validation.
    
    Why separate from Pydantic validation?
    - Pydantic validates individual models
    - This validates relationships between models
    - Graph-specific logic (connectivity, reachability)
    """
    if state.get("error"):
        return state  # Skip if previous error
    
    graph = state["generated_graph"]
    errors = validate_graph_logic(graph)
    
    if errors:
        return {
            "validation_errors": errors,
            "error": f"Graph validation failed: {'; '.join(errors)}"
        }
    
    return {
        "validation_errors": [],
        "error": None
    }
```

**What Gets Validated Here:**

1. **Structural Requirements**
   ```python
   # Must have start and end nodes
   if "start" not in node_ids:
       errors.append("Missing 'start' node")
   
   if "end" not in node_ids:
       errors.append("Missing 'end' node")
   ```

2. **Node Type Consistency**
   ```python
   # Start node must have type "start"
   if node_types["start"] != "start":
       errors.append("Node 'start' must have type 'start'")
   ```

3. **Edge Validity**
   ```python
   # All edges must reference existing nodes
   for edge in graph.edges:
       if edge.source not in node_ids:
           errors.append(f"Invalid source: {edge.source}")
   ```

4. **Graph Connectivity**
   ```python
   # All nodes must be reachable from start
   reachable = get_reachable_nodes(graph)
   unreachable = node_ids - reachable
   if unreachable:
       errors.append(f"Unreachable nodes: {', '.join(unreachable)}")
   ```

5. **Question-Specific Validation**
   ```python
   # Radio/checkbox must have options
   if node.data.type in ["radio", "checkbox"]:
       if not node.data.options:
           errors.append(f"Question {node.id} needs options")
   ```

**Why Not Include This in Pydantic Validators?**

Could we do this in Pydantic's `@model_validator`?
```python
class QNRGraph(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    
    @model_validator(mode='after')
    def validate_connectivity(self):
        # Check graph logic here?
        ...
```

**Reasons for separate node:**

1. **Separation of Concerns**
   - Pydantic: Schema validation (types, required fields)
   - This node: Business logic validation (graph semantics)

2. **Better Error Messages**
   - Pydantic errors are generic
   - We can provide specific guidance (e.g., "Add edge from q3 to end")

3. **Potential Auto-Fix**
   - Future: If validation fails, could auto-fix minor issues
   - Example: Add missing edge to end node
   - Example: Remove unreachable nodes

4. **Flexibility**
   - Can skip strict validation for "draft" mode
   - Can have different validation levels (basic, strict, pedantic)

**Future Enhancement: Auto-Repair**

```python
async def validate_graph_node(state, config):
    graph = state["generated_graph"]
    errors = validate_graph_logic(graph)
    
    if errors and settings.enable_auto_repair:
        # Attempt to fix common issues
        fixed_graph = auto_repair_graph(graph, errors)
        errors = validate_graph_logic(fixed_graph)  # Re-validate
        
        if not errors:
            return {
                "generated_graph": fixed_graph,
                "validation_warnings": ["Auto-repaired graph issues"]
            }
    
    # ... rest of validation
```

---

### Node 5: Save to Database

```python
async def save_qnr_node(
    state: GenerationState,
    config: RunnableConfig
) -> GenerationState:
    """
    Persist the generated QNR to PostgreSQL.
    
    Why last?
    - Only save if everything is valid
    - Transaction-safe (if this fails, nothing saved)
    - Can add version control here
    """
    if state.get("error"):
        return state  # Don't save if errors
    
    db: AsyncSession = config["configurable"]["db"]
    user_id: int = config["configurable"]["user_id"]
    
    graph = state["generated_graph"]
    
    qnr = QNR(
        title=graph.metadata.title,
        description=graph.metadata.description,
        author_id=user_id,
        graph_data=graph.model_dump(),  # JSONB column
        is_published=False,  # Draft by default
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
```

**Why This Is a Separate Node:**

1. **Database Session Management**
   - Gets `db` from `RunnableConfig` (per our pattern)
   - Session lifecycle controlled by route
   - Transaction boundary is clear

2. **Atomic Operation**
   - Either saves completely or not at all
   - If save fails, state has error set
   - Route can handle error appropriately

3. **Additional Operations**
   - Can send notifications (email, webhook)
   - Can create audit log entry
   - Can trigger post-generation tasks

**Future Enhancements:**

```python
async def save_qnr_node(state, config):
    # ... create QNR ...
    
    # Save metadata separately for indexing
    await create_search_index(db, qnr)
    
    # Create initial version
    await create_qnr_version(db, qnr, version="1.0.0")
    
    # Notify user
    await send_notification(
        user_id=user_id,
        message=f"QNR '{qnr.title}' generated successfully"
    )
    
    # Track for analytics
    await track_generation_event(
        user_id=user_id,
        qnr_id=qnr.id,
        prompt_length=len(state["user_prompt"])
    )
    
    return {"qnr_id": qnr.id, "error": None}
```

---

## Workflow Routing

### Implementation: Conditional Retry Flow

```
enhance_prompt → call_llm → validate_pydantic → validate_graph → save_qnr → END
                     ↑              │                    │
                     │              ▼                    │
                     │         (invalid?)                │
                     │              │                    │
                     └──────────────┘                    │
                     │                                   │
                     │              ▼                    │
                     │         (invalid?)                │
                     │              │                    │
                     └──────────────┴────────────────────┘
```

**Implementation with conditional edges:**

```python
workflow = StateGraph(GenerationState)

# Add nodes
workflow.add_node("enhance_prompt", enhance_prompt_node)
workflow.add_node("call_llm", call_llm_node)
workflow.add_node("validate_pydantic", validate_pydantic_node)
workflow.add_node("validate_graph", validate_graph_logic_node)
workflow.add_node("save_qnr", save_qnr_node)

# Linear flow
workflow.set_entry_point("enhance_prompt")
workflow.add_edge("enhance_prompt", "call_llm")
workflow.add_edge("call_llm", "validate_pydantic")

# Conditional: Retry Pydantic validation
workflow.add_conditional_edges(
    "validate_pydantic",
    should_retry_pydantic,  # Routing function
    {
        "retry": "call_llm",      # Loop back with feedback
        "continue": "validate_graph",
        "fail": END
    }
)

# Conditional: Retry graph validation
workflow.add_conditional_edges(
    "validate_graph",
    should_retry_graph,  # Routing function
    {
        "retry": "call_llm",      # Loop back with feedback
        "continue": "save_qnr",
        "fail": END
    }
)

workflow.add_edge("save_qnr", END)
```

### Routing Functions

**Pydantic Validation Routing:**

```python
def should_retry_pydantic(state: GenerationState) -> Literal["retry", "continue", "fail"]:
    """Decide whether to retry after Pydantic validation."""
    if state.get("pydantic_errors"):
        retry_count = state.get("retry_count", 0)
        if retry_count < 3:
            return "retry"  # Loop back to LLM with errors
        return "fail"  # Give up after 3 attempts
    return "continue"  # Validation passed
```

**Graph Logic Validation Routing:**

```python
def should_retry_graph(state: GenerationState) -> Literal["retry", "continue", "fail"]:
    """Decide whether to retry after graph validation."""
    if state.get("graph_errors"):
        retry_count = state.get("validation_retry_count", 0)
        if retry_count < 2:
            return "retry"  # Loop back to LLM with errors
        return "fail"  # Give up after 2 attempts
    return "continue"  # Validation passed
```

**Key Pattern:** State tracks errors and retry counts. Routing functions decide next step. LLM node reads errors from state and includes them in prompt.

---

## Error Handling Strategy

### Error Propagation

```python
# Every node follows this pattern:
async def some_node(state, config):
    # 1. Check for upstream errors
    if state.get("error"):
        return state  # Pass through unchanged
    
    try:
        # 2. Do work
        result = await do_something()
        
        # 3. Return only updated fields (LangGraph merges automatically)
        return {
            "some_field": result,
            "error": None
        }
    
    except Exception as e:
        # 4. Return error (LangGraph merges automatically)
        return {"error": f"Node failed: {str(e)}"}
```

**Benefits:**
- Errors don't crash the workflow
- All nodes get chance to clean up
- Final state always has result or error
- Route can handle error appropriately

### Error Types

```python
class GenerationError(Exception):
    """Base for generation errors."""
    pass

class PromptTooVagueError(GenerationError):
    """Prompt doesn't provide enough context."""
    pass

class LLMValidationError(GenerationError):
    """LLM output failed validation after retries."""
    pass

class GraphStructureError(GenerationError):
    """Generated graph has structural issues."""
    pass

class DatabaseSaveError(GenerationError):
    """Failed to save to database."""
    pass
```

**Node-specific handling:**

```python
async def generate_graph_node(state, config):
    try:
        qnr_graph = await generate_qnr_graph(...)
        return {...}
    
    except LLMValidationError as e:
        # Specific guidance for this error type
        return {
            "error": "The AI couldn't generate a valid questionnaire. Try being more specific in your prompt.",
            "error_type": "llm_validation",
            "retry_suggestions": [
                "Add more details about the target audience",
                "Specify the number of questions you want",
                "Mention any specific topics to cover"
            ]
        }
    
    except Exception as e:
        # Generic error
        return {
            "error": f"Unexpected error: {str(e)}",
            "error_type": "unknown"
        }
```

---

## Observability & Debugging

### LangSmith Integration

LangSmith automatically traces the entire workflow:

```
QNR Generation Run #12345
├─ enhance_prompt_node (0.1s)
│  ├─ Input: {"user_prompt": "..."}
│  └─ Output: {"enhanced_prompt": "..."}
│
├─ generate_graph_node (3.2s)
│  ├─ PydanticAI Agent Call
│  │  ├─ LLM Request (gpt-4o)
│  │  │  ├─ Tokens: 450 input, 1850 output
│  │  │  └─ Cost: $0.0012
│  │  ├─ Validation Attempt 1: FAIL
│  │  │  └─ Error: "Question 'q2' missing options for radio type"
│  │  ├─ Validation Attempt 2: SUCCESS
│  │  └─ Result: QNRGraph(nodes=10, edges=12)
│  └─ Output: {"generated_graph": {...}}
│
├─ validate_graph_node (0.05s)
│  ├─ Connectivity check: PASS
│  ├─ Edge validation: PASS
│  └─ Output: {"validation_errors": []}
│
└─ save_qnr_node (0.3s)
   ├─ Database INSERT
   └─ Output: {"qnr_id": "uuid-..."}

Total: 3.65s, SUCCESS
```

### Logging Strategy

All workflow nodes use **structured logging** with context, timing, and metadata for production observability.

#### Logger Setup

```python
import logging
import time

# Per-workflow named logger
logger = logging.getLogger("smeme.qnr.generation.workflow")
```

#### Node Logging Pattern

```python
async def generate_graph_node(state, config):
    """Generate QNR graph with structured logging."""
    start_time = time.time()
    
    # Extract runtime context
    user_id: int = config["configurable"]["user_id"]
    
    logger.info(
        "Starting QNR generation",
        extra={
            "user_id": user_id,
            "node": "generate_graph",
            "prompt_length": len(state["enhanced_prompt"]),
            "retry_count": state.get("retry_count", 0),
        },
    )
    
    try:
        qnr_graph = await generate_qnr_graph(...)
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "QNR generation successful",
            extra={
                "user_id": user_id,
                "node": "generate_graph",
                "node_count": len(qnr_graph.nodes),
                "edge_count": len(qnr_graph.edges),
                "has_conditional_edges": any(e.condition for e in qnr_graph.edges),
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )
        
        return {"generated_graph": qnr_graph}
    
    except Exception as e:
        logger.error(
            "QNR generation failed",
            extra={
                "user_id": user_id,
                "node": "generate_graph",
                "error": str(e),
                "prompt_snippet": state["enhanced_prompt"][:100],
            },
            exc_info=True,  # Include stack trace
        )
        return {"error": str(e)}
```

#### Key Logging Patterns

1. **Always Include**:
   - `user_id`: Track which user triggered the generation
   - `node`: Name of the current node (for filtering logs)
   - `elapsed_ms`: Execution time for performance monitoring

2. **Use `extra` Dict**:
   - Structured metadata that can be indexed/searched
   - JSON-compatible values only
   - Enables filtering: `grep 'user_id.*42' logs/app.log`

3. **Log Retry Context**:
   ```python
   logger.warning(
       "Validation failed - retrying",
       extra={
           "user_id": user_id,
           "node": "validate_pydantic",
           "retry_count": state["retry_count"],
           "error_count": len(state["pydantic_errors"]),
           "errors": state["pydantic_errors"][:3],  # First 3
       },
   )
   ```

4. **Smart Model Selection Logging**:
   ```python
   logger.info(
       "Calling LLM for QNR generation",
       extra={
           "user_id": user_id,
           "node": "call_llm",
           "model": model,  # gpt-4o-mini vs gpt-4o
           "temperature": temperature,
           "retry_count": retry_count,
           "has_feedback": feedback is not None,
       },
   )
   ```

#### Production Log Analysis

```bash
# Filter by user
grep 'user_id.*42' logs/app.log | jq '.extra'

# Find slow generations (>5s)
grep 'elapsed_ms' logs/app.log | awk -F'elapsed_ms=' '$2 > 5000'

# Count validation failures
grep 'Validation failed' logs/app.log | wc -l

# Track retry patterns
grep 'retry_count' logs/app.log | jq '.extra | {node, retry_count, model}'
```

---

## Code Quality Configuration

### Linter & Type Checker Setup

```toml
# pyproject.toml

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = [
    "E", "W",    # pycodestyle
    "F",         # pyflakes
    "I",         # isort (import sorting)
    "ANN",       # type hints required
    "ASYNC",     # async best practices
    "B",         # bugbear
    "DTZ",       # timezone-aware datetimes
    "PTH",       # use pathlib
]

[tool.mypy]
disallow_untyped_defs = true
warn_unused_ignores = true
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
module = ["langgraph.*", "openai.*"]
ignore_missing_imports = true
```

### Key Enforcements

1. **Type Hints Required** - All functions must have type annotations
2. **Timezone-Aware Datetimes** - Enforces `datetime.now(UTC)`
3. **Modern Python** - Enforces `list[str]` over `List[str]`
4. **Async Best Practices** - Detects blocking operations in async functions

---

## State Persistence (Future)

LangGraph supports state persistence for long-running workflows:

```python
from langgraph.checkpoint.postgres import PostgresSaver

# Create checkpointer
checkpointer = PostgresSaver(async_connection_string=settings.database_url)

# Compile workflow with checkpointing
workflow = build_generation_workflow().compile(
    checkpointer=checkpointer
)

# Execute with thread ID (enables pause/resume)
result = await workflow.ainvoke(
    initial_state,
    config={
        "configurable": {
            "thread_id": f"gen-{user_id}-{timestamp}",
            "db": db,
            "user_id": user_id
        }
    }
)
```

**Use cases:**
1. **Long-running generations** - User can close browser, come back later
2. **Human-in-the-loop** - Pause after validation for manual review
3. **Debugging** - Replay workflow from any node
4. **A/B testing** - Fork workflow to try different approaches

---

## Testing Strategy

### Unit Test Each Node

```python
import pytest
from smeme.qnr.generation.workflow import generate_graph_node

@pytest.mark.asyncio
async def test_generate_graph_node_success():
    """Test successful graph generation."""
    state = {
        "user_prompt": "Create a Python framework questionnaire",
        "enhanced_prompt": "...",
        "user_id": 1
    }
    
    config = {
        "configurable": {
            "user_id": 1
        }
    }
    
    result = await generate_graph_node(state, config)
    
    assert "generated_graph" in result
    assert result["error"] is None
    assert len(result["generated_graph"].nodes) > 0


@pytest.mark.asyncio
async def test_generate_graph_node_handles_error():
    """Test node handles LLM errors gracefully."""
    state = {"enhanced_prompt": "", "user_id": 1}
    config = {"configurable": {"user_id": 1}}
    
    result = await generate_graph_node(state, config)
    
    assert result["error"] is not None
    assert "generated_graph" not in result
```

### Integration Test Full Workflow

```python
@pytest.mark.asyncio
async def test_full_generation_workflow(db_session):
    """Test complete generation workflow."""
    workflow = build_generation_workflow()
    
    initial_state = {
        "user_prompt": "Create a questionnaire about Python frameworks",
        "user_id": 1
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={
            "configurable": {
                "db": db_session,
                "user_id": 1
            }
        }
    )
    
    # Verify success
    assert result["error"] is None
    assert "qnr_id" in result
    
    # Verify database
    qnr = await db_session.get(QNR, result["qnr_id"])
    assert qnr is not None
    assert qnr.title is not None
    assert qnr.author_id == 1
```

---

## Performance Considerations

### Node Execution Times

```
enhance_prompt:     ~0.1s  (passthrough in MVP)
generate_graph:     ~3.0s  (LLM call + validation)
validate_graph:     ~0.05s (pure Python logic)
save_qnr:          ~0.3s  (database operation)
─────────────────────────
Total:             ~3.45s per generation
```

### Optimization Strategies

1. **Parallel Enhancement (Future)**
   ```python
   # Run enhancement and preliminary validation in parallel
   async def enhance_and_validate_parallel(state, config):
       enhanced, meta = await asyncio.gather(
           enhance_prompt(state["user_prompt"]),
           get_user_preferences(config["configurable"]["user_id"])
       )
       return {...}
   ```

2. **Caching**
   ```python
   from aiocache import cached
   
   @cached(ttl=3600)  # Cache for 1 hour
   async def generate_similar_qnr(prompt_hash: str):
       # If similar prompt was generated recently, return cached result
       pass
   ```

3. **Streaming (Phase 3)**
   ```python
   # Stream partial results to user as they're generated
   async def generate_graph_node_streaming(state, config):
       async for partial_graph in qnr_agent.run_stream(...):
           yield {**state, "partial_graph": partial_graph}
   ```

---

## Summary

### LangGraph's Role

✅ **Workflow Orchestration** - Sequences nodes, manages state  
✅ **Dependency Injection** - Passes DB session via `RunnableConfig`  
✅ **Error Handling** - Propagates errors, enables early exit  
✅ **Observability** - LangSmith traces every step  
✅ **Testability** - Each node is independently testable  
✅ **Extensibility** - Easy to add nodes, conditional routing  

### Why This Architecture Works

1. **Separation of Concerns**
   - LangGraph: Workflow orchestration, conditional routing, retry logic
   - OpenAI SDK: LLM interaction with structured outputs
   - Pydantic: Data model definition and validation
   - Custom code: Business logic and graph validation

2. **Follows Our Patterns**
   - PostgreSQL First (JSONB storage)
   - HTMX/Jinja First (server-side rendering)
   - Type-safe state (Pydantic V2 throughout)
   - Async-first architecture
   - Dependency injection via RunnableConfig
   - Database session management
   - Strict linting (Ruff) and type checking (MyPy)

3. **Observable & Debuggable**
   - LangSmith traces entire LangGraph workflow
   - Each validation attempt visible as separate node execution
   - Structured logging with context, timing, and metadata
   - Per-workflow named loggers (`smeme.qnr.generation.workflow`)
   - Production-ready log filtering and analysis
   - Clear error propagation through state
   - Conditional edge decisions visible in trace

4. **Extensible**
   - Add nodes without changing others
   - Conditional routing for complex flows
   - State persistence for long operations
   - Easy to switch LLM providers

This orchestration approach gives us **flexibility, maintainability, and observability** while keeping each component focused and testable. LangGraph's conditional routing provides intelligent validation retry with full visibility into each attempt.

