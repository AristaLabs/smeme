# Memo Generation Workflow - Implementation Plan

## Overview

This document outlines the plan to implement a LangGraph workflow that generates a structured memo from completed QNR sessions. When a user clicks "Generate Memo" on the completion screen, the workflow will:

1. Load the completed QNR session with questions and answers
2. Format the Q&A data for the LLM
3. Call OpenAI to generate a structured memo
4. Save the memo to the database
5. Render the memo as HTML for HTMX display

## Goal

**Input**: Completed QNR session ID  
**Output**: Structured memo with Title, Summary, and Recommendations  
**Trigger**: "Generate Memo" button on QNR completion screen  

---

## Architecture Overview

```
User clicks "Generate Memo"
    ↓
HTMX POST /qnr/generate_memo
    ↓
LangGraph Workflow (smeme/qnr/memo_workflow.py)
    ↓
┌──────────────────────────────────────┐
│ Node 1: Load QNR Session             │
│ - L1: Check aiocache (~1-5ms)        │
│ - L2: Check database (~150ms)        │
│ - If found: return memo, skip to end │
│ - If not: fetch QNR & extract Q&A    │
└──────────────────────────────────────┘
    ↓
    Decision: Memo already generated?
    ├─ YES (skip_to_render) ──────────────┐
    │   • L1 cache hit: ~5ms              │
    │   • L2 DB hit: ~150ms               │
    └─ NO (generate)                      │
        ↓                                 │
    ┌──────────────────────────────────┐  │
    │ Node 2: Format for LLM           │  │
    │ - Build context from Q&A         │  │
    │ - Create LLM prompt              │  │
    └──────────────────────────────────┘  │
        ↓                                 │
    ┌──────────────────────────────────┐  │
    │ Node 3: Call OpenAI (Structured) │  │
    │ - Use response_format (Pydantic) │  │
    │ - Generate Memo model            │  │
    └──────────────────────────────────┘  │
        ↓                                 │
    ┌──────────────────────────────────┐  │
    │ Node 4: Save Memo to Database    │  │
    │ - Create Memo record             │  │
    │ - Link to session                │  │
    │ - Populate L1 cache              │  │
    └──────────────────────────────────┘  │
        ↓                                 │
        └─────────────────────────────────┘
                    ↓
    ┌──────────────────────────────────┐
    │ Node 5: Render HTML              │
    │ - Use Jinja2 template            │
    │ - Return formatted memo          │
    └──────────────────────────────────┘
    ↓
HTMX swaps content → User sees memo

Performance (Two-Tier Caching):
- L1 cache hit:  load_session (~5ms) → render_memo (~18ms)    = 23ms, $0
- L2 DB hit:     load_session (~150ms) → render_memo (~18ms)  = 168ms, $0
- Cache miss:    all 5 nodes with LLM call                     = 3.5s, $0.0003
```

---

## Data Models

### 1. Database Model (`smeme/core/models.py`)

```python
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Column, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped
from sqlmodel import Field, SQLModel


class Memo(SQLModel, table=True):
    """Generated memo from QNR session."""
    
    model_config = {"arbitrary_types_allowed": True}
    
    __tablename__ = "memos"
    
    # Primary key
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    
    # Foreign keys
    session_id: UUID = Field(foreign_key="qnr_sessions.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    
    # Memo content
    title: str = Field(max_length=500, nullable=False)
    summary: str = Field(sa_column=Column(Text, nullable=False))
    recommendations: str = Field(sa_column=Column(Text, nullable=False))
    
    # Optional: Store raw LLM response for debugging
    llm_response: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}")
    )
    
    # Timestamps (timezone-aware)
    generated_at: Mapped[datetime] = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default_factory=lambda: datetime.now(UTC),
            server_default=sa.func.now(),
        )
    )
```

### 2. Pydantic Model for LLM Response (`smeme/qnr/models.py`)

```python
from pydantic import BaseModel, Field

class MemoContent(BaseModel):
    """Structured memo output from LLM."""
    
    title: str = Field(
        ...,
        description="Concise title summarizing the assessment focus",
        min_length=10,
        max_length=200
    )
    
    summary: str = Field(
        ...,
        description="2-3 paragraph summary of the user's responses and key insights",
        min_length=100,
        max_length=2000
    )
    
    recommendations: str = Field(
        ...,
        description="Bullet-point list of actionable recommendations based on responses",
        min_length=50,
        max_length=2000
    )
```

### 3. LangGraph State (`smeme/qnr/models.py`)

```python
from typing import TypedDict

class MemoGenerationState(TypedDict, total=False):
    """State for memo generation workflow."""
    
    # Input
    session_id: str
    user_id: str  # UUID as string
    
    # Intermediate data
    qa_pairs: list[dict[str, str]]  # [{"question": "...", "answer": "..."}]
    system_prompt: str  # System prompt for LLM
    llm_prompt: str     # User prompt for LLM
    already_generated: bool  # Whether memo was previously generated (L1 cache or DB)
    
    # Output
    memo_content: dict  # MemoContent as dict
    memo_id: str | None
    rendered_html: str
    
    # Error handling
    error: str | None
```

---

## LangSmith Integration

### Automatic Tracing

LangSmith automatically traces all LangGraph workflows when enabled via environment variables:

```bash
# .env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_api_key_here
LANGCHAIN_PROJECT=smeme_v2
```

### What Gets Traced

When you execute the workflow, LangSmith captures:

1. **Workflow Execution**
   - Start time, end time, total duration
   - Final state (input and output)
   - Success/failure status

2. **Each Node Execution**
   - Node name (e.g., "load_session", "call_llm")
   - Input state (what came in)
   - Output state (what was returned)
   - Duration
   - Any errors

