"""Question evidence_sources: storage, hash stability, editor save, validation, worksheet."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from smeme.decision_tree.editor.operations import update_node
from smeme.decision_tree.helpers.validation import validate_graph_for_editing
from smeme.decision_tree.models import (
    AuthorityReference,
    ConclusionData,
    DTGraph,
    DTGraphMetadata,
    EvidenceSource,
    GraphEdge,
    GraphNode,
    QuestionData,
)
from smeme.mcp.authoring_graph import _QUESTION_DATA_SCHEMA
from smeme.mcp.reasoning_template_worksheet import build_manifest_core, render_manifest_markdown
from smeme.reasoning.graph_hash import canonical_graph_hash

_TREE_ID = UUID("00000000-0000-4000-8000-000000000001")


def _graph(**question_kwargs) -> DTGraph:
    return DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Is trailing 12-month spend above $50,000?",
                    type="radio",
                    options=["Yes", "No", "Unsure"],
                    required=True,
                    **question_kwargs,
                ),
            ),
            GraphNode(
                id="c_review",
                type="conclusion",
                data=ConclusionData(title="Full review", summary="Run the full review."),
            ),
            GraphNode(
                id="c_light",
                type="conclusion",
                data=ConclusionData(title="Light touch", summary="Skip the full review."),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="c_review", condition="Yes"),
            GraphEdge(source="q1", target="c_light", condition="No"),
            GraphEdge(source="q1", target="c_review", condition="Unsure"),
        ],
        metadata=DTGraphMetadata(title="Vendor review"),
    )


_SOURCES = [
    EvidenceSource(
        kind="mcp_tool",
        ref="erp_invoice_summary",
        note="Sum invoiced amounts over the trailing 12 months; exclude credits.",
    ),
    EvidenceSource(kind="file", ref="Finance/Archive/", avoid=True),
]


def test_empty_evidence_sources_are_omitted_and_hash_is_unchanged() -> None:
    graph = _graph()
    dumped = graph.model_dump(mode="json")
    assert "evidence_sources" not in dumped["nodes"][0]["data"]
    reloaded = DTGraph.model_validate(dumped)
    assert canonical_graph_hash(reloaded) == canonical_graph_hash(graph)


def test_evidence_sources_round_trip_and_change_the_hash() -> None:
    graph = _graph(evidence_sources=_SOURCES)
    data = graph.model_dump(mode="json")["nodes"][0]["data"]
    assert data["evidence_sources"][1] == {
        "kind": "file",
        "ref": "Finance/Archive/",
        "note": None,
        "avoid": True,
    }
    assert DTGraph.model_validate(graph.model_dump(mode="json")) == graph
    assert canonical_graph_hash(graph) != canonical_graph_hash(_graph())


def test_evidence_source_rejects_unknown_kind_and_extra_keys() -> None:
    with pytest.raises(ValidationError):
        EvidenceSource(kind="spreadsheet", ref="x")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        EvidenceSource.model_validate({"kind": "file", "ref": "x", "leads_to": "c1"})
    with pytest.raises(ValidationError):
        EvidenceSource(kind="file", ref="")


def test_authoring_schema_accepts_evidence_sources() -> None:
    schema = _QUESTION_DATA_SCHEMA["properties"]["evidence_sources"]
    item = schema["items"]
    assert set(item["required"]) == {"kind", "ref"}
    assert item["additionalProperties"] is False
    assert set(item["properties"]["kind"]["enum"]) == {
        "mcp_tool",
        "database",
        "file",
        "url",
        "system",
        "person",
        "instruction",
    }


def test_editor_save_keeps_authorities_and_evidence_sources() -> None:
    graph = _graph(
        authorities=[AuthorityReference(citation="Vendor Policy § 4.2")],
        evidence_sources=_SOURCES,
    )
    updated = update_node(
        graph,
        node_id="q1",
        question_text="Is trailing 12-month spend above $50,000?",
        question_type="radio",
        options=["Yes", "No", "Unsure"],
        help_text="Use invoiced amounts, not purchase orders.",
    )
    qdata = next(n for n in updated.nodes if n.id == "q1").question_data
    assert qdata is not None
    assert qdata.help_text == "Use invoiced amounts, not purchase orders."
    assert [a.citation for a in qdata.authorities] == ["Vendor Policy § 4.2"]
    assert qdata.evidence_sources == _SOURCES


def test_validation_warns_when_hints_name_an_outcome() -> None:
    clean = validate_graph_for_editing(
        _graph(help_text="Use invoiced amounts.", evidence_sources=_SOURCES)
    )
    assert not any("names the outcome" in w for w in clean["warnings"])

    leaky = validate_graph_for_editing(
        _graph(
            help_text="If above the threshold this means Full review.",
            evidence_sources=[
                EvidenceSource(kind="instruction", ref="policy", note="Yes leads to light touch")
            ],
        )
    )
    hits = [w for w in leaky["warnings"] if "names the outcome" in w]
    assert any("help_text" in w and "Full review" in w for w in hits)
    assert any("evidence_sources[0].note" in w and "Light touch" in w for w in hits)


def test_worksheet_prints_hints_per_question() -> None:
    graph = _graph(help_text="Use invoiced amounts.", evidence_sources=_SOURCES)
    core = build_manifest_core(graph, _TREE_ID)
    q1 = core["questions"][0]
    assert q1["help_text"] == "Use invoiced amounts."
    assert q1["evidence_sources"][1] == {"kind": "file", "ref": "Finance/Archive/", "avoid": True}
    md = render_manifest_markdown(
        manifest_core=core, title="Vendor review", decision_tree_id=_TREE_ID, slug="vendor-review"
    )
    assert "How to answer: Use invoiced amounts." in md
    assert "Look in (mcp tool): `erp_invoice_summary` — Sum invoiced amounts" in md
    assert "Do not use (file): `Finance/Archive/`" in md


def test_worksheet_without_hints_is_unchanged() -> None:
    core = build_manifest_core(_graph(), _TREE_ID)
    assert "help_text" not in core["questions"][0]
    assert "evidence_sources" not in core["questions"][0]
