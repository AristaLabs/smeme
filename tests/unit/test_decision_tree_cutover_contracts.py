"""Schema / contract regression tests for the D024 DecisionTree hard cutover."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from smeme.app_factory import create_core_app
from smeme.core.models import (
    BaseSQLModel,
    DecisionTree,
    DecisionTreeLexiconDraft,
    DecisionTreeResearchCorpus,
    DecisionTreeSession,
)
from smeme.decision_tree.helpers.export import EXPORT_VERSION, build_decision_tree_export
from smeme.decision_tree.models import DTGraph
from smeme.mcp.authoring_graph import extract_graph_dict, parse_authoring_graph_json
from smeme.mcp.design_guidance_artifact import DESIGN_GUIDANCE_CONTENT_VERSION
from smeme.mcp.guidance_artifact import GUIDANCE_CONTENT_VERSION
from smeme.mcp.reasoning_fastmcp import REASONING_CAPABILITIES_VERSION
from smeme.mcp.tool_contract import REASONING_TOOL_ERROR_CODES

ROOT = Path(__file__).resolve().parents[2]
LEGACY = "q" + "nr"

_MIN_GRAPH = {
    "nodes": [
        {
            "id": "q1",
            "type": "question",
            "data": {
                "text": "Ready?",
                "type": "radio",
                "options": ["Yes", "No"],
                "required": True,
            },
        },
        {
            "id": "c1",
            "type": "conclusion",
            "data": {"title": "Done", "summary": "ok"},
        },
        {
            "id": "c2",
            "type": "conclusion",
            "data": {"title": "Other", "summary": "other"},
        },
    ],
    "edges": [
        {"source": "q1", "target": "c1", "condition": "Yes"},
        {"source": "q1", "target": "c2", "condition": "No"},
    ],
    "metadata": {"title": "Cutover contract"},
}


def test_orm_table_names_are_decision_tree() -> None:
    assert DecisionTree.__tablename__ == "decision_trees"
    assert DecisionTreeSession.__tablename__ == "decision_tree_sessions"
    assert DecisionTreeResearchCorpus.__tablename__ == "decision_tree_research_corpora"
    assert DecisionTreeLexiconDraft.__tablename__ == "decision_tree_lexicon_drafts"


def test_decision_tree_fk_columns_use_decision_tree_id() -> None:
    cols = {c.name for c in DecisionTree.__table__.columns}
    assert "parent_decision_tree_id" in cols
    assert f"{LEGACY}_id" not in cols
    assert f"parent_{LEGACY}_id" not in cols

    session_cols = {c.name for c in DecisionTreeSession.__table__.columns}
    assert "decision_tree_id" in session_cols
    assert f"{LEGACY}_id" not in session_cols


def test_all_schema_object_names_exclude_legacy_namespace() -> None:
    names: list[str] = []
    for table in BaseSQLModel.metadata.tables.values():
        names.append(table.name)
        names.extend(column.name for column in table.columns)
        names.extend(
            constraint.name for constraint in table.constraints if constraint.name is not None
        )
        names.extend(index.name for index in table.indexes if index.name is not None)
    assert not [name for name in names if LEGACY in name.lower()]


def test_openapi_exposes_only_decision_tree_routes() -> None:
    paths = set(create_core_app().openapi()["paths"])
    assert "/decision-trees/dashboard" in paths
    assert any(path.startswith("/decision-trees/editor") for path in paths)
    assert not [path for path in paths if f"/{LEGACY}" in path.lower()]


def test_export_version_is_v2_with_decision_tree_envelope() -> None:
    assert EXPORT_VERSION == "2"
    decision_tree = SimpleNamespace(
        id=uuid4(),
        title="Export contract",
        version_number=1,
        created_at=None,
        updated_at=None,
        graph_data=_MIN_GRAPH,
    )
    payload = build_decision_tree_export(decision_tree)  # type: ignore[arg-type]
    assert payload["smeme_export_version"] == "2"
    assert "decision_tree" in payload
    assert LEGACY not in payload
    assert payload["decision_tree"]["graph"]["nodes"]


def test_authoring_accepts_v2_and_raw_rejects_v1_and_legacy_envelopes() -> None:
    raw = json.dumps(_MIN_GRAPH)
    assert isinstance(parse_authoring_graph_json(raw), DTGraph)

    v2 = json.dumps(
        {
            "smeme_export_version": "2",
            "decision_tree": {"graph": _MIN_GRAPH},
        }
    )
    assert isinstance(parse_authoring_graph_json(v2), DTGraph)

    v1_with_current_key = json.dumps(
        {
            "smeme_export_version": "1",
            "decision_tree": {"graph": _MIN_GRAPH},
        }
    )
    err = extract_graph_dict(v1_with_current_key)
    assert isinstance(err, str)
    assert "Only version '2'" in err

    v1_with_legacy_key = json.dumps(
        {
            "smeme_export_version": "1",
            LEGACY: {"graph": _MIN_GRAPH},
        }
    )
    err = extract_graph_dict(v1_with_legacy_key)
    assert isinstance(err, str)
    assert "Only version '2'" in err


def test_mcp_contract_versions_and_error_codes() -> None:
    assert REASONING_CAPABILITIES_VERSION == "3.3.0"
    assert GUIDANCE_CONTENT_VERSION == "2.2.0"
    assert DESIGN_GUIDANCE_CONTENT_VERSION == "2.4.0"
    assert "invalid_decision_tree_id" in REASONING_TOOL_ERROR_CODES
    assert f"invalid_{LEGACY}_id" not in REASONING_TOOL_ERROR_CODES


def test_alembic_baseline_has_no_legacy_identifiers() -> None:
    versions = ROOT / "alembic" / "versions"
    files = [p for p in versions.glob("*.py") if p.name != "__init__.py"]
    assert files, "expected Core Alembic baseline"
    for path in files:
        assert LEGACY not in path.name.lower()
        text = path.read_text(encoding="utf-8")
        assert LEGACY not in text.lower()