3. **LLM Calls** (within `call_llm_node`)
   - Model used (gpt-4o-mini)
   - Token counts (input/output)
   - Cost
   - Prompt and completion
   - Temperature and other parameters

4. **Conditional Edges** (if any)
   - Which path was taken
   - Why (based on state)

### Viewing Traces

In LangSmith UI, you'll see:

```
# SCENARIO 1: Fresh Generation (not cached)
Trace: memo_generation_workflow
├─ load_session (342ms)
│  ├─ Input: {session_id: "abc123", user_id: 42}
│  ├─ L1 Cache (aiocache): MISS
│  ├─ L2 Database: MISS
│  └─ Output: {qa_pairs: [...], already_generated: false}
├─ [route_after_load] → "generate"
├─ format_prompt (2ms)
│  └─ Output: {system_prompt: "...", llm_prompt: "..."}
├─ call_llm (2847ms) 💰 $0.0003
│  ├─ OpenAI API Call (gpt-4o-mini)
│  │  ├─ Input: 487 tokens
│  │  ├─ Output: 312 tokens
│  │  └─ Response: {title: "...", summary: "...", ...}
│  └─ Output: {memo_content: {...}}
├─ save_memo (156ms)
│  ├─ Saved to database
│  ├─ Populated L1 cache
│  └─ Output: {memo_id: "def456"}
└─ render_memo (23ms)
   └─ Output: {rendered_html: "..."}

Total: 3.37s | Cost: $0.0003 | Status: ✅ Success


# SCENARIO 2: L1 Cache Hit (aiocache)
Trace: memo_generation_workflow
├─ load_session (5ms) ⚡
│  ├─ Input: {session_id: "abc123", user_id: 42}
│  ├─ L1 Cache (aiocache): HIT ✨
│  └─ Output: {memo_content: {...}, memo_id: "def456", already_generated: true}
├─ [route_after_load] → "skip_to_render" (skips format/call/save)
└─ render_memo (18ms)
   └─ Output: {rendered_html: "..."}

Total: 0.023s | Cost: $0 | Status: ✅ Success (L1 cached)


# SCENARIO 3: L2 Database Hit (after server restart)
Trace: memo_generation_workflow
├─ load_session (148ms)
│  ├─ Input: {session_id: "abc123", user_id: 42}
│  ├─ L1 Cache (aiocache): MISS (cache cleared on restart)
│  ├─ L2 Database: HIT
│  ├─ Populated L1 cache for next request
│  └─ Output: {memo_content: {...}, memo_id: "def456", already_generated: true}
├─ [route_after_load] → "skip_to_render" (skips format/call/save)
└─ render_memo (18ms)
   └─ Output: {rendered_html: "..."}

Total: 0.166s | Cost: $0 | Status: ✅ Success (L2 cached)
```

### Correlation with Structured Logs

Our structured logging complements LangSmith:

- **LangSmith**: High-level workflow visualization, LLM call details, costs
- **Structured Logs**: Detailed business logic, database queries, user context

Example correlation:

```python
# In your logs (grep by session_id)
INFO Loading QNR session | session_id=abc123 user_id=42 node=load_session
INFO Session loaded | session_id=abc123 qa_count=8 elapsed_ms=342.15
INFO Calling LLM | user_id=42 model=gpt-4o-mini node=call_llm
INFO LLM completed | user_id=42 title_length=67 elapsed_ms=2847.32
INFO Memo saved | session_id=abc123 memo_id=def456

# In LangSmith (same session)
- View full workflow trace
- See exact LLM prompt/completion
- Check token usage and cost
- Debug if LLM returned invalid structure
```

### Debugging with LangSmith

**Scenario**: Memo generation fails

1. **Check structured logs** → Find which node failed and why
2. **Open LangSmith trace** → See exact state at each node
3. **If LLM node failed** → View the actual prompt sent and response received
4. **Compare traces** → See successful vs failed runs side-by-side

### Configuration in Code

No special code needed! LangGraph automatically integrates when you:

```python
# smeme/core/config.py
class Settings(BaseSettings):
    # ... other settings ...
    
    # LangSmith (optional - only for tracing)
    langchain_api_key: str | None = None
    langchain_tracing_v2: bool = False
    langchain_project: str = "smeme_v2"
```

The workflow execution in `routes.py` is already instrumented:

```python
result = await workflow.ainvoke(  # ← LangSmith traces this automatically
    initial_state,
    config={"configurable": {...}}
)
```

### Cost Tracking

LangSmith tracks cumulative costs:
- Per workflow run
- Per user (if you tag runs with user_id)
- Per day/week/month
- Per model

This helps monitor your OpenAI spending across all memo generations.

---

## Workflow Implementation

### File: `smeme/qnr/memo_workflow.py`

