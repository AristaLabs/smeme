"""Unit tests for DecisionTree dashboard, session-start routes, and in-app docs.

Covers:
- GET /decision-trees/dashboard returns 200 for authenticated user
- Dashboard renders the user's own current non-archived DecisionTree titles
- Dashboard requires authentication
- Public /docs/* pages return 200 anonymously; /docs/delete-account stays authenticated
- Public docs emit unique SEO metadata, absolute canonicals, and JSON-LD
- POST /decision-trees/start creates a DecisionTreeSession row with no payment gate
"""

import json
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from smeme.app_factory import create_core_app as create_app
from smeme.core.config import settings as process_settings
from smeme.core.models import DecisionTree, DecisionTreeSession, User
from smeme.mcp.urls import mcp_connector_url
from tests.conftest import auth_as

_PUBLIC_DOCS_PATHS = (
    "/docs",
    "/docs/quick-start",
    "/docs/run-a-tree",
    "/docs/ask-more",
    "/docs/introduction",
    "/docs/plans",
    "/docs/creator-dashboard",
    "/docs/download-workflow",
    "/docs/import",
    "/docs/langgraph",
    "/docs/mcp",
    "/docs/changelog",
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


# =============================================================================
# Fixtures
# =============================================================================


def _minimal_graph(title: str = "Test Decision Tree") -> dict:
    from smeme.decision_tree.models import (
        ConclusionData,
        DTGraph,
        DTGraphMetadata,
        GraphEdge,
        GraphNode,
        QuestionData,
    )

    g = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(text="Q?", type="radio", options=["Yes", "No"], required=True),
            ),
            GraphNode(id="c1", type="conclusion", data=ConclusionData(title="A", summary="a")),
            GraphNode(id="c2", type="conclusion", data=ConclusionData(title="B", summary="b")),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="c2", condition="No"),
        ],
        metadata=DTGraphMetadata(title=title),
    )
    return g.model_dump(mode="json")


