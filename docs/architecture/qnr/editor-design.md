# QNR Graph Viewer & Editor Workflows - Implementation Plan

## Overview

This document outlines the plan to implement **two separate LangGraph workflows** for QNR graph visualization and editing:

1. **QNR Viewer Workflow**: Fast, cacheable, read-only visualization
2. **QNR Editor Workflow**: Stateful CRUD operations on nodes and edges

This separation provides clear boundaries, better caching strategies, and independent scaling.

---

## Lessons Learned (Nov 2025 Iteration)

Recent development and bug-fix sessions surfaced several important insights that influence both the implementation and future roadmap:

1. **Ensure Every Node Gets a Position**  
   Disconnected or reverse-only nodes were occasionally omitted by the BFS layer assignment, causing them to render off-canvas. The layout algorithm now appends any unlayered nodes to additional layers, guaranteeing full coverage.

2. **SVG `viewBox` + Explicit Height Improves Scrolling**  
   Relying on `height:auto` prevented the scroll container from recognising the full canvas height. Setting a `viewBox` and fixed pixel height enables native scrolling without distorting aspect ratio.

3. **UI Scroll & Resize Enhancements**  
   The graph container now uses `overflow:auto` with `max-height: calc(100vh - 200px)` so authors can reach deep layers. The side-panel is marked `resize:horizontal`, giving users control of workspace width.

4. **Full-page vs Partial Template Rendering**  
   A `full_page` flag in the viewer workflow lets the initial GET request return the complete `editor.html` (including base layout and scripts) while subsequent HTMX swaps return only `_editor_content.html`. This keeps the payload small after the first load.

5. **Consistent `success` Flags in Editor Workflow**  
   Every node in the editor pipeline now sets an explicit `success: True/False` to avoid ambiguous conditional edges and guarantee deterministic early exits.

6. **UI-First Debugging Pays Off**  
   Small CSS tweaks (overflow, resize, flex gaps) quickly resolved perceived backend issues ("missing" nodes). Invest in front-end diagnostics before assuming algorithmic failure.

These lessons have already been incorporated into the codebase and should inform future phases, especially advanced features like zoom/pan and curriculum builder.

## Goals

### QNR Viewer Workflow
**Input**: QNR ID, optional selection state  
**Output**: Graph visualization with edit controls (read-only UI)  
**Trigger**: User navigates to `/qnr/{qnr_id}/editor` or after completing an edit operation  
**Characteristics**: Fast, cacheable, simple state

### QNR Editor Workflow
**Input**: QNR ID, operation type, changes  
**Output**: Updated QNR in database, cache invalidation  
**Trigger**: User submits CRUD operation (create, update, delete node/edge)  
**Characteristics**: Stateful, transactional, validation-heavy

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    QNR Editor Page Flow                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  User clicks "Edit QNR" → GET /qnr/{qnr_id}/editor                  │
│                                                                     │
│         ↓                                                           │
│  ┌────────────────────────────────────────────────┐                 │
│  │  QNR VIEWER WORKFLOW (Read-Only)               │                 │
│  │  smeme/qnr/viewer/workflow.py                  │                 │
│  ├────────────────────────────────────────────────┤                 │
│  │  Node 1: Load QNR Graph (with cache)           │                 │
│  │  Node 2: Generate Visualization Data           │                 │
│  │  Node 3: Render Editor UI (read-only)          │                 │
│  └────────────────────────────────────────────────┘                 │
│         ↓                                                           │
│  Returns: HTML with graph visualization + side panel                │
│                                                                     │
│  ┌─────────────────────────┐  ┌──────────────────────────┐          │
│  │ Graph Visualization     │  │  Side Panel (CRUD Form)  │          │
│  │ • Clickable nodes       │  │  • Create/Update/Delete  │          │
│  │ • Selection highlighting│  │  • Split/Merge buttons   │          │
│  └─────────────────────────┘  └──────────────────────────┘          │
│                                           │                         │
│                                           │ User clicks "Save"      │
│                                           ↓                         │
│                    POST /qnr/editor/update_node                     │
│                                           ↓                         │
│  ┌────────────────────────────────────────────────┐                 │
│  │  QNR EDITOR WORKFLOW (Write)                   │                 │
│  │  smeme/qnr/editor/workflow.py                  │                 │
│  ├────────────────────────────────────────────────┤                 │
│  │  Node 1: Load QNR (no cache, always fresh)     │                 │
│  │  Node 2: Parse Edit Request                    │                 │
│  │  Node 3: Apply CRUD Operation                  │                 │
│  │  Node 4: Validate Graph                        │                 │
│  │  Node 5: Save to Database                      │                 │
│  │  Node 6: Invalidate Cache                      │                 │
│  └────────────────────────────────────────────────┘                 │
│         ↓                                                           │
│  Returns: Redirect → GET /qnr/{qnr_id}/editor                       │
│                                                                     │
│         ↓                                                           │
│  Viewer workflow re-runs with updated data                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

Performance:
- Viewer initial load: ~100-200ms (cached)
- Viewer subsequent loads: ~20-50ms (cache hit)
- Editor operations: ~150-300ms (validate + DB write + cache invalidation)
- No LLM calls in either workflow (pure data manipulation)
```

---

## Two-Workflow Design Rationale

### Why Two Workflows?

#### 1. **Clear Separation of Concerns**
- **Viewer**: Read-only, fast, cacheable, simple state
- **Editor**: Write operations, transactional, validation-heavy, complex state

#### 2. **Better Caching Strategy**
- **Viewer**: Aggressively cache (same strategy as navigation workflow)
- **Editor**: Always load fresh data, invalidate cache on save
- No confusion about when to cache

#### 3. **Independent Scaling**
- Viewing is high-frequency, low-cost (can be heavily cached)
- Editing is low-frequency, high-cost (validation, DB writes)
- Different performance profiles → different workflows

#### 4. **Simpler State Management**
```python
# Viewer State (Simple, Read-Only)
class QNRViewerState(TypedDict):
    qnr_id: str
    graph: dict
    selected_node_id: str | None
    selected_edge_id: str | None
    visualization: dict
    rendered_output: str

# Editor State (Complex, Transactional)
class QNREditorState(TypedDict):
    qnr_id: str
    graph: dict
    operation: Literal["create_node", "update_node", "delete_node", ...]
    target_id: str | None
    changes: dict
    validation_errors: list[str]
    retry_count: int
    success: bool
```

#### 5. **Cleaner Routing Pattern**
```python
# Viewer route (GET - read-only)
@router.get("/qnr/{qnr_id}/editor")
async def view_qnr_editor(qnr_id: int):
    """Render editor UI using viewer workflow (cached)"""
    result = await qnr_viewer_workflow.invoke({"qnr_id": qnr_id})
    return HTMLResponse(result["rendered_output"])

# Editor routes (POST - write operations)
@router.post("/qnr/editor/update_node")
async def edit_qnr_node(qnr_id: int, changes: dict):
    """Apply edit using editor workflow (no cache)"""
    result = await qnr_editor_workflow.invoke({
        "qnr_id": qnr_id,
        "operation": "update_node",
        "changes": changes
    })
    # Redirect back to viewer (htmx swap re-renders using cached viewer)
    return RedirectResponse(f"/qnr/{qnr_id}/editor")
```

#### 6. **Easier Testing**
- Test viewer without DB write permissions
- Test editor operations in isolation
- Mock viewer for editor tests, and vice versa

#### 7. **Follows Existing Pattern**
Similar to Generation + Navigation:
- **Generation workflow**: Heavy, stateful, creates QNRs
- **Navigation workflow**: Light, cached, consumes QNRs

New pattern:
- **Viewer workflow**: Light, cached, reads QNRs
- **Editor workflow**: Heavy, stateful, modifies QNRs

#### 8. **Better Error Handling**
- Viewer failures are non-critical (just re-render)
- Editor failures need rollback, validation retry logic
- Different error recovery strategies

---

## Data Models

### 1. Viewer Workflow State (`smeme/qnr/viewer/models.py`)

**Note**: This file also contains the visual models (`NodePosition`, `VisualNode`, `VisualEdge`, `GraphVisualization`) that are ephemeral outputs of the Viewer Workflow. These models are NOT used by the Editor Workflow.

```python
"""State for QNR viewer workflow (read-only)."""

from typing import TypedDict, NotRequired
from pydantic import BaseModel, Field


# Visual Models (ephemeral, never persisted)
class NodePosition(BaseModel):
    """Position of a node in the visualization."""
    x: float
    y: float
    width: float = 200.0
    height: float = 80.0


class VisualNode(BaseModel):
    """Node with position for rendering."""
    id: str
    type: str
    data: dict
    position: NodePosition


class VisualEdge(BaseModel):
    """Edge with rendering metadata."""
    source: str
    target: str
    condition: str | None = None
    path: str  # SVG path string


class GraphVisualization(BaseModel):
    """Complete visualization of a QNR graph."""
    nodes: list[VisualNode]
    edges: list[VisualEdge]
    width: float
    height: float


# Workflow State (used by LangGraph)
class QNRViewerState(TypedDict):
    """LangGraph workflow state for QNR viewer."""
    
    # Input
    qnr_id: str
    user_id: str
    
    # Optional selection state (for highlighting selected node)
    selected_node_id: NotRequired[str | None]
    
    # Loaded data (from DB)
    graph: NotRequired[dict]  # QNRGraph as dict (semantic data)
    
    # Generated visualization (ephemeral, from layout algorithm)
    visualization: NotRequired[dict]  # GraphVisualization as dict (visual data)
    
    # UI state
    rendered_output: NotRequired[str]
    
    # Error handling
    error_message: NotRequired[str | None]
```

### 3. Editor Workflow State (`smeme/qnr/editor/models.py`)

```python
"""State for QNR editor workflow (write operations)."""

from typing import TypedDict, NotRequired, Literal


class QNREditorState(TypedDict):
    """LangGraph workflow state for QNR editor."""
    
    # Input
    qnr_id: str
    user_id: str
    
    # Operation details
    operation: Literal[
        "create_node",
        "update_node",
        "delete_node",
        "create_edge",
        "update_edge",
        "delete_edge",
        "split_qnr",
        "merge_qnr",
    ]
    target_id: NotRequired[str | None]  # Node ID or Edge ID
    changes: NotRequired[dict]  # Data to apply
    
    # Loaded data
    graph: NotRequired[dict]  # QNRGraph as dict (fresh from DB)
    
    # Validation
    validation_errors: NotRequired[list[str]]  # Blocking errors
    warnings: NotRequired[list[str]]  # Non-blocking warnings
    retry_count: NotRequired[int]
    
    # Result
    success: NotRequired[bool]
    error_message: NotRequired[str | None]
```

### 3. Edit Request Models (`smeme/qnr/editor/models.py`)

```python
"""Request models for edit operations."""

from pydantic import BaseModel, Field
from smeme.qnr.shared.models import NodePosition


class NodeUpdateRequest(BaseModel):
    """Update an existing node's data."""
    node_id: str
    text: str | None = None
    type: str | None = None  # "text", "number", "radio", "checkbox"
    options: list[str] | None = None
    required: bool | None = None
    help_text: str | None = None


class NodeCreateRequest(BaseModel):
    """Create a new node."""
    node_id: str  # User provides or auto-generate
    text: str
    type: str = "text"
    options: list[str] | None = None
    required: bool = True
    help_text: str | None = None
    position: NodePosition | None = None  # Optional initial position


class EdgeCreateRequest(BaseModel):
    """Create a new edge."""
    source: str
    target: str
    condition: str | None = None


class EdgeUpdateRequest(BaseModel):
    """Update an existing edge."""
    edge_id: str  # "{source}_{target}_{condition}"
    condition: str | None = None
```

---

## Workflow Implementations

### Workflow 1: QNR Viewer (Read-Only)

#### File: `smeme/qnr/viewer/workflow.py`

```python
"""LangGraph workflow for QNR graph viewing (read-only)."""

import logging
import time
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.types import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.qnr.viewer.models import QNRViewerState
from smeme.qnr.shared.models import GraphVisualization
from smeme.qnr.shared.layout import calculate_layout
from smeme.qnr.shared.renderer import render_graph_svg, render_side_panel
from smeme.qnr.helpers.db_queries import get_qnr_by_id, parse_graph_data
from smeme.qnr.helpers.validation import validate_graph
from smeme.qnr.models import QNRGraph
from smeme.core.cache import get_cached_qnr, set_cached_qnr

logger = logging.getLogger("smeme.qnr.viewer.workflow")


# ============================================================================
# Node 1: Load QNR Graph (with caching)
# ============================================================================

async def load_qnr_node(
    state: QNRViewerState,
    config: RunnableConfig
) -> QNRViewerState:
    """
    Load QNR graph from cache or database.
    
    Note: Viewer workflow aggressively caches because it's read-only.
    This is the same caching strategy as the navigation workflow.
    """
    start_time = time.time()
    
    db: AsyncSession = config["configurable"]["db"]
    user_id: UUID = config["configurable"]["user_id"]
    qnr_id = UUID(state["qnr_id"])
    
    logger.info(
        "Loading QNR for viewing",
        extra={
            "qnr_id": str(qnr_id),
            "user_id": str(user_id),
            "node": "load_qnr",
        },
    )
    
    # Try cache first
    cached_graph = await get_cached_qnr(qnr_id)
    if cached_graph:
        logger.info(
            "QNR loaded from cache",
            extra={"qnr_id": str(qnr_id), "node": "load_qnr"},
        )
        return {"graph": cached_graph}
    
    # Load from database
    qnr = await get_qnr_by_id(db, qnr_id)
    if not qnr:
        logger.warning(
            "QNR not found",
            extra={"qnr_id": str(qnr_id), "user_id": str(user_id), "node": "load_qnr"},
        )
        return {"error_message": f"QNR {qnr_id} not found"}
    
    # Verify ownership
    if qnr.author_id != user_id:
        logger.warning(
            "Unauthorized QNR access attempt",
            extra={"qnr_id": str(qnr_id), "user_id": str(user_id), "node": "load_qnr"},
        )
        return {"error_message": "Unauthorized"}
    
    try:
        graph = parse_graph_data(qnr)
        
        # Validate graph
        is_valid, error = validate_graph(graph)
        if not is_valid:
            logger.error(
                "Invalid graph structure",
                extra={
                    "qnr_id": str(qnr_id),
                    "validation_error": error,
                    "node": "load_qnr",
                },
            )
            return {"error_message": f"Invalid graph: {error}"}
        
        # Cache for future reads
        graph_dict = graph.model_dump()
        await set_cached_qnr(qnr_id, graph_dict)
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "QNR loaded from database and cached",
            extra={
                "qnr_id": str(qnr_id),
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "load_qnr",
            },
        )
        
        return {"graph": graph_dict}
        
    except Exception as e:
        logger.error(
            "Failed to parse graph",
            extra={"qnr_id": str(qnr_id), "error": str(e), "node": "load_qnr"},
            exc_info=True,
        )
        return {"error_message": str(e)}


