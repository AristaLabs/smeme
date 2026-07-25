"""Unit tests for MCP authoring graph validate + create_draft tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from smeme.core.models import User
from smeme.decision_tree.helpers.validation import validate_graph_for_editing
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
                    options=["Yes", "No"],
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
        result = validate_graph_for_editing(graph)
        body = validation_payload(graph, result)
        assert body["draft_ready"] is True
        assert body["deploy_ready"] is False
        assert body["is_valid"] is True


class TestAuthoringGraphCapabilities:
    def test_tools_absent_by_default(self) -> None:
        doc = reasoning_capabilities_document()
        tools = doc["reasoning"]["tools"]
        assert "smeme_authoring_validate_graph" not in tools
        assert "smeme_authoring_create_draft" not in tools
        assert "smeme_authoring_design_guidance" not in tools
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
        assert doc["authoring_graph"]["validate"] == "smeme_authoring_validate_graph"
        assert doc["authoring_graph"]["design_guidance"] == "smeme_authoring_design_guidance"
        assert "schema" in doc["authoring_graph"]
        assert doc["authoring_graph"]["schema"]["required"] == ["nodes", "edges", "metadata"]
        node_items = doc["authoring_graph"]["schema"]["properties"]["nodes"]["items"]
        assert "oneOf" in node_items
        titles = {variant.get("title") for variant in node_items["oneOf"]}
        assert titles == {"QuestionNode", "ConclusionNode"}
        assert "authoring_design" in doc


class TestAuthoringGraphQuota:
    def test_quota_weights(self) -> None:
        assert quota_weight_for_tool("smeme_authoring_design_guidance") == 0.0
        assert quota_weight_for_tool("smeme_authoring_validate_graph") == 0.0
        assert quota_weight_for_tool("smeme_authoring_create_draft") == 0.0

    def test_internal_cost(self) -> None:
        assert internal_cost_units_for_tool("smeme_authoring_design_guidance") == 0.0
        assert internal_cost_units_for_tool("smeme_authoring_validate_graph") == 0.0
        assert internal_cost_units_for_tool("smeme_authoring_create_draft") == 0.1


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