@pytest_asyncio.fixture
async def dashboard_user(test_session_factory):
    """Free-tier user with one active DecisionTree."""
    uid = uuid4().hex[:8]
    email = f"dash_{uid}@example.com"

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password="unused_in_clerk_mode",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"dashuser_{uid}",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        my_decision_tree = DecisionTree(
            author_id=user.id,
            title=f"My DecisionTree {uid}",
            graph_data=_minimal_graph(f"My DecisionTree {uid}"),
            is_public=False,
            is_current=True,
            is_archived=False,
        )
        session.add(my_decision_tree)
        await session.commit()
        await session.refresh(my_decision_tree)

    yield {"user": user, "my_decision_tree": my_decision_tree}

    async with test_session_factory() as session:
        await session.execute(
            delete(DecisionTreeSession).where(
                DecisionTreeSession.decision_tree_id == my_decision_tree.id
            )
        )
        await session.execute(delete(DecisionTree).where(DecisionTree.id == my_decision_tree.id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


@pytest_asyncio.fixture
async def app_with_db(test_session_factory):
    from smeme.core.database import get_db

    application = create_app()

    async def override_get_db():
        async with test_session_factory() as session:
            try:
                yield session
            finally:
                await session.close()

    application.dependency_overrides[get_db] = override_get_db
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app_with_db):
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# =============================================================================
# GET /decision-trees/dashboard
# =============================================================================


async def test_dashboard_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/decision-trees/dashboard")
    assert r.status_code == 200


async def test_dashboard_requires_auth(client):
    r = await client.get("/decision-trees/dashboard")
    assert r.status_code in (302, 401, 403)


async def test_dashboard_shows_authored_decision_tree_title(client, app_with_db, dashboard_user):
    """The user's own current non-archived DecisionTree title appears in the response body."""
    title = dashboard_user["my_decision_tree"].title
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/decision-trees/dashboard")
    assert r.status_code == 200
    assert title.encode() in r.content


async def test_dashboard_has_no_acme_preview_box(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/decision-trees/dashboard")

    assert r.status_code == 200
    assert b"acme-langgraph-heading" not in r.content
    assert b"Load ACME LangGraph example" not in r.content
    assert b"LangGraph example" not in r.content
    assert b"Download synthetic case files" not in r.content


async def test_acme_example_page_requires_auth(client):
    for method in ("GET", "POST"):
        r = await client.request(method, "/decision-trees/acme-langgraph-example")
        assert r.status_code in (302, 401, 403)
        assert b"Load ACME LangGraph example" not in r.content
        assert b"Fictional-demo disclaimer" not in r.content


async def test_acme_example_page_shows_slot_warning_and_disclaimer(
    client, app_with_db, dashboard_user
):
    from smeme.decision_tree.acme_example import ACME_EXAMPLE_DISCLAIMER

    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/decision-trees/acme-langgraph-example")

    assert r.status_code == 200
    assert b"Load ACME LangGraph example" in r.content
    assert b"consumes one decision-tree slot" in r.content
    assert b"does not replace the small first-run sample" in r.content
    assert ACME_EXAMPLE_DISCLAIMER in r.text
    assert b'href="/docs/langgraph"' in r.content
    assert "no-store" in r.headers["cache-control"]


def _mark_tree_as_acme(session_factory, tree_id):
    from smeme.decision_tree.acme_example import ACME_EXAMPLE_SAMPLE_KEY

    async def _mark():
        async with session_factory() as session:
            persisted = await session.get(DecisionTree, tree_id)
            assert persisted is not None
            persisted.sample_key = ACME_EXAMPLE_SAMPLE_KEY
            session.add(persisted)
            await session.commit()

    return _mark()


async def test_acme_return_link_is_only_on_the_owners_acme_tree(
    client, app_with_db, dashboard_user, test_session_factory
):
    tree = dashboard_user["my_decision_tree"]
    with auth_as(app_with_db, dashboard_user["user"]):
        before = await client.get("/decision-trees/dashboard")
        editor_before = await client.get(f"/decision-trees/{tree.id}/editor")
    assert b"LangGraph example" not in before.content
    assert b"LangGraph example" not in editor_before.content

    await _mark_tree_as_acme(test_session_factory, tree.id)

    with auth_as(app_with_db, dashboard_user["user"]):
        dashboard = await client.get("/decision-trees/dashboard")
        editor = await client.get(f"/decision-trees/{tree.id}/editor")

    assert dashboard.status_code == 200
    assert b"LangGraph example" in dashboard.content
    assert b'href="/decision-trees/acme-langgraph-example"' in dashboard.content
    assert b"Load ACME LangGraph example" not in dashboard.content
    assert editor.status_code == 200
    assert b"LangGraph example" in editor.content
    assert b'href="/decision-trees/acme-langgraph-example"' in editor.content


async def test_acme_example_page_command_is_deployment_scoped(
    client,
    app_with_db,
    dashboard_user,
    monkeypatch,
    test_session_factory,
):
    tree = dashboard_user["my_decision_tree"]
    await _mark_tree_as_acme(test_session_factory, tree.id)
    monkeypatch.setattr(process_settings, "mcp_enabled", True)
    monkeypatch.setattr(process_settings, "mcp_http_path", "/preview/mcp")
    monkeypatch.setattr(process_settings, "mcp_allowed_oauth_client_ids", ["staging-client"])
    monkeypatch.setattr(
        process_settings,
        "acme_dataset_url",
        "https://test/downloads/smeme-acme-dataset-distributed.zip",
    )

    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/decision-trees/acme-langgraph-example")

    assert r.status_code == 200
    assert b"Open example tree" in r.content
    assert b"Download synthetic case files" in r.content
    assert b"https://test/downloads/smeme-acme-dataset-distributed.zip" in r.content
    assert b"SMEME_MCP_URL=http://test/preview/mcp" in r.content
    assert b"SMEME_OAUTH_CLIENT_ID=staging-client" in r.content
    assert f"--decision-tree-id {tree.id}".encode() in r.content
    lowered = r.text.lower()
    assert "bearer " not in lowered
    assert "secret" not in lowered
    assert "production-client" not in r.text


async def test_acme_load_error_keeps_the_example_page(
    client, app_with_db, dashboard_user, monkeypatch
):
    from smeme.decision_tree import acme_example
    from smeme.decision_tree.acme_example import ACME_EXAMPLE_DISCLAIMER

    async def fail_load(user, db):
        raise acme_example.AcmeExampleError("quota_exceeded", "No decision-tree slot remains.")

    monkeypatch.setattr(acme_example, "ensure_acme_example_tree", fail_load)

    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.post("/decision-trees/acme-langgraph-example")

    assert r.status_code == 200
    assert b"No decision-tree slot remains." in r.content
    assert b"Load ACME LangGraph example" in r.content
    assert ACME_EXAMPLE_DISCLAIMER in r.text
    assert b"consumes one decision-tree slot" in r.content
    assert "no-store" in r.headers["cache-control"]


async def test_acme_load_success_redirects_and_reload_is_idempotent(
    client, app_with_db, dashboard_user, test_session_factory
):
    from smeme.decision_tree.acme_example import ACME_EXAMPLE_SAMPLE_KEY

    user = dashboard_user["user"]
    with auth_as(app_with_db, user):
        first = await client.post("/decision-trees/acme-langgraph-example", follow_redirects=False)
        second = await client.post("/decision-trees/acme-langgraph-example", follow_redirects=False)

    assert first.status_code == 303
    assert first.headers["location"] == "/decision-trees/acme-langgraph-example"
    assert second.status_code == 303
    assert second.headers["location"] == "/decision-trees/acme-langgraph-example"

    async with test_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(DecisionTree).where(
                        DecisionTree.author_id == user.id,
                        DecisionTree.sample_key == ACME_EXAMPLE_SAMPLE_KEY,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    created_ids = [row.id for row in rows]
    async with test_session_factory() as session:
        from smeme.core.models import ReasoningCompiledArtifact

        await session.execute(
            delete(ReasoningCompiledArtifact).where(
                ReasoningCompiledArtifact.decision_tree_id.in_(created_ids)
            )
        )
        await session.execute(delete(DecisionTree).where(DecisionTree.id.in_(created_ids)))
        await session.commit()


async def test_acme_example_page_is_account_scoped(
    client, app_with_db, dashboard_user, test_session_factory
):
    owner = dashboard_user["user"]
    owner_tree = dashboard_user["my_decision_tree"]
    await _mark_tree_as_acme(test_session_factory, owner_tree.id)

    uid = uuid4().hex[:8]
    async with test_session_factory() as session:
        other = User(
            email=f"acme_other_{uid}@example.com",
            hashed_password="x",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"acme_other_{uid}",
        )
        session.add(other)
        await session.commit()
        await session.refresh(other)
        other_id = other.id

    with auth_as(app_with_db, other):
        page = await client.get("/decision-trees/acme-langgraph-example")
        dashboard = await client.get("/decision-trees/dashboard")
        loaded = await client.post("/decision-trees/acme-langgraph-example", follow_redirects=False)
    assert str(owner_tree.id) not in page.text
    assert b"LangGraph example" not in dashboard.content
    assert b"Load ACME LangGraph example" in page.content
    assert loaded.status_code == 303

    async with test_session_factory() as session:
        owner_rows = (
            (
                await session.execute(
                    select(DecisionTree.id).where(
                        DecisionTree.author_id == owner.id,
                        DecisionTree.sample_key == "smeme_acme_xborder_withholding_v1",
                    )
                )
            )
            .scalars()
            .all()
        )
        other_ids = (
            (
                await session.execute(
                    select(DecisionTree.id).where(DecisionTree.author_id == other_id)
                )
            )
            .scalars()
            .all()
        )
    assert owner_rows == [owner_tree.id]
    assert owner_tree.id not in other_ids

    async with test_session_factory() as session:
        if other_ids:
            from smeme.core.models import ReasoningCompiledArtifact

            await session.execute(
                delete(ReasoningCompiledArtifact).where(
                    ReasoningCompiledArtifact.decision_tree_id.in_(other_ids)
                )
            )
            await session.execute(delete(DecisionTree).where(DecisionTree.id.in_(other_ids)))
        await session.execute(delete(User).where(User.id == other_id))
        await session.commit()


async def test_docs_langgraph_seo_and_not_in_creator_nav(client):
    from smeme.decision_tree.acme_example import ACME_EXAMPLE_DISCLAIMER

    index = await client.get("/docs")
    page = await client.get("/docs/langgraph")
    assert index.status_code == 200
    assert page.status_code == 200
    assert "text/html" in page.headers.get("content-type", "")
    assert b'href="/docs/langgraph"' not in index.content
    assert b'href="/docs/langgraph"' not in page.content
    assert b"Load the example in your account" in page.content
    assert b'href="/decision-trees/acme-langgraph-example"' in page.content
    assert ACME_EXAMPLE_DISCLAIMER in page.text
    assert b"does not replace the two-question sample" in page.content


async def test_dashboard_generation_disabled_offers_mcp_authoring(
    client,
    app_with_db,
    dashboard_user,
    monkeypatch,
    test_session_factory,
):
    async with test_session_factory() as session:
        await session.execute(
            delete(DecisionTree).where(DecisionTree.id == dashboard_user["my_decision_tree"].id)
        )
        await session.commit()

    monkeypatch.setattr(process_settings, "smeme_ai_generation_enabled", False)
    monkeypatch.setattr(process_settings, "mcp_enabled", True)
    monkeypatch.setattr(process_settings, "mcp_authoring_graph_tools_enabled", True)

    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/decision-trees/dashboard")

    assert r.status_code == 200
    assert b"Web generation is disabled for this deployment" in r.content
    assert b"Set up MCP authoring" in r.content
    assert b'href="/decision-trees/agentic/wizard-start"' not in r.content


async def test_dashboard_prunes_completed_generation_rows(monkeypatch, dashboard_user):
    """Saved workflows should not continue occupying the in-progress dashboard slot."""
    from smeme.decision_tree import routes as decision_tree_routes
    from smeme.decision_tree.generation.agentic import workflow as workflow_module
    from smeme.decision_tree.generation.agentic.services import checkpoint_manager

    decision_tree_id = dashboard_user["my_decision_tree"].id
    generation = SimpleNamespace(
        id=uuid4(),
        langgraph_thread_id="completed-thread",
    )
    cleaned_threads: list[str] = []

    class FakeWorkflow:
        async def aget_state(self, config):
            return SimpleNamespace(
                values={"decision_tree_id": str(decision_tree_id), "final_status": "has_errors"},
            )

    async def fake_get_compiled_workflow():
        return FakeWorkflow()

    async def fake_complete_generation(db, thread_id, *, user_id):
        cleaned_threads.append(thread_id)
        assert user_id == dashboard_user["user"].id

    monkeypatch.setattr(workflow_module, "get_compiled_workflow", fake_get_compiled_workflow)
    monkeypatch.setattr(checkpoint_manager, "complete_generation", fake_complete_generation)

    active = await decision_tree_routes._prune_completed_dashboard_generations(
        db=object(),
        current_user=dashboard_user["user"],
        generations=[generation],
    )

    assert active == []
    assert cleaned_threads == ["completed-thread"]


async def test_dashboard_hides_archive_ui(client, app_with_db, dashboard_user):
    """Archive affordances removed from product."""
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/decision-trees/dashboard")
    assert r.status_code == 200
    assert b"archive-confirm" not in r.content
    assert b'id="archived-heading"' not in r.content
    assert b"Restore archived workflow" not in r.content
    assert b"delete-confirm" in r.content


async def test_docs_index_public_anonymous(client):
    r = await client.get("/docs")
    assert r.status_code == 200
    assert b"Documentation" in r.content
    assert b'id="why-smeme"' in r.content
    assert b"Business rules don&rsquo;t belong in prompts." in r.content
    assert b"SMEme is rational AI." in r.content
    assert b"It asks only what still matters." in r.content
    assert b"/docs/mcp" in r.content
    assert b"/docs/delete-account" not in r.content
    assert "public, max-age=300" in r.headers.get("cache-control", "")
    assert "Cookie" in r.headers.get("vary", "")
    assert "Authorization" in r.headers.get("vary", "")


async def test_docs_index_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs")
    assert r.status_code == 200
    assert b"Deploy" in r.content
    assert b"Listed" in r.content
    from smeme.docs.constants import DOCS_VERSION

    assert DOCS_VERSION.encode() in r.content
    assert b"/docs/creator-dashboard" in r.content
    assert b"/docs/download-workflow" in r.content
    assert b"/docs/import" in r.content
    assert b"/docs/mcp" in r.content
    assert b"/docs/quick-start" in r.content
    assert b"/docs/run-a-tree" in r.content
    assert b"/docs/ask-more" in r.content
    assert b"/docs/delete-account" in r.content
    assert b"copy-paste" in r.content.lower() or b"Copy prompts" in r.content
    assert b"marketplace" not in r.content.lower()
    assert b"revenue" not in r.content.lower()
    cache = r.headers.get("cache-control", "")
    assert "private" in cache
    assert "no-store" in cache or "no-cache" in cache


async def test_docs_introduction_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs/introduction")
    assert r.status_code == 200
    assert b"How to fix" in r.content
    assert b"Deploy, list" in r.content
    assert b"build or revise a draft through MCP" in r.content
    assert b"/docs/mcp#mcp-authoring-quickstart" in r.content


async def test_docs_public_pages_anonymous_ok(client):
    for path in _PUBLIC_DOCS_PATHS:
        r = await client.get(path)
        assert r.status_code == 200, path
        assert "public, max-age=300" in r.headers.get("cache-control", ""), path
        assert "Cookie" in r.headers.get("vary", ""), path


async def test_docs_public_seo_metadata_and_json_ld(client):
    """Each public docs page has unique title/description, self-canonical, one H1, JSON-LD."""
    site_base = process_settings.effective_base_url.rstrip("/")
    titles: set[str] = set()
    descriptions: set[str] = set()

    for path in _PUBLIC_DOCS_PATHS:
        r = await client.get(path)
        assert r.status_code == 200, path
        html = r.text

        title_m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
        assert title_m, path
        title = re.sub(r"\s+", " ", title_m.group(1)).strip()
        assert title, path
        assert title not in titles, f"duplicate title for {path}: {title}"
        titles.add(title)

        desc_m = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html, re.I)
        assert desc_m, path
        description = desc_m.group(1).strip()
        assert description, path
        assert description not in descriptions, f"duplicate description for {path}"
        descriptions.add(description)
        assert "/docs/delete-account" not in description, path

        canonical_m = re.search(r'<link\s+rel="canonical"\s+href="([^"]+)"', html, re.I)
        assert canonical_m, path
        canonical = canonical_m.group(1)
        assert canonical == f"{site_base}{path}", path
        assert "/docs/delete-account" not in canonical

        assert len(re.findall(r"<h1\b", html, re.I)) == 1, path

        ld_blocks = re.findall(
            r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
            html,
            re.I | re.S,
        )
        assert ld_blocks, path
        types_seen: set[str] = set()
        for raw in ld_blocks:
            data = json.loads(raw)
            assert data.get("@context") == "https://schema.org", path
            schema_type = data.get("@type")
            assert schema_type in {"TechArticle", "WebPage", "BreadcrumbList", "HowTo"}, path
            types_seen.add(schema_type)
            if schema_type == "BreadcrumbList":
                for item in data["itemListElement"]:
                    assert "/docs/delete-account" not in item["item"]
            else:
                assert data.get("url") == canonical, path
                assert data.get("description") == description, path
        assert types_seen & {"TechArticle", "WebPage"}, path
        if path != "/docs":
            assert "BreadcrumbList" in types_seen, path

    mcp = await client.get("/docs/mcp")
    assert b"creator how-to" in mcp.content or b"Creator setup" in mcp.content
    assert b'href="/mcp"' in mcp.content
    assert b"wire" in mcp.content.lower() or b"tool reference" in mcp.content.lower()
    assert b'href="/docs/quick-start"' in mcp.content


async def test_docs_quick_start_path(client):
    r = await client.get("/docs/quick-start")
    assert r.status_code == 200
    html = r.text
    assert "1. Connect SMEme" in html
    assert "2. Choose and build a decision tree" in html
    assert "3. Deploy, List, and try it" in html
    assert "opens a browser tab where you sign in to SMEme" in html
    assert "Help me add SMEme as a remote MCP connector." in html
    assert "to this app" not in html
    assert "Check that SMEme is working." in html
    assert "You have a specific decision procedure in mind." in html
    assert "Have your agent observe your work." in html
    assert "not sure which decision procedure to encode." in html
    assert "Record where each answer should come from and where not to look" in html
    assert "docs-dash" in html
    assert 'href="/docs#why-smeme"' in html
    assert "asks only the questions that can still change the outcome" in html
    assert "which open questions can" not in html
    assert 'href="/docs/run-a-tree"' in html
    assert 'href="/docs/ask-more"' in html
    assert '"@type": "HowTo"' in html
    nav = html.split('aria-label="Docs sections"', 1)[1].split("</nav>", 1)[0]
    assert nav.index("/docs/quick-start") < nav.index("/docs/introduction")
    assert nav.index("/docs/run-a-tree") < nav.index("/docs/introduction")
    assert nav.index("/docs/ask-more") < nav.index("/docs/introduction")


async def test_docs_run_and_ask_more_prompts(client):
    run = await client.get("/docs/run-a-tree")
    assert run.status_code == 200
    assert "Run it in a <strong" in run.text
    assert "follow the hints on that question about where to look and what to avoid" in run.text
    assert "docs-chat" in run.text
    assert 'data-testid="docs-result-kinds"' in run.text
    for result in (
        "Concluded",
        "Several outcomes possible",
        "Needs more information",
        "Sources conflict",
    ):
        assert result in run.text
    assert "Send a batch of answers in one shot" in run.text
    assert "instead of guessing" in run.text
    assert "were not independently re-checked" in run.text
    assert "answer the questions you can from the evidence" in run.text
    ask = await client.get("/docs/ask-more")
    assert ask.status_code == 200
    assert "Which answers decided this outcome?" in ask.text
    assert "Keep [answers that can" in ask.text
    assert "Which open questions would settle it" in ask.text
    assert "What outcomes can my [decision tree name] reach?" in ask.text
    for removed in ("admitted", "What cannot change the result", 'href="/mcp"'):
        assert removed not in ask.text


async def test_docs_creator_dashboard_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs/creator-dashboard")
    assert r.status_code == 200
    assert b"Deploy, validate" in r.content
    assert b"How to fix" in r.content
    assert b"Live" in r.content
    assert b"Stale" in r.content
    assert b"marketplace" not in r.content.lower()
    assert b"revenue" not in r.content.lower()
    assert b"Load sample" in r.content
    assert b"one decision-tree slot" in r.content


async def test_docs_import_content_contract(client):
    """Anonymous readers get the public guide, not the engineering brief."""
    r = await client.get("/docs/import")
    assert r.status_code == 200
    html = r.text
    assert "<title>Upload decision tree — Docs</title>" in html
    assert html.index("file selector") < html.index('id="file-heading"')
    assert "Import copy" in html
    assert 'id="file-heading"' in html
    assert "The file" in html
    assert 'id="limits-heading"' in html
    assert "Limits" in html
    assert 'id="refused-heading"' in html
    assert "If the file is refused" in html
    assert "does not share your tree" in html
    assert "smeme_export_version" in html
    lowered = html.lower()
    for term in (
        "advisory",
        "import_filename",
        "validate_graph_for_editing",
        "reserve_decision_tree_slot",
    ):
        assert term not in lowered


async def test_docs_download_workflow_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs/download-workflow")
    assert r.status_code == 200
    assert b"Download your decision tree" in r.content
    assert b"smeme_export_version" in r.content
    assert b'href="/docs/import"' in r.content
    assert b"not available yet" not in r.content


async def test_docs_delete_account_requires_auth(client):
    r = await client.get("/docs/delete-account")
    assert r.status_code in (302, 401, 403)


async def test_docs_mcp_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs/mcp")
    assert r.status_code == 200
    assert b"Connect your agent" in r.content
    assert b"smeme_reasoning" in r.content
    assert b"there is no separate install package" in r.content
    # MCP authoring sequence (agent constructs; SMEme validates/saves)
    assert b'id="mcp-authoring-quickstart"' in r.content
    assert b"dt_graph_json" in r.content
    assert b"draft_ready" in r.content
    assert b"smeme_authoring_design_guidance" in r.content
    assert b"smeme_authoring_validate_graph" in r.content
    assert b"smeme_authoring_create_draft" in r.content
    assert b"smeme_authoring_get_draft" in r.content
    assert b"smeme_authoring_update_draft" in r.content
    assert b"expected_graph_hash" in r.content
    assert b"graph_conflict" in r.content
    assert b"Open the editor" in r.content
    assert b"review" in r.content.lower()
    assert b"Deploy" in r.content
    assert b"Listed" in r.content
    assert b"Hidden" in r.content
    assert b"Load sample" in r.content
    assert b"sample_key" in r.content
    assert b"decision_tree_id" in r.content
    assert b"examples/smeme_apply_sample.py" in r.content
    assert b"discussions/categories/mcp-tools" in r.content
    assert b"discussions/categories/mcp-clients" in r.content
    assert b'href="https://github.com/AristaLabs/smeme/discussions"' not in r.content
    if process_settings.mcp_enabled:
        assert b"install-claude" in r.content
        assert b"install-chatgpt" in r.content
        assert b"Developer mode" in r.content
        assert b"create dialog" in r.content
        assert b"Advanced settings" in r.content
        assert b"Customize" in r.content
        assert b"chatgpt.com" in r.content
        assert b"browser" in r.content
        assert mcp_connector_url(process_settings).encode() in r.content
    else:
        assert b"MCP is not enabled on this server" in r.content


async def test_mcp_discoverable_toggle_requires_owner(
    client, app_with_db, dashboard_user, test_session_factory
):
    """Non-owner cannot toggle discoverability (403)."""
    from sqlalchemy import delete

    uid = uuid4().hex[:8]
    async with test_session_factory() as session:
        other = User(
            email=f"other_{uid}@example.com",
            hashed_password="x",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"other_{uid}",
        )
        session.add(other)
        await session.commit()
        await session.refresh(other)

    qid = dashboard_user["my_decision_tree"].id
    with auth_as(app_with_db, other):
        r = await client.post(
            "/decision-trees/mcp/discoverable",
            data={"decision_tree_id": str(qid), "enabled": "true"},
            follow_redirects=False,
        )
    assert r.status_code == 403

    async with test_session_factory() as session:
        await session.execute(delete(User).where(User.id == other.id))
        await session.commit()


# =============================================================================
# POST /decision-trees/start — no payment gate
# =============================================================================


async def test_start_decision_tree_creates_session_without_payment_gate(
    client, app_with_db, dashboard_user, test_session_factory
):
    """POST /decision-trees/start must create a DecisionTreeSession and return 200 with no billing redirect.

    Before Phase 1 this route checked price_cents and redirected free-tier users
    to /billing/session-pay/...  That gate is gone; any authenticated user can
    start a session on any DecisionTree directly.
    """
    user = dashboard_user["user"]
    decision_tree_id = dashboard_user["my_decision_tree"].id

    with auth_as(app_with_db, user):
        r = await client.post(
            "/decision-trees/start", data={"decision_tree_id": str(decision_tree_id)}
        )

    # Must not redirect to billing
    assert r.status_code == 200
    assert "session-pay" not in str(r.headers.get("location", ""))
    assert "session-pay" not in r.text

    # A DecisionTreeSession row must exist in the DB
    async with test_session_factory() as session:
        result = await session.execute(
            select(DecisionTreeSession).where(
                DecisionTreeSession.user_id == user.id,
                DecisionTreeSession.decision_tree_id == decision_tree_id,
            )
        )
        decision_tree_session = result.scalar_one_or_none()

    assert decision_tree_session is not None
