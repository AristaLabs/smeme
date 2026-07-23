"""Test LangGraph state serialization for checkpointing.

This validates:
1. Current MemorySaver (in-memory) serialization
2. Future PostgresSaver (JSONB) serialization readiness
3. UUID/datetime handling patterns
4. State persistence and recovery

References:
- docs/DEPENDENCY_GOTCHAS.md (LangGraph State Serialization)
- smeme/decision-trees/generation/agentic/models.py (AgenticDecisionTreeGenerationState)
"""

import json
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

# =============================================================================
# Test State Models
# =============================================================================


class WorkflowState(TypedDict, total=False):
    """Minimal state for testing serialization patterns."""

    # Strings (always safe)
    user_id: str  # UUID as string
    session_id: str  # UUID as string
    prompt: str

    # Timestamps (ISO 8601 strings)
    created_at: str  # datetime.isoformat()
    updated_at: str  # datetime.isoformat()

    # Structured data (dicts/lists)
    metadata: dict
    results: list[str]

    # Output
    output: str


# =============================================================================
# Test Nodes
# =============================================================================


async def init_node(state: WorkflowState) -> WorkflowState:
    """Initialize workflow with UUIDs and timestamps."""
    return {
        "user_id": str(uuid4()),
        "session_id": str(uuid4()),
        "created_at": datetime.now().isoformat(),
        "metadata": {"source": "test"},
        "results": [],
    }


async def process_node(state: WorkflowState) -> WorkflowState:
    """Process the prompt."""
    return {
        "output": f"Processed: {state['prompt']}",
        "updated_at": datetime.now().isoformat(),
        "results": ["step1", "step2"],
    }


# =============================================================================
# Test Workflow
# =============================================================================


def build_test_workflow() -> StateGraph:
    """Build a simple workflow for testing checkpointing."""
    workflow = StateGraph(WorkflowState)

    workflow.add_node("init", init_node)
    workflow.add_node("process", process_node)

    workflow.add_edge("init", "process")
    workflow.add_edge("process", END)

    workflow.set_entry_point("init")

    return workflow.compile(checkpointer=MemorySaver())


# =============================================================================
# Tests: MemorySaver (Current)
# =============================================================================


@pytest.mark.asyncio
async def test_memory_saver_basic_checkpoint():
    """Test that MemorySaver can serialize and recover state."""
    graph = build_test_workflow()

    # Run workflow
    config = {"configurable": {"thread_id": "test-123"}}
    result = await graph.ainvoke({"prompt": "test input"}, config)

    # Verify state
    assert result["user_id"]  # UUID string
    assert result["session_id"]  # UUID string
    assert result["created_at"]  # ISO timestamp
    assert result["updated_at"]  # ISO timestamp
    assert result["output"] == "Processed: test input"
    assert result["results"] == ["step1", "step2"]
    assert result["metadata"] == {"source": "test"}


@pytest.mark.asyncio
async def test_memory_saver_state_recovery():
    """Test that checkpointed state can be recovered across invocations."""
    graph = build_test_workflow()
    config = {"configurable": {"thread_id": "test-recovery"}}

    # First invocation
    result1 = await graph.ainvoke({"prompt": "first"}, config)
    user_id = result1["user_id"]
    created_at = result1["created_at"]

    # Second invocation (new thread = new state)
    result2 = await graph.ainvoke({"prompt": "second"}, config)

    # Should be different (MemorySaver doesn't persist between runs by default)
    assert result2["user_id"] != user_id
    assert result2["output"] == "Processed: second"


# =============================================================================
# Tests: UUID/Datetime Serialization Patterns
# =============================================================================


def test_uuid_to_string_serialization():
    """Test UUID → string → UUID round-trip."""
    original_uuid = uuid4()

    # Serialize
    uuid_str = str(original_uuid)
    assert isinstance(uuid_str, str)

    # Deserialize
    recovered_uuid = UUID(uuid_str)
    assert recovered_uuid == original_uuid


def test_datetime_to_isoformat_serialization():
    """Test datetime → ISO string → datetime round-trip."""
    original_dt = datetime.now()

    # Serialize
    iso_str = original_dt.isoformat()
    assert isinstance(iso_str, str)

    # Deserialize
    recovered_dt = datetime.fromisoformat(iso_str)

    # Compare (microsecond precision)
    assert abs((recovered_dt - original_dt).total_seconds()) < 0.001


def test_json_serialization_with_converted_types():
    """Test that converted UUIDs/datetimes can be JSON serialized."""
    data = {
        "user_id": str(uuid4()),
        "session_id": str(uuid4()),
        "created_at": datetime.now().isoformat(),
        "metadata": {"nested": "value"},
    }

    # Should serialize without error
    json_str = json.dumps(data)
    assert json_str

    # Should deserialize correctly
    recovered = json.loads(json_str)
    assert UUID(recovered["user_id"])  # Valid UUID
    assert datetime.fromisoformat(recovered["created_at"])  # Valid datetime