```python
"""LangGraph workflow for generating memos from QNR sessions."""

import logging
import time
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from jinja2 import Environment, FileSystemLoader
from langgraph.graph import END, StateGraph
from langgraph.types import RunnableConfig
from openai import AsyncOpenAI
from sqlmodel.ext.asyncio.session import AsyncSession

from smeme.core.models import Memo, QNRSession
from smeme.qnr.helpers.cache import cache_memo, get_cached_memo
from smeme.qnr.helpers.db_queries import get_qnr_by_id, get_session_by_id
from smeme.qnr.helpers.validation import get_node_by_id
from smeme.qnr.models import MemoContent, MemoGenerationState, QNRGraph

logger = logging.getLogger("smeme.qnr.memo_workflow")
jinja_env = Environment(loader=FileSystemLoader("smeme/templates"))


# Node 1: Load QNR session and questions (with caching check)
async def load_session_node(
    state: MemoGenerationState,
    config: RunnableConfig
) -> MemoGenerationState:
    """Load QNR session with questions and answers. Return existing memo if available."""
    start_time = time.time()
    
    db: AsyncSession = config["configurable"]["db"]
    user_id: UUID = config["configurable"]["user_id"]
    session_id = UUID(state["session_id"])
    
    logger.info(
        "Loading QNR session for memo generation",
        extra={
            "session_id": str(session_id),
            "user_id": user_id,
            "node": "load_session",
        },
    )
    
    # Get session
    session = await get_session_by_id(db, session_id)
    if not session:
        logger.error(
            "Session not found",
            extra={"session_id": str(session_id), "node": "load_session"},
        )
        return {"error": "Session not found"}
    
    # Verify ownership
    if session.user_id != user_id:
        logger.warning(
            "Unauthorized access attempt",
            extra={
                "session_id": str(session_id),
                "user_id": user_id,
                "session_user_id": session.user_id,
                "node": "load_session",
            },
        )
        return {"error": "Unauthorized"}
    
    # Verify completion
    if not session.completed_at:
        logger.warning(
            "Attempted to generate memo for incomplete session",
            extra={"session_id": str(session_id), "node": "load_session"},
        )
        return {"error": "Session not completed"}
    
    # ========================================================================
    # TWO-TIER CACHING: Check aiocache (L1) then database (L2)
    # ========================================================================
    
    # L1: Check aiocache (~1-5ms) - FAST
    cached_memo = await get_cached_memo(session_id)
    if cached_memo:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Memo loaded from L1 cache (aiocache)",
            extra={
                "session_id": str(session_id),
                "memo_id": str(cached_memo.id),
                "user_id": user_id,
                "cache_layer": "L1_aiocache",
                "cache_hit": True,
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "load_session",
            },
        )
        
        # Return cached memo data - skip to render
        return {
            "memo_content": {
                "title": cached_memo.title,
                "summary": cached_memo.summary,
                "recommendations": cached_memo.recommendations,
            },
            "memo_id": str(cached_memo.id),
            "already_generated": True,
        }
    
    # L2: Check database (~150ms) - one-and-done persistence
    from sqlmodel import select
    stmt = select(Memo).where(Memo.session_id == session_id)
    result = await db.execute(stmt)
    existing_memo = result.scalar_one_or_none()
    
    if existing_memo:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Memo loaded from L2 database - populating L1 cache",
            extra={
                "session_id": str(session_id),
                "memo_id": str(existing_memo.id),
                "user_id": user_id,
                "cache_layer": "L2_database",
                "cache_hit": True,
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "load_session",
            },
        )
        
        # Populate L1 cache for next request
        await cache_memo(session_id, existing_memo)
        
        # Return existing memo data - skip to render
        return {
            "memo_content": {
                "title": existing_memo.title,
                "summary": existing_memo.summary,
                "recommendations": existing_memo.recommendations,
            },
            "memo_id": str(existing_memo.id),
            "already_generated": True,
        }
    
    # No existing memo found - proceed with generation
    logger.info(
        "No existing memo found - proceeding with generation",
        extra={
            "session_id": str(session_id),
            "user_id": user_id,
            "cache_hit": False,
            "node": "load_session",
        },
    )
    
    # Get QNR with questions
    qnr = await get_qnr_by_id(db, session.qnr_id)
    if not qnr:
        return {"error": "QNR not found"}
    
    # Parse graph to get question texts
    from smeme.qnr.helpers.db_queries import parse_graph_data
    graph = parse_graph_data(qnr)
    
    # Build Q&A pairs
    qa_pairs = []
    responses = session.user_responses or {}
    
    for question_id, answer in responses.items():
        node = get_node_by_id(graph, question_id)
        if node and node.data:
            qa_pairs.append({
                "question": node.data.text,
                "answer": answer
            })
    
    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "Session loaded successfully",
        extra={
            "session_id": str(session_id),
            "user_id": user_id,
            "qa_count": len(qa_pairs),
            "elapsed_ms": round(elapsed_ms, 2),
            "node": "load_session",
        },
    )
    
    return {"qa_pairs": qa_pairs, "already_generated": False}


# Node 2: Format for LLM
async def format_prompt_node(
    state: MemoGenerationState,
    config: RunnableConfig
) -> MemoGenerationState:
    """Format Q&A data into LLM prompt."""
    user_id: UUID = config["configurable"]["user_id"]
    
    if state.get("error"):
        return state
    
    qa_pairs = state["qa_pairs"]
    
    # Build Q&A context
    qa_text = "\n\n".join([
        f"Q: {qa['question']}\nA: {qa['answer']}"
        for qa in qa_pairs
    ])
    
    # System prompt
    system_prompt = """You are an expert analyst creating executive summaries.

Given a questionnaire with questions and answers, generate a professional memo with:

1. **Title**: A concise, descriptive title (10-100 words)
2. **Summary**: A 2-3 paragraph overview of key points and insights (100-500 words)
3. **Recommendations**: Actionable recommendations in markdown format (3-7 bullet points, 50-300 words total)

Format the recommendations section as a markdown list. For example:
- **Action 1**: Brief description
- **Action 2**: Brief description

Be clear, professional, and actionable. Focus on insights and value."""
    
    # User prompt
    user_prompt = f"""Based on the following questionnaire responses, generate a professional memo:

{qa_text}

Generate the memo now."""
    
    logger.info(
        "Prompt formatted for LLM",
        extra={
            "user_id": user_id,
            "qa_count": len(qa_pairs),
            "prompt_length": len(user_prompt),
            "node": "format_prompt",
        },
    )
    
    return {
        "llm_prompt": user_prompt,
        "system_prompt": system_prompt
    }


# Node 3: Call OpenAI
async def call_llm_node(
    state: MemoGenerationState,
    config: RunnableConfig
) -> MemoGenerationState:
    """Call OpenAI to generate structured memo."""
    start_time = time.time()
    
    if state.get("error"):
        return state
    
    openai_client: AsyncOpenAI = config["configurable"]["openai_client"]
    user_id: UUID = config["configurable"]["user_id"]
    
    logger.info(
        "Calling LLM for memo generation",
        extra={
            "user_id": user_id,
            "model": "gpt-4o-mini",
            "node": "call_llm",
        },
    )
    
    try:
        response = await openai_client.beta.chat.completions.parse(
            model="gpt-4o-mini",  # Sufficient for summaries
            messages=[
                {"role": "system", "content": state["system_prompt"]},
                {"role": "user", "content": state["llm_prompt"]},
            ],
            response_format=MemoContent,
            temperature=0.7,
        )
        
        memo_content = response.choices[0].message.parsed
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "LLM call completed",
            extra={
                "user_id": user_id,
                "title_length": len(memo_content.title),
                "summary_length": len(memo_content.summary),
                "recommendations_length": len(memo_content.recommendations),
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "call_llm",
            },
        )
        
        return {"memo_content": memo_content.model_dump()}
        
    except Exception as e:
        logger.error(
            "LLM call failed",
            extra={
                "user_id": user_id,
                "error": str(e),
                "node": "call_llm",
            },
            exc_info=True,
        )
        return {"error": f"Failed to generate memo: {str(e)}"}


# Node 4: Save to database
async def save_memo_node(
    state: MemoGenerationState,
    config: RunnableConfig
) -> MemoGenerationState:
    """Save generated memo to database."""
    if state.get("error"):
        return state
    
    db: AsyncSession = config["configurable"]["db"]
    user_id: UUID = config["configurable"]["user_id"]
    session_id = UUID(state["session_id"])
    
    memo_content = state["memo_content"]
    
    logger.info(
        "Saving memo to database",
        extra={
            "session_id": str(session_id),
            "user_id": user_id,
            "node": "save_memo",
        },
    )
    
    try:
        memo = Memo(
            session_id=session_id,
            user_id=user_id,
            title=memo_content["title"],
            summary=memo_content["summary"],
            recommendations=memo_content["recommendations"],
            llm_response=memo_content,
            # generated_at is auto-set by model default_factory
        )
        
        db.add(memo)
        await db.commit()
        await db.refresh(memo)
        
        # Populate L1 cache for fast subsequent access
        await cache_memo(session_id, memo)
        
        logger.info(
            "Memo saved successfully and cached",
            extra={
                "session_id": str(session_id),
                "memo_id": str(memo.id),
                "user_id": user_id,
                "cache_populated": True,
                "node": "save_memo",
            },
        )
        
        return {"memo_id": str(memo.id)}
        
    except Exception as e:
        logger.error(
            "Failed to save memo",
            extra={
                "session_id": str(session_id),
                "user_id": user_id,
                "error": str(e),
                "node": "save_memo",
            },
            exc_info=True,
        )
        return {"error": f"Failed to save memo: {str(e)}"}


# Node 5: Render HTML
async def render_memo_node(
    state: MemoGenerationState,
    config: RunnableConfig
) -> MemoGenerationState:
    """Render memo as HTML for HTMX."""
    if state.get("error"):
        error_html = f"""
        <div class="max-w-2xl mx-auto p-6">
            <div class="bg-red-50 border border-red-200 rounded-lg p-6">
                <h2 class="text-xl font-bold text-red-800 mb-2">Error</h2>
                <p class="text-red-700">{state['error']}</p>
                <a href="/qnr/dashboard" class="text-red-600 hover:underline mt-4 inline-block">
                    Return to Dashboard
                </a>
            </div>
        </div>
        """
        return {"rendered_html": error_html}
    
    user_id: UUID = config["configurable"]["user_id"]
    memo_content = state["memo_content"]
    session_id = state["session_id"]
    
    logger.info(
        "Rendering memo HTML",
        extra={
            "session_id": session_id,
            "user_id": user_id,
            "memo_id": state.get("memo_id"),
            "node": "render_memo",
        },
    )
    
    # Render template
    template = jinja_env.get_template("qnr/memo.html")
    html = template.render(
        title=memo_content["title"],
        summary=memo_content["summary"],
        recommendations=memo_content["recommendations"],
        session_id=session_id,
        memo_id=state.get("memo_id"),
    )
    
    return {"rendered_html": html}


# Conditional routing function
def route_after_load(state: MemoGenerationState) -> Literal["skip_to_render", "generate"]:
    """
    Route based on whether memo was previously generated.
    
    Returns:
        "skip_to_render": Skip to render_memo (memo found in L1 cache or L2 database)
        "generate": Continue through generation pipeline (LLM call needed)
    """
    if state.get("already_generated"):
        return "skip_to_render"
    return "generate"


# Build workflow
def build_memo_workflow() -> StateGraph:
    """Build and compile the memo generation workflow."""
    workflow = StateGraph(MemoGenerationState)
    
    # Add nodes
    workflow.add_node("load_session", load_session_node)
    workflow.add_node("format_prompt", format_prompt_node)
    workflow.add_node("call_llm", call_llm_node)
    workflow.add_node("save_memo", save_memo_node)
    workflow.add_node("render_memo", render_memo_node)
    
    # Set entry point
    workflow.set_entry_point("load_session")
    
    # Conditional routing after load_session
    workflow.add_conditional_edges(
        "load_session",
        route_after_load,
        {
            "skip_to_render": "render_memo",  # Skip directly to render (L1/L2 cache hit)
            "generate": "format_prompt"       # Continue through generation (cache miss)
        }
    )
    
    # Linear flow for generation path
    workflow.add_edge("format_prompt", "call_llm")
    workflow.add_edge("call_llm", "save_memo")
    workflow.add_edge("save_memo", "render_memo")
    
    # End
    workflow.add_edge("render_memo", END)
    
    return workflow.compile()
```

