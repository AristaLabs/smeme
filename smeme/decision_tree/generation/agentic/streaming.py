"""In-process SSE event bus for agentic DecisionTree research streaming (Release 1)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from smeme.core.logging import get_logger

logger = get_logger(__name__)

REPLAY_MAX_DELTA_BYTES = 256 * 1024
REPLAY_MAX_EVENTS = 2000
BUS_CLEANUP_TTL_S = 600
HEARTBEAT_INTERVAL_S = 15

BusState = Literal["running", "complete", "error"]


@dataclass
class StreamBus:
    """Per-thread event bus: replay buffer + per-subscriber live queues."""

    thread_id: str
    subscriber_queues: list[asyncio.Queue[dict[str, Any]]] = field(default_factory=list)
    replay_buffer: list[dict[str, Any]] = field(default_factory=list)
    state: BusState = "running"
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    next_id: int = 0
    delta_text_bytes: int = 0
    truncated_replay_emitted: bool = False


_buses: dict[str, StreamBus] = {}
_tasks: dict[str, asyncio.Task[Any]] = {}
_cleanup_tasks: dict[str, asyncio.Task[Any]] = {}


def get_bus(thread_id: str) -> StreamBus | None:
    return _buses.get(thread_id)


def get_or_create_bus(thread_id: str) -> StreamBus:
    bus = _buses.get(thread_id)
    if bus is None:
        bus = StreamBus(thread_id=thread_id)
        _buses[thread_id] = bus
    return bus


def reset_bus_for_run(thread_id: str) -> StreamBus:
    """Fresh bus for another research stream on the same thread_id (e.g. retry)."""
    existing_cleanup = _cleanup_tasks.pop(thread_id, None)
    if existing_cleanup and not existing_cleanup.done():
        existing_cleanup.cancel()
    bus = StreamBus(thread_id=thread_id)
    _buses[thread_id] = bus
    return bus


def get_cancel_event(thread_id: str) -> asyncio.Event:
    return get_or_create_bus(thread_id).cancel_event


def subscribe(thread_id: str) -> asyncio.Queue[dict[str, Any]]:
    """Register one SSE consumer; each subscriber gets its own fanout queue."""
    bus = get_or_create_bus(thread_id)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    bus.subscriber_queues.append(queue)
    return queue


def unsubscribe(thread_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
    bus = _buses.get(thread_id)
    if not bus:
        return
    try:
        bus.subscriber_queues.remove(queue)
    except ValueError:
        pass


async def _broadcast(bus: StreamBus, envelope: dict[str, Any]) -> None:
    for queue in list(bus.subscriber_queues):
        await queue.put(envelope)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _make_envelope(
    bus: StreamBus,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    bus.next_id += 1
    return {
        "id": bus.next_id,
        "type": event_type,
        "ts": _now_iso(),
        "thread_id": bus.thread_id,
        "payload": payload,
    }


def _delta_text_byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _apply_replay_limits(bus: StreamBus, envelope: dict[str, Any]) -> None:
    """Append to replay buffer respecting limits A (delta bytes) and B (event count)."""
    event_type = envelope["type"]
    if event_type == "research_delta":
        text = envelope["payload"].get("text", "")
        bus.delta_text_bytes += _delta_text_byte_len(text)

    bus.replay_buffer.append(envelope)

    while bus.delta_text_bytes > REPLAY_MAX_DELTA_BYTES:
        dropped = _drop_oldest_delta(bus)
        if not dropped:
            break
        if not bus.truncated_replay_emitted:
            bus.truncated_replay_emitted = True
            truncated = _make_envelope(
                bus,
                "status",
                {"phase": "truncated_replay"},
            )
            bus.replay_buffer.append(truncated)
            asyncio.create_task(_broadcast(bus, truncated))

    while len(bus.replay_buffer) > REPLAY_MAX_EVENTS:
        dropped = _drop_oldest_delta(bus)
        if not dropped:
            break


def _drop_oldest_delta(bus: StreamBus) -> bool:
    for i, event in enumerate(bus.replay_buffer):
        if event["type"] == "research_delta":
            text = event["payload"].get("text", "")
            bus.delta_text_bytes = max(0, bus.delta_text_bytes - _delta_text_byte_len(text))
            bus.replay_buffer.pop(i)
            return True
    return False


async def put_event(
    thread_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enqueue one canonical event (replay buffer + fanout to subscribers)."""
    bus = get_or_create_bus(thread_id)
    envelope = _make_envelope(bus, event_type, payload or {})
    _apply_replay_limits(bus, envelope)
    await _broadcast(bus, envelope)
    return envelope