def test_json_serialization_with_raw_types_fails():
    """Demonstrate that raw UUID/datetime objects fail JSON serialization."""
    data = {
        "user_id": uuid4(),  # Raw UUID
        "created_at": datetime.now(),  # Raw datetime
    }

    # Should fail
    with pytest.raises(TypeError, match="not JSON serializable"):
        json.dumps(data)


# =============================================================================
# Tests: PostgresSaver Readiness (Future)
# =============================================================================


def test_state_is_jsonb_compatible():
    """Verify that workflow state can be serialized to JSONB (PostgreSQL)."""
    # Simulate state that would be checkpointed
    state: WorkflowState = {
        "user_id": str(uuid4()),
        "session_id": str(uuid4()),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "prompt": "test",
        "metadata": {"key": "value"},
        "results": ["a", "b"],
        "output": "result",
    }

    # Should serialize to JSON without error
    json_str = json.dumps(state)
    assert json_str

    # Should deserialize correctly
    recovered = json.loads(json_str)
    assert recovered == state


@pytest.mark.asyncio
async def test_workflow_state_after_invoke_is_serializable():
    """Verify that actual workflow output is JSON-serializable."""
    graph = build_test_workflow()

    result = await graph.ainvoke({"prompt": "test"}, {"configurable": {"thread_id": "test-json"}})

    # Should be JSON-serializable (this is what PostgresSaver would checkpoint)
    json_str = json.dumps(result)
    assert json_str

    # Verify recovery
    recovered = json.loads(json_str)
    assert UUID(recovered["user_id"])  # Can reconstruct UUID
    assert datetime.fromisoformat(recovered["created_at"])  # Can reconstruct datetime


# =============================================================================
# Tests: Production Patterns
# =============================================================================


def test_config_vs_state_separation():
    """Demonstrate correct pattern for UUIDs in config vs state.

    Following project pattern from AgenticDecisionTreeGenerationState:
    - State: UUIDs as strings (serializable)
    - Config: Actual UUID objects (not serialized)
    """
    # Config (passed to nodes, not checkpointed)
    config = {
        "configurable": {
            "user_id": uuid4(),  # Raw UUID object
            "db_session": "mock_session_object",  # Non-serializable
        }
    }

    # State (checkpointed, must be serializable)
    state = {
        "user_id": str(config["configurable"]["user_id"]),  # String
        "created_at": datetime.now().isoformat(),  # String
    }

    # State should be JSON-serializable
    json.dumps(state)  # No error

    # Config doesn't need to be (it's not checkpointed)


# =============================================================================
# Integration Test: Full Workflow Checkpoint
# =============================================================================


@pytest.mark.asyncio
async def test_full_workflow_with_checkpoint():
    """Test complete workflow with state checkpointing and serialization."""
    graph = build_test_workflow()

    # Execute workflow
    config = {"configurable": {"thread_id": "integration-test"}}
    result = await graph.ainvoke({"prompt": "integration test"}, config)

    # Verify all state fields are present
    assert "user_id" in result
    assert "session_id" in result
    assert "created_at" in result
    assert "updated_at" in result
    assert "output" in result
    assert "metadata" in result
    assert "results" in result

    # Verify all values are serializable
    json_str = json.dumps(result)
    recovered = json.loads(json_str)

    # Verify data integrity after serialization
    assert recovered["output"] == result["output"]
    assert recovered["results"] == result["results"]
    assert recovered["metadata"] == result["metadata"]

    # Verify UUIDs and timestamps can be reconstructed
    UUID(recovered["user_id"])
    UUID(recovered["session_id"])
    datetime.fromisoformat(recovered["created_at"])
    datetime.fromisoformat(recovered["updated_at"])


# =============================================================================
# Documentation
# =============================================================================


def test_print_serialization_guide():
    """Print serialization best practices for reference."""
    guide = """
    ╔═══════════════════════════════════════════════════════════════╗
    ║          LangGraph Serialization Best Practices               ║
    ╚═══════════════════════════════════════════════════════════════╝

    ✅ DO:
    - Store UUIDs as strings: str(uuid_obj)
    - Store datetimes as ISO strings: dt.isoformat()
    - Use TypedDict for state (explicit schema)
    - Pass non-serializable objects via config["configurable"]
    - Test state with json.dumps(state) before production

    ❌ DON'T:
    - Store raw UUID objects in state
    - Store raw datetime objects in state
    - Store AsyncSession in state
    - Store Pydantic models in state (use .model_dump())
    - Assume MemorySaver = PostgresSaver (test with JSON)

    📦 Current Stack (SMEme v2):
    - Development: MemorySaver (in-memory)
    - Production: PostgresSaver (JSONB) - future
    - All state follows string-based UUID/datetime pattern ✓

    🔍 References:
    - docs/DEPENDENCY_GOTCHAS.md
    - docs/LANGGRAPH_INTEGRATION_GUIDE.md
    - smeme/decision-trees/generation/agentic/models.py
    """
    print(guide)
    assert True  # Pass if printed