# ============================================================================
# Node 2: Generate Visualization Data
# ============================================================================

async def generate_visualization_node(
    state: QNRViewerState,
    config: RunnableConfig
) -> QNRViewerState:
    """Convert QNRGraph to visualization format with layout."""
    start_time = time.time()
    
    if state.get("error_message"):
        return state
    
    user_id: UUID = config["configurable"]["user_id"]
    qnr_id = state["qnr_id"]
    
    logger.info(
        "Generating visualization",
        extra={"qnr_id": qnr_id, "user_id": str(user_id), "node": "generate_visualization"},
    )
    
    try:
        graph_dict = state["graph"]
        graph = QNRGraph.model_validate(graph_dict)
        
        # Calculate layout (positions for nodes)
        visualization = calculate_layout(graph)
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Visualization generated",
            extra={
                "qnr_id": qnr_id,
                "node_count": len(visualization.nodes),
                "edge_count": len(visualization.edges),
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "generate_visualization",
            },
        )
        
        return {"visualization": visualization.model_dump()}
        
    except Exception as e:
        logger.error(
            "Visualization generation failed",
            extra={"qnr_id": qnr_id, "error": str(e), "node": "generate_visualization"},
            exc_info=True,
        )
        return {"error_message": f"Failed to generate visualization: {str(e)}"}


# ============================================================================
# Node 3: Render Viewer UI
# ============================================================================

async def render_viewer_node(
    state: QNRViewerState,
    config: RunnableConfig
) -> QNRViewerState:
    """Render interactive graph viewer UI (read-only)."""
    start_time = time.time()
    
    if state.get("error_message"):
        # Render error state
        error_html = f"""
        <div class="max-w-4xl mx-auto p-6">
            <div class="bg-red-50 border border-red-200 rounded-lg p-6">
                <h2 class="text-xl font-bold text-red-800 mb-2">Error</h2>
                <p class="text-red-700">{state["error_message"]}</p>
                <a href="/qnr/dashboard" class="text-red-600 hover:underline mt-4 inline-block">
                    ← Return to Dashboard
                </a>
            </div>
        </div>
        """
        return {"rendered_output": error_html}
    
    user_id: UUID = config["configurable"]["user_id"]
    qnr_id = state["qnr_id"]
    
    logger.info(
        "Rendering viewer UI",
        extra={"qnr_id": qnr_id, "user_id": str(user_id), "node": "render_viewer"},
    )
    
    try:
        visualization_dict = state["visualization"]
        visualization = GraphVisualization.model_validate(visualization_dict)
        
        # Render graph SVG
        graph_svg = render_graph_svg(
            visualization,
            selected_node_id=state.get("selected_node_id"),
        )
        
        # Render side panel
        side_panel = render_side_panel(
            state.get("graph"),
            selected_node_id=state.get("selected_node_id"),
            qnr_id=qnr_id,
        )
        
        # Combine into full editor layout
        from jinja2 import Environment, FileSystemLoader
        
        jinja_env = Environment(loader=FileSystemLoader("smeme/templates"))
        template = jinja_env.get_template("qnr/editor.html")
        
        html = template.render(
            qnr_id=qnr_id,
            graph_svg=graph_svg,
            side_panel=side_panel,
            metadata=visualization.metadata,
        )
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Viewer UI rendered",
            extra={
                "qnr_id": qnr_id,
                "html_length": len(html),
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "render_viewer",
            },
        )
        
        return {"rendered_output": html}
        
    except Exception as e:
        logger.error(
            "Viewer rendering failed",
            extra={"qnr_id": qnr_id, "error": str(e), "node": "render_viewer"},
            exc_info=True,
        )
        return {"error_message": f"Failed to render viewer: {str(e)}"}


# ============================================================================
# Build Workflow
# ============================================================================

def build_viewer_workflow() -> StateGraph:
    """Build and compile the QNR viewer workflow."""
    workflow = StateGraph(QNRViewerState)
    
    # Add nodes
    workflow.add_node("load_qnr", load_qnr_node)
    workflow.add_node("generate_visualization", generate_visualization_node)
    workflow.add_node("render_viewer", render_viewer_node)
    
    # Linear flow
    workflow.add_edge(START, "load_qnr")
    workflow.add_edge("load_qnr", "generate_visualization")
    workflow.add_edge("generate_visualization", "render_viewer")
    workflow.add_edge("render_viewer", END)
    
    return workflow.compile()
```

---

### Workflow 2: QNR Editor (Write Operations)

#### File: `smeme/qnr/editor/workflow.py`

```python
"""LangGraph workflow for QNR graph editing (write operations)."""

import logging
import time
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.types import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.qnr.editor.models import QNREditorState
from smeme.qnr.editor.operations import apply_operation
from smeme.qnr.helpers.db_queries import get_qnr_by_id, parse_graph_data, update_qnr_graph
from smeme.qnr.helpers.validation import validate_graph
from smeme.qnr.models import QNRGraph
from smeme.core.cache import invalidate_qnr_cache

logger = logging.getLogger("smeme.qnr.editor.workflow")


# ============================================================================
# Node 1: Load QNR (No Cache, Always Fresh)
# ============================================================================

async def load_qnr_node(
    state: QNREditorState,
    config: RunnableConfig
) -> QNREditorState:
    """
    Load QNR graph from database (no caching).

    Note: Editor always loads fresh from DB to ensure we're working with the
    authoritative source, especially important for concurrent edits.
    Cache is invalidated after successful save.
    """
    start_time = time.time()
    
    db: AsyncSession = config["configurable"]["db"]
    user_id: UUID = config["configurable"]["user_id"]
    qnr_id = UUID(state["qnr_id"])
    
    logger.info(
        "Loading QNR for editing",
        extra={
            "qnr_id": str(qnr_id),
            "user_id": str(user_id),
            "operation": state["operation"],
            "node": "load_qnr",
        },
    )
    
    # Load from database (always fresh)
    qnr = await get_qnr_by_id(db, qnr_id)
    if not qnr:
        logger.warning(
            "QNR not found",
            extra={"qnr_id": str(qnr_id), "user_id": str(user_id), "node": "load_qnr"},
        )
        return {"error_message": f"QNR {qnr_id} not found", "success": False}
    
    # Verify ownership
    if qnr.author_id != user_id:
        logger.warning(
            "Unauthorized QNR edit attempt",
            extra={"qnr_id": str(qnr_id), "user_id": str(user_id), "node": "load_qnr"},
        )
        return {"error_message": "Unauthorized", "success": False}
    
    try:
        graph = parse_graph_data(qnr)
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "QNR loaded for editing",
            extra={
                "qnr_id": str(qnr_id),
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "load_qnr",
            },
        )
        
        return {"graph": graph.model_dump()}
        
    except Exception as e:
        logger.error(
            "Failed to parse graph",
            extra={"qnr_id": str(qnr_id), "error": str(e), "node": "load_qnr"},
            exc_info=True,
        )
        return {"error_message": str(e), "success": False}


# ============================================================================
# Node 2: Apply Operation
# ============================================================================

async def apply_operation_node(
    state: QNREditorState,
    config: RunnableConfig
) -> QNREditorState:
    """Apply the requested CRUD operation to the graph."""
    start_time = time.time()
    
    if state.get("error_message"):
        return state
    
    qnr_id = state["qnr_id"]
    operation = state["operation"]
    
    logger.info(
        "Applying operation",
        extra={
            "qnr_id": qnr_id,
            "operation": operation,
            "target_id": state.get("target_id"),
            "node": "apply_operation",
        },
    )
    
    try:
        graph_dict = state["graph"]
        graph = QNRGraph.model_validate(graph_dict)
        
        # Apply operation (defined in operations.py)
        updated_graph = apply_operation(
            graph,
            operation,
            target_id=state.get("target_id"),
            changes=state.get("changes", {}),
        )
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Operation applied",
            extra={
                "qnr_id": qnr_id,
                "operation": operation,
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "apply_operation",
            },
        )
        
        return {"graph": updated_graph.model_dump()}
        
    except Exception as e:
        logger.error(
            "Operation failed",
            extra={
                "qnr_id": qnr_id,
                "operation": operation,
                "error": str(e),
                "node": "apply_operation",
            },
            exc_info=True,
        )
        return {"error_message": f"Operation failed: {str(e)}", "success": False}


# ============================================================================
# Node 3: Validate Graph (Lenient for Drafts)
# ============================================================================

async def validate_graph_node(
    state: QNREditorState,
    config: RunnableConfig
) -> QNREditorState:
    """Validate the updated graph structure (lenient draft validation)."""
    start_time = time.time()
    
    if state.get("error_message"):
        return state
    
    qnr_id = state["qnr_id"]
    
    logger.info(
        "Validating graph",
        extra={"qnr_id": qnr_id, "node": "validate_graph"},
    )
    
    try:
        graph_dict = state["graph"]
        graph = QNRGraph.model_validate(graph_dict)
        
        # Lenient validation for draft editing
        is_ok, blocking_errors, warnings = validate_graph_for_editing(graph)
        
        if not is_ok:
            # Block critical errors
            retry_count = state.get("retry_count", 0)
            logger.warning(
                "Validation failed (critical errors)",
                extra={
                    "qnr_id": qnr_id,
                    "blocking_errors": blocking_errors,
                    "retry_count": retry_count,
                    "node": "validate_graph",
                },
            )
            return {
                "validation_errors": blocking_errors,
                "retry_count": retry_count + 1,
                "success": False,
                "error_message": f"Cannot save: {blocking_errors[0]}",
            }
        
        # Success! Include warnings in state (will be displayed in UI)
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Graph validated successfully",
            extra={
                "qnr_id": qnr_id,
                "warnings": warnings,
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "validate_graph",
            },
        )
        
        return {
            "validation_errors": [],
            "warnings": warnings,  # Pass warnings to UI
            "success": True
        }
        
    except Exception as e:
        logger.error(
            "Validation error",
            extra={"qnr_id": qnr_id, "error": str(e), "node": "validate_graph"},
            exc_info=True,
        )
        return {"error_message": f"Validation error: {str(e)}", "success": False}


# ============================================================================
# Node 4: Save to Database
# ============================================================================

async def save_to_db_node(
    state: QNREditorState,
    config: RunnableConfig
) -> QNREditorState:
    """Save the updated graph to the database."""
    start_time = time.time()
    
    if not state.get("success", False):
        return state
    
    db: AsyncSession = config["configurable"]["db"]
    qnr_id = UUID(state["qnr_id"])
    
    logger.info(
        "Saving to database",
        extra={"qnr_id": str(qnr_id), "node": "save_to_db"},
    )
    
    try:
        graph_dict = state["graph"]
        graph = QNRGraph.model_validate(graph_dict)
        
        # Update QNR in database
        await update_qnr_graph(db, qnr_id, graph)
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Saved to database",
            extra={
                "qnr_id": str(qnr_id),
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "save_to_db",
            },
        )
        
        return {"success": True}
        
    except Exception as e:
        logger.error(
            "Database save failed",
            extra={"qnr_id": str(qnr_id), "error": str(e), "node": "save_to_db"},
            exc_info=True,
        )
        return {"error_message": f"Save failed: {str(e)}", "success": False}


# ============================================================================
# Node 5: Invalidate Cache
# ============================================================================

async def invalidate_cache_node(
    state: QNREditorState,
    config: RunnableConfig
) -> QNREditorState:
    """Invalidate cache so viewer workflow loads fresh data."""
    start_time = time.time()
    
    if not state.get("success", False):
        return state
    
    qnr_id = UUID(state["qnr_id"])
    
    logger.info(
        "Invalidating cache",
        extra={"qnr_id": str(qnr_id), "node": "invalidate_cache"},
    )
    
    try:
        await invalidate_qnr_cache(qnr_id)
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Cache invalidated",
            extra={
                "qnr_id": str(qnr_id),
                "elapsed_ms": round(elapsed_ms, 2),
                "node": "invalidate_cache",
            },
        )
        
        return {"success": True}
        
    except Exception as e:
        logger.error(
            "Cache invalidation failed",
            extra={"qnr_id": str(qnr_id), "error": str(e), "node": "invalidate_cache"},
            exc_info=True,
        )
        # Non-critical failure - don't mark as unsuccessful
        return state


# ============================================================================
# Build Workflow
# ============================================================================

def build_editor_workflow() -> StateGraph:
    """Build and compile the QNR editor workflow."""
    workflow = StateGraph(QNREditorState)
    
    # Add nodes
    workflow.add_node("load_qnr", load_qnr_node)
    workflow.add_node("apply_operation", apply_operation_node)
    workflow.add_node("validate_graph", validate_graph_node)
    workflow.add_node("save_to_db", save_to_db_node)
    workflow.add_node("invalidate_cache", invalidate_cache_node)
    
    # Linear flow
    workflow.add_edge(START, "load_qnr")
    workflow.add_edge("load_qnr", "apply_operation")
    workflow.add_edge("apply_operation", "validate_graph")
    workflow.add_edge("validate_graph", "save_to_db")
    workflow.add_edge("save_to_db", "invalidate_cache")
    workflow.add_edge("invalidate_cache", END)
    
    return workflow.compile()
```

---

## Shared Components

### Overview

**What's Actually Shared**:
- **Layout Algorithm**: BFS-based positioning (used by Viewer)
- **Renderer**: SVG + HTML generation (used by Viewer)
- **Validation Helpers**: Graph validation logic (used by Editor)
- **Base Models**: `QNRGraph`, `QNRNode`, `QNREdge` (stored in DB)

**What's NOT Shared** (Viewer-Only):
- `NodePosition`, `VisualNode`, `VisualEdge`, `GraphVisualization`
- These are **ephemeral outputs** of the Viewer Workflow, generated on-demand
- Never persisted to DB or used by Editor Workflow
- Editor modifies `QNRGraph` → saves → redirects → Viewer re-generates visual models

**Key Design Principle**: 
- Editor Workflow: Operates on **semantic graph** (questions, edges, conditions)
- Viewer Workflow: Generates **visual representation** (positions, SVG paths)
- Clean separation of concerns: data vs. presentation

---

### Enhanced Graph Validation (Tiered Strategy)

#### File: `smeme/qnr/helpers/validation.py` (additions)

```python
"""Enhanced validation for graph editing operations with tiered validation."""

