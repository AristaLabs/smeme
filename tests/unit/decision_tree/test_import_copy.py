"""Import copy: v2 export becomes a new Hidden draft."""

from __future__ import annotations

import asyncio
import json
from importlib.resources import files
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Depends
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.auth.users import get_current_active_user
from smeme.billing.providers import hosted_quota_enforcement_scope
from smeme.billing.tiers import TIER_LIMITS, BillingTier
from smeme.core.database import get_db
from smeme.core.models import DecisionTree, ReasoningCompiledArtifact, User
from smeme.decision_tree.helpers.import_copy import (
    IMPORT_MAX_STRING_CHARS,
    ImportCopyError,
    import_banner_visible,
    import_decision_tree_export,
    parse_import_export,
    sanitize_import_filename,
)
from smeme.decision_tree.helpers.validation import validate_graph_for_editing
from smeme.decision_tree.models import DTGraph
from tests.conftest import auth_as

pytestmark = pytest.mark.asyncio(loop_scope="session")

_SOURCE_ID = "11111111-1111-1111-1111-111111111111"


def _envelope(graph: dict, title: str, **extra: object) -> bytes:
    payload = {
        "smeme_export_version": "2",
        "exported_at": "2026-01-01T00:00:00Z",
        "note": "ignored",
        "decision_tree": {
            "id": _SOURCE_ID,
            "title": title,
            "version_number": 9,
            "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2020-01-02T00:00:00Z",
            "graph": graph,
        },
    }
    payload.update(extra)
    return json.dumps(payload).encode()


def _fixture_envelope(name: str) -> tuple[bytes, dict]:
    raw = json.loads(files("smeme.decision_tree").joinpath("fixtures", name).read_text())
    return _envelope(raw["graph"], raw["title"]), raw


def _node_ids(graph: dict) -> set[str]:
    return {node["id"] for node in graph["nodes"]}


def _authority_urls(graph: dict) -> list[object]:
    urls: list[object] = []
    for node in graph["nodes"]:
        for authority in (node.get("data") or {}).get("authorities") or []:
            urls.append(authority.get("url", None) if "url" in authority else "<missing>")
    return urls


def _minimal_graph(title: str = "Imported") -> dict:
    graph, _raw = _fixture_envelope("smeme_sample_v1.json")
    payload = json.loads(graph)
    payload["decision_tree"]["title"] = title
    payload["decision_tree"]["graph"]["metadata"]["title"] = title
    return payload["decision_tree"]["graph"]


@pytest_asyncio.fixture
async def import_user(test_session_factory):
    uid = uuid4().hex[:8]
    async with test_session_factory() as session:
        user = User(
            email=f"import_{uid}@example.com",
            hashed_password="unused",
            is_active=True,
            is_verified=True,
            username=f"import_{uid}",
            is_premium=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    yield user
    async with test_session_factory() as session:
        tree_ids = list(
            (
                await session.execute(
                    select(DecisionTree.id).where(DecisionTree.author_id == user.id)
                )
            ).scalars()
        )
        if tree_ids:
            await session.execute(
                delete(ReasoningCompiledArtifact).where(
                    ReasoningCompiledArtifact.decision_tree_id.in_(tree_ids)
                )
            )
        await session.execute(delete(DecisionTree).where(DecisionTree.author_id == user.id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


async def _count(session_factory, user: User) -> int:
    async with session_factory() as session:
        return int(
            (
                await session.execute(
                    select(func.count(DecisionTree.id)).where(DecisionTree.author_id == user.id)
                )
            ).scalar_one()
        )


async def test_sanitize_import_filename_drops_directories() -> None:
    assert sanitize_import_filename(r"..\..\secret.smeme.json") == "secret.smeme.json"
    assert sanitize_import_filename(None) == "import.smeme.json"


async def test_import_banner_hides_after_deploy() -> None:
    assert import_banner_visible(imported_at=None, current_artifact_id=None) is False
    assert import_banner_visible(imported_at=object(), current_artifact_id=None) is True
    assert import_banner_visible(imported_at=object(), current_artifact_id=object()) is False


async def test_round_trip_sample_and_acme(test_session_factory, import_user) -> None:
    for fixture_name in (
        "smeme_sample_v1.json",
        "smeme_acme_xborder_withholding_v1.json",
    ):
        raw_bytes, fixture = _fixture_envelope(fixture_name)
        async with test_session_factory() as session:
            tree = await import_decision_tree_export(
                session,
                import_user,
                raw_bytes,
                filename=f"{fixture_name}.smeme.json",
            )
        assert str(tree.id) != _SOURCE_ID
        assert tree.version_number == 1
        assert tree.sample_key is None
        assert tree.mcp_discoverable is False
        assert tree.is_public is False
        assert tree.current_artifact_id is None
        assert tree.title == fixture["title"]
        assert tree.import_export_version == "2"
        assert tree.imported_at is not None
        assert _node_ids(tree.graph_data) == _node_ids(fixture["graph"])
        assert _authority_urls(tree.graph_data) == _authority_urls(fixture["graph"])

    sample_graph = json.loads(
        files("smeme.decision_tree").joinpath("fixtures", "smeme_sample_v1.json").read_text()
    )["graph"]
    options = [
        option
        for node in sample_graph["nodes"]
        if node["type"] == "question"
        for option in node["data"]["options"]
    ]
    assert "Unsure" not in options


async def test_second_import_creates_a_second_tree(test_session_factory, import_user) -> None:
    raw_bytes, _fixture = _fixture_envelope("smeme_sample_v1.json")
    ids = []
    for _ in range(2):
        async with test_session_factory() as session:
            tree = await import_decision_tree_export(
                session, import_user, raw_bytes, "a.smeme.json"
            )
            ids.append(tree.id)
    assert ids[0] != ids[1]
    assert await _count(test_session_factory, import_user) == 2


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"nodes": [], "edges": []}, "invalid_envelope"),
        (
            {"smeme_export_version": "1", "decision_tree": {"title": "T", "graph": {}}},
            "unsupported_export_version",
        ),
        ({"smeme_export_version": "2", "decision_tree": {"title": "T"}}, "invalid_envelope"),
    ],
)
async def test_rejected_shapes_insert_nothing(
    test_session_factory, import_user, payload, code
) -> None:
    raw = json.dumps(payload).encode()
    with pytest.raises(ImportCopyError) as caught:
        async with test_session_factory() as session:
            await import_decision_tree_export(session, import_user, raw, "bad.smeme.json")
    assert caught.value.code == code
    assert await _count(test_session_factory, import_user) == 0