---

## Route Integration

### File: `smeme/qnr/routes.py` (add new route)

```python
@router.post("/generate_memo")
async def generate_memo(
    request: Request,
    session_id: str = Form(...),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
    openai_client: AsyncOpenAI = Depends(get_openai_client),
) -> HTMLResponse:
    """
    Generate memo from completed QNR session.
    
    Dependencies:
    - user: Authenticated user (FastAPI-Users)
    - db: Database session (per-request)
    - openai_client: OpenAI client (singleton, cached)
    """
    from smeme.qnr.memo_workflow import build_memo_workflow
    from smeme.qnr.models import MemoGenerationState
    
    # Build and execute workflow
    workflow = build_memo_workflow()
    
    initial_state: MemoGenerationState = {
        "session_id": session_id,
        "user_id": str(user.id),  # Convert UUID to string for state
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={
            "configurable": {
                "db": db,
                "openai_client": openai_client,
                "user_id": user.id,
            }
        }
    )
    
    return HTMLResponse(content=result["rendered_html"])
```

---

## Cache Invalidation

### Overview

The two-tier caching system requires proper invalidation when memos are updated or deleted. This ensures users always see the most current data.

### Invalidation Triggers

**When to invalidate memo cache:**

1. **Memo Deletion** - User explicitly deletes a memo
2. **Memo Regeneration** - User overrides one-and-done policy to regenerate
3. **Administrative Actions** - Admin edits or removes memo