def has_cycle(graph: QNRGraph) -> tuple[bool, str | None]:
    """
    Check for cycles in the graph using DFS.
    
    Returns:
        (has_cycle, error_message)
    """
    visited = set()
    rec_stack = set()
    
    def dfs(node_id: str, path: list[str]) -> tuple[bool, list[str] | None]:
        """DFS with path tracking for better error messages."""
        visited.add(node_id)
        rec_stack.add(node_id)
        path.append(node_id)
        
        for edge in graph.edges:
            if edge.source == node_id:
                if edge.target not in visited:
                    has_cycle_result, cycle_path = dfs(edge.target, path.copy())
                    if has_cycle_result:
                        return True, cycle_path
                elif edge.target in rec_stack:
                    # Cycle detected! Return the cycle path
                    cycle_start = path.index(edge.target)
                    cycle = path[cycle_start:] + [edge.target]
                    return True, cycle
        
        rec_stack.remove(node_id)
        return False, None
    
    for node in graph.nodes:
        if node.id not in visited:
            has_cycle_result, cycle_path = dfs(node.id, [])
            if has_cycle_result:
                cycle_str = " → ".join(cycle_path)
                return True, f"Cycle detected: {cycle_str}"
    
    return False, None


def find_orphaned_nodes(graph: QNRGraph) -> list[str]:
    """Find nodes with no incoming edges (except entry nodes)."""
    entry_nodes = [n.id for n in graph.nodes if not any(e.target == n.id for e in graph.edges)]
    
    if not entry_nodes:
        return []
    
    # All nodes without incoming edges (other than first entry node)
    orphans = []
    for node in graph.nodes:
        has_incoming = any(e.target == node.id for e in graph.edges)
        if not has_incoming and node.id not in entry_nodes[:1]:  # Allow first entry node
            orphans.append(node.id)
    
    return orphans


def validate_graph_for_editing(graph: QNRGraph) -> tuple[bool, list[str], list[str]]:
    """
    Lenient validation during editing (draft mode).
    
    Returns:
        (is_critically_broken, blocking_errors, warnings)
    """
    blocking = []
    warnings = []
    
    # BLOCK: Self-loops
    for edge in graph.edges:
        if edge.source == edge.target:
            blocking.append(f"Self-loop: {edge.source} → {edge.target}")
    
    # BLOCK: Duplicate edges (same source + target)
    edge_set = set()
    for edge in graph.edges:
        key = (edge.source, edge.target)
        if key in edge_set:
            blocking.append(f"Duplicate edge: {edge.source} → {edge.target}")
        edge_set.add(key)
    
    # BLOCK: Invalid edge conditions (won't work in navigation)
    for edge in graph.edges:
        if edge.condition:
            source_node = next((n for n in graph.nodes if n.id == edge.source), None)
            if source_node and source_node.data.type in ["radio", "checkbox"]:
                if not source_node.data.options or edge.condition not in source_node.data.options:
                    blocking.append(
                        f"Invalid condition '{edge.condition}' on edge {edge.source}→{edge.target}. "
                        f"Must match one of: {source_node.data.options}"
                    )
    
    # WARN: Cycles (allow during editing!)
    has_cycle_result, cycle_error = has_cycle(graph)
    if has_cycle_result:
        warnings.append(f"⚠️ {cycle_error}")
    
    # WARN: Orphaned nodes
    orphans = find_orphaned_nodes(graph)
    if orphans:
        warnings.append(f"⚠️ Orphaned nodes: {', '.join(orphans)}")
    
    # WARN: No entry point
    entry_nodes = [n for n in graph.nodes if not any(e.target == n.id for e in graph.edges)]
    if not entry_nodes:
        warnings.append("⚠️ No entry point (all nodes have incoming edges)")
    elif len(entry_nodes) > 1:
        # Multiple entry points: check for default (no entry_condition)
        has_default = any(not n.data.get("entry_condition") for n in entry_nodes)
        if not has_default:
            warnings.append(
                f"⚠️ Multiple entry points ({len(entry_nodes)}) with no default fallback. "
                f"Mark one entry point without entry_condition as the default."
            )
    
    # WARN: No terminal nodes
    terminal_nodes = [n for n in graph.nodes if not any(e.source == n.id for e in graph.edges)]
    if not terminal_nodes:
        warnings.append("⚠️ No terminal nodes (all nodes have outgoing edges)")
    
    # WARN: Missing default edges
    for node in graph.nodes:
        outgoing = [e for e in graph.edges if e.source == node.id]
        conditional = [e for e in outgoing if e.condition]
        default = [e for e in outgoing if not e.condition]
        
        if conditional and not default:
            if node.data.type == "radio":
                # Check if conditions cover all options
                conditions = {e.condition for e in conditional}
                if node.data.options and set(node.data.options) != conditions:
                    warnings.append(f"⚠️ {node.id} has conditional edges but no default edge")
            else:
                warnings.append(f"⚠️ {node.id} has conditional edges but no default edge")
    
    is_ok = len(blocking) == 0
    return is_ok, blocking, warnings


def validate_graph_for_publication(graph: QNRGraph) -> tuple[bool, list[str]]:
    """
    Strict validation before publication.
    All warnings become errors.
    """
    _, blocking, warnings = validate_graph_for_editing(graph)
    
    # Promote all warnings to errors
    all_errors = blocking + [w.replace("⚠️ ", "") for w in warnings]
    
    is_valid = len(all_errors) == 0
    return is_valid, all_errors


# Legacy function for backward compatibility
def validate_graph(graph: QNRGraph) -> tuple[bool, str | None]:
    """
    Validate QNR graph structure and logic.
    
    Note: This now uses validate_graph_for_publication for strict validation.
    Use validate_graph_for_editing for lenient draft validation.
    """
    is_valid, errors = validate_graph_for_publication(graph)
    error_msg = errors[0] if errors else None
    return is_valid, error_msg
```

---

### Layout Algorithm (Viewer-Only)

#### File: `smeme/qnr/viewer/layout.py`

**Note**: This is NOT used by the Editor Workflow. Editor saves semantic graph changes and redirects to Viewer, which re-calculates positions.

```python
"""Graph layout algorithms for QNR visualization."""

from smeme.qnr.viewer.models import GraphVisualization, VisualNode, VisualEdge, NodePosition
from smeme.qnr.models import QNRGraph
from smeme.qnr.helpers.validation import (
    get_first_question_id,
    get_outgoing_edges,
    get_incoming_edges,
    has_conditional_edges,
)


def calculate_layout(graph: QNRGraph) -> GraphVisualization:
    """
    Calculate node positions using hierarchical layout.
    
    Algorithm:
    1. Identify entry node (no incoming edges)
    2. Perform breadth-first traversal to assign levels
    3. Position nodes in levels (top-to-bottom, left-to-right)
    4. Calculate edge paths
    """
    # Constants
    NODE_WIDTH = 200
    NODE_HEIGHT = 80
    HORIZONTAL_SPACING = 100
    VERTICAL_SPACING = 120
    CANVAS_PADDING = 50
    
    # Step 1: Assign levels via BFS
    entry_id = get_first_question_id(graph)
    if not entry_id:
        raise ValueError("No entry node found")
    
    levels: dict[str, int] = {}  # node_id -> level
    queue = [(entry_id, 0)]
    visited = set()
    
    while queue:
        node_id, level = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        levels[node_id] = level
        
        # Add children
        for edge in get_outgoing_edges(graph, node_id):
            if edge.target not in visited:
                queue.append((edge.target, level + 1))
    
    # Step 2: Group nodes by level
    level_groups: dict[int, list[str]] = {}
    for node_id, level in levels.items():
        if level not in level_groups:
            level_groups[level] = []
        level_groups[level].append(node_id)
    
    # Step 3: Calculate positions
    visual_nodes: list[VisualNode] = []
    max_level = max(level_groups.keys()) if level_groups else 0
    
    for level, node_ids in level_groups.items():
        y = CANVAS_PADDING + (level * (NODE_HEIGHT + VERTICAL_SPACING))
        
        # Center nodes horizontally
        total_width = len(node_ids) * NODE_WIDTH + (len(node_ids) - 1) * HORIZONTAL_SPACING
        start_x = CANVAS_PADDING + (1200 - total_width) / 2  # Assume 1200px canvas
        
        for i, node_id in enumerate(node_ids):
            x = start_x + (i * (NODE_WIDTH + HORIZONTAL_SPACING))
            
            node = next(n for n in graph.nodes if n.id == node_id)
            
            visual_node = VisualNode(
                id=node_id,
                type=node.type,
                label=node.data.text if node.data else node_id,
                position=NodePosition(x=x, y=y),
                is_entry=len(get_incoming_edges(graph, node_id)) == 0,
                is_terminal=len(get_outgoing_edges(graph, node_id)) == 0,
                has_conditionals=has_conditional_edges(graph, node_id),
                data=node.data.model_dump() if node.data else None,
            )
            visual_nodes.append(visual_node)
    
    # Step 4: Create visual edges
    visual_edges: list[VisualEdge] = []
    node_positions = {vn.id: vn.position for vn in visual_nodes}
    
    for edge in graph.edges:
        edge_id = f"{edge.source}_{edge.target}_{edge.condition or 'default'}"
        
        # Calculate SVG path (simple straight line for now)
        source_pos = node_positions.get(edge.source)
        target_pos = node_positions.get(edge.target)
        
        path = None
        if source_pos and target_pos:
            # Path from bottom of source to top of target
            path = f"M {source_pos.x + NODE_WIDTH/2} {source_pos.y + NODE_HEIGHT} L {target_pos.x + NODE_WIDTH/2} {target_pos.y}"
        
        visual_edge = VisualEdge(
            id=edge_id,
            source=edge.source,
            target=edge.target,
            condition=edge.condition,
            is_default=edge.condition is None,
            path=path,
        )
        visual_edges.append(visual_edge)
    
    # Calculate canvas dimensions
    max_x = max((vn.position.x for vn in visual_nodes), default=0) + NODE_WIDTH + CANVAS_PADDING
    max_y = max((vn.position.y for vn in visual_nodes), default=0) + NODE_HEIGHT + CANVAS_PADDING
    
    return GraphVisualization(
        nodes=visual_nodes,
        edges=visual_edges,
        width=int(max_x),
        height=int(max_y),
        metadata=graph.metadata.model_dump() if graph.metadata else None,
    )
```

---

### Renderer (Viewer-Only)

#### File: `smeme/qnr/viewer/renderer.py`

**Note**: This renders the visual output generated by the Viewer Workflow. Editor never calls this directly; it redirects to Viewer routes that use this renderer.

```python
"""HTML/SVG rendering for QNR viewer/editor."""

from smeme.qnr.viewer.models import GraphVisualization


def render_graph_svg(
    visualization: GraphVisualization,
    selected_node_id: str | None = None,
) -> str:
    """Render graph as interactive SVG with clickable nodes only."""
    
    svg_parts = [
        f'<svg width="{visualization.width}" height="{visualization.height}" ',
        'class="border border-gray-300 bg-gray-50" ',
        'xmlns="http://www.w3.org/2000/svg">',
    ]
    
    # Render edges first (so they appear behind nodes)
    # Edges are NOT clickable - users edit them via node selection
    for edge in visualization.edges:
        stroke_color = "#6b7280"  # Gray
        stroke_width = "2"
        
        if edge.path:
            svg_parts.append(
                f'<path d="{edge.path}" '
                f'stroke="{stroke_color}" stroke-width="{stroke_width}" '
                f'fill="none" marker-end="url(#arrowhead)" />'
            )
            
            # Add label for conditional edges
            if edge.condition:
                # Calculate midpoint
                # (Simplified - would need proper path parsing)
                svg_parts.append(
                    f'<text x="..." y="..." '
                    f'class="text-xs fill-gray-600 pointer-events-none">{edge.condition}</text>'
                )
    
    # Define arrowhead marker
    svg_parts.append(
        '<defs>'
        '<marker id="arrowhead" markerWidth="10" markerHeight="10" '
        'refX="9" refY="3" orient="auto">'
        '<polygon points="0 0, 10 3, 0 6" fill="#6b7280" />'
        '</marker>'
        '</defs>'
    )
    
    # Render nodes
    for node in visualization.nodes:
        is_selected = node.id == selected_node_id
        
        # Node styling based on type and state
        if is_selected:
            fill = "#ddd6fe"  # purple-200
            stroke = "#7c3aed"  # purple-600
        elif node.is_entry:
            fill = "#dcfce7"  # green-100
            stroke = "#16a34a"  # green-600
        elif node.is_terminal:
            fill = "#fef3c7"  # yellow-100
            stroke = "#f59e0b"  # yellow-600
        else:
            fill = "#ffffff"
            stroke = "#9ca3af"  # gray-400
        
        # Render node rectangle
        svg_parts.append(
            f'<rect x="{node.position.x}" y="{node.position.y}" '
            f'width="200" height="80" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="2" rx="8" '
            f'class="cursor-pointer hover:fill-purple-100" '
            f'hx-post="/qnr/editor/select_node" '
            f'hx-vals=\'{{"node_id": "{node.id}"}}\' '
            f'hx-target="#side-panel" '
            f'hx-swap="innerHTML" />'
        )
        
        # Render node label (truncated)
        label = node.label[:30] + "..." if len(node.label) > 30 else node.label
        svg_parts.append(
            f'<text x="{node.position.x + 100}" y="{node.position.y + 45}" '
            f'text-anchor="middle" class="text-sm fill-gray-800 pointer-events-none">'
            f'{label}</text>'
        )
        
        # Render node ID badge
        svg_parts.append(
            f'<text x="{node.position.x + 10}" y="{node.position.y + 20}" '
            f'class="text-xs fill-gray-500 pointer-events-none">{node.id}</text>'
        )
    
    svg_parts.append('</svg>')
    
    return ''.join(svg_parts)


def render_side_panel(
    graph: dict | None,
    selected_node_id: str | None,
    qnr_id: str,
) -> str:
    """Render side panel with edit controls."""
    
    if selected_node_id:
        return render_node_editor(graph, selected_node_id, qnr_id)
    else:
        return render_empty_state(qnr_id)