async def test_unknown_envelope_key_is_ignored(test_session_factory, import_user) -> None:
    raw, _fixture = _fixture_envelope("smeme_sample_v1.json")
    payload = json.loads(raw)
    payload["future_field"] = {"ok": True}
    async with test_session_factory() as session:
        tree = await import_decision_tree_export(
            session, import_user, json.dumps(payload).encode(), "future.smeme.json"
        )
    assert tree.title == "SMEme sample"


async def test_deeply_nested_json_is_invalid_graph() -> None:
    raw = b"[" * 100_000 + b"]" * 100_000
    with pytest.raises(ImportCopyError) as caught:
        parse_import_export(raw)
    assert caught.value.code == "invalid_graph"


async def test_oversize_string_and_bad_authority_url() -> None:
    graph = _minimal_graph()
    graph["metadata"]["description"] = "x" * (IMPORT_MAX_STRING_CHARS + 1)
    with pytest.raises(ImportCopyError) as caught:
        parse_import_export(_envelope(graph, "Too big"))
    assert caught.value.code == "graph_too_large"

    graph = _minimal_graph()
    graph["nodes"][0]["data"]["authorities"] = [{"citation": "Notes", "url": "javascript:alert(1)"}]
    with pytest.raises(ImportCopyError) as caught:
        parse_import_export(_envelope(graph, "Bad link"))
    assert caught.value.code == "invalid_graph"

    graph = _minimal_graph()
    graph["nodes"][0]["data"]["authorities"] = [
        {"citation": "Empty", "url": ""},
        {"citation": "Omitted"},
    ]
    parsed, _title = parse_import_export(_envelope(graph, "Links"))
    urls = [item.url for item in parsed.get_question_nodes()[0].question_data.authorities]
    assert urls == ["", None]


async def test_warning_alone_does_not_reject(test_session_factory, import_user) -> None:
    from smeme.decision_tree.models import (
        ConclusionData,
        DTGraphMetadata,
        GraphEdge,
        GraphNode,
        QuestionData,
    )

    validated = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Q?",
                    type="radio",
                    options=["Yes", "No", "Maybe"],
                    required=True,
                ),
            ),
            GraphNode(id="c1", type="conclusion", data=ConclusionData(title="A", summary="a")),
            GraphNode(id="c2", type="conclusion", data=ConclusionData(title="B", summary="b")),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="c2", condition="No"),
        ],
        metadata=DTGraphMetadata(title="With warning"),
    )
    graph = validated.model_dump(mode="json")
    result = validate_graph_for_editing(validated)
    assert result["is_valid"] is True
    assert result["warnings"]
    async with test_session_factory() as session:
        tree = await import_decision_tree_export(
            session, import_user, _envelope(graph, "With warning"), "warn.smeme.json"
        )
    assert tree.title == "With warning"


async def test_pick_live_does_not_insert(test_session_factory, import_user) -> None:
    import_user.workflow_pick_required = True
    raw, _fixture = _fixture_envelope("smeme_sample_v1.json")
    with hosted_quota_enforcement_scope():
        with pytest.raises(ImportCopyError) as caught:
            async with test_session_factory() as session:
                await import_decision_tree_export(session, import_user, raw, "pick.smeme.json")
    assert caught.value.code == "account_downgrade_pending"
    assert await _count(test_session_factory, import_user) == 0