async def mark_complete(thread_id: str) -> None:
    bus = _buses.get(thread_id)
    if not bus or bus.state != "running":
        return
    bus.state = "complete"
    await put_event(thread_id, "research_complete", {})
    _schedule_bus_cleanup(thread_id)


async def mark_error(thread_id: str) -> None:
    bus = _buses.get(thread_id)
    if not bus or bus.state != "running":
        return
    bus.state = "error"
    _schedule_bus_cleanup(thread_id)


def _schedule_bus_cleanup(thread_id: str) -> None:
    existing = _cleanup_tasks.pop(thread_id, None)
    if existing and not existing.done():
        existing.cancel()

    async def _cleanup() -> None:
        await asyncio.sleep(BUS_CLEANUP_TTL_S)
        _buses.pop(thread_id, None)
        _cleanup_tasks.pop(thread_id, None)

    _cleanup_tasks[thread_id] = asyncio.create_task(_cleanup())


async def _heartbeat_loop(thread_id: str) -> None:
    """Producer-only heartbeat: every 15s while bus is running."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            bus = _buses.get(thread_id)
            if not bus or bus.state != "running":
                break
            await put_event(thread_id, "heartbeat", {})
    except asyncio.CancelledError:
        pass


def register_task(thread_id: str, task: asyncio.Task[Any]) -> None:
    _tasks[thread_id] = task
    task.add_done_callback(lambda t: _on_task_done(thread_id, t))


def unregister_task(thread_id: str) -> None:
    _tasks.pop(thread_id, None)


def _on_task_done(thread_id: str, task: asyncio.Task[Any]) -> None:
    unregister_task(thread_id)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Generation background task failed",
            extra={"thread_id": thread_id, "error": str(exc)},
            exc_info=exc,
        )


def get_registered_task(thread_id: str) -> asyncio.Task[Any] | None:
    return _tasks.get(thread_id)


async def sse_event_stream(thread_id: str) -> AsyncIterator[str]:
    """Replay buffered events, then drain this subscriber's queue (dedupe by event id)."""
    bus = _buses.get(thread_id)
    if not bus:
        return

    subscriber_queue = subscribe(thread_id)
    try:
        seen_ids: set[int] = set()
        max_replay_id = 0

        for envelope in bus.replay_buffer:
            seen_ids.add(envelope["id"])
            max_replay_id = max(max_replay_id, envelope["id"])
            yield f"data: {json.dumps(envelope)}\n\n"

        while True:
            if bus.state in ("complete", "error") and subscriber_queue.empty():
                break
            try:
                envelope = await asyncio.wait_for(
                    subscriber_queue.get(),
                    timeout=HEARTBEAT_INTERVAL_S + 5,
                )
            except TimeoutError:
                if bus.state in ("complete", "error"):
                    break
                continue

            if envelope["id"] in seen_ids or envelope["id"] <= max_replay_id:
                if envelope["type"] in ("research_complete", "error"):
                    if envelope["id"] not in seen_ids:
                        yield f"data: {json.dumps(envelope)}\n\n"
                    break
                continue

            seen_ids.add(envelope["id"])
            yield f"data: {json.dumps(envelope)}\n\n"

            if envelope["type"] in ("research_complete", "error"):
                break
    finally:
        unsubscribe(thread_id, subscriber_queue)


def reset_streaming_state() -> None:
    """Test helper: clear all buses and tasks."""
    for task in list(_tasks.values()):
        if not task.done():
            task.cancel()
    for task in list(_cleanup_tasks.values()):
        if not task.done():
            task.cancel()
    _buses.clear()
    _tasks.clear()
    _cleanup_tasks.clear()