def render_empty_state(qnr_id: str) -> str:
    """Render empty side panel."""
    return f"""
    <div class="p-6 text-center text-gray-500">
        <p class="mb-4">Select a node or edge to edit</p>
        <button
            hx-post="/qnr/editor/add_node"
            hx-vals='{{"qnr_id": "{qnr_id}"}}'
            hx-target="#root"
            hx-swap="innerHTML"
            class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-lg">
            + Add Node
        </button>
    </div>
    """


def render_node_editor(graph: dict, node_id: str, qnr_id: str) -> str:
    """Render node editing form with outgoing/incoming edges."""
    # Find node in graph
    node = next((n for n in graph["nodes"] if n["id"] == node_id), None)
    if not node:
        return "<p class='text-red-600'>Node not found</p>"
    
    data = node.get("data", {})
    
    # Get outgoing and incoming edges
    outgoing_edges = [e for e in graph["edges"] if e["source"] == node_id]
    incoming_edges = [e for e in graph["edges"] if e["target"] == node_id]
    
    # Render outgoing edges list
    outgoing_html = ""
    for edge in outgoing_edges:
        condition_text = f'"{edge.get("condition")}"' if edge.get("condition") else "(default)"
        outgoing_html += f"""
        <div class="flex items-center justify-between p-2 bg-gray-50 rounded mb-2">
            <span class="text-sm">→ <strong>{edge["target"]}</strong> {condition_text}</span>
            <div class="flex gap-1">
                <button
                    type="button"
                    hx-post="/qnr/editor/update_edge_form"
                    hx-vals='{{"qnr_id": "{qnr_id}", "source": "{edge["source"]}", "target": "{edge["target"]}", "condition": "{edge.get("condition", "")}"}}'
                    hx-target="#edge-form-{edge["target"]}"
                    hx-swap="innerHTML"
                    class="text-xs text-blue-600 hover:underline">
                    Edit
                </button>
                <button
                    type="button"
                    hx-post="/qnr/editor/delete_edge"
                    hx-vals='{{"qnr_id": "{qnr_id}", "source": "{edge["source"]}", "target": "{edge["target"]}"}}'
                    hx-confirm="Delete this edge?"
                    class="text-xs text-red-600 hover:underline">
                    Delete
                </button>
            </div>
        </div>
        <div id="edge-form-{edge["target"]}"></div>
        """
    
    # Render incoming edges list (read-only)
    incoming_html = ""
    for edge in incoming_edges:
        condition_text = f'"{edge.get("condition")}"' if edge.get("condition") else "(default)"
        incoming_html += f"""
        <div class="p-2 bg-gray-50 rounded mb-2">
            <span class="text-sm"><strong>{edge["source"]}</strong> → {condition_text}</span>
        </div>
        """
    
    return f"""
    <div class="p-6 space-y-6">
        <div>
            <h3 class="text-lg font-bold mb-4">Edit Node: {node_id}</h3>
            
            <form
                hx-post="/qnr/editor/update_node"
                hx-vals='{{"qnr_id": "{qnr_id}", "node_id": "{node_id}"}}'
                hx-target="#root"
                hx-swap="innerHTML"
                class="space-y-4">
                
                <div>
                    <label class="block text-sm font-medium mb-1">Question Text</label>
                    <textarea
                        name="text"
                        rows="3"
                        class="w-full border rounded px-3 py-2"
                        required>{data.get("text", "")}</textarea>
                </div>
                
                <div>
                    <label class="block text-sm font-medium mb-1">Type</label>
                    <select name="type" class="w-full border rounded px-3 py-2">
                        <option value="text" {"selected" if data.get("type") == "text" else ""}>Text</option>
                        <option value="number" {"selected" if data.get("type") == "number" else ""}>Number</option>
                        <option value="radio" {"selected" if data.get("type") == "radio" else ""}>Radio</option>
                        <option value="checkbox" {"selected" if data.get("type") == "checkbox" else ""}>Checkbox</option>
                    </select>
                </div>
                
                <div>
                    <label class="block text-sm font-medium mb-1">Options (one per line, for radio/checkbox)</label>
                    <textarea
                        name="options"
                        rows="3"
                        class="w-full border rounded px-3 py-2"
                        placeholder="Option 1\nOption 2\nOption 3">{"\\n".join(data.get("options", []))}</textarea>
                </div>
                
                <div class="flex items-center">
                    <input
                        type="checkbox"
                        name="required"
                        id="required"
                        {"checked" if data.get("required", True) else ""}
                        class="mr-2">
                    <label for="required" class="text-sm">Required</label>
                </div>
                
                <div>
                    <label class="block text-sm font-medium mb-1">Help Text</label>
                    <input
                        type="text"
                        name="help_text"
                        value="{data.get("help_text", "")}"
                        class="w-full border rounded px-3 py-2">
                </div>
                
                <div class="flex gap-2 pt-4">
                    <button
                        type="submit"
                        class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded flex-1">
                        Save Changes
                    </button>
                    <button
                        type="button"
                        hx-post="/qnr/editor/delete_node"
                        hx-vals='{{"qnr_id": "{qnr_id}", "node_id": "{node_id}"}}'
                        hx-confirm="Delete this node and all connected edges?"
                        hx-target="#root"
                        hx-swap="innerHTML"
                        class="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded">
                        Delete
                    </button>
                </div>
            </form>
        </div>
        
        <div class="border-t pt-4">
            <h4 class="text-md font-semibold mb-2">Outgoing Edges</h4>
            <div class="space-y-2">
                {outgoing_html if outgoing_html else '<p class="text-sm text-gray-500">No outgoing edges</p>'}
            </div>
            <button
                type="button"
                hx-post="/qnr/editor/create_edge_form"
                hx-vals='{{"qnr_id": "{qnr_id}", "source": "{node_id}"}}'
                hx-target="#new-edge-form"
                hx-swap="innerHTML"
                class="mt-2 text-sm text-purple-600 hover:underline">
                + Add Edge
            </button>
            <div id="new-edge-form" class="mt-2"></div>
        </div>
        
        <div class="border-t pt-4">
            <h4 class="text-md font-semibold mb-2">Incoming Edges</h4>
            <div class="space-y-2">
                {incoming_html if incoming_html else '<p class="text-sm text-gray-500">No incoming edges</p>'}
            </div>
        </div>
    </div>
    """
```

---

## Routes

### Viewer Routes

#### File: `smeme/qnr/viewer/routes.py`

```python
"""API routes for QNR graph viewer (read-only)."""

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from uuid import UUID

from smeme.core.dependencies import AsyncSessionDep, CurrentUser
from smeme.qnr.viewer.workflow import build_viewer_workflow
from smeme.qnr.viewer.models import QNRViewerState

router = APIRouter(prefix="/qnr", tags=["qnr-viewer"])