### Implementation

#### 1. Delete Memo Route (Optional)

If you decide to allow memo deletion by user.

```python
# smeme/qnr/routes.py

from smeme.qnr.helpers.cache import invalidate_memo_cache

@router.delete("/memo/{memo_id}")
async def delete_memo(
    memo_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Delete memo and invalidate cache."""
    
    # Fetch memo
    memo = await db.get(Memo, memo_id)
    if not memo:
        raise HTTPException(status_code=404, detail="Memo not found")
    
    # Verify ownership
    if memo.user_id != user.id:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    # Store session_id before deleting
    session_id = memo.session_id
    
    # Delete from database
    await db.delete(memo)
    await db.commit()
    
    # Invalidate L1 cache
    await invalidate_memo_cache(session_id)
    
    logger.info(
        "Memo deleted and cache invalidated",
        extra={
            "memo_id": str(memo_id),
            "session_id": str(session_id),
            "user_id": user.id,
        },
    )
    
    return {"status": "deleted", "memo_id": str(memo_id)}
```

#### 2. Regenerate Memo Route (Optional)

If you decide to allow memo regeneration (overriding one-and-done policy):

```python
@router.post("/memo/{session_id}/regenerate")
async def regenerate_memo(
    session_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
    openai_client: AsyncOpenAI = Depends(get_openai_client),
) -> HTMLResponse:
    """Regenerate memo (invalidates cache and creates new memo)."""
    
    # Verify session ownership
    session = await get_session_by_id(db, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    # Delete existing memo
    result = await db.execute(
        select(Memo).where(Memo.session_id == session_id)
    )
    existing_memo = result.scalar_one_or_none()
    if existing_memo:
        await db.delete(existing_memo)
        await db.commit()
    
    # Invalidate L1 cache
    await invalidate_memo_cache(session_id)
    
    logger.info(
        "Memo cache invalidated for regeneration",
        extra={"session_id": str(session_id), "user_id": user.id},
    )
    
    # Execute workflow (will generate fresh memo)
    workflow = build_memo_workflow()
    initial_state: MemoGenerationState = {
        "session_id": str(session_id),
        "user_id": str(user.id),  # Convert UUID to string for state
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={
            "configurable": {
                "db": db,
                "openai_client": openai_client,
                "user_id": user.id,
            }
        }
    )
    
    return HTMLResponse(content=result["rendered_html"])
```

### Cache Invalidation in Tests

```python
# tests/test_memo_caching.py

async def test_cache_invalidation():
    """Test that cache is properly invalidated on deletion."""
    
    # Generate memo (populates cache)
    response1 = await client.post("/qnr/generate_memo", data={"session_id": session_id})
    assert response1.status_code == 200
    
    # Verify L1 cache is populated
    from smeme.qnr.helpers.cache import get_cached_memo
    cached = await get_cached_memo(session_id)
    assert cached is not None
    
    # Delete memo
    memo_id = cached.id
    response2 = await client.delete(f"/memo/{memo_id}")
    assert response2.status_code == 200
    
    # Verify L1 cache is cleared
    cached_after = await get_cached_memo(session_id)
    assert cached_after is None
```

### Cache Warming (Optional)

For high-traffic scenarios, you can pre-populate the cache:

```python
async def warm_memo_cache(db: AsyncSession, session_ids: list[UUID]):
    """Pre-populate L1 cache with memos for specified sessions."""
    from smeme.qnr.helpers.cache import cache_memo
    
    for session_id in session_ids:
        result = await db.execute(
            select(Memo).where(Memo.session_id == session_id)
        )
        memo = result.scalar_one_or_none()
        if memo:
            await cache_memo(session_id, memo)
            logger.info(f"Cache warmed for session {session_id}")
```

### Monitoring Cache Performance

Track cache hit rates in production logs:

```python
# Structured logging already captures this in load_session_node:
# - cache_layer: "L1_aiocache" | "L2_database" | None (miss)
# - cache_hit: True | False

# Query logs to calculate hit rates:
# grep "cache_layer" logs/app.log | jq '.extra.cache_layer' | sort | uniq -c
```

**Expected metrics:**
- **L1 hit rate**: 70-90% (repeated views within 1 hour)
- **L2 hit rate**: 90-99% (one-and-done policy)
- **Cache miss**: 1-10% (first-time generation)

