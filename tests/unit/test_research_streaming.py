"""Unit tests for research-phase SSE streaming (Release 1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from smeme.qnr.generation.agentic.streaming import (
    REPLAY_MAX_DELTA_BYTES,
    REPLAY_MAX_EVENTS,
    get_bus,
    get_cancel_event,
    mark_complete,
    put_event,
    reset_bus_for_run,
    reset_streaming_state,
    sse_event_stream,
)
from smeme.qnr.generation.agentic.subgraphs.research import (
    _cancelled_return,
    _content_delta_text,
    _is_cancelled,
    _stream_research_completion,
    search_node,
)


@pytest.fixture(autouse=True)
def _clean_streaming():
    reset_streaming_state()
    yield
    reset_streaming_state()


class TestContentDeltaExtraction:
    def test_content_delta_event_uses_delta_field(self):
        from openai.lib.streaming.chat._events import ContentDeltaEvent

        event = ContentDeltaEvent(type="content.delta", delta="factor ", snapshot="factor ")
        assert _content_delta_text(event) == "factor "


class TestBusReset:
    @pytest.mark.asyncio
    async def test_reset_bus_for_run_allows_new_complete(self):
        thread_id = str(uuid4())
        await put_event(thread_id, "research_delta", {"text": "old"})
        await mark_complete(thread_id)
        assert get_bus(thread_id).state == "complete"

        reset_bus_for_run(thread_id)
        await put_event(thread_id, "research_delta", {"text": "new"})
        await mark_complete(thread_id)
        assert get_bus(thread_id).state == "complete"
        deltas = [e for e in get_bus(thread_id).replay_buffer if e["type"] == "research_delta"]
        assert len(deltas) == 1
        assert deltas[0]["payload"]["text"] == "new"


class TestStreamEnvelope:
    @pytest.mark.asyncio
    async def test_put_event_canonical_shape(self):
        thread_id = str(uuid4())
        envelope = await put_event(thread_id, "status", {"phase": "llm"})
        assert envelope["id"] == 1
        assert envelope["type"] == "status"
        assert envelope["thread_id"] == thread_id
        assert "ts" in envelope
        assert envelope["payload"] == {"phase": "llm"}


class TestReplayLimits:
    @pytest.mark.asyncio
    async def test_limit_a_truncates_oldest_deltas(self):
        thread_id = str(uuid4())
        chunk = "x" * 1024
        chunks_needed = (REPLAY_MAX_DELTA_BYTES // 1024) + 2
        for _ in range(chunks_needed):
            await put_event(thread_id, "research_delta", {"text": chunk})

        bus = get_bus(thread_id)
        assert bus is not None
        delta_events = [e for e in bus.replay_buffer if e["type"] == "research_delta"]
        assert len(delta_events) < chunks_needed
        truncated = [e for e in bus.replay_buffer if e["payload"].get("phase") == "truncated_replay"]
        assert truncated

    @pytest.mark.asyncio
    async def test_limit_b_drops_oldest_deltas_first(self):
        thread_id = str(uuid4())
        await put_event(thread_id, "generation_started", {"goal": "g"})
        for i in range(REPLAY_MAX_EVENTS):
            await put_event(thread_id, "research_delta", {"text": f"d{i}"})

        bus = get_bus(thread_id)
        assert bus is not None
        assert len(bus.replay_buffer) <= REPLAY_MAX_EVENTS + 2
        assert bus.replay_buffer[0]["type"] == "generation_started"
        delta_ids = [e["payload"].get("text") for e in bus.replay_buffer if e["type"] == "research_delta"]
        assert "d0" not in delta_ids


class TestSSEFanout:
    @pytest.mark.asyncio
    async def test_concurrent_subscribers_both_receive_terminal_event(self):
        import asyncio
        import json

        thread_id = str(uuid4())
        await put_event(thread_id, "generation_started", {"goal": "test"})

        async def collect_events() -> list[str]:
            types: list[str] = []
            async for line in sse_event_stream(thread_id):
                types.append(json.loads(line[6:].strip())["type"])
            return types

        consumer_a = asyncio.create_task(collect_events())
        consumer_b = asyncio.create_task(collect_events())
        await put_event(thread_id, "research_delta", {"text": "x"})
        await mark_complete(thread_id)

        types_a, types_b = await asyncio.gather(consumer_a, consumer_b)
        assert "research_delta" in types_a
        assert "research_delta" in types_b
        assert types_a[-1] == "research_complete"
        assert types_b[-1] == "research_complete"


class TestSSEDrain:
    @pytest.mark.asyncio
    async def test_replay_then_live_no_duplicates(self):
        thread_id = str(uuid4())
        await put_event(thread_id, "generation_started", {"goal": "test"})
        await put_event(thread_id, "status", {"phase": "llm"})
        await put_event(thread_id, "research_delta", {"text": "hello"})
        await mark_complete(thread_id)

        events = []
        async for line in sse_event_stream(thread_id):
            assert line.startswith("data: ")
            import json

            events.append(json.loads(line[6:].strip()))

        types = [e["type"] for e in events]
        assert types.count("generation_started") == 1
        assert "research_delta" in types
        assert types[-1] == "research_complete"


class TestCancelCheckpoints:
    def test_checkpoint_1_before_ainvoke(self):
        thread_id = str(uuid4())
        get_cancel_event(thread_id).set()
        assert _is_cancelled({"configurable": {"cancel_event": get_cancel_event(thread_id)}})

    @pytest.mark.asyncio
    async def test_checkpoint_2_before_tavily(self):
        from smeme.qnr.generation.agentic.subgraphs.models import ResearchSubgraphState

        thread_id = str(uuid4())
        cancel = get_cancel_event(thread_id)
        cancel.set()

        state = ResearchSubgraphState(
            user_prompt="A" * 30,
            user_id=str(uuid4()),
            include_domains=["https://example.com/doc"],
        )
        mock_tavily = AsyncMock()
        config = {
            "configurable": {
                "thread_id": thread_id,
                "openai_client": AsyncMock(),
                "tavily_client": mock_tavily,
                "research_stream_queue": True,
                "cancel_event": cancel,
            }
        }
        result = await search_node(state, config)
        assert result == _cancelled_return()
        mock_tavily.extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_checkpoint_3_after_tavily_before_llm(self):
        from smeme.qnr.generation.agentic.subgraphs.models import ResearchSubgraphState

        thread_id = str(uuid4())
        cancel = get_cancel_event(thread_id)

        state = ResearchSubgraphState(
            user_prompt="A" * 30,
            user_id=str(uuid4()),
            skip_web_search=True,
        )
        config = {
            "configurable": {
                "thread_id": thread_id,
                "openai_client": AsyncMock(),
                "tavily_client": None,
                "research_stream_queue": True,
                "cancel_event": cancel,
            }
        }
        cancel.set()
        result = await search_node(state, config)
        assert result == _cancelled_return()

    @pytest.mark.asyncio
    async def test_checkpoint_4_mid_stream_at_32_deltas(self):
        thread_id = str(uuid4())
        cancel = get_cancel_event(thread_id)

        class FakeEvent:
            def __init__(self, delta: str):
                self.type = "content.delta"
                self.delta = delta

        class FakeStream:
            def __init__(self, events):
                self._events = list(events)
                self._index = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._index >= len(self._events):
                    raise StopAsyncIteration
                event = self._events[self._index]
                self._index += 1
                if self._index == 33:
                    cancel.set()
                return event

        openai_client = MagicMock()
        mock_client = MagicMock()
        mock_client.chat.completions.stream = MagicMock(
            return_value=FakeStream([FakeEvent("x") for _ in range(40)])
        )

        config = {
            "configurable": {
                "thread_id": thread_id,
                "cancel_event": cancel,
                "stream_metrics": {},
            }
        }

        with patch(
            "smeme.qnr.generation.agentic.subgraphs.research._research_openai_client",
            return_value=mock_client,
        ):
            partial = await _stream_research_completion(
                openai_client,
                messages=[{"role": "user", "content": "go"}],
                config=config,
            )

        assert len(partial) == 32
        assert cancel.is_set()


class TestBackgroundCancelCheckpoint1:
    @pytest.mark.asyncio
    async def test_cancel_before_ainvoke_emits_error_not_complete(self):
        from smeme.qnr.generation.agentic.background import _run_generation_workflow

        thread_id = str(uuid4())
        get_cancel_event(thread_id).set()

        with (
            patch(
                "smeme.qnr.generation.agentic.background.get_compiled_workflow",
                new_callable=AsyncMock,
            ) as mock_wf,
            patch("smeme.qnr.generation.agentic.background.AsyncSessionLocal") as mock_session,
        ):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
            await _run_generation_workflow(
                thread_id=thread_id,
                user_id=uuid4(),
                generation_id=uuid4(),
                initial_state={"user_prompt": "x" * 25, "user_id": "u", "title": "T"},
                phase_started_at=0.0,
                goal="goal",
                enable_web_search=False,
                graph_version="v2",
            )
            mock_wf.assert_not_called()

        bus = get_bus(thread_id)
        assert bus is not None
        assert bus.state == "error"
        types = [e["type"] for e in bus.replay_buffer]
        assert "error" in types
        assert "research_complete" not in types

    @pytest.mark.asyncio
    async def test_unexpected_completion_emits_error_and_terminal_state(self):
        from smeme.qnr.generation.agentic.background import _run_generation_workflow

        thread_id = str(uuid4())
        mock_workflow = AsyncMock()
        mock_workflow.ainvoke = AsyncMock(return_value={})

        with (
            patch(
                "smeme.qnr.generation.agentic.background.get_compiled_workflow",
                new_callable=AsyncMock,
                return_value=mock_workflow,
            ),
            patch("smeme.qnr.generation.agentic.background.AsyncSessionLocal") as mock_session,
        ):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
            await _run_generation_workflow(
                thread_id=thread_id,
                user_id=uuid4(),
                generation_id=uuid4(),
                initial_state={"user_prompt": "x" * 25, "user_id": "u", "title": "T"},
                phase_started_at=0.0,
                goal="goal",
                enable_web_search=False,
                graph_version="v2",
            )

        bus = get_bus(thread_id)
        assert bus is not None
        assert bus.state == "error"
        error_events = [e for e in bus.replay_buffer if e["type"] == "error"]
        assert error_events
        assert error_events[-1]["payload"]["message"] == "Workflow completed unexpectedly."
        assert "research_complete" not in [e["type"] for e in bus.replay_buffer]