async def test_quota_and_concurrent_imports(test_session_factory, import_user) -> None:
    cap = TIER_LIMITS[BillingTier.FREE].max_workflows
    raw, _fixture = _fixture_envelope("smeme_sample_v1.json")
    with hosted_quota_enforcement_scope():
        async with test_session_factory() as session:
            for index in range(cap):
                await import_decision_tree_export(
                    session, import_user, raw, f"fill-{index}.smeme.json"
                )
        with pytest.raises(ImportCopyError) as caught:
            async with test_session_factory() as session:
                await import_decision_tree_export(session, import_user, raw, "over.smeme.json")
        assert caught.value.code == "quota_exceeded"

    assert await _count(test_session_factory, import_user) == cap


async def test_concurrent_imports_stop_at_one_free_slot(test_session_factory, import_user) -> None:
    cap = TIER_LIMITS[BillingTier.FREE].max_workflows
    raw, _fixture = _fixture_envelope("smeme_sample_v1.json")
    with hosted_quota_enforcement_scope():
        async with test_session_factory() as session:
            for index in range(cap - 1):
                await import_decision_tree_export(
                    session, import_user, raw, f"seat-{index}.smeme.json"
                )

        async def once(name: str):
            async with test_session_factory() as session:
                return await import_decision_tree_export(session, import_user, raw, name)

        results = await asyncio.gather(
            once("race-a.smeme.json"), once("race-b.smeme.json"), return_exceptions=True
        )

    denied = [item for item in results if isinstance(item, ImportCopyError)]
    created = [item for item in results if isinstance(item, DecisionTree)]
    assert len(denied) == 1
    assert denied[0].code == "quota_exceeded"
    assert len(created) == 1
    assert await _count(test_session_factory, import_user) == cap


async def test_dashboard_import_copy_escapes_filename_and_banner(
    client, app, import_user, test_session_factory
) -> None:
    raw, _fixture = _fixture_envelope("smeme_sample_v1.json")
    filename = "<img src=x onerror=alert(1)>.smeme.json"
    with auth_as(app, import_user):
        page = await client.get("/decision-trees/dashboard")
        assert b"Import copy" in page.content
        uploaded = await client.post(
            "/decision-trees/import",
            files={"file": (filename, raw, "application/json")},
        )
        assert uploaded.status_code == 303
        editor = await client.get(uploaded.headers["location"])
    assert editor.status_code == 200
    assert b"Imported copy" in editor.content
    assert b"<img src=x" not in editor.content
    assert b"&lt;img src=x onerror=alert(1)&gt;.smeme.json" in editor.content

    async with test_session_factory() as session:
        tree = (
            await session.execute(
                select(DecisionTree).where(DecisionTree.author_id == import_user.id)
            )
        ).scalar_one()
        artifact = ReasoningCompiledArtifact(
            decision_tree_id=tree.id,
            ir_json={"kind": "test"},
            graph_hash="a" * 64,
            compiler_version="test",
            ir_format_version=1,
            ir_hash="b" * 64,
            artifact_hash="c" * 64,
            artifact_version=1,
        )
        session.add(artifact)
        await session.commit()
        await session.refresh(artifact)
        tree.current_artifact_id = artifact.id
        session.add(tree)
        await session.commit()

    with auth_as(app, import_user):
        deployed = await client.get(f"/decision-trees/{tree.id}/editor")
    assert deployed.status_code == 200
    assert b"Imported copy" not in deployed.content


async def test_oversize_upload_renders_dashboard_message(
    client, app, import_user, test_session_factory
) -> None:
    blob = b"{" + b" " * (700 * 1024)
    with auth_as(app, import_user):
        response = await client.post(
            "/decision-trees/import",
            files={"file": ("big.smeme.json", blob, "application/json")},
        )
    assert response.status_code == 200
    assert b"larger than 600 KiB" in response.content
    assert await _count(test_session_factory, import_user) == 0


async def test_import_route_quota_denial_refreshes_request_session_user(
    client, app, import_user, test_session_factory
) -> None:
    """Quota denial rolls back the request session; the Clerk user must be refreshed."""

    async def current_user_on_request_session(
        db: AsyncSession = Depends(get_db),
    ) -> User:
        user = await db.get(User, import_user.id)
        assert user is not None
        return user

    cap = TIER_LIMITS[BillingTier.FREE].max_workflows
    raw, _fixture = _fixture_envelope("smeme_sample_v1.json")
    with hosted_quota_enforcement_scope():
        async with test_session_factory() as session:
            for index in range(cap):
                await import_decision_tree_export(
                    session, import_user, raw, f"cap-{index}.smeme.json"
                )
        app.dependency_overrides[get_current_active_user] = current_user_on_request_session
        try:
            response = await client.post(
                "/decision-trees/import",
                files={"file": ("over.smeme.json", raw, "application/json")},
            )
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

    assert response.status_code == 200
    assert b"allows 3 active decision trees" in response.content
    assert await _count(test_session_factory, import_user) == cap