---

## Template

### File: `smeme/templates/qnr/memo.html`

```html
<div class="max-w-4xl mx-auto p-6">
    <div class="bg-white border border-gray-200 rounded-lg p-8 shadow-sm">
        <!-- Header -->
        <div class="mb-8">
            <h1 class="text-3xl font-bold text-gray-900 mb-2">{{ title }}</h1>
            <p class="text-sm text-gray-500">Generated on {{ generated_date }}</p>
        </div>
        
        <!-- Summary Section -->
        <div class="mb-8">
            <h2 class="text-xl font-semibold text-gray-800 mb-4">Summary</h2>
            <div class="prose max-w-none text-gray-700">
                {{ summary | safe }}
            </div>
        </div>
        
        <!-- Recommendations Section -->
        <div class="mb-8">
            <h2 class="text-xl font-semibold text-gray-800 mb-4">Recommendations</h2>
            <div class="prose max-w-none text-gray-700">
                {{ recommendations | safe }}
            </div>
        </div>
        
        <!-- Actions -->
        <div class="flex gap-4 pt-6 border-t border-gray-200">
            <button
                hx-post="/qnr/navigate"
                hx-vals='{"session_id": "{{ session_id }}", "direction": "review"}'
                hx-target="#root"
                hx-swap="innerHTML"
                class="bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium py-2 px-4 rounded-lg transition"
            >
                ← Review Answers
            </button>
            
            <button
                onclick="window.print()"
                class="bg-purple-600 hover:bg-purple-700 text-white font-medium py-2 px-4 rounded-lg transition"
            >
                🖨️ Print Memo
            </button>
            
            <a
                href="/qnr/dashboard"
                class="bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium py-2 px-4 rounded-lg transition inline-flex items-center"
            >
                Dashboard
            </a>
        </div>
    </div>
</div>
```

---

## Database Migration

```bash
# Generate migration
uv run alembic revision --autogenerate -m "Add memos table"

# Apply migration
uv run alembic upgrade head
```

---

## Implementation Checklist

### Phase 1: Core Workflow (MVP)
- [x] Add `Memo` model to `smeme/core/models.py`
- [x] Add `MemoContent` and `MemoGenerationState` (created in `smeme/memo/models.py`)
- [x] Create memo workflow with all nodes (created in `smeme/memo/memo_workflow.py`)
- [x] Add `/generate_memo` route (created in `smeme/memo/routes.py`)
- [x] Add "Generate Memo" button to completion screen (updated to call `/memo/generate_memo`)
- [x] Include memo router in `smeme/main.py`
- [x] Create `smeme/templates/qnr/memo.html` template
- [x] Create migration for `memos` table (manually fixed Alembic autogenerate issues)
- [x] Apply migration (successfully migrated database)
- [ ] Test workflow with completed QNR session
- [ ] Verify structured logging output

