"""Background execution for agentic DecisionTree generation (research streaming Release 1)."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID

from langgraph.types import Interrupt

from smeme.core.database import AsyncSessionLocal
from smeme.core.llm import get_openai_client
from smeme.core.logging import get_logger
from smeme.core.search import TavilyNotConfiguredError
from smeme.decision_tree.generation.agentic.routes._helpers import (
    wizard_generation_error_recoverable,
)
from smeme.decision_tree.generation.agentic.streaming import (
    _heartbeat_loop,
    get_cancel_event,
    get_or_create_bus,
    mark_complete,
    mark_error,
    put_event,
    register_task,
    reset_bus_for_run,
)
from smeme.decision_tree.generation.agentic.subgraphs.models import (
    InterruptPayload,
    ResearchSubgraphOutput,
)
from smeme.decision_tree.generation.agentic.subgraphs.research import (
    create_research_subgraph,
    extract_research_input,
    merge_research_output,
)
from smeme.decision_tree.generation.agentic.telemetry import (
    track_phase_enter,
    track_phase_error,
    track_phase_submit,
)
from smeme.decision_tree.generation.agentic.workflow import get_compiled_workflow

logger = get_logger(__name__)


def schedule_generation_workflow(
    *,
    thread_id: str,
    user_id: UUID,
    generation_id: UUID,
    initial_state: dict[str, Any],
    phase_started_at: float,
    goal: str,
    enable_web_search: bool,
    graph_version: str = "v2",
) -> asyncio.Task[None]:
    """Fire-and-forget background LangGraph run with streaming side effects."""
    get_or_create_bus(thread_id)
    task = asyncio.create_task(
        _run_generation_workflow(
            thread_id=thread_id,
            user_id=user_id,
            generation_id=generation_id,
            initial_state=initial_state,
            phase_started_at=phase_started_at,
            goal=goal,
            enable_web_search=enable_web_search,
            graph_version=graph_version,
        )
    )
    register_task(thread_id, task)
    return task


def schedule_retry_research_workflow(
    *,
    thread_id: str,
    user_id: UUID,
    generation_id: UUID,
    goal: str,
    enable_web_search: bool,
) -> asyncio.Task[None]:
    """Re-run research subgraph with streaming; updates checkpoint then signals complete."""
    reset_bus_for_run(thread_id)
    task = asyncio.create_task(
        _run_retry_research_workflow(
            thread_id=thread_id,
            user_id=user_id,
            generation_id=generation_id,
            goal=goal,
            enable_web_search=enable_web_search,
        )
    )
    register_task(thread_id, task)
    return task


async def _emit_research_phase_telemetry(
    db,
    *,
    user_id: UUID,
    thread_id: str,
    generation_id: UUID,
    phase_started_at: float,
    interrupt_reached: bool,
    error_message: str | None,
    stream_metrics: dict[str, Any],
    had_partial_stream: bool,
) -> None:
    duration_ms = int((time.perf_counter() - phase_started_at) * 1000)
    submit_metadata: dict[str, Any] = {}
    if stream_metrics.get("first_token_ms") is not None:
        submit_metadata["first_token_ms"] = stream_metrics["first_token_ms"]
    if stream_metrics.get("total_stream_ms") is not None:
        submit_metadata["total_stream_ms"] = stream_metrics["total_stream_ms"]

    if interrupt_reached:
        await track_phase_submit(
            db,
            user_id=user_id,
            phase="brief",
            thread_id=thread_id,
            duration_ms=duration_ms,
            generation_id=generation_id,
            **submit_metadata,
        )
        await track_phase_enter(
            db,
            user_id=user_id,
            phase="research",
            thread_id=thread_id,
            generation_id=generation_id,
            source="generate",
        )
        return

    if error_message:
        failure_stage = "before_first_token"
        if had_partial_stream:
            failure_stage = "after_partial_stream"
        elif stream_metrics.get("stream_ended_at"):
            failure_stage = "post_stream_pre_interrupt"

        await track_phase_error(
            db,
            user_id=user_id,
            phase="brief",
            thread_id=thread_id,
            duration_ms=duration_ms,
            error_message=error_message,
            generation_id=generation_id,
            failure_stage=failure_stage,
            **submit_metadata,
        )


async def _run_generation_workflow(
    *,
    thread_id: str,
    user_id: UUID,
    generation_id: UUID,
    initial_state: dict[str, Any],
    phase_started_at: float,
    goal: str,
    enable_web_search: bool,
    graph_version: str,
) -> None:
    get_or_create_bus(thread_id)
    await put_event(thread_id, "generation_started", {"goal": goal})

    cancel_event = get_cancel_event(thread_id)
    stream_metrics: dict[str, Any] = {
        "stream_started_at": None,
        "first_token_at": None,
        "stream_ended_at": None,
        "first_token_ms": None,
        "total_stream_ms": None,
    }
    had_partial_stream = False

    heartbeat_task = asyncio.create_task(_heartbeat_loop(thread_id))

    if cancel_event.is_set():
        await put_event(
            thread_id,
            "error",
            {"message": "Cancelled", "recoverable": True},
        )
        await mark_error(thread_id)
        heartbeat_task.cancel()
        return

    tavily_client = None
    if enable_web_search:
        try:
            from smeme.core.search import get_tavily_client

            tavily_client = get_tavily_client()
        except TavilyNotConfiguredError:
            tavily_client = None

    openai_client = get_openai_client()
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user_id,
            "openai_client": openai_client,
            "tavily_client": tavily_client,
            "research_stream_queue": True,
            "cancel_event": cancel_event,
            "stream_metrics": stream_metrics,
        },
        "metadata": {
            "phase": "research",
            "graph_version": graph_version,
            "user_id": str(user_id),
            "generation_id": str(generation_id),
        },
    }

    interrupt_reached = False
    workflow_error: str | None = None
    recoverable_error = True

    try:
        workflow = await get_compiled_workflow()
        result = await workflow.ainvoke(initial_state, config)

        interrupts = result.get("__interrupt__", [])
        if interrupts:
            interrupt_obj: Interrupt = interrupts[0]
            if isinstance(interrupt_obj.value, dict):
                try:
                    InterruptPayload(**interrupt_obj.value)
                except Exception:
                    pass
            interrupt_reached = True
        elif result.get("error"):
            workflow_error = str(result.get("error"))
            recoverable_error = bool(result.get("error_recoverable", True))
        else:
            workflow_error = "Workflow completed unexpectedly."
            recoverable_error = True
            logger.warning(
                "Workflow completed without research interrupt",
                extra={"thread_id": thread_id, "user_id": str(user_id)},
            )
    except Exception as exc:
        workflow_error = str(exc)
        recoverable_error = wizard_generation_error_recoverable(exc)
        logger.error(
            "Agentic generation background workflow failed",
            extra={"thread_id": thread_id, "user_id": str(user_id), "error": workflow_error},
            exc_info=True,
        )
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        if stream_metrics.get("first_token_at") is not None:
            had_partial_stream = True
            stream_metrics["first_token_ms"] = int(
                (stream_metrics["first_token_at"] - phase_started_at) * 1000
            )
        if stream_metrics.get("stream_started_at") and stream_metrics.get("stream_ended_at"):
            stream_metrics["total_stream_ms"] = int(
                (stream_metrics["stream_ended_at"] - stream_metrics["stream_started_at"]) * 1000
            )

        try:
            async with AsyncSessionLocal() as db:
                await _emit_research_phase_telemetry(
                    db,
                    user_id=user_id,
                    thread_id=thread_id,
                    generation_id=generation_id,
                    phase_started_at=phase_started_at,
                    interrupt_reached=interrupt_reached,
                    error_message=workflow_error,
                    stream_metrics=stream_metrics,
                    had_partial_stream=had_partial_stream,
                )
        except Exception:
            logger.exception(
                "Failed to emit research phase telemetry",
                extra={"thread_id": thread_id},
            )

        if interrupt_reached:
            await put_event(thread_id, "status", {"phase": "complete"})
            await mark_complete(thread_id)
        else:
            message = workflow_error or "Workflow completed unexpectedly."
            await put_event(
                thread_id,
                "error",
                {"message": message, "recoverable": recoverable_error},
            )
            await mark_error(thread_id)


async def _run_retry_research_workflow(
    *,
    thread_id: str,
    user_id: UUID,
    generation_id: UUID,
    goal: str,
    enable_web_search: bool,
) -> None:
    await put_event(thread_id, "generation_started", {"goal": goal})

    cancel_event = get_cancel_event(thread_id)
    stream_metrics: dict[str, Any] = {
        "stream_started_at": None,
        "first_token_at": None,
        "stream_ended_at": None,
    }
    heartbeat_task = asyncio.create_task(_heartbeat_loop(thread_id))

    if cancel_event.is_set():
        await put_event(
            thread_id,
            "error",
            {"message": "Cancelled", "recoverable": True},
        )
        await mark_error(thread_id)
        heartbeat_task.cancel()
        return

    tavily_client = None
    if enable_web_search:
        try:
            from smeme.core.search import get_tavily_client

            tavily_client = get_tavily_client()
        except TavilyNotConfiguredError:
            tavily_client = None

    openai_client = get_openai_client()
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user_id,
            "openai_client": openai_client,
            "tavily_client": tavily_client,
            "research_stream_queue": True,
            "cancel_event": cancel_event,
            "stream_metrics": stream_metrics,
        },
    }

    workflow_error: str | None = None
    recoverable_error = True

    try:
        workflow = await get_compiled_workflow()
        state_snapshot = await workflow.aget_state(config)
        state = state_snapshot.values or {}
        if not state:
            raise ValueError("No saved workflow state for this generation")

        research_input = extract_research_input(state)
        research_subgraph = create_research_subgraph().compile()
        subgraph_result = await research_subgraph.ainvoke(
            research_input.model_dump(),
            config,
        )
        output = ResearchSubgraphOutput(**subgraph_result)
        await workflow.aupdate_state(config, merge_research_output(state, output))
    except Exception as exc:
        workflow_error = str(exc)
        recoverable_error = wizard_generation_error_recoverable(exc)
        logger.error(
            "Retry research background workflow failed",
            extra={"thread_id": thread_id, "user_id": str(user_id), "error": workflow_error},
            exc_info=True,
        )
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        if workflow_error:
            await put_event(
                thread_id,
                "error",
                {"message": workflow_error, "recoverable": recoverable_error},
            )
            await mark_error(thread_id)
        else:
            await put_event(thread_id, "status", {"phase": "complete"})
            await mark_complete(thread_id)