@router.get("/{qnr_id}/editor")
async def view_editor_page(
    qnr_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """Render QNR graph editor page (read-only viewer)."""
    
    workflow = build_viewer_workflow()
    
    initial_state: QNRViewerState = {
        "qnr_id": str(qnr_id),
        "user_id": str(user.id),
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={
            "configurable": {
                "db": db,
                "user_id": user.id,
            }
        }
    )
    
    if result.get("error_message"):
        raise HTTPException(status_code=404, detail=result["error_message"])
    
    return HTMLResponse(content=result["rendered_output"])


@router.post("/editor/select_node")
async def select_node(
    node_id: str = Form(...),
    qnr_id: str = Form(...),
    user: CurrentUser = ...,
    db: AsyncSessionDep = ...,
) -> HTMLResponse:
    """Select a node and render its editor form in side panel."""
    
    # Re-run viewer workflow with selection state
    workflow = build_viewer_workflow()
    
    initial_state: QNRViewerState = {
        "qnr_id": qnr_id,
        "user_id": str(user.id),
        "selected_node_id": node_id,
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={"configurable": {"db": db, "user_id": user.id}}
    )
    
    return HTMLResponse(content=result["rendered_output"])
```

---

### Editor Routes

#### File: `smeme/qnr/editor/routes.py`

```python
"""API routes for QNR graph editor (write operations)."""

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import RedirectResponse
from uuid import UUID

from smeme.core.dependencies import AsyncSessionDep, CurrentUser
from smeme.qnr.editor.workflow import build_editor_workflow
from smeme.qnr.editor.models import QNREditorState

router = APIRouter(prefix="/qnr/editor", tags=["qnr-editor"])


@router.post("/update_node")
async def update_node(
    qnr_id: str = Form(...),
    node_id: str = Form(...),
    text: str = Form(...),
    type: str = Form(...),
    options: str = Form(""),
    required: bool = Form(False),
    help_text: str = Form(""),
    user: CurrentUser = ...,
    db: AsyncSessionDep = ...,
) -> RedirectResponse:
    """Update a node's data via editor workflow."""
    
    workflow = build_editor_workflow()
    
    # Parse options (newline-separated)
    options_list = [opt.strip() for opt in options.split("\n") if opt.strip()]
    
    initial_state: QNREditorState = {
        "qnr_id": qnr_id,
        "user_id": str(user.id),
        "operation": "update_node",
        "target_id": node_id,
        "changes": {
            "text": text,
            "type": type,
            "options": options_list if options_list else None,
            "required": required,
            "help_text": help_text or None,
        },
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={"configurable": {"db": db, "user_id": user.id}}
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error_message"))
    
    # Redirect back to viewer (which will load updated data)
    return RedirectResponse(f"/qnr/{qnr_id}/editor", status_code=303)


@router.post("/delete_node")
async def delete_node(
    qnr_id: str = Form(...),
    node_id: str = Form(...),
    user: CurrentUser = ...,
    db: AsyncSessionDep = ...,
) -> RedirectResponse:
    """Delete a node via editor workflow."""
    
    workflow = build_editor_workflow()
    
    initial_state: QNREditorState = {
        "qnr_id": qnr_id,
        "user_id": str(user.id),
        "operation": "delete_node",
        "target_id": node_id,
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={"configurable": {"db": db, "user_id": user.id}}
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error_message"))
    
    return RedirectResponse(f"/qnr/{qnr_id}/editor", status_code=303)


@router.post("/create_node")
async def create_node(
    qnr_id: str = Form(...),
    node_id: str = Form(...),
    text: str = Form(...),
    type: str = Form("text"),
    user: CurrentUser = ...,
    db: AsyncSessionDep = ...,
) -> RedirectResponse:
    """Create a new node via editor workflow."""
    
    workflow = build_editor_workflow()
    
    initial_state: QNREditorState = {
        "qnr_id": qnr_id,
        "user_id": str(user.id),
        "operation": "create_node",
        "changes": {
            "node_id": node_id,
            "text": text,
            "type": type,
        },
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={"configurable": {"db": db, "user_id": user.id}}
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error_message"))
    
    return RedirectResponse(f"/qnr/{qnr_id}/editor", status_code=303)


@router.post("/update_edge_form")
async def update_edge_form(
    qnr_id: str = Form(...),
    source: str = Form(...),
    target: str = Form(...),
    condition: str = Form(""),
    user: CurrentUser = ...,
    db: AsyncSessionDep = ...,
) -> HTMLResponse:
    """Render inline form for editing an edge (target + condition)."""
    
    # Get all available nodes for target dropdown
    workflow = build_viewer_workflow()
    result = await workflow.ainvoke(
        {"qnr_id": qnr_id, "user_id": str(user.id)},
        config={"configurable": {"db": db, "user_id": user.id}}
    )
    
    graph = result.get("graph", {})
    all_nodes = [n["id"] for n in graph.get("nodes", [])]
    
    # Build options (exclude source node to prevent self-loops)
    target_options = "".join([
        f'<option value="{n}" {"selected" if n == target else ""}>{n}</option>'
        for n in all_nodes if n != source
    ])
    
    form_html = f"""
    <form
        hx-post="/qnr/editor/update_edge"
        hx-vals='{{"qnr_id": "{qnr_id}", "source": "{source}", "old_target": "{target}"}}'
        class="p-2 bg-blue-50 rounded mb-2 space-y-2">
        <label class="block text-xs font-medium text-gray-700">Target Node</label>
        <select name="new_target" required class="w-full text-sm border rounded px-2 py-1">
            {target_options}
        </select>
        <label class="block text-xs font-medium text-gray-700 mt-2">Condition (optional)</label>
        <input type="text" name="new_condition" value="{condition}" 
               placeholder="e.g., Yes, No, Option A" 
               class="w-full text-sm border rounded px-2 py-1">
        <p class="text-xs text-gray-500">Leave empty for default edge. Must match option label for radio/checkbox.</p>
        <div class="flex gap-1">
            <button type="submit" class="text-xs bg-blue-600 text-white px-2 py-1 rounded">Save</button>
            <button type="button" onclick="this.closest('form').remove()" 
                    class="text-xs bg-gray-300 px-2 py-1 rounded">Cancel</button>
        </div>
    </form>
    """
    return HTMLResponse(content=form_html)


@router.post("/update_edge")
async def update_edge(
    qnr_id: str = Form(...),
    source: str = Form(...),
    old_target: str = Form(...),
    new_target: str = Form(...),
    new_condition: str = Form(""),
    user: CurrentUser = ...,
    db: AsyncSessionDep = ...,
) -> RedirectResponse:
    """Update an edge (both target and condition) via editor workflow."""
    
    workflow = build_editor_workflow()
    
    initial_state: QNREditorState = {
        "qnr_id": qnr_id,
        "user_id": str(user.id),
        "operation": "update_edge",
        "changes": {
            "source": source,
            "old_target": old_target,
            "new_target": new_target,
            "new_condition": new_condition or None,
        },
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={"configurable": {"db": db, "user_id": user.id}}
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error_message"))
    
    return RedirectResponse(f"/qnr/{qnr_id}/editor", status_code=303)


@router.post("/delete_edge")
async def delete_edge(
    qnr_id: str = Form(...),
    source: str = Form(...),
    target: str = Form(...),
    user: CurrentUser = ...,
    db: AsyncSessionDep = ...,
) -> RedirectResponse:
    """Delete an edge via editor workflow."""
    
    workflow = build_editor_workflow()
    
    initial_state: QNREditorState = {
        "qnr_id": qnr_id,
        "user_id": str(user.id),
        "operation": "delete_edge",
        "changes": {
            "source": source,
            "target": target,
        },
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={"configurable": {"db": db, "user_id": user.id}}
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error_message"))
    
    return RedirectResponse(f"/qnr/{qnr_id}/editor", status_code=303)


@router.post("/create_edge_form")
async def create_edge_form(
    qnr_id: str = Form(...),
    source: str = Form(...),
    user: CurrentUser = ...,
    db: AsyncSessionDep = ...,
) -> HTMLResponse:
    """Render inline form for creating a new edge."""
    
    # Get all available nodes for target dropdown
    # (In real implementation, would fetch from viewer workflow or DB)
    form_html = f"""
    <form
        hx-post="/qnr/editor/create_edge"
        hx-vals='{{"qnr_id": "{qnr_id}", "source": "{source}"}}'
        class="p-2 bg-green-50 rounded space-y-2">
        <input type="text" name="target" placeholder="Target node ID (e.g., q2)" 
               required class="w-full text-sm border rounded px-2 py-1">
        <input type="text" name="condition" placeholder="Condition (optional)" 
               class="w-full text-sm border rounded px-2 py-1">
        <div class="flex gap-1">
            <button type="submit" class="text-xs bg-green-600 text-white px-2 py-1 rounded">Create</button>
            <button type="button" onclick="this.closest('form').remove()" 
                    class="text-xs bg-gray-300 px-2 py-1 rounded">Cancel</button>
        </div>
    </form>
    """
    return HTMLResponse(content=form_html)


@router.post("/create_edge")
async def create_edge(
    qnr_id: str = Form(...),
    source: str = Form(...),
    target: str = Form(...),
    condition: str = Form(""),
    user: CurrentUser = ...,
    db: AsyncSessionDep = ...,
) -> RedirectResponse:
    """Create a new edge via editor workflow."""
    
    workflow = build_editor_workflow()
    
    initial_state: QNREditorState = {
        "qnr_id": qnr_id,
        "user_id": str(user.id),
        "operation": "create_edge",
        "changes": {
            "source": source,
            "target": target,
            "condition": condition or None,
        },
    }
    
    result = await workflow.ainvoke(
        initial_state,
        config={"configurable": {"db": db, "user_id": user.id}}
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error_message"))
    
    return RedirectResponse(f"/qnr/{qnr_id}/editor", status_code=303)


@router.post("/{qnr_id}/preview")
async def preview_qnr(
    qnr_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> Response:
    """Validate QNR before preview (strict validation)."""
    
    # Load current graph
    qnr = await get_qnr_by_id(db, qnr_id)
    if not qnr:
        raise HTTPException(status_code=404, detail="QNR not found")
    
    if qnr.author_id != user.id:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    graph = parse_graph_data(qnr)
    
    # Strict validation
    is_valid, errors = validate_graph_for_publication(graph)
    
    if not is_valid:
        # Show modal with errors
        error_list = "\n".join(f"<li>{e}</li>" for e in errors)
        error_html = f"""
        <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div class="bg-white rounded-lg p-6 max-w-lg">
                <h2 class="text-xl font-bold text-red-800 mb-4">Cannot Preview</h2>
                <p class="mb-4">Fix these issues before previewing:</p>
                <ul class="list-disc list-inside text-red-700 mb-6">
                    {error_list}
                </ul>
                <button 
                    onclick="this.closest('div').remove()" 
                    class="bg-gray-600 text-white px-4 py-2 rounded hover:bg-gray-700">
                    Back to Editor
                </button>
            </div>
        </div>
        """
        return HTMLResponse(content=error_html)
    
    # Valid! Redirect to preview
    return RedirectResponse(f"/qnr/{qnr_id}/preview", status_code=303)


@router.post("/{qnr_id}/publish")
async def publish_qnr(
    qnr_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> Response:
    """Publish QNR (strict validation + status change)."""
    
    # Load QNR
    qnr = await get_qnr_by_id(db, qnr_id)
    if not qnr:
        raise HTTPException(status_code=404, detail="QNR not found")
    
    if qnr.author_id != user.id:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    graph = parse_graph_data(qnr)
    
    # Strict validation
    is_valid, errors = validate_graph_for_publication(graph)
    
    if not is_valid:
        error_list = "\n".join(f"<li>{e}</li>" for e in errors)
        error_html = f"""
        <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div class="bg-white rounded-lg p-6 max-w-lg">
                <h2 class="text-xl font-bold text-red-800 mb-4">Cannot Publish</h2>
                <p class="mb-4">Fix these issues before publishing:</p>
                <ul class="list-disc list-inside text-red-700 mb-6">
                    {error_list}
                </ul>
                <button 
                    onclick="this.closest('div').remove()" 
                    class="bg-gray-600 text-white px-4 py-2 rounded hover:bg-gray-700">
                    Back to Editor
                </button>
            </div>
        </div>
        """
        return HTMLResponse(content=error_html)
    
    # Publish!
    qnr.status = "published"
    qnr.published_at = datetime.utcnow()
    await db.commit()
    
    # Invalidate cache
    await invalidate_qnr_cache(qnr_id)
    
    logger.info(
        "QNR published",
        extra={"qnr_id": str(qnr_id), "user_id": str(user.id)}
    )
    
    success_html = """
    <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div class="bg-white rounded-lg p-6 max-w-lg">
            <h2 class="text-xl font-bold text-green-800 mb-4">✅ QNR Published!</h2>
            <p class="mb-6">Your questionnaire is now live and available to users.</p>
            <div class="flex gap-2">
                <a href="/qnr/dashboard" class="bg-purple-600 text-white px-4 py-2 rounded hover:bg-purple-700">
                    Dashboard
                </a>
                <button 
                    onclick="this.closest('div').remove()" 
                    class="bg-gray-300 px-4 py-2 rounded hover:bg-gray-400">
                    Continue Editing
                </button>
            </div>
        </div>
    </div>
    """
    return HTMLResponse(content=success_html)
```

---

## Templates

### File: `smeme/templates/qnr/editor.html`

```html
{% extends "layouts/base.html" %}

{% block content %}
<div class="flex h-screen flex-col">
    <!-- Warning banner (if warnings exist) -->
    {% if warnings %}
    <div class="bg-yellow-50 border-b-4 border-yellow-400 p-4">
        <div class="flex">
            <div class="flex-shrink-0">
                <svg class="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
                </svg>
            </div>
            <div class="ml-3">
                <p class="text-sm font-medium text-yellow-800">
                    Draft has warnings (fix before publishing):
                </p>
                <ul class="mt-2 text-sm text-yellow-700 list-disc list-inside">
                    {% for warning in warnings %}
                    <li>{{ warning }}</li>
                    {% endfor %}
                </ul>
            </div>
        </div>
    </div>
    {% endif %}
    
    <!-- Main content area -->
    <div class="flex flex-1 overflow-hidden">
        <!-- Canvas area -->
        <div id="canvas-area" class="flex-1 overflow-auto p-4">
            <div class="mb-4 flex items-center justify-between">
                <div>
                    <h1 class="text-2xl font-bold">QNR Editor</h1>
                    {% if metadata %}
                    <p class="text-gray-600">{{ metadata.title }}</p>
                    {% endif %}
                    {% if status %}
                    <span class="inline-block mt-1 px-2 py-1 text-xs font-semibold rounded
                        {% if status == 'published' %}bg-green-100 text-green-800{% else %}bg-gray-100 text-gray-800{% endif %}">
                        {{ status|title }}
                    </span>
                    {% endif %}
                </div>
                <div class="flex gap-2">
                    <a href="/qnr/{{ qnr_id }}/preview" 
                       hx-post="/qnr/editor/{{ qnr_id }}/preview"
                       hx-target="body"
                       hx-swap="beforeend"
                       class="btn-secondary">
                        Preview
                    </a>
                    <button 
                        hx-post="/qnr/editor/{{ qnr_id }}/publish"
                        hx-target="body"
                        hx-swap="beforeend"
                        class="btn-primary">
                        Publish
                    </button>
                </div>
            </div>
            
            <div id="graph-container">
                {{ graph_svg|safe }}
            </div>
        </div>
        
        <!-- Side panel -->
        <div id="side-panel" class="w-96 border-l bg-white overflow-auto">
            {{ side_panel|safe }}
        </div>
    </div>
</div>

<!-- Root div for HTMX full-page swaps -->
<div id="root" style="display: none;"></div>
{% endblock %}
```

---

## Implementation Checklist

### Phase 1: Core Viewer & Editor (MVP)

#### Shared Components (Actually Shared)
- [ ] Enhance validation (`smeme/qnr/helpers/validation.py`)
  - [ ] `has_cycle()` - DFS with path tracking for clear error messages
  - [ ] `find_orphaned_nodes()` - Detect unreachable nodes
  - [ ] `validate_graph_for_editing()` - Lenient draft validation (3-tier)
    - [ ] Block: Self-loops, duplicate edges, invalid conditions
    - [ ] Warn: Cycles, orphans, no entry/terminal, missing defaults
  - [ ] `validate_graph_for_publication()` - Strict validation (all warnings → errors)
  - [ ] Update `validate_graph()` for backward compatibility
  - **Used by**: Editor Workflow (editing), Preview/Publish routes (publication)

#### Viewer-Specific Components (NOT Shared)
- [ ] Create `smeme/qnr/viewer/` directory structure
- [ ] Implement viewer models (`smeme/qnr/viewer/models.py`)
  - [ ] `NodePosition`, `VisualNode`, `VisualEdge`, `GraphVisualization` (Pydantic)
  - **Note**: These are ephemeral outputs, never used by Editor
- [ ] Implement layout algorithm (`smeme/qnr/viewer/layout.py`)
  - [ ] Hierarchical BFS-based layout
  - [ ] Node position calculation
  - [ ] Edge path generation
  - **Used by**: Viewer Workflow only (generates positions on-demand)
- [ ] Implement renderer (`smeme/qnr/viewer/renderer.py`)
  - [ ] SVG graph rendering (nodes clickable, edges non-interactive)
  - [ ] Side panel rendering with outgoing/incoming edges
  - [ ] Node editor form with edge lists
  - **Used by**: Viewer Workflow only (Editor redirects to Viewer routes)

#### Viewer Workflow (Read-Only)
- [ ] Implement state models (`smeme/qnr/viewer/models.py`)
  - [ ] `QNRViewerState` (TypedDict - simple, no edge selection)
  - **Note**: Visual models (`NodePosition`, `VisualNode`, etc.) already in this file
- [ ] Implement workflow (`smeme/qnr/viewer/workflow.py`)
  - [ ] `load_qnr_node` (with caching)
  - [ ] `generate_visualization_node`
  - [ ] `render_viewer_node`
  - [ ] `build_viewer_workflow`
- [ ] Implement routes (`smeme/qnr/viewer/routes.py`)
  - [ ] GET `/qnr/{qnr_id}/editor` - main editor page (uses viewer)
  - [ ] POST `/qnr/editor/select_node` - select node, show edges in side panel

#### Editor Workflow (Write Operations)
- [ ] Create `smeme/qnr/editor/` directory structure
- [ ] Implement models (`smeme/qnr/editor/models.py`)
  - [ ] `QNREditorState` (TypedDict with `warnings` field)
  - [ ] Request models for CRUD operations
- [ ] Implement operations (`smeme/qnr/editor/operations.py`)
  - [ ] `apply_operation` function
  - [ ] Node CRUD logic (create, update, delete)
  - [ ] Edge CRUD logic (create, update, delete)
- [ ] Implement workflow (`smeme/qnr/editor/workflow.py`)
  - [ ] `load_qnr_node` (no cache, always fresh - comment updated)
  - [ ] `apply_operation_node`
  - [ ] `validate_graph_node` (uses `validate_graph_for_editing`)
  - [ ] `save_to_db_node`
  - [ ] `invalidate_cache_node`
  - [ ] `build_editor_workflow`
- [ ] Implement routes (`smeme/qnr/editor/routes.py`)
  - [ ] POST `/qnr/editor/update_node` - update node data
  - [ ] POST `/qnr/editor/delete_node` - delete node
  - [ ] POST `/qnr/editor/create_node` - create node
  - [ ] POST `/qnr/editor/create_edge_form` - render inline form for new edge
  - [ ] POST `/qnr/editor/create_edge` - create edge (from node context)
  - [ ] POST `/qnr/editor/update_edge_form` - render inline form with target dropdown + condition
  - [ ] POST `/qnr/editor/update_edge` - update edge target and/or condition (validates cycles)
  - [ ] POST `/qnr/editor/delete_edge` - delete edge (from node context)
  - [ ] POST `/qnr/editor/{qnr_id}/preview` - strict validation before preview
  - [ ] POST `/qnr/editor/{qnr_id}/publish` - strict validation + status change to "published"

#### Integration
- [ ] Add `status` and `published_at` fields to `QNR` model (`smeme/qnr/models.py`)
- [ ] Create template (`smeme/templates/qnr/editor.html`)
  - [ ] Warning banner for draft issues (yellow, top of page)
  - [ ] Status badge (draft/published)
  - [ ] Preview and Publish buttons with HTMX
- [ ] Register both routers in `smeme/main.py`
- [ ] Implement cache helper functions (`smeme/core/cache.py`)
  - [ ] `get_cached_qnr`
  - [ ] `set_cached_qnr`
  - [ ] `invalidate_qnr_cache`
- [ ] Implement DB helper functions (`smeme/qnr/helpers/db_queries.py`)
  - [ ] `update_qnr_graph` (update QNR in database)
- [ ] Test viewer workflow end-to-end
- [ ] Test editor workflow end-to-end
- [ ] Test viewer → editor → viewer round-trip (with warnings)
- [ ] Test preview/publish validation (blocking modal)
- [ ] Verify cache invalidation works correctly
- [ ] Verify structured logging in both workflows
- [ ] Test tiered validation scenarios:
  - [ ] Create cycle → see warning banner → delete edge → warning disappears
  - [ ] Try to publish with cycle → blocked by modal
  - [ ] Fix issues → publish succeeds → status changes to "published"

### Phase 2: QNR Relationships & Structure

- [ ] Split QNR at node
  - [ ] Select split point (node becomes terminal in QNR A, entry in QNR B)
  - [ ] Create two new QNRs from original
  - [ ] Delete original QNR
  - [ ] Set prerequisite relationship (optional)
- [ ] Merge QNRs
  - [ ] Select two QNRs to merge
  - [ ] Validate no branching conflicts
  - [ ] Connect terminal nodes of first to entry node of second
  - [ ] Create single merged QNR
- [ ] QNR Prerequisites
  - [ ] Mark QNR as requiring another QNR completion
  - [ ] Pass result from prerequisite QNR to first question
  - [ ] Validation: prevent circular dependencies
- [ ] Generate Follow-on QNR
  - [ ] Button in editor: "Generate Follow-on QNR"
  - [ ] Pass current QNR context to generation workflow
  - [ ] Optionally include current QNR results in prompt
  - [ ] Auto-link as prerequisite relationship

### Phase 3: Advanced Features

- [ ] Visual edge creation (click source, click target)
- [ ] Zoom and pan controls
- [ ] Auto-layout button (re-calculate positions)
- [ ] Graph validation warnings (inline)
- [ ] Live preview mode (split screen)
- [ ] Version history and diff view
- [ ] Export as image (PNG/SVG)
- [ ] QNR Curriculum Builder
  - [ ] Order multiple QNRs into sequence
  - [ ] Set pricing tiers per level
  - [ ] Marketing restrictions (complete lower tier first)
  - [ ] Hierarchy visualization

---

## QNR Status Management

### Database Schema: QNR Status Field

The `QNR` model needs a `status` field to track draft vs. published state:

```python
# smeme/qnr/models.py additions

class QNR(SQLModel, table=True):
    # ... existing fields ...
    
    # Status tracking
    status: str = Field(default="draft")  # "draft", "published", "archived"
    published_at: datetime | None = Field(default=None)
```

### Status Transitions

```
draft → published  (via publish route, strict validation)
published → draft  (via unpublish, if needed)
published → archived  (soft delete, keep for history)
```

### Validation by Status

| Status | Validation Level | Can Edit? | Visible to Users? |
|--------|------------------|-----------|-------------------|
| `draft` | Lenient (warnings only) | ✅ Yes | ❌ No |
| `published` | N/A (already validated) | ⚠️ Creates new draft | ✅ Yes |
| `archived` | N/A | ❌ No | ❌ No |

### Editing Published QNRs

**Option 1: Create Draft Copy** (Recommended)
- Published QNRs are immutable
- Clicking "Edit" on published QNR creates a draft copy
- Author edits draft, then publishes again (new version)

**Option 2: Direct Edit with Versioning**
- Published QNRs can be edited
- Each edit creates a new version in history
- Active sessions use old version until completion

**Decision**: Start with Option 1 (simpler, prevents breaking active sessions)

---

## Authorization & Visibility by Status

### Visibility Rules

QNR visibility depends on **status** and **authorship**:

| QNR Status | Author Can See? | Other Users Can See? | Can Navigate? |
|------------|-----------------|---------------------|---------------|
| `draft` | ✅ Yes (edit/preview) | ❌ No | ❌ No (author can preview) |
| `published` | ✅ Yes (view/copy) | ✅ Yes | ✅ Yes (all users) |
| `archived` | ✅ Yes (view only) | ❌ No | ❌ No |

### Implementation: Query Filters & Authorization

#### Dashboard Route (List QNRs)

```python
# smeme/qnr/routes.py

@router.get("/dashboard")
async def qnr_dashboard(
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """Show QNRs available to this user."""
    
    # Author's own QNRs (all statuses except archived)
    authored_qnrs = await db.execute(
        select(QNR)
        .where(
            QNR.author_id == user.id,
            QNR.status.in_(["draft", "published"])
        )
        .order_by(QNR.updated_at.desc())
    )
    my_qnrs = authored_qnrs.scalars().all()
    
    # Published QNRs by others (only published)
    published_qnrs = await db.execute(
        select(QNR)
        .where(
            QNR.status == "published",
            QNR.author_id != user.id
        )
        .order_by(QNR.published_at.desc())
    )
    available_qnrs = published_qnrs.scalars().all()
    
    return render_template(
        "qnr/dashboard.html",
        my_qnrs=my_qnrs,  # Includes drafts
        available_qnrs=available_qnrs  # Only published
    )
```

#### Editor Route (View/Edit QNR)

```python
# smeme/qnr/viewer/routes.py

@router.get("/{qnr_id}/editor")
async def view_editor_page(
    qnr_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """Render QNR graph editor page."""
    
    # Load QNR
    qnr = await get_qnr_by_id(db, qnr_id)
    if not qnr:
        raise HTTPException(status_code=404, detail="QNR not found")
    
    # Authorization: Only author can view/edit drafts
    if qnr.status == "draft" and qnr.author_id != user.id:
        raise HTTPException(
            status_code=403, 
            detail="Draft QNRs can only be accessed by their author"
        )
    
    # Published QNRs: Anyone can view, only author can edit
    # (Editing published QNR creates draft copy - Phase 2 feature)
    
    # Continue with viewer workflow...
```

#### Navigation Route (Start QNR Session)

```python
# smeme/qnr/routes.py

@router.post("/start")
async def start_qnr(
    qnr_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """Start a QNR session."""
    
    # Load QNR
    qnr = await get_qnr_by_id(db, qnr_id)
    if not qnr:
        raise HTTPException(status_code=404, detail="QNR not found")
    
    # Only published QNRs can be navigated
    if qnr.status != "published":
        if qnr.author_id == user.id:
            # Author trying to start draft → suggest preview
            return HTMLResponse(
                content=f"""
                <div class="bg-yellow-50 border-l-4 border-yellow-400 p-4">
                    <p class="font-medium text-yellow-800">This is a draft QNR</p>
                    <p class="text-yellow-700 text-sm mt-1">
                        Draft QNRs cannot be started. Please publish it first or use Preview mode.
                    </p>
                    <div class="mt-3 flex gap-2">
                        <a href="/qnr/{qnr_id}/editor" class="text-yellow-600 hover:underline">Edit</a>
                        <a href="/qnr/{qnr_id}/preview" class="text-yellow-600 hover:underline">Preview</a>
                    </div>
                </div>
                """
            )
        else:
            # Non-author trying to access draft → 404 (don't reveal existence)
            raise HTTPException(status_code=404, detail="QNR not found")
    
    # Continue with navigation workflow...
```

#### Preview Route (Author-Only for Drafts)

```python
# smeme/qnr/routes.py

@router.get("/{qnr_id}/preview")
async def preview_qnr(
    qnr_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """Preview QNR in navigation mode (no saving results)."""
    
    # Load QNR
    qnr = await get_qnr_by_id(db, qnr_id)
    if not qnr:
        raise HTTPException(status_code=404, detail="QNR not found")
    
    # Authorization
    if qnr.status == "draft" and qnr.author_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="Cannot preview draft QNRs by other authors"
        )
    
    # Run navigation workflow in preview mode (no result saving)
    # ... workflow invocation ...
```

### Dashboard Template with Status Badges

```html
<!-- smeme/templates/qnr/dashboard.html -->

{% extends "layouts/base.html" %}

{% block content %}
<div class="container mx-auto p-6">
    <!-- My QNRs (includes drafts) -->
    <section class="mb-8">
        <h2 class="text-2xl font-bold mb-4">My Questionnaires</h2>
        {% if my_qnrs %}
        <div class="grid gap-4">
            {% for qnr in my_qnrs %}
            <div class="border rounded-lg p-4 flex justify-between items-center hover:bg-gray-50">
                <div class="flex-1">
                    <div class="flex items-center gap-2">
                        <h3 class="text-lg font-semibold">{{ qnr.metadata.title }}</h3>
                        <span class="inline-block px-2 py-1 text-xs font-semibold rounded
                            {% if qnr.status == 'published' %}bg-green-100 text-green-800
                            {% elif qnr.status == 'draft' %}bg-gray-100 text-gray-800
                            {% else %}bg-yellow-100 text-yellow-800{% endif %}">
                            {{ qnr.status|title }}
                        </span>
                    </div>
                    <p class="text-sm text-gray-600 mt-1">{{ qnr.metadata.description }}</p>
                    <p class="text-xs text-gray-500 mt-2">
                        Updated {{ qnr.updated_at|format_datetime }}
                        {% if qnr.status == 'published' %}
                        • Published {{ qnr.published_at|format_datetime }}
                        {% endif %}
                    </p>
                </div>
                <div class="flex gap-2 ml-4">
                    {% if qnr.status == 'draft' %}
                        <a href="/qnr/{{ qnr.id }}/editor" class="btn-primary">Edit</a>
                        <a href="/qnr/{{ qnr.id }}/preview" class="btn-secondary">Preview</a>
                    {% elif qnr.status == 'published' %}
                        <a href="/qnr/{{ qnr.id }}/editor" class="btn-secondary">View</a>
                        <a href="/qnr/{{ qnr.id }}/start" class="btn-primary">Take</a>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <div class="bg-gray-50 border-2 border-dashed rounded-lg p-8 text-center">
            <p class="text-gray-600 mb-4">You haven't created any questionnaires yet.</p>
            <a href="/qnr/generate" class="btn-primary">Create Your First QNR</a>
        </div>
        {% endif %}
    </section>
    
    <!-- Available QNRs (published only, by others) -->
    <section>
        <h2 class="text-2xl font-bold mb-4">Available Questionnaires</h2>
        {% if available_qnrs %}
        <div class="grid gap-4">
            {% for qnr in available_qnrs %}
            <div class="border rounded-lg p-4 flex justify-between items-center hover:bg-gray-50">
                <div class="flex-1">
                    <h3 class="text-lg font-semibold">{{ qnr.metadata.title }}</h3>
                    <p class="text-sm text-gray-600 mt-1">{{ qnr.metadata.description }}</p>
                    <p class="text-xs text-gray-500 mt-2">
                        by {{ qnr.author.username }} • 
                        Published {{ qnr.published_at|format_datetime }} •
                        {{ qnr.metadata.estimated_time }} min
                    </p>
                </div>
                <div class="flex gap-2 ml-4">
                    <a href="/qnr/{{ qnr.id }}/start" class="btn-primary">Take</a>
                </div>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <div class="bg-gray-50 border-2 border-dashed rounded-lg p-8 text-center">
            <p class="text-gray-600">No published questionnaires available yet.</p>
        </div>
        {% endif %}
    </section>
</div>
{% endblock %}
```

### Security Considerations

1. **Draft Privacy**: Non-authors should never know a draft QNR exists (404, not 403)
2. **Query Filtering**: Always filter by status in DB queries, never rely on UI hiding
3. **Authorization Checks**: Check status + authorship in every route that accesses QNRs
4. **Cache Keys**: Cached data doesn't include authorization info, so routes must still check

### Testing Authorization

```python
# tests/test_qnr_authorization.py

async def test_draft_visibility_author_only():
    """Author can see their drafts, others get 404."""
    # Author creates draft
    draft_qnr = create_draft_qnr(author=user1)
    
    # Author can access
    response = await client.get(f"/qnr/{draft_qnr.id}/editor", user=user1)
    assert response.status_code == 200
    
    # Other user gets 404
    response = await client.get(f"/qnr/{draft_qnr.id}/editor", user=user2)
    assert response.status_code == 404

async def test_published_visibility_all_users():
    """Published QNRs visible to all users."""
    # Author publishes QNR
    published_qnr = create_published_qnr(author=user1)
    
    # Any user can access
    response = await client.get(f"/qnr/{published_qnr.id}/start", user=user2)
    assert response.status_code == 200

async def test_draft_cannot_be_started():
    """Draft QNRs cannot be navigated, even by author."""
    draft_qnr = create_draft_qnr(author=user1)
    
    # Author tries to start draft
    response = await client.post(f"/qnr/{draft_qnr.id}/start", user=user1)
    assert response.status_code == 200
    assert "draft QNR" in response.text.lower()
    assert "/editor" in response.text  # Suggests editing
```

---

## QNR Relationships & Prerequisites

### Database Schema Extensions

```python
# smeme/core/models.py additions

class QNRRelationship(SQLModel, table=True):
    """Relationships between QNRs (prerequisites, sequences)."""
    
    model_config = {"arbitrary_types_allowed": True}
    
    __tablename__ = "qnr_relationships"
    
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    
    # The dependent QNR (requires prerequisite to be completed)
    qnr_id: UUID = Field(foreign_key="qnrs.id", index=True)
    
    # The prerequisite QNR (must be completed first)
    prerequisite_qnr_id: UUID = Field(foreign_key="qnrs.id", index=True)
    
    # Relationship type
    relationship_type: str = Field(default="prerequisite")  # "prerequisite", "sequence", "curriculum"
    
    # Should the result of prerequisite QNR be passed to dependent QNR?
    pass_result: bool = Field(default=False)
    
    # If pass_result=True, which question in dependent QNR receives the result?
    target_question_id: str | None = Field(default=None)
    
    # Optional: Order in sequence/curriculum
    sequence_order: int | None = Field(default=None, index=True)
    
    # Metadata
    created_at: Mapped[datetime] = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default_factory=lambda: datetime.now(UTC),
            server_default=sa.func.now(),
        )
    )
```

### Split QNR Operation

```python
# smeme/qnr/editor/operations.py

async def split_qnr_at_node(
    db: AsyncSession,
    qnr_id: UUID,
    split_node_id: str,
    user_id: UUID,
    create_prerequisite: bool = False,
) -> tuple[UUID, UUID]:
    """
    Split QNR into two QNRs at specified node.
    
    Algorithm:
    1. Load original QNR
    2. Find all nodes reachable from entry to split_node (QNR A)
    3. Find all nodes reachable from split_node to terminals (QNR B)
    4. Create QNR A: entry → split_node (split_node becomes terminal)
    5. Create QNR B: split_node → terminals (split_node becomes entry)
    6. If create_prerequisite: link A → B
    7. Delete original QNR
    
    Returns:
        (qnr_a_id, qnr_b_id)
    """
    # Implementation details...
    pass
```

### Generate Follow-on QNR with Context

Enhanced generation prompt that includes current QNR context:

```python
# Extension to smeme/qnr/generation/prompts.py

GENERATE_FOLLOWON_QUESTIONNAIRE_PROMPT = """You are a subject matter expert on {{topic}}.

You are creating a follow-on questionnaire that builds upon a prerequisite questionnaire
that the user must complete first.

## Context from Prerequisite QNR

Title: {{prerequisite_title}}
Description: {{prerequisite_description}}

Questions covered:
{{prerequisite_questions}}

## Your Task

Create a new questionnaire that:
1. Builds upon the knowledge gathered in the prerequisite
2. Addresses the user's new goal: {{goal}}
3. Does NOT repeat questions already asked in prerequisite
4. Can reference/use results from prerequisite if needed

The first question can optionally receive the result/summary from the prerequisite QNR.

[... rest of standard generation prompt ...]
"""
```

### QNR Curriculum Structure

```python
# smeme/qnr/models.py additions

class QNRCurriculum(BaseModel):
    """Curriculum - ordered sequence of related QNRs."""
    
    id: UUID
    title: str
    description: str
    author_id: UUID
    
    # Ordered list of QNR IDs
    qnr_sequence: list[UUID]
    
    # Pricing tiers (optional)
    pricing_tiers: dict[int, float] | None = None  # level -> price
    
    # Marketing restrictions
    require_sequential_completion: bool = True
    hide_until_prerequisite_complete: bool = False
```

### Navigation Workflow Integration

When starting a QNR with prerequisites:

```python
# smeme/qnr/routes.py modification

@router.post("/start")
async def start_qnr(
    qnr_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
):
    """Start QNR (check prerequisites first)."""
    
    # Check if QNR has prerequisites
    prerequisites = await get_qnr_prerequisites(db, qnr_id)
    
    for prereq in prerequisites:
        # Check if user has completed prerequisite
        completed = await user_completed_qnr(db, user.id, prereq.prerequisite_qnr_id)
        
        if not completed:
            return HTMLResponse(
                content=f"<div>You must complete prerequisite QNR first</div>"
            )
        
        # If pass_result=True, get the result and prepopulate target question
        if prereq.pass_result and prereq.target_question_id:
            result = await get_qnr_session_result(
                db, user.id, prereq.prerequisite_qnr_id
            )
            # Store in session for prepopulation
            state["prepopulated_answers"] = {
                prereq.target_question_id: result
            }
    
    # Continue with normal workflow...
```

---

## Multiple Entry Points & Context-Aware Navigation

### Use Case: Adaptive Questionnaire Starting Points

QNRs can have **multiple entry points** with conditions to determine which question to start from based on user context (e.g., prior QNR completion, session history, user preferences).

#### Example: Marathon Training Assessment

```
Entry Points:
1. q1 (default): "Have you run a marathon before?"
   - entry_condition: None (fallback for all users)
   
2. q5 (advanced): "What's your target marathon time?"
   - entry_condition: "completed_qnr:basic_running_assessment"
   
3. q8 (returning): "How has your training been since last assessment?"
   - entry_condition: "last_session_within:90_days"
```

### Database Schema Extension

```python
# smeme/qnr/models.py

class QuestionData(BaseModel):
    """Question node data."""
    text: str
    type: Literal["text", "number", "radio", "checkbox"]
    options: list[str] | None = None
    placeholder: str | None = None
    required: bool = True
    help_text: str | None = None
    
    # NEW: Entry point condition (Phase 2)
    entry_condition: str | None = None
    """
    Condition for this node to serve as entry point.
    Examples:
    - None: Default entry (no condition)
    - "completed_qnr:<qnr_id>": User completed prerequisite QNR
    - "last_session_within:<days>_days": User has recent session
    - "user_attribute:<key>=<value>": User has specific attribute
    """
```

### Navigation Workflow Integration

```python
# smeme/qnr/workflow.py - Enhanced entry point determination

async def determine_entry_point_node(
    state: QNRNavigationState,
    config: RunnableConfig
) -> QNRNavigationState:
    """
    Determine which entry point to use based on user context.
    
    For single entry point: Use that node (simple case)
    For multiple entry points: Evaluate conditions, fallback to default
    """
    graph = state["graph"]
    user_id = state["user_id"]
    db: AsyncSession = config["configurable"]["db"]
    
    # Get all entry points (nodes with no incoming edges)
    entry_points = [n for n in graph.nodes if not any(e.target == n.id for e in graph.edges)]
    
    if len(entry_points) == 1:
        # Simple case: single entry point
        logger.info(
            "Single entry point found",
            extra={"node_id": entry_points[0].id, "user_id": str(user_id)}
        )
        return {"current_question_id": entry_points[0].id}
    
    # Multiple entry points: evaluate conditions
    logger.info(
        "Evaluating multiple entry points",
        extra={
            "entry_point_count": len(entry_points),
            "user_id": str(user_id)
        }
    )
    
    # Build user context for condition evaluation
    user_context = await build_user_context(db, user_id)
    
    # Evaluate conditions in order (most specific first)
    conditional_entries = [e for e in entry_points if e.data.entry_condition]
    for entry in conditional_entries:
        if await evaluate_entry_condition(entry.data.entry_condition, user_context):
            logger.info(
                "Entry condition matched",
                extra={
                    "node_id": entry.id,
                    "condition": entry.data.entry_condition,
                    "user_id": str(user_id)
                }
            )
            return {"current_question_id": entry.id}
    
    # Fallback: use default entry point (no condition)
    default_entry = next((e for e in entry_points if not e.data.entry_condition), None)
    if default_entry:
        logger.info(
            "Using default entry point",
            extra={"node_id": default_entry.id, "user_id": str(user_id)}
        )
        return {"current_question_id": default_entry.id}
    
    # Error: no valid entry point
    logger.error(
        "No valid entry point found",
        extra={"entry_point_count": len(entry_points), "user_id": str(user_id)}
    )
    return {"error": "No valid entry point found"}


async def build_user_context(db: AsyncSession, user_id: UUID) -> dict:
    """Build context for entry condition evaluation."""
    
    # Get user's completed QNRs
    completed_qnrs = await db.execute(
        select(QNRSession.qnr_id)
        .where(
            QNRSession.user_id == user_id,
            QNRSession.completed_at.isnot(None)
        )
    )
    completed_qnr_ids = [str(qnr_id) for (qnr_id,) in completed_qnrs]
    
    # Get last session date
    last_session = await db.execute(
        select(QNRSession.created_at)
        .where(QNRSession.user_id == user_id)
        .order_by(QNRSession.created_at.desc())
        .limit(1)
    )
    last_session_date = last_session.scalar_one_or_none()
    
    return {
        "completed_qnrs": completed_qnr_ids,
        "last_session_date": last_session_date,
        # Future: user attributes, preferences, etc.
    }


async def evaluate_entry_condition(condition: str, context: dict) -> bool:
    """
    Evaluate entry condition against user context.
    
    Supported conditions:
    - "completed_qnr:<qnr_id>": Check if user completed QNR
    - "last_session_within:<days>_days": Check if user has recent session
    - Future: More complex conditions
    """
    
    if condition.startswith("completed_qnr:"):
        required_qnr_id = condition.split(":", 1)[1]
        return required_qnr_id in context.get("completed_qnrs", [])
    
    elif condition.startswith("last_session_within:"):
        days_str = condition.split(":")[1].replace("_days", "")
        days = int(days_str)
        last_session = context.get("last_session_date")
        if not last_session:
            return False
        days_since = (datetime.utcnow() - last_session).days
        return days_since <= days
    
    # Unknown condition → False (fail closed)
    logger.warning(
        "Unknown entry condition",
        extra={"condition": condition}
    )
    return False
```

### Validation Rules

#### Tier-2 Warning (Draft Editing)

```python
# Already implemented in validate_graph_for_editing()

entry_nodes = [n for n in graph.nodes if not any(e.target == n.id for e in graph.edges)]

if len(entry_nodes) > 1:
    # Check for default (no entry_condition)
    has_default = any(not n.data.get("entry_condition") for n in entry_nodes)
    if not has_default:
        warnings.append(
            f"⚠️ Multiple entry points ({len(entry_nodes)}) with no default fallback. "
            f"Mark one entry point without entry_condition as the default."
        )
```

#### Tier-3 Blocking (Publish)

```python
# In validate_graph_for_publication()

# All warnings promoted to errors, including:
# "Multiple entry points with no default fallback"
# → Blocks publication until one entry point has entry_condition=None
```

**Rationale**: During editing, authors can experiment with multiple entry points. But before publishing, they MUST designate a default fallback to ensure all users can start the QNR.

### Editor UI for Entry Conditions (Phase 2)

```python
# In render_node_editor() - add entry condition field for nodes with no incoming edges

is_entry_point = not any(e["target"] == node_id for e in graph["edges"])

if is_entry_point:
    entry_condition_html = f"""
    <div class="border-t pt-4 mt-4">
        <h4 class="text-md font-semibold mb-2">Entry Point Condition</h4>
        <p class="text-sm text-gray-600 mb-2">
            This node is an entry point. Set a condition to make it conditional,
            or leave empty to make it the default entry.
        </p>
        <input
            type="text"
            name="entry_condition"
            value="{data.get("entry_condition", "")}"
            placeholder="e.g., completed_qnr:abc123 or last_session_within:90_days"
            class="w-full border rounded px-3 py-2 text-sm">
        <p class="text-xs text-gray-500 mt-1">
            Examples: <code>completed_qnr:&lt;qnr_id&gt;</code>, 
            <code>last_session_within:&lt;days&gt;_days</code>
        </p>
    </div>
    """
```

### Benefits

1. **Personalized Experience**: Users with context get advanced starting points
2. **Skip Redundancy**: Don't re-ask questions answered in prerequisite QNRs
3. **Returning Users**: Special paths for users with session history
4. **Gradual Complexity**: Beginners start simple, advanced users skip ahead

### Limitations (Phase 1)

- Entry conditions are **author-defined strings** (no validation during editing)
- Navigation workflow **fails gracefully** (unknown condition → use default)
- Phase 2 will add:
  - Entry condition builder UI
  - Validation of condition syntax
  - Testing entry conditions in preview mode

---

## Design Decisions & Lessons Learned

### 1. Two-Workflow Architecture (Viewer + Editor)

**Decision**: Split into separate workflows for read-only viewing and write operations.

**Rationale**:
- Clear separation of concerns (read vs write)
- Different performance profiles (viewer: high-frequency/cacheable, editor: low-frequency/transactional)
- Simpler state management (viewer: simple/readonly, editor: complex/stateful)
- Follows existing pattern (generation + navigation)
- Better error handling (viewer failures non-critical, editor failures need rollback)
- Independent scaling and testing

**Trade-offs**:
- Two workflows to maintain instead of one
- Slightly more code complexity
- BUT: Each workflow is simpler individually, and the separation is justified

### 2. Aggressive Caching in Viewer, No Caching in Editor

**Decision**: Viewer uses same caching strategy as navigation workflow; editor always loads fresh data.

**Rationale**:
- Viewer is read-only, so cached data is safe
- Editor is actively modifying data, so cache would be stale
- Editor invalidates cache after successful save
- Viewer benefits from navigation workflow's cache hits

**Implementation**:
- Viewer: Try cache → DB → cache result
- Editor: DB (fresh) → apply changes → validate → save → invalidate cache
- Navigation workflow: Shares cache with viewer

### 3. No LLM Calls in Core Viewer/Editor

- Pure data transformation workflows (fast, cheap, predictable)
- All intelligence in layout algorithm and validation
- LLM is used in "Generate Follow-on QNR" feature (separate workflow)

### 4. HTMX-First Interaction Model

- No JavaScript framework needed
- Server-side rendering for all updates
- Simpler state management
- Progressive enhancement possible

**Flow**:
1. User clicks "Edit QNR" → GET `/qnr/{id}/editor` → Viewer workflow → HTML
2. User clicks node → HTMX POST `/qnr/editor/select_node` → Viewer workflow (with selection) → HTML swap
3. User clicks "Save" → HTMX POST `/qnr/editor/update_node` → Editor workflow → Redirect to viewer
4. Viewer re-renders with updated (cache-invalidated) data

### 5. Hierarchical Layout Algorithm

- BFS traversal ensures logical top-to-bottom flow
- Works well for tree-like and DAG structures
- Can be enhanced with force-directed layout later
- Shared by both viewer and editor workflows

### 6. Validation After Every Edit Operation

- Editor workflow validates before saving
- Prevents invalid graphs from reaching database
- Show validation errors to user (failed editor workflow)
- User can retry after fixing issues

### 7. QNR Relationships Enable Complex Workflows

- **Lemma Pattern**: Prerequisite QNRs are like lemmas in proofs - complete smaller proof first, use result in larger proof
- **Curriculum Building**: Authors can create learning paths with multiple QNRs
- **Context Passing**: Results from one QNR flow into the next (prepopulated answers)
- **Circular Dependency Prevention**: Validation ensures no QNR requires itself (directly or transitively)

### 8. Transaction-Like Editor Workflow

**Decision**: Editor workflow is a 5-node pipeline with early exit on failure.

**Nodes**:
1. Load QNR (fresh from DB)
2. Apply operation (in-memory transformation)
3. Validate graph (check constraints)
4. Save to database (atomic write)
5. Invalidate cache (non-critical)

**Benefits**:
- Early exit if load/operation/validation fails
- No partial writes to database
- Clear success/failure states
- Cache invalidation is separate (doesn't block user on failure)

### 9. Node-Only Clicking (Edges Not Clickable)

**Decision**: Only nodes are clickable in the graph visualization. Edges are edited via the selected node's side panel.

**Rationale**:
- **Simpler User Mental Model**: Users think in terms of "questions" (nodes), not "connections" (edges). Edges are properties of nodes.
- **Better Click Targets**: Nodes are large (200x80px), edges are thin (2-3px) and hard to click precisely.
- **Context-Aware Edge Editing**: When editing edges from a node, the source (for outgoing) or target (for incoming) is already known.
- **Cleaner Visualization**: No need for edge hover states, selection highlighting, or complex event handling.
- **Matches Common Patterns**: Most node-based editors (n8n, Node-RED, LangGraph Studio) work this way.

**Implementation**:
- SVG edges are non-interactive (no click handlers, `pointer-events-none` on labels)
- Side panel shows two sections when node is selected:
  - **Outgoing Edges**: List with inline edit/delete, "+ Add Edge" button
  - **Incoming Edges**: Read-only list (edit from source node)
- Edge operations use `source + target` as identifier instead of `edge_id`

**UX Flow**:
1. User clicks node → Side panel shows node properties + outgoing/incoming edges
2. User clicks "Edit" on an edge → Inline form appears with target dropdown + condition input
3. User changes target and/or condition → Validation checks for cycles, self-loops, duplicates
4. User clicks "Delete" on an edge → Edge deleted immediately (with confirmation)
5. User clicks "+ Add Edge" → Inline form appears for new edge from this node

### 10. Visual Models are Viewer-Only (Not Shared)

**Decision**: `NodePosition`, `VisualNode`, `VisualEdge`, `GraphVisualization` live in `smeme/qnr/viewer/models.py` and are NOT used by the Editor Workflow.

**Rationale**:
- **Editor operates on semantic data**: Questions, edges, conditions (stored in DB as `QNRGraph`)
- **Viewer generates visual data**: Positions, SVG paths, layout (ephemeral, never persisted)
- **Clean separation**: Data layer (Editor) vs. Presentation layer (Viewer)
- **Editor never positions nodes**: It modifies the graph and redirects to Viewer, which re-calculates positions

**Flow**:
```
POST /qnr/editor/update_node
  ↓
Editor Workflow
  ↓ (modifies QNRGraph, saves to DB, invalidates cache)
  ↓
Redirect to GET /qnr/{id}/editor
  ↓
Viewer Workflow (cache empty, loads fresh from DB)
  ↓
Layout algorithm → NodePosition for each node
  ↓
Renderer → SVG with positioned nodes
```

**Why This Matters**:
- Prevents confusion about who "owns" positions
- Makes it clear positions are derived, not stored
- Editor can't accidentally corrupt visual state
- Simpler mental model: Editor = data CRUD, Viewer = visualization

### 11. Editable Edge Targets (Not Just Conditions)

**Decision**: Users can change both the target node and condition when editing an edge.

**Rationale**:
- **Common Refactoring Need**: "Question 3 should go to question 5, not question 4"
- **Fewer Operations**: Change target in one operation vs. delete + recreate (2 operations)
- **Preserves Conditions**: No need to re-enter condition when just changing target
- **Better UX**: More intuitive and flexible for restructuring questionnaires

**Validation Required**:
1. **Self-Loops**: Prevent `source == target` (dropdown excludes source node)
2. **Cycles**: DFS-based cycle detection with path tracking for clear error messages
3. **Duplicate Edges**: Check for existing `(source, target)` pairs
4. **Orphaned Subgraphs**: Already caught by existing "unreachable nodes" validation

**Implementation**:
- `update_edge_form` route fetches all nodes, builds dropdown excluding source
- `update_edge` route takes `old_target` and `new_target` parameters
- Editor workflow's `validate_graph_node` runs enhanced validation
- Clear error messages show cycle path: "Cycle detected: q1 → q2 → q3 → q1"

**Trade-offs**:
- Slightly more complex validation (DFS cycle detection)
- But: Validation is fast O(V + E), runs only on save, provides immediate feedback
- Benefit far outweighs cost for better editing flexibility

### 12. Tiered Validation: Draft vs. Published (Lenient During Editing)

**Decision**: Three-tier validation strategy based on QNR lifecycle stage.

**Problem**: 
- Authors need flexibility to work incrementally (create cycle, then delete node to break it)
- But published QNRs must be fully valid (users can't navigate broken questionnaires)
- Industry leaders (LangGraph Studio, n8n) allow "messy" drafts, validate on run/publish

**Solution**: Three validation tiers based on context

#### Tier 1: Critical Errors (Block Immediately During Editing)
```python
- Self-loops (always a mistake)
- Duplicate edges (same source→target)
- Invalid edge conditions (won't work in navigation workflow)
```

**Why Block**: These will definitely break the navigation workflow and are never intentional.

#### Tier 2: Warnings (Allow During Editing)
```python
- Cycles (might be working toward breaking them)
- Orphaned nodes (might be adding connections)
- No entry point (might be building from bottom-up)
- No terminal nodes (might be adding endings)
- Missing default edges (might be adding options/edges)
```

**Why Warn**: Authors may be working incrementally. Show yellow banner but don't block save.

#### Tier 3: Strict Validation (Block on Preview/Publish)
```python
All Tier 2 warnings become blocking errors
- Cannot preview with cycles
- Cannot publish with orphaned nodes
- Must have entry + terminal nodes
```

**Why Block**: Published QNRs must be fully navigable by users.

**Industry Comparison**:

| Tool | Draft Validation | Publish Validation |
|------|------------------|-------------------|
| **LangGraph Studio** | None (allow anything) | Compile-time (block) |
| **n8n** | Warnings only | Cannot execute if invalid |
| **GitHub Actions** | Block invalid immediately | N/A (always valid) |
| **Our QNR Editor** | Block critical only | Block all warnings |

**Implementation**:

```python
# During editing (POST /qnr/editor/update_node)
is_ok, blocking_errors, warnings = validate_graph_for_editing(graph)
if not is_ok:
    return {"error": blocking_errors[0]}  # Block critical errors
# Save succeeds, warnings shown in yellow banner

# Before preview/publish (POST /qnr/editor/{id}/publish)
is_valid, all_errors = validate_graph_for_publication(graph)
if not is_valid:
    return modal_with_errors(all_errors)  # Block publication
# Publish succeeds, status → "published"
```

**User Experience**:

```
Author: *Creates q1, q2, q3*
Author: *Adds edge q1 → q2, q2 → q3, q3 → q1 (cycle!)*
System: ✅ Saved
        ⚠️  Yellow banner: "Cycle detected: q1 → q2 → q3 → q1"
        
Author: *Continues editing, adds q4*
System: ✅ Saved (still shows cycle warning)

Author: *Clicks "Publish"*
System: ❌ Modal: "Cannot publish - fix these issues:
             • Cycle detected: q1 → q2 → q3 → q1
             • Orphaned node: q4"
        [Back to Editor]
        
Author: *Deletes edge q3 → q1, adds edge q3 → q4*
System: ✅ Saved
        ✅ No warnings! Yellow banner disappears
        
Author: *Clicks "Publish"*
System: ✅ "QNR Published!"
```

**Benefits**:
1. **Flexibility**: Authors can work in any order (top-down, bottom-up, middle-out)
2. **Clear Feedback**: Warnings visible but not blocking
3. **Quality Gate**: Published QNRs are guaranteed valid
4. **Matches Industry Standards**: Similar to LangGraph Studio (messy drafts, clean runtime)

**Trade-offs**:
- More complex validation logic (three functions instead of one)
- Yellow warning banner adds UI complexity
- But: Significantly better UX for authors working on complex QNRs

**Key Insight from User Discussion**:
> "What if a user creates a cycle but intends to delete a node on the next edit that will break that cycle?"

This is the core use case for lenient draft validation. Without it, authors would need to plan edits carefully to avoid ever creating an invalid intermediate state.

---

## Performance Considerations

### 1. Layout Calculation

- O(N + E) complexity for BFS traversal
- Acceptable for graphs with <100 nodes
- Consider caching layout for large graphs

### 2. SVG Rendering

- Server-side SVG generation is fast
- Browser handles rendering efficiently
- Consider Canvas for very large graphs (>200 nodes)

### 3. Database Updates

- Atomic updates with optimistic locking
- Invalidate cache on every edit
- Consider debouncing rapid edits

### 4. HTMX Payload Size

- Full graph re-render on each edit
- Acceptable for <50 nodes
- Consider partial updates for large graphs

---

## Open Questions

### 1. Layout Algorithm Choice

**Question**: Hierarchical vs Force-Directed?  
**Options**:
- A: Hierarchical (BFS-based, predictable)
- B: Force-directed (organic, handles cycles)
- C: User-choice toggle

**Recommendation**: A for MVP (simpler, works for tree-like QNRs), later enhancement if needed

### 2. Edit Persistence

**Question**: When to save edits to database?  
**Options**:
- A: Auto-save on every edit
- B: Manual save button
- C: Auto-save with debounce (5 seconds)

**Recommendation**: A for MVP (immediate persistence, simpler UX)

### 3. Split QNR Naming

**Question**: How to name the two QNRs created from a split?  
**Options**:
- A: Auto-generate: "{original_title} - Part 1", "{original_title} - Part 2"
- B: Prompt user for new titles
- C: Preserve original title for first part, prompt for second part title

**Recommendation**: B for MVP (explicit naming prevents confusion)

### 4. Prerequisite Result Format

**Question**: What format should prerequisite QNR results take when passed to dependent QNR?  
**Options**:
- A: Raw JSON of all answers
- B: LLM-generated summary of key findings
- C: User-selectable: specific answers or full summary

**Recommendation**: C for MVP (flexibility for different use cases), start with A (raw answers)

### 5. Circular Dependency Detection

**Question**: When to check for circular dependencies (both in graph edges and QNR prerequisites)?  
**Options**:
- A: On every edit/relationship creation (immediate feedback)
- B: Batch validation on QNR publish
- C: User-triggered "Validate" button

**Decision**: A for MVP (prevent invalid state from being created)

**Implementation**:
- **Graph Cycles**: Validated in editor workflow's `validate_graph_node` using DFS
- **QNR Prerequisites**: Validated when creating QNR relationships (Phase 2)
- Both use similar DFS-based cycle detection algorithms
- User gets immediate feedback with clear error messages showing the cycle path

---

## Summary

This plan outlines **two separate LangGraph workflows** for visual QNR editing with relationship management:

### Workflow Architecture
✅ **Two-Workflow Design** - Separate viewer (read) and editor (write) workflows  
✅ **Viewer Workflow** (3 nodes) - Fast, cacheable, read-only visualization  
✅ **Editor Workflow** (5 nodes) - Transactional, stateful write operations  
✅ **Shared Components** - Layout algorithm, renderer, visualization models  

### Core Viewer Workflow (Phase 1)
✅ **Aggressive caching** - Same strategy as navigation workflow  
✅ **3-node pipeline** - Load (cache) → Visualize → Render  
✅ **Fast rendering** - ~20-50ms for cache hits, ~100-200ms for DB loads  
✅ **Selection state** - Highlight nodes/edges, render side panel forms  
✅ **No LLM calls** - Pure data transformation (fast, cheap)  

### Core Editor Workflow (Phase 1)
✅ **No caching** - Always fresh data from database  
✅ **5-node pipeline** - Load → Apply → Validate → Save → Invalidate Cache  
✅ **Transaction-like** - Early exit on failure, no partial writes  
✅ **Operation-based** - Single workflow handles all CRUD operations  
✅ **Cache invalidation** - Ensures viewer loads updated data  
✅ **Tiered validation** - Lenient for drafts (warnings only), strict for publication  
✅ **Draft/Published status** - Track QNR lifecycle, enforce quality gates  

### Shared Features (Phase 1)
✅ **HTMX-first** - Server-side rendering, no JS framework  
✅ **Interactive SVG** - Nodes clickable, edges non-interactive  
✅ **Hierarchical layout** - BFS-based positioning  
✅ **Observable** - Structured logging throughout both workflows  
✅ **Node-centric editing** - Edges edited via node's side panel (simpler UX)  
✅ **Inline forms** - Edge CRUD happens inline without full page reload  
✅ **Editable edge targets** - Change both target node and condition in one operation  
✅ **Three-tier validation** - Critical (block), warnings (allow), publication (strict)  
✅ **Cycle detection** - DFS-based validation prevents cycles, self-loops, duplicates  
✅ **Warning banners** - Yellow banner shows draft issues without blocking edits  
✅ **Quality gates** - Preview/Publish blocked until all issues resolved  
✅ **Clean separation** - Editor (semantic data) vs. Viewer (visual data)  
✅ **Ephemeral positions** - Layout calculated on-demand, never persisted  

### Request Flow
```
GET /qnr/{id}/editor
  → Viewer Workflow (cached)
  → HTML with graph + side panel

POST /qnr/editor/select_node
  → Viewer Workflow (with selection)
  → HTML swap (full page with selected node highlighted)
  → Side panel shows node properties + outgoing/incoming edges

POST /qnr/editor/create_edge_form
  → Returns inline form HTML
  → HTMX swaps into side panel

POST /qnr/editor/create_edge
  → Editor Workflow (load → apply → validate → save → invalidate)
  → Redirect to viewer
  → Viewer Workflow (fresh, no cache)
  → HTML with updated graph + same node selected + warnings banner (if any)

POST /qnr/editor/update_node
  → Editor Workflow (load → apply → validate → save → invalidate)
  → Redirect to viewer
  → Viewer Workflow (fresh, no cache)
  → HTML with updated graph + warnings banner (if any)

POST /qnr/editor/{id}/preview
  → Load QNR from DB
  → Strict validation (validate_graph_for_publication)
  → If invalid: Modal with blocking errors
  → If valid: Redirect to /qnr/{id}/preview

POST /qnr/editor/{id}/publish
  → Load QNR from DB
  → Strict validation (validate_graph_for_publication)
  → If invalid: Modal with blocking errors
  → If valid: Set status="published", save, show success modal
```

### Validation Strategy (Tiered)

| Validation Check | During Editing | Before Preview/Publish |
|------------------|----------------|------------------------|
| Self-loops | ❌ Block | ❌ Block |
| Duplicate edges | ❌ Block | ❌ Block |
| Invalid conditions | ❌ Block | ❌ Block |
| **Cycles** | ⚠️ Warn | ❌ Block |
| **Orphaned nodes** | ⚠️ Warn | ❌ Block |
| **No entry point** | ⚠️ Warn | ❌ Block |
| **Multiple entries, no default** | ⚠️ Warn | ❌ Block |
| **No terminal** | ⚠️ Warn | ❌ Block |
| **Missing defaults** | ⚠️ Warn | ❌ Block |

**Key Insights**: 
- Authors can work incrementally with cycles/orphans during editing (yellow banner)
- Multiple entry points allowed, but at least one must be default (no `entry_condition`)
- All issues must be fixed before publishing (modal blocker)

### QNR Relationships (Phase 2)
✅ **Split QNRs** - Cut graph at node, create two related QNRs  
✅ **Merge QNRs** - Combine sequential QNRs into one  
✅ **Prerequisites** - QNR A must complete before QNR B starts  
✅ **Context Passing** - Results from prerequisite flow to dependent QNR  
✅ **Follow-on Generation** - Use LLM to generate next QNR with context  
✅ **Lemma Pattern** - Small proofs (QNRs) build into larger proofs  

### Advanced Features (Phase 3)
✅ **Curriculum Builder** - Order QNRs into learning paths  
✅ **Pricing Tiers** - Different prices for different curriculum levels  
✅ **Marketing Controls** - Hide advanced QNRs until prerequisites complete  
✅ **Dependency Validation** - Prevent circular prerequisites  

**Next Steps**: Implement Phase 1 (viewer + editor workflows with shared components), test end-to-end with cache invalidation, implement relationship features in Phase 2, gather user feedback on curriculum building needs.

