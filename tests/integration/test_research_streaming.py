"""Integration tests for research-phase SSE streaming (Release 1)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from smeme.qnr.generation.agentic.streaming import (
    mark_complete,
    put_event,
    reset_streaming_state,
)
from tests.conftest import auth_as

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean_streaming():
    reset_streaming_state()
    yield
    reset_streaming_state()


def _mock_user():
    user = MagicMock()
    user.id = uuid4()
    user.is_premium = True
    user.subscription_period_start = None
    user.subscription_period_end = None
    return user


def _parse_sse_payloads(body: str) -> list[dict]:
    events = []
    for block in body.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


async def test_post_generate_returns_loading_shell(app):
    user = _mock_user()
    captured: dict = {}
    in_progress = MagicMock()
    in_progress.id = uuid4()
    in_progress.langgraph_thread_id = str(uuid4())

    def fake_schedule(**kwargs):
        captured.update(kwargs)

    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=0)
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=count_result)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()

    async def override_db():
        yield mock_db

    from smeme.core.database import get_db

    original_get_db = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with (
                auth_as(app, user),
                patch(
                    "smeme.billing.quota.check_wizard_start_block",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "smeme.qnr.generation.agentic.routes.phase1_research.checkpoint_manager.list_user_generations",
                    new_callable=AsyncMock,
                    return_value=[],
                ),
                patch(
                    "smeme.qnr.generation.agentic.routes.phase1_research.checkpoint_manager.start_new_generation",
                    new_callable=AsyncMock,
                    return_value=in_progress,
                ),
                patch(
                    "smeme.qnr.generation.agentic.routes.phase1_research.schedule_generation_workflow",
                    side_effect=fake_schedule,
                ),
            ):
                response = await client.post(
                    "/qnr/agentic/generate",
                    data={
                        "title": "Test Stream QNR",
                        "user_prompt": "A" * 25 + " product liability matter in Georgia.",
                        "confirm_goal_only": "on",
                    },
                    headers={"HX-Request": "true"},
                )

        assert response.status_code == 200
        assert "research-stream-preview" in response.text
        assert "Draft preview" in response.text
        assert captured.get("goal", "").startswith("A")
        assert captured.get("thread_id") == in_progress.langgraph_thread_id
    finally:
        if original_get_db is not None:
            app.dependency_overrides[get_db] = original_get_db
        else:
            app.dependency_overrides.pop(get_db, None)


async def test_post_generate_without_sources_prompts_for_confirm(app):
    user = _mock_user()
    start_mock = AsyncMock()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            auth_as(app, user),
            patch(
                "smeme.billing.quota.check_wizard_start_block",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "smeme.qnr.generation.agentic.routes.phase1_research.checkpoint_manager.list_user_generations",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "smeme.qnr.generation.agentic.routes.phase1_research.checkpoint_manager.start_new_generation",
                start_mock,
            ),
        ):
            response = await client.post(
                "/qnr/agentic/generate",
                data={
                    "title": "Goal only workflow",
                    "user_prompt": "B" * 25 + " narrow scope test matter.",
                },
                headers={"HX-Request": "true"},
            )

    assert response.status_code == 200
    assert "Continue with goal only?" in response.text
    assert 'id="research-source-confirm-modal"' in response.text
    assert 'id="research-source-tip"' in response.text
    assert "research-stream-preview" not in response.text
    start_mock.assert_not_called()


async def test_sse_event_sequence(app):
    user = _mock_user()
    thread_id = str(uuid4())
    generation = MagicMock()
    generation.user_id = user.id

    await put_event(thread_id, "generation_started", {"goal": "g"})
    await put_event(thread_id, "status", {"phase": "tavily"})
    await put_event(thread_id, "research_delta", {"text": "factor "})
    await mark_complete(thread_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            auth_as(app, user),
            patch(
                "smeme.qnr.generation.agentic.routes.phase1_research.checkpoint_manager.get_generation_by_thread_id",
                new_callable=AsyncMock,
                return_value=generation,
            ),
        ):
            response = await client.get(f"/qnr/agentic/generate/{thread_id}/stream")

    assert response.status_code == 200
    events = _parse_sse_payloads(response.text)
    types = [e["type"] for e in events]
    assert "generation_started" in types
    assert "status" in types
    assert "research_delta" in types
    assert types[-1] == "research_complete"


async def test_sse_forbidden_non_owner(app):
    user = _mock_user()
    thread_id = str(uuid4())
    generation = MagicMock()
    generation.user_id = uuid4()

    await put_event(thread_id, "generation_started", {"goal": "g"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            auth_as(app, user),
            patch(
                "smeme.qnr.generation.agentic.routes.phase1_research.checkpoint_manager.get_generation_by_thread_id",
                new_callable=AsyncMock,
                return_value=generation,
            ),
        ):
            response = await client.get(f"/qnr/agentic/generate/{thread_id}/stream")

    assert response.status_code == 403


async def test_retry_research_returns_loading_shell(app):
    user = _mock_user()
    thread_id = str(uuid4())
    generation = MagicMock()
    generation.id = uuid4()
    generation.user_id = user.id
    generation.langgraph_thread_id = thread_id
    generation.user_prompt_preview = "Goal for retry " + "x" * 20

    state = {
        "user_prompt": "Goal for retry " + "x" * 20,
        "user_id": str(user.id),
        "title": "Retry test",
        "skip_web_search": False,
    }
    mock_snapshot = MagicMock()
    mock_snapshot.values = state
    mock_workflow = AsyncMock()
    mock_workflow.aget_state = AsyncMock(return_value=mock_snapshot)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            auth_as(app, user),
            patch(
                "smeme.qnr.generation.agentic.routes.phase1_research.checkpoint_manager.get_generation_by_thread_id",
                new_callable=AsyncMock,
                return_value=generation,
            ),
            patch(
                "smeme.qnr.generation.agentic.routes.phase1_research.get_compiled_workflow",
                new_callable=AsyncMock,
                return_value=mock_workflow,
            ),
            patch(
                "smeme.qnr.generation.agentic.routes.phase1_research.schedule_retry_research_workflow",
            ) as mock_schedule,
        ):
            response = await client.post(
                "/qnr/agentic/retry-research",
                data={"thread_id": thread_id},
                headers={"HX-Request": "true"},
            )

    assert response.status_code == 200
    assert "research-stream-preview" in response.text
    assert "Retrying AI research" in response.text
    mock_schedule.assert_called_once()


async def test_brief_enter_only_from_get_brief(app):
    """Brief phase enter is recorded on GET /brief only, not on POST /generate."""
    from smeme.qnr.generation.agentic.routes import phase1_research

    user = _mock_user()
    enter_calls: list[dict] = []

    async def capture_enter(db, **kwargs):
        enter_calls.append(kwargs)

    mock_db = AsyncMock()
    mock_request = MagicMock()

    with (
        patch.object(phase1_research, "track_phase_enter", side_effect=capture_enter),
        patch.object(
            phase1_research.checkpoint_manager,
            "list_user_generations",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch.object(phase1_research, "templates") as mock_templates,
    ):
        mock_templates.TemplateResponse.return_value = MagicMock()
        await phase1_research.agentic_generation_brief(mock_request, user, mock_db)

    brief_enters_after_get = [c for c in enter_calls if c.get("phase") == "brief"]
    assert len(brief_enters_after_get) == 1
    assert brief_enters_after_get[0].get("source") == "new"

    enter_calls.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            auth_as(app, user),
            patch(
                "smeme.qnr.generation.agentic.routes.phase1_research.schedule_generation_workflow",
            ),
            patch(
                "smeme.qnr.generation.agentic.routes.phase1_research.track_phase_enter",
                side_effect=capture_enter,
            ),
        ):
            in_progress = MagicMock()
            in_progress.id = uuid4()
            in_progress.langgraph_thread_id = str(uuid4())
            with (
                patch(
                    "smeme.billing.quota.check_wizard_start_block",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "smeme.qnr.generation.agentic.routes.phase1_research.checkpoint_manager.list_user_generations",
                    new_callable=AsyncMock,
                    return_value=[],
                ),
                patch(
                    "smeme.qnr.generation.agentic.routes.phase1_research.checkpoint_manager.start_new_generation",
                    new_callable=AsyncMock,
                    return_value=in_progress,
                ),
            ):
                count_result = MagicMock()
                count_result.scalar = MagicMock(return_value=0)
                mock_db = AsyncMock()
                mock_db.execute = AsyncMock(return_value=count_result)
                mock_db.commit = AsyncMock()
                mock_db.refresh = AsyncMock()
                mock_db.add = MagicMock()

                async def override_db():
                    yield mock_db

                from smeme.core.database import get_db

                original_get_db = app.dependency_overrides.get(get_db)
                app.dependency_overrides[get_db] = override_db
                try:
                    await client.post(
                        "/qnr/agentic/generate",
                        data={
                            "title": "Telemetry test",
                            "user_prompt": "B" * 25 + " goal for telemetry.",
                            "confirm_goal_only": "on",
                        },
                        headers={"HX-Request": "true"},
                    )
                finally:
                    if original_get_db is not None:
                        app.dependency_overrides[get_db] = original_get_db
                    else:
                        app.dependency_overrides.pop(get_db, None)

    brief_enters_after_post = [c for c in enter_calls if c.get("phase") == "brief"]
    assert brief_enters_after_post == []


async def test_wizard_start_blocked_modal_returns_trigger_when_unblocked(app):
    user = _mock_user()
    user.is_premium = False

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            auth_as(app, user),
            patch(
                "smeme.qnr.generation.agentic.routes.phase1_research._wizard_start_context",
                new_callable=AsyncMock,
                return_value=(None, 0),
            ),
        ):
            response = await client.get(
                "/qnr/agentic/wizard-start-blocked-modal",
                headers={"HX-Request": "true"},
            )

    assert response.status_code == 200
    assert response.text == ""
    assert response.headers.get("hx-trigger") == "refreshWizardBrief"


async def test_brief_partial_reflects_current_block_state(app):
    user = _mock_user()
    user.is_premium = False

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            auth_as(app, user),
            patch(
                "smeme.qnr.generation.agentic.routes.phase1_research._wizard_start_context",
                new_callable=AsyncMock,
                return_value=(None, 0),
            ),
        ):
            response = await client.get(
                "/qnr/agentic/brief-partial",
                headers={"HX-Request": "true"},
            )

    assert response.status_code == 200
    assert "Finish your current build first" not in response.text
    assert 'id="generate-form"' in response.text
    assert 'name="title"' in response.text
    assert "disabled" not in response.text.split('name="title"')[1].split(">")[0]
