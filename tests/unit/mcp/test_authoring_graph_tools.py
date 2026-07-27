"""Unit tests for MCP authoring graph validate + create_draft tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from smeme.core.models import User
from smeme.decision_tree.helpers.validation import validate_graph_for_agent_authoring
from smeme.decision_tree.models import (
    ConclusionData,
    DTGraph,
    DTGraphMetadata,
    GraphEdge,
    GraphNode,
    QuestionData,
)
from smeme.mcp.authoring_graph import (
    AUTHORING_GRAPH_JSON_MAX_UTF8_BYTES,
    extract_graph_dict,
    parse_authoring_graph_json,
    validation_payload,
)
from smeme.mcp.invocation_telemetry import (
    internal_cost_units_for_tool,
    quota_weight_for_tool,
)
from smeme.mcp.reasoning_fastmcp import (
    REASONING_CAPABILITIES_VERSION,
    reasoning_capabilities_document,
    reset_mcp_runtime_for_tests,
)


def _minimal_graph(title: str = "Vendor Check") -> dict:
    g = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Is the vendor sound?",
                    type="radio",
                    options=["Yes", "No", "Unsure"],
                    required=True,
                ),
            ),
            GraphNode(
                id="c1",
                type="conclusion",
                data=ConclusionData(title="Approve", summary="ok"),
            ),
            GraphNode(
                id="c2",
                type="conclusion",
                data=ConclusionData(title="Reject", summary="no"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="c2", condition="No"),
            GraphEdge(source="q1", target="c2", condition="Unsure"),
        ],
        metadata=DTGraphMetadata(title=title),
    )
    return g.model_dump(mode="json")


class TestAuthoringGraphHelpers:
    def test_extract_raw_graph(self) -> None:
        raw = _minimal_graph()
        out = extract_graph_dict(raw)
        assert isinstance(out, dict)
        assert out["metadata"]["title"] == "Vendor Check"

    def test_extract_export_envelope(self) -> None:
        envelope = {
            "smeme_export_version": "2",
            "decision_tree": {"title": "X", "graph": _minimal_graph("From Export")},
        }
        out = extract_graph_dict(envelope)
        assert isinstance(out, dict)
        assert out["metadata"]["title"] == "From Export"

    def test_parse_invalid_json(self) -> None:
        err = parse_authoring_graph_json("{not-json")
        assert isinstance(err, str)
        payload = json.loads(err)
        assert payload["error"]["code"] == "invalid_graph"

    def test_parse_oversized(self) -> None:
        pad = "x" * (AUTHORING_GRAPH_JSON_MAX_UTF8_BYTES + 10)
        err = parse_authoring_graph_json(f'{{"pad": "{pad}"}}')
        assert isinstance(err, str)
        assert json.loads(err)["error"]["code"] == "payload_too_large"

    def test_parse_schema_errors_are_aggregated(self) -> None:
        bad = {
            "nodes": [
                {
                    "id": "q1",
                    "type": "question",
                    "data": {
                        "text": "Q?",
                        "type": "radio",
                        "options": ["A"],
                        "required": True,
                        "bogus": 1,
                    },
                },
                {
                    "id": "c1",
                    "type": "conclusion",
                    "data": {"title": "Only title"},
                },
            ],
            "edges": [{"source": "q1", "target": "c1", "condition": "A", "id": "e1"}],
            "metadata": {"title": "X"},
        }
        err = parse_authoring_graph_json(json.dumps(bad))
        assert isinstance(err, str)
        payload = json.loads(err)
        assert payload["error"]["code"] == "invalid_graph"
        errors = payload["error"]["errors"]
        assert isinstance(errors, list)
        assert len(errors) >= 2
        joined = "\n".join(errors)
        assert "nodes.0.data.bogus" in joined
        assert "nodes.1.data.summary" in joined
        assert "nodes.1.data.question" not in joined
        assert "edges.0.id" in joined

    def test_conclusion_schema_errors_use_conclusion_fields(self) -> None:
        bad = {
            "nodes": [
                {
                    "id": "q1",
                    "type": "question",
                    "data": {
                        "text": "Q?",
                        "type": "radio",
                        "options": ["A"],
                        "required": True,
                    },
                },
                {
                    "id": "c1",
                    "type": "conclusion",
                    "data": {"title": "Approve"},  # missing summary
                },
            ],
            "edges": [],
            "metadata": {"title": "X"},
        }
        err = parse_authoring_graph_json(json.dumps(bad))
        payload = json.loads(err)
        joined = "\n".join(payload["error"]["errors"])
        assert "nodes.1.data.summary" in joined
        assert "nodes.1.data.question" not in joined
        assert "nodes.1.data.options" not in joined

    def test_validation_payload_draft_ready(self) -> None:
        graph = DTGraph.model_validate(_minimal_graph())
        result = validate_graph_for_agent_authoring(graph)
        body = validation_payload(graph, result)
        assert body["draft_ready"] is True
        assert body["deploy_ready"] is False
        assert body["is_valid"] is True

    def test_agent_authoring_requires_unknown_option(self) -> None:
        graph_dict = _minimal_graph()
        graph_dict["nodes"][0]["data"]["options"] = ["Yes", "No"]
        graph_dict["edges"] = graph_dict["edges"][:2]
        result = validate_graph_for_agent_authoring(DTGraph.model_validate(graph_dict))
        assert result["is_valid"] is False
        assert any("explicit unknown option" in error for error in result["errors"])


class TestAuthoringGraphCapabilities:
    def test_tools_absent_when_disabled(self) -> None:
        from smeme.core.config import Settings

        mock_settings = MagicMock(spec=Settings)
        mock_settings.mcp_authoring_graph_tools_enabled = False
        doc = reasoning_capabilities_document(cap_settings=mock_settings)
        tools = doc["reasoning"]["tools"]
        assert "smeme_authoring_validate_graph" not in tools
        assert "smeme_authoring_create_draft" not in tools
        assert "smeme_authoring_design_guidance" not in tools
        assert "smeme_authoring_get_draft" not in tools
        assert "smeme_authoring_update_draft" not in tools
        assert "authoring_graph" not in doc
        assert "authoring_design" not in doc

    def test_tools_present_when_enabled(self) -> None:
        from smeme.core.config import Settings

        mock_settings = MagicMock(spec=Settings)
        mock_settings.mcp_authoring_graph_tools_enabled = True
        doc = reasoning_capabilities_document(cap_settings=mock_settings)
        tools = doc["reasoning"]["tools"]
        assert "smeme_authoring_validate_graph" in tools
        assert "smeme_authoring_create_draft" in tools
        assert "smeme_authoring_design_guidance" in tools
        assert "smeme_authoring_get_draft" in tools
        assert "smeme_authoring_update_draft" in tools
        assert doc["authoring_graph"]["validate"] == "smeme_authoring_validate_graph"
        assert doc["authoring_graph"]["design_guidance"] == "smeme_authoring_design_guidance"
        assert doc["authoring_graph"]["get_draft"] == "smeme_authoring_get_draft"
        assert doc["authoring_graph"]["update_draft"] == "smeme_authoring_update_draft"
        assert "schema" in doc["authoring_graph"]
        assert doc["authoring_graph"]["schema"]["required"] == ["nodes", "edges", "metadata"]
        node_items = doc["authoring_graph"]["schema"]["properties"]["nodes"]["items"]
        assert "oneOf" in node_items
        titles = {variant.get("title") for variant in node_items["oneOf"]}
        assert titles == {"QuestionNode", "ConclusionNode"}
        metadata = doc["authoring_graph"]["schema"]["properties"]["metadata"]["properties"]
        assert metadata["estimated_time"]["description"].endswith("minutes.")
        assert metadata["effective_date"]["format"] == "date"
        assert metadata["review_by"]["format"] == "date"
        assert "regression_fixtures" in metadata
        question_schema = next(
            item["properties"]["data"]
            for item in node_items["oneOf"]
            if item["title"] == "QuestionNode"
        )
        assert "authorities" in question_schema["properties"]
        assert "authoring_design" in doc


class TestAuthoringGraphQuota:
    def test_quota_weights(self) -> None:
        assert quota_weight_for_tool("smeme_authoring_design_guidance") == 0.0
        assert quota_weight_for_tool("smeme_authoring_validate_graph") == 0.0
        assert quota_weight_for_tool("smeme_authoring_create_draft") == 0.0
        assert quota_weight_for_tool("smeme_authoring_get_draft") == 0.0
        assert quota_weight_for_tool("smeme_authoring_update_draft") == 0.0

    def test_internal_cost(self) -> None:
        assert internal_cost_units_for_tool("smeme_authoring_design_guidance") == 0.0
        assert internal_cost_units_for_tool("smeme_authoring_validate_graph") == 0.0
        assert internal_cost_units_for_tool("smeme_authoring_create_draft") == 0.1
        assert internal_cost_units_for_tool("smeme_authoring_get_draft") == 0.0
        assert internal_cost_units_for_tool("smeme_authoring_update_draft") == 0.1


class TestAuthoringDesignGuidanceTool:
    @pytest.mark.asyncio
    async def test_returns_design_markdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from smeme.mcp._generated_design_guidance import (
            DESIGN_GUIDANCE_DIGEST,
            DESIGN_GUIDANCE_MARKDOWN,
            DESIGN_GUIDANCE_VERSION,
        )

        reset_mcp_runtime_for_tests()
        user = User(id=uuid4(), clerk_user_id="user_test", email="a@example.com")
        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)

        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_design_guidance"].fn
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(MagicMock())

        payload = json.loads(raw)
        assert "error" not in payload
        assert payload["content_version"] == DESIGN_GUIDANCE_VERSION
        assert payload["content_digest"] == DESIGN_GUIDANCE_DIGEST
        assert payload["content_markdown"] == DESIGN_GUIDANCE_MARKDOWN
        assert "Product constraints" in payload["content_markdown"]
        assert payload["_server_plugin_version"] == REASONING_CAPABILITIES_VERSION


class TestAuthoringValidateTool:
    @pytest.mark.asyncio
    async def test_validate_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_mcp_runtime_for_tests()
        user = User(id=uuid4(), clerk_user_id="user_test", email="a@example.com")
        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)

        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_validate_graph"].fn
        ctx = MagicMock()
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(json.dumps(_minimal_graph()), ctx)

        payload = json.loads(raw)
        assert "error" not in payload
        assert payload["draft_ready"] is True
        assert payload["_server_plugin_version"] == REASONING_CAPABILITIES_VERSION

    @pytest.mark.asyncio
    async def test_validate_requires_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_mcp_runtime_for_tests()
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)
        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(
                return_value=json.dumps({"error": {"code": "auth_error", "message": "nope"}})
            ),
        )
        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_validate_graph"].fn
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(json.dumps(_minimal_graph()), MagicMock())
        assert json.loads(raw)["error"]["code"] == "auth_error"


class TestAuthoringCreateDraftTool:
    @pytest.mark.asyncio
    async def test_create_draft_persists_decision_tree(
        self, monkeypatch: pytest.MonkeyPatch, test_session_factory
    ) -> None:
        reset_mcp_runtime_for_tests()
        uid = uuid4()
        async with test_session_factory() as session:
            user = User(
                id=uid,
                email=f"author_{uid.hex[:8]}@example.com",
                hashed_password="unused",
                is_active=True,
                is_verified=True,
                clerk_user_id=f"user_{uid.hex[:8]}",
                username=f"author_{uid.hex[:8]}",
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)

        # Bind tool's AsyncSessionLocal to the test factory.
        monkeypatch.setattr("smeme.mcp.reasoning_fastmcp.AsyncSessionLocal", test_session_factory)

        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_create_draft"].fn
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(
                json.dumps(_minimal_graph("MCP Draft")),
                MagicMock(),
                title=None,
            )

        payload = json.loads(raw)
        assert "error" not in payload, payload
        assert payload["status"] == "draft"
        assert payload["title"] == "MCP Draft"
        assert payload["deployed"] is False
        assert "/decision-trees/" in payload["editor_url"]
        assert payload["editor_url"].endswith("/editor")
        assert "/decision-trees/editor/" not in payload["editor_url"]
        assert payload["_server_plugin_version"] == REASONING_CAPABILITIES_VERSION
        assert isinstance(payload["graph_hash"], str)
        assert len(payload["graph_hash"]) == 64

        from sqlalchemy import select

        from smeme.core.models import DecisionTree

        async with test_session_factory() as session:
            row = (
                await session.execute(
                    select(DecisionTree).where(DecisionTree.id == payload["decision_tree_id"])
                )
            ).scalar_one()
            assert row.author_id == uid
            assert row.title == "MCP Draft"
            assert row.mcp_discoverable is False

    @pytest.mark.asyncio
    async def test_create_rejects_invalid_graph(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_mcp_runtime_for_tests()
        user = User(id=uuid4(), clerk_user_id="user_test", email="a@example.com")
        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)
        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_create_draft"].fn
        bad = {
            "nodes": [],
            "edges": [],
            "metadata": {"title": "Empty"},
        }
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(json.dumps(bad), MagicMock(), title=None)
        assert json.loads(raw)["error"]["code"] == "invalid_graph"


async def _seed_user_and_draft(
    test_session_factory,
    *,
    title: str = "Seed Draft",
    mcp_discoverable: bool = False,
    reasoning_status: str | None = None,
    artifact_hash: str | None = None,
    is_archived: bool = False,
    is_public: bool = False,
    was_ever_public: bool = False,
):
    from smeme.core.models import DecisionTree, ReasoningCompiledArtifact
    from smeme.reasoning.graph_hash import canonical_graph_hash

    uid = uuid4()
    graph = _minimal_graph(title)
    async with test_session_factory() as session:
        user = User(
            id=uid,
            email=f"author_{uid.hex[:8]}@example.com",
            hashed_password="unused",
            is_active=True,
            is_verified=True,
            clerk_user_id=f"user_{uid.hex[:8]}",
            username=f"author_{uid.hex[:8]}",
        )
        session.add(user)
        await session.flush()
        decision_tree = DecisionTree(
            title=title,
            author_id=uid,
            graph_data=graph,
            mcp_discoverable=mcp_discoverable,
            reasoning_status=reasoning_status,
            is_archived=is_archived,
            is_public=is_public,
            was_ever_public=was_ever_public,
        )
        session.add(decision_tree)
        await session.flush()
        if artifact_hash is not None:
            from smeme.reasoning.artifact_identity import (
                compute_identity_fields_from_stored_artifact,
            )

            artifact = ReasoningCompiledArtifact(
                decision_tree_id=decision_tree.id,
                ir_json={"nodes": [], "edges": []},
                graph_hash=artifact_hash,
                compiler_version="test",
                ir_format_version=1,
                artifact_version=1,
            )
            artifact.ir_hash, artifact.artifact_hash = (
                compute_identity_fields_from_stored_artifact(artifact)
            )
            session.add(artifact)
            await session.flush()
            decision_tree.current_artifact_id = artifact.id
        await session.commit()
        await session.refresh(decision_tree)
        await session.refresh(user)
        tree_id = decision_tree.id
        live_hash = canonical_graph_hash(DTGraph.model_validate(graph))
    return user, tree_id, live_hash, graph


class TestAuthoringGetDraftTool:
    @pytest.mark.asyncio
    async def test_get_draft_returns_graph_and_validation(
        self, monkeypatch: pytest.MonkeyPatch, test_session_factory
    ) -> None:
        reset_mcp_runtime_for_tests()
        user, tree_id, live_hash, graph = await _seed_user_and_draft(
            test_session_factory, mcp_discoverable=False
        )
        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)
        monkeypatch.setattr("smeme.mcp.reasoning_fastmcp.AsyncSessionLocal", test_session_factory)

        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_get_draft"].fn
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(str(tree_id), MagicMock())

        payload = json.loads(raw)
        assert "error" not in payload, payload
        assert payload["decision_tree_id"] == str(tree_id)
        assert payload["graph_hash"] == live_hash
        assert payload["graph"]["metadata"]["title"] == graph["metadata"]["title"]
        assert payload["draft_ready"] is True
        assert payload["deployment_sync"] == "not_built"
        assert payload["mcp_discoverable"] is False
        assert payload["editable"] is True
        assert payload["_server_plugin_version"] == REASONING_CAPABILITIES_VERSION

    @pytest.mark.asyncio
    async def test_get_draft_owner_only(
        self, monkeypatch: pytest.MonkeyPatch, test_session_factory
    ) -> None:
        reset_mcp_runtime_for_tests()
        _owner, tree_id, _hash, _graph = await _seed_user_and_draft(test_session_factory)
        other = User(id=uuid4(), clerk_user_id="user_other", email="other@example.com")
        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(return_value=other),
        )
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)
        monkeypatch.setattr("smeme.mcp.reasoning_fastmcp.AsyncSessionLocal", test_session_factory)

        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_get_draft"].fn
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(str(tree_id), MagicMock())
        assert json.loads(raw)["error"]["code"] == "not_found"


class TestAuthoringUpdateDraftTool:
    @pytest.mark.asyncio
    async def test_update_valid_graph(
        self, monkeypatch: pytest.MonkeyPatch, test_session_factory
    ) -> None:
        reset_mcp_runtime_for_tests()
        user, tree_id, live_hash, graph = await _seed_user_and_draft(test_session_factory)
        revised = json.loads(json.dumps(graph))
        revised["nodes"][0]["data"]["text"] = "Revised question?"
        revised["metadata"]["title"] = "Revised Title"

        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)
        monkeypatch.setattr("smeme.mcp.reasoning_fastmcp.AsyncSessionLocal", test_session_factory)

        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp
        from smeme.reasoning.graph_hash import canonical_graph_hash

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_update_draft"].fn
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(
                str(tree_id),
                json.dumps(revised),
                live_hash,
                MagicMock(),
                title=None,
            )

        payload = json.loads(raw)
        assert "error" not in payload, payload
        assert payload["previous_graph_hash"] == live_hash
        assert payload["graph_hash"] == canonical_graph_hash(DTGraph.model_validate(revised))
        assert payload["title"] == "Revised Title"
        assert payload["draft_ready"] is True
        assert payload["deployment_sync"] == "not_built"

        from sqlalchemy import select

        from smeme.core.models import DecisionTree

        async with test_session_factory() as session:
            row = (
                await session.execute(select(DecisionTree).where(DecisionTree.id == tree_id))
            ).scalar_one()
            assert row.title == "Revised Title"
            assert row.graph_data["nodes"][0]["data"]["text"] == "Revised question?"
            assert row.mcp_discoverable is False

    @pytest.mark.asyncio
    async def test_update_persists_edit_invalid_but_schema_valid(
        self, monkeypatch: pytest.MonkeyPatch, test_session_factory
    ) -> None:
        """Lenient update: missing Unsure fails draft_ready but still saves."""
        reset_mcp_runtime_for_tests()
        user, tree_id, live_hash, graph = await _seed_user_and_draft(test_session_factory)
        broken = json.loads(json.dumps(graph))
        broken["nodes"][0]["data"]["options"] = ["Yes", "No"]
        broken["edges"] = broken["edges"][:2]

        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)
        monkeypatch.setattr("smeme.mcp.reasoning_fastmcp.AsyncSessionLocal", test_session_factory)

        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_update_draft"].fn
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(
                str(tree_id),
                json.dumps(broken),
                live_hash,
                MagicMock(),
                title=None,
            )

        payload = json.loads(raw)
        assert "error" not in payload, payload
        assert payload["draft_ready"] is False
        assert any("explicit unknown option" in e for e in payload["errors"])
        assert len(payload["graph_hash"]) == 64

        from sqlalchemy import select

        from smeme.core.models import DecisionTree

        async with test_session_factory() as session:
            row = (
                await session.execute(select(DecisionTree).where(DecisionTree.id == tree_id))
            ).scalar_one()
            assert row.graph_data["nodes"][0]["data"]["options"] == ["Yes", "No"]

    @pytest.mark.asyncio
    async def test_update_rejects_schema_invalid(
        self, monkeypatch: pytest.MonkeyPatch, test_session_factory
    ) -> None:
        reset_mcp_runtime_for_tests()
        user, tree_id, live_hash, _graph = await _seed_user_and_draft(test_session_factory)
        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)
        monkeypatch.setattr("smeme.mcp.reasoning_fastmcp.AsyncSessionLocal", test_session_factory)

        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_update_draft"].fn
        bad = {
            "nodes": [
                {
                    "id": "q1",
                    "type": "question",
                    "data": {
                        "text": "Q?",
                        "type": "radio",
                        "options": ["A"],
                        "required": True,
                        "bogus": 1,
                    },
                }
            ],
            "edges": [],
            "metadata": {"title": "X"},
        }
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(
                str(tree_id),
                json.dumps(bad),
                live_hash,
                MagicMock(),
                title=None,
            )
        assert json.loads(raw)["error"]["code"] == "invalid_graph"

    @pytest.mark.asyncio
    async def test_update_graph_conflict(
        self, monkeypatch: pytest.MonkeyPatch, test_session_factory
    ) -> None:
        reset_mcp_runtime_for_tests()
        user, tree_id, live_hash, graph = await _seed_user_and_draft(test_session_factory)
        stale_hash = "a" * 64
        assert stale_hash != live_hash

        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)
        monkeypatch.setattr("smeme.mcp.reasoning_fastmcp.AsyncSessionLocal", test_session_factory)

        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_update_draft"].fn
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(
                str(tree_id),
                json.dumps(graph),
                stale_hash,
                MagicMock(),
                title=None,
            )
        err = json.loads(raw)["error"]
        assert err["code"] == "graph_conflict"
        assert err["current_hash"] == live_hash
        assert err["expected_hash"] == stale_hash

    @pytest.mark.asyncio
    async def test_update_blocks_archived(
        self, monkeypatch: pytest.MonkeyPatch, test_session_factory
    ) -> None:
        reset_mcp_runtime_for_tests()
        user, tree_id, live_hash, graph = await _seed_user_and_draft(
            test_session_factory, is_archived=True
        )
        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)
        monkeypatch.setattr("smeme.mcp.reasoning_fastmcp.AsyncSessionLocal", test_session_factory)

        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_update_draft"].fn
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(
                str(tree_id),
                json.dumps(graph),
                live_hash,
                MagicMock(),
                title=None,
            )
        assert json.loads(raw)["error"]["code"] == "draft_not_editable"

    @pytest.mark.asyncio
    async def test_update_deployed_becomes_stale_without_touching_artifact(
        self, monkeypatch: pytest.MonkeyPatch, test_session_factory
    ) -> None:
        reset_mcp_runtime_for_tests()
        from sqlalchemy import select

        from smeme.core.models import DecisionTree, ReasoningCompiledArtifact
        from smeme.reasoning.graph_hash import canonical_graph_hash

        title = "Seed Draft"
        initial_graph_hash = canonical_graph_hash(DTGraph.model_validate(_minimal_graph(title)))
        user, tree_id, live_hash, graph = await _seed_user_and_draft(
            test_session_factory,
            title=title,
            mcp_discoverable=True,
            reasoning_status="compiled",
            artifact_hash=initial_graph_hash,
        )
        assert live_hash == initial_graph_hash

        revised = json.loads(json.dumps(graph))
        revised["nodes"][0]["data"]["text"] = "Post-deploy revision?"

        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)
        monkeypatch.setattr("smeme.mcp.reasoning_fastmcp.AsyncSessionLocal", test_session_factory)

        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_update_draft"].fn
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(
                str(tree_id),
                json.dumps(revised),
                live_hash,
                MagicMock(),
                title=None,
            )

        payload = json.loads(raw)
        assert "error" not in payload, payload
        assert payload["deployment_sync"] == "stale"
        assert payload["deployed_stale"] is True
        assert payload["mcp_discoverable"] is True
        assert payload["graph_hash"] == canonical_graph_hash(DTGraph.model_validate(revised))

        async with test_session_factory() as session:
            row = (
                await session.execute(select(DecisionTree).where(DecisionTree.id == tree_id))
            ).scalar_one()
            art = (
                await session.execute(
                    select(ReasoningCompiledArtifact).where(
                        ReasoningCompiledArtifact.decision_tree_id == tree_id
                    )
                )
            ).scalar_one()
            assert row.mcp_discoverable is True
            assert row.reasoning_status == "compiled"
            assert art.graph_hash == live_hash

    @pytest.mark.asyncio
    async def test_concurrent_updates_one_wins(
        self, monkeypatch: pytest.MonkeyPatch, test_session_factory
    ) -> None:
        """Two updates with the same expected hash: exactly one commits."""
        from smeme.core.models import DecisionTree
        from smeme.mcp.authoring_graph import update_draft_from_graph
        from smeme.reasoning.graph_hash import canonical_graph_hash

        user, tree_id, live_hash, graph = await _seed_user_and_draft(test_session_factory)
        g_a = DTGraph.model_validate(graph)
        g_b = DTGraph.model_validate(graph)
        g_a = g_a.model_copy(
            update={
                "nodes": [
                    g_a.nodes[0].model_copy(
                        update={
                            "data": g_a.nodes[0].question_data.model_copy(
                                update={"text": "Agent A?"}
                            )
                        }
                    ),
                    *g_a.nodes[1:],
                ]
            }
        )
        g_b = g_b.model_copy(
            update={
                "nodes": [
                    g_b.nodes[0].model_copy(
                        update={
                            "data": g_b.nodes[0].question_data.model_copy(
                                update={"text": "Agent B?"}
                            )
                        }
                    ),
                    *g_b.nodes[1:],
                ]
            }
        )

        import asyncio

        async def _run(graph_obj: DTGraph) -> dict | str:
            async with test_session_factory() as session:
                return await update_draft_from_graph(
                    session,
                    user=user,
                    decision_tree_id=tree_id,
                    graph=graph_obj,
                    expected_graph_hash=live_hash,
                    base_url="http://test",
                )

        results = await asyncio.gather(_run(g_a), _run(g_b))
        successes = [r for r in results if isinstance(r, dict)]
        conflicts = [
            r
            for r in results
            if isinstance(r, str) and json.loads(r)["error"]["code"] == "graph_conflict"
        ]
        assert len(successes) == 1, results
        assert len(conflicts) == 1, results

        async with test_session_factory() as session:
            from sqlalchemy import select

            row = (
                await session.execute(select(DecisionTree).where(DecisionTree.id == tree_id))
            ).scalar_one()
            saved_text = row.graph_data["nodes"][0]["data"]["text"]
            assert saved_text in {"Agent A?", "Agent B?"}
            assert (
                canonical_graph_hash(DTGraph.model_validate(row.graph_data))
                == successes[0]["graph_hash"]
            )

    @pytest.mark.asyncio
    async def test_update_invalidates_graph_cache(
        self, monkeypatch: pytest.MonkeyPatch, test_session_factory
    ) -> None:
        reset_mcp_runtime_for_tests()
        user, tree_id, live_hash, graph = await _seed_user_and_draft(test_session_factory)
        revised = json.loads(json.dumps(graph))
        revised["nodes"][0]["data"]["help_text"] = "cache bust"

        invalidate = AsyncMock()
        monkeypatch.setattr(
            "smeme.mcp.authoring_graph.invalidate_graph_cache",
            invalidate,
        )
        monkeypatch.setattr(
            "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr("smeme.core.config.settings.mcp_authoring_graph_tools_enabled", True)
        monkeypatch.setattr("smeme.mcp.reasoning_fastmcp.AsyncSessionLocal", test_session_factory)

        from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

        fm = get_or_create_fastmcp()
        tool_fn = fm._tool_manager._tools["smeme_authoring_update_draft"].fn
        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            raw = await tool_fn(
                str(tree_id),
                json.dumps(revised),
                live_hash,
                MagicMock(),
                title=None,
            )
        assert "error" not in json.loads(raw)
        invalidate.assert_awaited_once_with(tree_id)
