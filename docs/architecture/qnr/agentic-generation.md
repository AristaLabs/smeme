# Agentic QNR Generation

## Overview

This document describes the **agentic QNR generation workflow** - the production system for creating high-quality questionnaires through web research, multi-stage LLM reasoning, and human-in-the-loop editing.

**Status**: Production (Active and maintained)  
**Location**: `smeme/qnr/generation/agentic/`  
**Route**: `POST /qnr/agentic/generate/`

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Why Agentic Generation?](#why-agentic-generation)
3. [Phase 1: Research & Analysis](#phase-1-research--analysis)
4. [Phase 2: Questionnaire Design](#phase-2-questionnaire-design)
5. [Phase 3: Build & Auto-Fix](#phase-3-build--auto-fix)
6. [State Management](#state-management)
7. [Error Handling & Degradation](#error-handling--degradation)
8. [Templates & UI Flow](#templates--ui-flow)
9. [Model Selection](#model-selection)
10. [Observability](#observability)

---

## Architecture Overview

### Three-Phase Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  Phase 1: RESEARCH & ANALYSIS                                       │
│  ─────────────────────────────────────────────────────────────────  │
│  • Tavily web search for relevant factors                           │
│  • LLM summarizes key concepts, constraints, edge cases             │
│  • Human reviews and edits factor list                              │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Phase 2: QUESTIONNAIRE DESIGN                                      │
│  ─────────────────────────────────────────────────────────────────  │
│  • Tavily search for decision patterns/checklists                   │
│  • LLM generates freeform questionnaire design (markdown)           │
│  • Human reviews and edits question flow                            │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Phase 3: BUILD & AUTO-FIX                                          │
│  ─────────────────────────────────────────────────────────────────  │
│  • LLM converts markdown → QNRGraph (structured output)             │
│  • Validate graph structure                                         │
│  • Apply deterministic auto-fixes                                   │
│  • Save QNR (always, even with remaining issues)                    │
│  • Open in editor                                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Technologies

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Workflow Engine** | LangGraph | Orchestration, state management, conditional routing |
| **Web Search** | Tavily API | Domain research, decision pattern discovery |
| **LLM Provider** | OpenAI (gpt-4o, gpt-4o-mini) | Text generation, structured output |
| **Validation** | Pydantic + Custom Logic | Schema validation, graph connectivity checks |
| **UI Framework** | HTMX + Jinja2 | Server-side rendering, dynamic updates |
| **Observability** | LangSmith | Workflow tracing, cost tracking |

---

## Why Agentic Generation?

### Advantages Over Simple Generation

| Feature | Simple Generation | Agentic Generation |
|---------|-------------------|-------------------|
| **Research** | ❌ LLM training data only | ✅ Live web search (Tavily) |
| **Reasoning** | ❌ Constrained by JSON format | ✅ Freeform thinking → structured output |
| **Quality** | ⚠️ Generic terminology | ✅ Domain-specific jargon and best practices |
| **Human Control** | ❌ No intermediate review | ✅ Edit factors and design before building |
| **Auto-Repair** | ⚠️ Simple retry loop | ✅ Intelligent deterministic fixes |

### When to Use Agentic Generation

**Use Agentic Generation for:**
- Domain-specific questionnaires (legal, medical, tax, technical)
- Decision trees requiring factual accuracy
- Topics requiring up-to-date information
- Complex branching logic
- Professional/high-stakes applications

**Simple Generation (deprecated) was suitable for:**
- Quick prototypes
- Internal team surveys
- Simple feedback forms
- General-purpose questionnaires

---

## Phase 1: Research & Analysis

### Purpose

Use web search to discover **relevant factors, concepts, and constraints** for the user's decision problem, then let the human author refine and approve this understanding before any questionnaire design.

### Flow

```
User Prompt: "Do I need to pay taxes on my crypto?"
         │
         ▼
┌────────────────────────────────────────────────────────────────┐
│ 1. Tavily Search: Relevant Factors                             │
│                                                                │
│    Query: "[USER PROMPT] key factors concepts constraints"     │
│    Results: "capital gains", "cost basis", "Form 8949",        │
│             "holding period", "taxable events"                 │
└────────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────┐
│ 2. LLM Summary (gpt-4o-mini)                                   │
│                                                                │
│    Input: User prompt + Tavily snippets                        │
│    Output: Concise markdown summary:                           │
│      • Key concepts                                            │
│      • Important thresholds/rules                              │
│      • Common edge cases/pitfalls                              │
└────────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────┐
│ 3. Human Review & Edit                                         │
│                                                                │
│    UI: Editable textarea with factor summary                   │
│    Human can:                                                  │
│      • Add/remove factors                                      │
│      • Clarify terminology                                     │
│      • Emphasize key areas                                     │
│                                                                │
│    On submit: Edited text → canonical "factors" context        │
└────────────────────────────────────────────────────────────────┘
```

### Implementation

**Search Node** (`smeme/qnr/generation/agentic/nodes/research.py`):

```python
async def search_and_summarize_node(
    state: AgenticQNRGenerationState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Phase 1: Search for relevant factors and analyze."""
    
    tavily_client = config["configurable"].get("tavily_client")
    user_prompt = state["user_prompt"]
    country = state.get("country")  # Optional jurisdiction
    
    # Tavily search with graceful degradation
    if tavily_client:
        try:
            search_kwargs = {
                "query": f"Provide exhaustive list of factors for: {user_prompt}",
                "max_results": 8,
                "search_depth": "advanced",
                "include_answer": "advanced",
                "exclude_domains": EXCLUDE_DOMAINS,  # Filter low-quality sources
            }
            if country:
                search_kwargs["country"] = country
            
            search_raw = await tavily_client.search(**search_kwargs)
            # ... (LLM analysis of results) ...
        except Exception as e:
            # Graceful degradation: Continue without web search
            logger.warning(f"Tavily failed, proceeding with LLM knowledge only: {e}")
            research_degraded = True
    else:
        # Tavily not configured
        research_degraded = True
    
    return {
        "research_context": analyzed_results,
        "research_degraded": research_degraded,
    }
```

### Graceful Degradation

When Tavily is unavailable:
1. LLM generates factor summary from training data only
2. UI shows warning banner: "Web search unavailable - using AI knowledge only"
3. Workflow continues normally
4. User can still edit and proceed

---

## Phase 2: Questionnaire Design

### Purpose

Use web search to discover **how experts structure decisions** (checklists, decision trees), then have a reasoning-capable LLM design the questionnaire in natural language (markdown). Human reviews and edits before conversion to graph structure.

### Why Freeform Design?

| Approach | Pros | Cons |
|----------|------|------|
| **Direct Structured Output** | Fast, deterministic | LLM fights JSON constraints, poor reasoning |
| **Freeform → Structured** | Better reasoning, human-readable | Extra conversion step |

We chose **freeform first** because:
1. LLM can think through branching logic without JSON constraints
2. Design is human-readable and editable before commitment
3. Easier to iterate on design
4. Natural format for humans

### Flow

```
Edited Factors (from Phase 1)
         │
         ▼
┌────────────────────────────────────────────────────────────────┐
│ 1. Tavily Search: Decision Patterns                            │
│                                                                │
│    Query: "[TOPIC] decision tree checklist how to decide"      │
│    Results: Expert flows, thresholds, decision frameworks      │
└────────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────┐
│ 2. LLM Design (gpt-4o)                                         │
│                                                                │
│    Input:                                                      │
│      • User prompt                                             │
│      • Edited factors                                          │
│      • Tavily decision patterns                                │
│                                                                │
│    Output: Structured markdown describing:                     │
│      • Questions (type, options, help text)                    │
│      • Branching logic                                         │
│      • Completion outcomes                                     │
└────────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────┐
│ 3. Human Review & Edit                                         │
│                                                                │
│    UI: Large textarea with full markdown design                │
│    Human can:                                                  │
│      • Add/remove questions                                    │
│      • Change wording, options                                 │
│      • Adjust branching descriptions                           │
│                                                                │
│    On submit: Edited markdown → source of truth for build      │
└────────────────────────────────────────────────────────────────┘
```

### Design Format (Markdown)

```markdown
## Questionnaire: Cryptocurrency Tax Liability

### Q1: Filing Status
- **Type**: radio
- **Options**: Single, Married filing jointly, Head of household
- **Required**: yes
- **Why we ask**: Determines tax brackets

### Q2: Transaction Types
- **Type**: checkbox
- **Options**: Bought, Sold, Traded, Staked, Mined
- **Required**: yes
- **Branching**:
  - If includes "Sold" → Q3 (holding period)
  - If includes "Staked" → Q4 (FMV tracking)
  - Default → Q5

### Q3: Holding Period
- **Type**: radio
- **Options**: Less than 1 year, 1 year or more, Mixed
- **Required**: yes
- **Why we ask**: Short-term vs long-term capital gains rates differ
- **Branching**: → Q5

...
```

### Implementation

**Design Node** (`smeme/qnr/generation/agentic/nodes/design.py`):

```python
async def design_questionnaire_node(
    state: AgenticQNRGenerationState,
    config: RunnableConfig,
) -> dict:
    """Generate freeform questionnaire design."""
    
    openai_client = config["configurable"]["openai_client"]
    
    # Use large model for complex reasoning
    response = await openai_client.chat.completions.create(
        model="gpt-4o",  # Reasoning-capable model
        messages=[
            {"role": "system", "content": DESIGN_QUESTIONNAIRE_PROMPT},
            {"role": "user", "content": f"""
                Topic: {state['user_prompt']}
                
                Relevant Factors:
                {state['research_context']}
                
                Decision Patterns:
                {state.get('decision_patterns_context', 'N/A')}
                
                Generate a complete questionnaire design in markdown format.
            """}
        ],
        temperature=0.7,
    )
    
    return {"questionnaire_design": response.choices[0].message.content}
```

---

## Phase 3: Build & Auto-Fix

### Purpose

Convert the human-edited markdown design into a validated `QNRGraph`, applying deterministic code-driven fixes for structural issues.

### Flow

```
Edited Markdown Design (from Phase 2)
         │
         ▼
┌────────────────────────────────────────────────────────────────┐
│ 1. Build QNRGraph (gpt-4o-mini structured output)              │
│                                                                │
│    Input: Markdown design                                      │
│    Output: QNRGraph (Pydantic model via structured output)     │
└────────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────┐
│ 2. Validate Graph                                              │
│                                                                │
│    Uses: validate_graph_for_editing()                          │
│    Checks:                                                     │
│      • Structural requirements (start/end nodes)               │
│      • Edge validity (valid sources/targets)                   │
│      • Graph connectivity (reachability)                       │
│      • Question-specific rules (radio has options)             │
└────────────────────────────────────────────────────────────────┘
         │
         ▼
    ┌───────┴────────┐
    │                │
[Valid]      [Has Issues]
    │                │
    │                ▼
    │        ┌─────────────────────────────────────────────────┐
    │        │ 3. Auto-Fix (Deterministic)                     │
    │        │                                                 │
    │        │ Fixes:                                          │
    │        │  • Self-loops → delete_edge()                   │
    │        │  • Duplicate edges → remove duplicates          │
    │        │  • Multiple defaults → keep first              │
    │        │  • Condition typos → fuzzy match to option      │
    │        │  • Orphan nodes → delete_node()                 │
    │        └─────────────────────────────────────────────────┘
    │                │
    │                ▼
    │        ┌─────────────────────────────────────────────────┐
    │        │ 4. Re-Validate                                  │
    │        └─────────────────────────────────────────────────┘
    │                │
    └────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────────────┐
│ 5. Save QNR (Always)                                           │
│                                                                │
│    Save to database regardless of remaining issues             │
│    Status:                                                     │
│      • "valid" - No issues                                     │
│      • "valid_with_warnings" - Minor suggestions               │
│      • "has_errors" - Needs manual fixes in editor             │
└────────────────────────────────────────────────────────────────┘
```

### Auto-Fix Strategy

**What Gets Auto-Fixed:**

| Issue Type | Auto-Fix Method | Example |
|------------|----------------|---------|
| **Self-loops** | ✅ Delete edge | `q1 → q1` → deleted |
| **Duplicate edges** | ✅ Remove duplicates | `q1 → q2` (x3) → keep 1 |
| **Multiple defaults** | ✅ Keep first | 3 default edges → keep first |
| **Condition typo** | ✅ Fuzzy match | "Yess" → "Yes" (90% match) |
| **Orphan nodes** | ✅ Delete node | Node with no edges → deleted |
| **Missing default** | ✅ Add edge to next | Radio without default → add edge |

**What Doesn't Get Auto-Fixed:**
- Content issues (wrong question text, missing questions)
- Complex logical flaws (requires LLM or human)
- Ambiguous branching conditions

### Implementation

**Auto-Fix** (`smeme/qnr/generation/agentic/auto_fix.py`):

```python
def auto_fix_graph(
    graph: QNRGraph,
    errors: list[str],
    warnings: list[str]
) -> tuple[QNRGraph, list[str], list[str], list[str]]:
    """
    Apply deterministic fixes using existing editor operations.
    
    Reuses: create_edge(), delete_edge(), update_edge(), delete_node()
    from smeme/qnr/editor/operations.py
    """
    remaining_errors = []
    remaining_warnings = []
    fixes_applied = []
    
    for error in errors:
        fixed = False
        
        # Self-loop detection: "Self-loop detected on node 'q3'"
        if match := re.search(r"Self-loop detected on node '(\w+)'", error):
            node_id = match.group(1)
            graph = delete_edge(graph, source=node_id, target=node_id)
            fixes_applied.append(f"Removed self-loop on '{node_id}'")
            fixed = True
        
        # Condition typo: "Condition 'Yess' from 'q1' must match an option"
        elif match := re.search(r"Condition '(.+)' from '(\w+)'", error):
            condition, node_id = match.group(1), match.group(2)
            result = _fuzzy_fix_condition(graph, node_id, condition)
            if result:
                graph, corrected = result
                fixes_applied.append(f"Fixed typo '{condition}' → '{corrected}'")
                fixed = True
        
        # ... (more fix patterns) ...
        
        if not fixed:
            remaining_errors.append(error)
    
    return graph, remaining_errors, remaining_warnings, fixes_applied
```

### Why Not Tool-Calling Agent?

We explicitly avoided using a tool-calling LLM agent for fixes:

| Problem | Impact |
|---------|--------|
| **Unpredictable sequencing** | Might add edge before target node exists |
| **Parameter hallucination** | Invents non-existent node IDs |
| **Loop risk** | Gets stuck repeating same failed fix |
| **Partial fixes** | Fixes one error, creates two more |
| **Cost** | Multiple LLM calls per fix |
| **Opacity** | Hard to debug "Why did it do that?" |

Deterministic fixes are:
- ✅ Predictable
- ✅ Cheap (no LLM calls)
- ✅ Debuggable
- ✅ Bounded (finite fix patterns)

---

## State Management

### State Schema

```python
class AgenticQNRGenerationState(TypedDict):
    """
    LangGraph state for agentic QNR generation.
    
    CRITICAL: TypedDict is a SILENT DATA FILTER - any field not
    declared here will be dropped between nodes!
    """
    
    # === Input ===
    user_prompt: str
    user_id: str  # UUID as string (actual UUID in config)
    country: NotRequired[str]  # ISO country for Tavily
    
    # === Phase 1: Research ===
    research_context: NotRequired[str]         # Analyzed factors (markdown)
    research_degraded: NotRequired[bool]       # True if Tavily failed
    
    # === Phase 2: Design ===
    decision_patterns_context: NotRequired[str]  # Pattern analysis (markdown)
    questionnaire_design: NotRequired[str]       # Initial design
    questionnaire_design_edited: NotRequired[str]  # Human-edited
    
    # === Phase 3: Build & Fix ===
    generated_graph: NotRequired[dict]         # QNRGraph as dict
    validation_errors: NotRequired[list[str]]
    validation_warnings: NotRequired[list[str]]
    fixes_applied: NotRequired[list[str]]
    
    # === Output ===
    qnr_id: NotRequired[str]                   # UUID as string
    final_status: NotRequired[Literal["valid", "valid_with_warnings", "has_errors"]]
    
    # === Error Handling ===
    error: NotRequired[str]                    # Fatal error (stops workflow)
    error_recoverable: NotRequired[bool]       # True = show retry button
```

### Dependency Injection Pattern

Following `docs/LANGGRAPH_INTEGRATION_GUIDE.md`:

```python
# In routes
from smeme.core.dependencies import AsyncSessionDep, OpenAIClientDep, CurrentUser
from smeme.core.search import get_tavily_client, TavilyNotConfiguredError

@router.post("/generate/{thread_id}")
async def generate_agentic_qnr(
    thread_id: str,
    user_prompt: str = Form(...),
    country: str | None = Form(None),
    user: CurrentUser = ...,
    db: AsyncSessionDep = ...,
    openai_client: OpenAIClientDep = ...,
):
    # Get Tavily client (optional)
    try:
        tavily_client = get_tavily_client()
    except TavilyNotConfiguredError:
        tavily_client = None
        logger.warning("Tavily not configured, proceeding without web search")
    
    # Prepare workflow config
    config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user.id,
            "db": db,
            "openai_client": openai_client,
            "tavily_client": tavily_client,  # May be None
        }
    }
    
    # Execute workflow
    result = await workflow.ainvoke(initial_state, config=config)
    return result
```

**Key Pattern:**
- **State**: Only serializable data (strings, dicts, lists)
- **Config**: Dependencies (DB session, API clients, UUIDs)
- Nodes extract dependencies from `config["configurable"]`

---

## Error Handling & Degradation

### Strategy: Hybrid Approach

| API | Failure Response | Rationale |
|-----|------------------|-----------|
| **Tavily** | ✅ Graceful degradation | User can proceed with LLM-only generation |
| **OpenAI** | ❌ Hard fail | Cannot proceed without LLM |

### Tavily Failures → Graceful Degradation

When Tavily is unavailable (rate limit, API down, network error):

1. **Node catches error**:
   ```python
   try:
       result = await tavily_client.search(...)
       return {"research_context": analyzed}
   except (httpx.TimeoutException, httpx.ConnectError) as e:
       logger.warning(f"Tavily search failed: {e}")
       return {
           "research_context": llm_only_analysis,
           "research_degraded": True,
           "search_skip_reason": "Web search temporarily unavailable",
       }
   ```

2. **UI shows warning banner**:
   ```html
   {% if research_degraded %}
   <div class="bg-yellow-50 border-l-4 border-yellow-400 p-4">
       <p><strong>Note:</strong> Web search was unavailable. 
          These suggestions are based on AI knowledge only.</p>
   </div>
   {% endif %}
   ```

3. **Workflow continues normally** - user can still edit and proceed

### OpenAI Failures → Hard Fail

When OpenAI is unavailable:

1. **Node returns error in state**:
   ```python
   try:
       response = await openai_client.chat.completions.create(...)
       return {"questionnaire_design": response.choices[0].message.content}
   except (OpenAIAPIError, httpx.TimeoutException) as e:
       logger.error(f"OpenAI API failed: {e}")
       return {
           "error": "AI service temporarily unavailable. Please try again.",
           "error_recoverable": True,
       }
   ```

2. **UI shows error with retry button**:
   ```html
   <div class="bg-red-50 border-l-4 border-red-400 p-4">
       <h3 class="font-medium text-red-800">Service Temporarily Unavailable</h3>
       <p class="text-red-700">{{ error_message }}</p>
       <button hx-post="/qnr/agentic/retry/{{ thread_id }}" 
               class="mt-4 bg-red-600 text-white px-4 py-2 rounded">
           Try Again
       </button>
   </div>
   ```

---

## Templates & UI Flow

### Template Files

```
smeme/templates/qnr/generation/
├── agentic/
│   ├── start.html              # Initial form (prompt + country picker)
│   ├── _research_review.html   # Phase 1: Review & edit factors
│   ├── _design_review.html     # Phase 2: Review & edit design
│   ├── _progress.html          # Spinner during processing
│   └── _result.html            # Final result with status
```

### UI Flow

```
1. Start Form
   ↓ (POST /qnr/agentic/generate)
   
2. Research Review
   - Show factor summary in textarea
   - Human edits
   ↓ (POST /qnr/agentic/research/submit)
   
3. Design Review
   - Show questionnaire design in textarea
   - Human edits
   ↓ (POST /qnr/agentic/design/submit)
   
4. Build & Fix
   - Show spinner
   - Auto-fix runs
   ↓ (Workflow completes)
   
5. Result
   ┌─────────────────────────────┐
   │ ✅ Valid                     │
   │ "Your questionnaire is ready"│
   │ [Open in Editor]            │
   └─────────────────────────────┘
   
   ┌─────────────────────────────┐
   │ ⚠️ Valid with Warnings       │
   │ "Created with suggestions:"  │
   │ • Warning 1                 │
   │ • Warning 2                 │
   │ [Review in Editor]          │
   └─────────────────────────────┘
   
   ┌─────────────────────────────┐
   │ 🔧 Has Errors                │
   │ "Needs manual fixes:"        │
   │ • Error 1                   │
   │ • Error 2                   │
   │ [Fix in Editor]             │
   └─────────────────────────────┘
```

### Country Picker (HTMX)

```html
<!-- Searchable country dropdown -->
<input type="hidden" id="country" name="country" value="united states">
<input
    id="country_search"
    type="text"
    placeholder="Type a country..."
    hx-get="/qnr/agentic/countries"
    hx-target="#country-options"
    hx-trigger="keyup changed delay:250ms"
>
<div id="country-options">
    <!-- HTMX loads matching countries here -->
</div>
```

**Route** (`/qnr/agentic/countries`):
- Fuzzy-matches user input against Tavily country enum
- Returns clickable list of matching countries
- On click: Updates hidden field + search box, clears dropdown

---

## Model Selection

Hard-coded for optimal cost/quality:

| Task | Model | Rationale |
|------|-------|-----------|
| **Research analysis** | `gpt-4o-mini` | Simple summarization of search results |
| **Questionnaire design** | `gpt-4o` | Complex reasoning for branching logic |
| **Build graph** | `gpt-4o-mini` | Mechanical conversion (structured output) |

**Temperature Settings:**
- Research: `0.3` (factual analysis)
- Design: `0.7` (creative but structured)
- Build: `0.2` (deterministic conversion)

**Cost Optimization:**
- Use `gpt-4o-mini` for simple tasks (50x cheaper)
- Reserve `gpt-4o` for complex reasoning (design phase only)
- Typical generation: $0.03 - $0.08 per QNR

---

## Observability

### Structured Logging

All nodes use structured logging with context:

```python
logger.info(
    "Phase 1: Research completed",
    extra={
        "user_id": str(user_id),
        "node": "search_and_summarize",
        "phase": 1,
        "elapsed_ms": round(elapsed_ms, 2),
        "result_count": len(search_results),
        "degraded": research_degraded,
    },
)
```

**Key Fields:**
- `user_id`: Filter by user
- `node`: LangGraph node name
- `phase`: Current phase (1-3)
- `elapsed_ms`: Performance tracking
- `degraded`: Whether degradation occurred

### LangSmith Integration

Automatically traces:
1. **Workflow execution**: Start/end times, state snapshots
2. **Each node**: Input state, output state, duration
3. **LLM calls**: Full prompts, completions, token counts, **costs**
4. **Tavily searches**: Queries, result counts (as tool calls)
5. **Conditional edges**: Which branch taken

**Dashboard Queries:**
- "Total cost per generation"
- "Average generation time by phase"
- "Tavily failure rate"
- "Auto-fix success rate"

**Setup** (already configured):
```bash
# .env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_key
LANGCHAIN_PROJECT=smeme_v2
```

### Production Debugging

1. **User reports issue** → Find in logs by `user_id`
2. **Open LangSmith trace** → See every node, LLM call, state change
3. **Identify bottleneck** → Usually Phase 2 (design) or Tavily timeout
4. **Fix and monitor** → Re-run with logging to verify

---

## Comparison: Simple vs. Agentic

| Dimension | Simple Generation | Agentic Generation |
|-----------|-------------------|-------------------|
| **Status** | ❌ Deprecated prototype | ✅ Production (active) |
| **Route** | `/qnr/generate/` | `/qnr/agentic/generate/` |
| **Workflow** | 4 nodes (linear) | 10+ nodes (3 phases) |
| **Research** | None | Tavily web search |
| **Human Input** | Prompt only | Prompt + edit factors + edit design |
| **LLM Reasoning** | Constrained by JSON | Freeform → structured |
| **Auto-Fix** | Simple retry | Intelligent deterministic fixes |
| **Cost** | ~$0.01 per QNR | ~$0.05 per QNR |
| **Time** | ~10 seconds | ~45 seconds |
| **Quality** | ⚠️ Generic | ✅ Domain-specific, research-backed |
| **Use Case** | Quick prototypes | Professional applications |

---

## Next Steps

### Current State
- ✅ All 3 phases implemented
- ✅ Tavily integration with graceful degradation
- ✅ Human-in-the-loop editing at both review points
- ✅ Deterministic auto-fix with editor operations
- ✅ HTMX UI with country picker
- ✅ LangSmith observability
- ✅ Production-ready error handling

### Future Enhancements

**Phase 3 Verification** (Optional, not in MVP):
- Additional Tavily searches to verify factual claims
- Deep research mode (controlled by checkbox)
- Fact-checking specific thresholds and requirements

**Performance Optimizations:**
- Cache frequent research queries (e.g., "US tax brackets")
- Parallel Tavily searches (factors + patterns simultaneously)
- Streaming UI updates during long operations

**Quality Improvements:**
- A/B test different design prompts
- Collect user feedback on generated QNRs
- Fine-tune auto-fix patterns based on production data

---

## References

- **Implementation**: `smeme/qnr/generation/agentic/`
- **Routes**: `smeme/qnr/generation/agentic/routes/` (package; `__init__.py` includes phase routers)
- **Workflow**: `smeme/qnr/generation/agentic/workflow.py`
- **Auto-Fix**: `smeme/qnr/generation/agentic/auto_fix.py`
- **Templates**: `smeme/templates/qnr/generation/agentic/`
- **Plan Document**: `docs/AGENTIC_QNR_GENERATION_PLAN.md` (original design)
- **LangGraph Guide**: `docs/LANGGRAPH_INTEGRATION_GUIDE.md` (patterns)
- **Simple Generation** (deprecated): `docs/QNR_GENERATION_ORCHESTRATION.md`