### Phase 2: Enhancements (Future)
- [ ] Add memo versioning (regenerate button)
- [ ] Add export to PDF functionality
- [ ] Add email delivery option
- [ ] Cache memos (don't regenerate for same session)
- [ ] Add custom memo templates based on QNR type
- [ ] Add user feedback on memo quality

---

## Open Questions for Discussion

### 1. **Memo Persistence Strategy** ✅ DECIDED
- **Decision**: One memo per session (no regeneration)
- **Rationale**: Simpler, cheaper, prevents abuse
- **Implementation**: Check if memo exists before generating (see caching below)

### 2. **Caching Strategy** ✅ DECIDED
- **Decision**: Return existing memo if already generated for this session
- **Rationale**: Fast, free, consistent results
- **Implementation**: 
  - Add query in `load_session_node` to check for existing memo
  - If found, skip to `render_memo_node` with existing data
  - If not found, proceed through full workflow

### 3. **Error Handling**
- **Question**: What if LLM call fails?
- **Options**:
  - A: Show error, let user retry
  - B: Automatic retry with exponential backoff
  - C: Queue job for background processing
- **Recommendation**: Start with A (immediate feedback), add B for production

### 4. **Model Selection**
- **Question**: Which OpenAI model for memo generation?
- **Options**:
  - A: `gpt-4o-mini` (faster, cheaper, sufficient for summaries)
  - B: `gpt-4o` (better quality, more expensive)
  - C: Let users choose based on subscription tier
- **Recommendation**: A for MVP, C for future premium feature

### 5. **Memo Access Control**
- **Question**: Who can access generated memos?
- **Current**: Only the user who completed the QNR
- **Future**: Share with others? Download as PDF?
- **Recommendation**: Keep private for MVP, add sharing later

### 6. **Recommendations Format** ✅ DECIDED
- **Decision**: Ask LLM to return recommendations as markdown
- **Rationale**: Easy to render, human-readable in DB, flexible
- **Implementation**: Update system prompt to request markdown format, use `| safe` filter in template

### 7. **Validation Node** ✅ DECIDED
- **Decision**: No validation node needed
- **Rationale**: OpenAI structured outputs + Pydantic handle it automatically
- **Note**: If quality issues arise, can add content validation in Phase 2

### 8. **Template Location** ✅ DECIDED
- **Decision**: `smeme/templates/qnr/memo.html`
- **Rationale**: Memo is part of QNR feature, keep templates together
- **Note**: If we add non-QNR memos later, can refactor to `templates/memo/`

### 9. **Template Customization**
- **Question**: Should memo format/style vary by QNR type?
- **Example**: Technical QNR might need code snippets, business QNR needs ROI focus
- **Recommendation**: Start with generic template, add customization if needed

### 10. **Rate Limiting**
- **Question**: Should we limit memo generation attempts?
- **Consideration**: Prevent abuse, manage costs
- **Note**: Since we're caching (one memo per session), this is less critical
- **Recommendation**: Monitor usage, add limits only if abuse detected

---

## Cost Estimation

**OpenAI Pricing (gpt-4o-mini):**
- Input: $0.15 / 1M tokens
- Output: $0.60 / 1M tokens

**Estimated per Memo:**
- Input: ~500 tokens (Q&A pairs + system prompt)
- Output: ~300 tokens (title + summary + recommendations)

**Cost per memo:** ~$0.0003 (0.03 cents)  
**Cost for 1000 memos:** ~$0.30

Very affordable for MVP.

---

## Testing Strategy

```python
# tests/test_memo_workflow.py

@pytest.mark.asyncio
async def test_memo_generation_success(db_session, completed_qnr_session):
    """Test successful memo generation."""
    from smeme.qnr.memo_workflow import build_memo_workflow
    
    workflow = build_memo_workflow()
    
    initial_state = {
        "session_id": str(completed_qnr_session.id),
        "user_id": str(completed_qnr_session.user_id),  # Convert UUID to string
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={
            "configurable": {
                "db": db_session,
                "openai_client": mock_openai_client,
                "user_id": completed_qnr_session.user_id,  # Pass UUID directly
            }
        }
    )
    
    assert result["error"] is None
    assert result["memo_id"] is not None
    assert "rendered_html" in result
    assert len(result["rendered_html"]) > 0


@pytest.mark.asyncio
async def test_memo_generation_unauthorized(db_session, completed_qnr_session):
    """Test that users can't generate memos for other users' sessions."""
    from uuid import uuid4
    
    workflow = build_memo_workflow()
    
    different_user_id = uuid4()  # Different user
    
    initial_state = {
        "session_id": str(completed_qnr_session.id),
        "user_id": str(different_user_id),  # Different user as string
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={
            "configurable": {
                "db": db_session,
                "openai_client": mock_openai_client,
                "user_id": different_user_id,  # Pass UUID directly
            }
        }
    )
    
    assert result["error"] == "Unauthorized"
```

---

## Summary

This plan outlines a straightforward LangGraph workflow for memo generation that:

✅ **Follows all patterns** from the integration guide  
✅ **Simple linear flow** (no complex conditional routing needed)  
✅ **Reuses existing infrastructure** (OpenAI client, auth, HTMX)  
✅ **Structured logging** throughout  
✅ **Type-safe** with Pydantic V2  
✅ **Cost-effective** (~$0.30 per 1000 memos)  

**Next Steps**: Discuss open questions and refine plan before implementation.

## Lessons Learned

### 1. **Always Review Existing Models First**
Before defining new database models, read `smeme/core/models.py` to understand:
- Import patterns and conventions
- Field type patterns (UUID, Mapped, etc.)
- Timestamp handling
- Model configuration placement

**What we caught:**
- Incorrect import statements (using wrong UUID import)
- Wrong user_id type (int vs UUID)
- Missing Mapped[datetime] wrapper
- Wrong foreign key table name (user.id vs users.id)

### 2. **UUID Type Consistency**
- **Import**: Use `from uuid import UUID, uuid4` (stdlib, not sqlalchemy.dialects.postgresql)
- **Model fields**: `id: UUID = Field(default_factory=uuid4, primary_key=True)`
- **State (TypedDict)**: `user_id: str` (UUIDs must be serializable, use strings)
- **Config (runtime)**: `user_id: UUID` (pass actual UUID objects)
- **Workflow nodes**: Extract as `user_id: UUID = config["configurable"]["user_id"]`

### 3. **Timestamp Pattern**
All timestamp fields must use:
```python
from sqlalchemy.orm import Mapped
from datetime import UTC, datetime

created_at: Mapped[datetime] = Field(
    sa_column=Column(
        DateTime(timezone=True),
        default_factory=lambda: datetime.now(UTC),
        server_default=sa.func.now(),
    )
)
```
- **Mapped[datetime]**: Tells SQLAlchemy/MyPy this is a datetime
- **DateTime(timezone=True)**: PostgreSQL TIMESTAMP WITH TIME ZONE
- **default_factory**: Python-side default for direct instantiation
- **server_default**: Database-side default for SQL inserts

### 4. **Import Organization**
Follow this pattern from existing models:
```python
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa  # ← "as sa" pattern
from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped
from sqlmodel import Field, SQLModel
```

### 5. **Model Structure Order**
```python
class MyModel(SQLModel, table=True):
    """Docstring."""
    
    model_config = {"arbitrary_types_allowed": True}  # ← First
    
    __tablename__ = "my_models"  # ← Second
    
    # Then fields in order: id, foreign keys, data fields, timestamps
```

### 6. **Foreign Key Table Names**
- ✅ `foreign_key="users.id"` (plural, matches actual table name)
- ❌ `foreign_key="user.id"` (common mistake)

Check `__tablename__` in the referenced model to verify.

### 7. **Dict Type Hints**
- **Modern Python**: `dict[str, Any]` (not `dict`)
- **Specific types**: `dict[str, str]` for Q&A pairs
- **Import**: Need `from typing import Any` for generic dicts

### 8. **State vs Config Type Split**
- **State (TypedDict)**: Serializable types only (str, int, list, dict)
  - `session_id: str` ← UUID as string
  - `user_id: str` ← UUID as string
- **Config (RunnableConfig)**: Can pass actual Python objects
  - `"user_id": user.id` ← Pass UUID object
  - `"db": db` ← Pass AsyncSession
  - `"openai_client": client` ← Pass client instance

### 9. **Avoid Manual Timestamp Setting**
Don't manually set timestamps that have default_factory:
```python
# ❌ WRONG
memo = Memo(..., generated_at=datetime.now(UTC))

# ✅ CORRECT - Let the model handle it
memo = Memo(...)  # generated_at set automatically
```

### 10. **Cache Function Naming**
Use consistent naming in cache helpers:
```python
async def get_cached_memo(session_id: UUID) -> Optional[Memo]:
async def cache_memo(session_id: UUID, memo: Memo) -> None:
async def invalidate_memo_cache(session_id: UUID) -> None:
```
Pattern: `get_cached_*`, `cache_*`, `invalidate_*_cache`

### 11. **Two-Tier Caching Logging**
Always log with `cache_layer` for observability:
```python
logger.info(
    "Data loaded from L1 cache",
    extra={
        "cache_layer": "L1_aiocache",  # ← Critical for metrics
        "cache_hit": True,
        "elapsed_ms": round(elapsed_ms, 2),
    }
)
```

### 12. **Test Data Types**
When writing tests, use proper types:
```python
# ❌ WRONG
"user_id": 99999  # Using int for UUID

# ✅ CORRECT
different_user_id = uuid4()
"user_id": str(different_user_id)  # UUID as string in state
```

### 13. **Centralized Dependency Management (FastAPI 2025)**
Use `smeme/core/dependencies.py` as single source of truth:
```python
# ❌ WRONG - Scattered imports across routes
from smeme.auth.users import current_active_user
from smeme.core.database import get_db
from smeme.core.llm import get_openai_client
from fastapi import Depends

@router.post("/route")
async def my_route(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
    openai: AsyncOpenAI = Depends(get_openai_client),
):

# ✅ CORRECT - Single import, clean Annotated pattern
from smeme.core.dependencies import AsyncSessionDep, CurrentUser, OpenAIClientDep

@router.post("/route")
async def my_route(
    user: CurrentUser,  # Self-documenting
    db: AsyncSessionDep,
    openai: OpenAIClientDep,
):
```

**Benefits:**
- Single import location for all routes
- Type-safe with `Annotated` pattern
- Easy to refactor (change once, affects all routes)
- Better IDE autocomplete and type checking
- Follows FastAPI 2025 best practices

### 14. **Singleton Client Pattern with `@lru_cache`**
For expensive-to-create clients (OpenAI, etc.):
```python
# smeme/core/llm.py
from functools import lru_cache
from openai import AsyncOpenAI

@lru_cache(maxsize=1)
def get_openai_client() -> AsyncOpenAI:
    """Singleton client - only created once."""
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=30.0,
        max_retries=3,
    )
```

**Why `@lru_cache`?**
- FastAPI official pattern for singletons
- Can override in tests via `app.dependency_overrides`
- Thread-safe
- Reuses connection pooling

### 15. **`Mapped` Import Source (Critical)**
`Mapped` is a SQLAlchemy type, not a SQLModel type:
```python
# ❌ WRONG - Will cause ImportError
from sqlmodel import Field, SQLModel, Mapped

# ✅ CORRECT - Import from sqlalchemy.orm
from sqlalchemy.orm import Mapped
from sqlmodel import Field, SQLModel
```

**Why this matters:**
- `Mapped` is used for type hints on timestamp columns
- Incorrect import causes server startup failure
- Easy to overlook when copying model templates

### 16. **Avoid Circular Imports with Centralized Dependencies**
When centralizing dependencies, avoid circular imports:
```python
# ❌ WRONG - Creates circular import
# smeme/core/dependencies.py
from smeme.auth.users import current_active_user

# smeme/auth/manager.py
from smeme.core.dependencies import get_db  # ← Circular!

# ✅ CORRECT - Import from source module
# smeme/auth/manager.py
from smeme.core.database import get_db  # ← Direct import
```

**Rule of thumb:**
- Core modules that are re-exported by `dependencies.py` should NOT import from `dependencies.py`
- They should import from their source modules directly
- Only route modules should import from `dependencies.py`

**Import hierarchy:**
```
smeme/core/database.py (defines get_db)
          ↓
smeme/auth/manager.py (imports get_db from database)
          ↓
smeme/auth/users.py (uses manager)
          ↓
smeme/core/dependencies.py (re-exports everything)
          ↓
smeme/*/routes.py (imports from dependencies)
```

### 17. **Alembic Autogenerate Limitations with `default_factory`**
Alembic's autogenerate cannot serialize Python `default_factory` functions:
```python
# ❌ WRONG - Alembic will fail with SyntaxError
# Generated migration has: default_factory=<function Memo.<lambda> at 0x...>

# ✅ CORRECT - Manually fix the migration file
# Remove default_factory from migration, keep only server_default
sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
```

**Common Alembic autogenerate issues:**
1. **default_factory serialization**: Remove from migration file (keep only `server_default`)
2. **AutoString type**: Change `sqlmodel.sql.sqltypes.AutoString` to `sa.String`
3. **Migration naming**: Use timestamp format: `YYYYMMDD_HHMM_description.py`

**Fix process:**
```bash
# If autogenerate fails:
1. Delete the broken migration file
2. Manually create migration with timestamp-based name
3. Copy structure from autogenerate output (visible before error)
4. Remove invalid syntax (default_factory, etc.)
5. Apply migration: uv run alembic upgrade head
```

### 18. **Module Organization for New Features**
When creating a new feature module:
```
smeme/
├── feature_name/
│   ├── __init__.py
│   ├── models.py        # Feature-specific Pydantic/TypedDict models
│   ├── routes.py        # FastAPI routes
│   ├── workflow.py      # LangGraph workflow (if needed)
│   └── helpers/         # Helper functions (optional)
│       ├── cache.py
│       ├── db_queries.py
│       └── validation.py
```

**Import conventions:**
- Models from same feature: `from smeme.feature_name.models import ...`
- Shared models: `from smeme.core.models import ...`
- Dependencies: `from smeme.core.dependencies import ...`
- Logger naming: `logger = logging.getLogger("smeme.feature_name.workflow")`
