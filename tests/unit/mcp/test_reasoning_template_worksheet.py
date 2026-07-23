"""Unit tests for reasoning worksheet manifest + MCP template tool helpers."""

from __future__ import annotations

import json
import re
from uuid import UUID

import pytest

from smeme.decision_tree.models import (
    ConclusionData,
    DTGraph,
    DTGraphMetadata,
    GraphEdge,
    GraphNode,
    QuestionData,
)
from smeme.mcp.reasoning_template_worksheet import (
    REASONING_TEMPLATE_SUCCESS_MAX_UTF8_BYTES,
    build_manifest_core,
    manifest_core_digest,
    normalize_manifest_text,
    render_manifest_markdown,
    safe_worksheet_slug,
    worksheet_payload_too_large,
)


def _golden_radio_graph() -> DTGraph:
    return DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(text="Pick", type="radio", options=["Yes", "No"], required=True),
            ),
            GraphNode(id="c1", type="conclusion", data=ConclusionData(title="Out A", summary="a")),
            GraphNode(id="c2", type="conclusion", data=ConclusionData(title="Out B", summary="b")),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="c2", condition="No"),
        ],
        metadata=DTGraphMetadata(title="IR unit test"),
    )


_GOLDEN_DECISION_TREE_ID = UUID("00000000-0000-4000-8000-000000000001")
_GOLDEN_DIGEST = "5dd33e91672b9330759953694e853a154bd9279cbfc1bfef21daca2082e58e5e"


def test_manifest_core_digest_golden_matches_fixture() -> None:
    g = _golden_radio_graph()
    m = build_manifest_core(g, _GOLDEN_DECISION_TREE_ID)
    assert manifest_core_digest(m) == _GOLDEN_DIGEST


def test_manifest_core_digest_changes_when_label_changes() -> None:
    g = _golden_radio_graph()
    m1 = build_manifest_core(g, _GOLDEN_DECISION_TREE_ID)
    # Mutate question text on a copy via model_validate — rebuild graph with different label
    nodes = list(g.nodes)
    q1 = nodes[0]
    assert q1.question_data is not None
    qd = q1.question_data.model_copy(update={"text": "Pick differently"})
    nodes[0] = GraphNode(id=q1.id, type=q1.type, data=qd)
    g2 = DTGraph(nodes=nodes, edges=g.edges, metadata=g.metadata)
    m2 = build_manifest_core(g2, _GOLDEN_DECISION_TREE_ID)
    assert manifest_core_digest(m1) != manifest_core_digest(m2)


def test_options_sorted_lexicographically_in_manifest() -> None:
    g = DTGraph(
        nodes=[
            GraphNode(
                id="z",
                type="question",
                data=QuestionData(
                    text="x",
                    type="radio",
                    options=["b", "a"],
                    required=True,
                ),
            ),
            GraphNode(id="c1", type="conclusion", data=ConclusionData(title="A", summary="s")),
            GraphNode(id="c2", type="conclusion", data=ConclusionData(title="B", summary="t")),
        ],
        edges=[
            GraphEdge(source="z", target="c1", condition="a"),
            GraphEdge(source="z", target="c2", condition="b"),
        ],
        metadata=DTGraphMetadata(title="t"),
    )
    m = build_manifest_core(g, _GOLDEN_DECISION_TREE_ID)
    opts = m["questions"][0]["options"]
    assert opts == ["a", "b"]


def test_nfc_question_label_normalization_stable_digest() -> None:
    """NFC vs NFD for the same logical question label — manifest normalizes; digest matches."""
    g1 = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="caf\u00e9",
                    type="radio",
                    options=["Yes", "No"],
                    required=True,
                ),
            ),
            GraphNode(id="c1", type="conclusion", data=ConclusionData(title="A", summary="s")),
            GraphNode(id="c2", type="conclusion", data=ConclusionData(title="B", summary="t")),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="c2", condition="No"),
        ],
        metadata=DTGraphMetadata(title="t"),
    )
    # NFD for é in question label
    g2 = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="cafe\u0301",
                    type="radio",
                    options=["Yes", "No"],
                    required=True,
                ),
            ),
            GraphNode(id="c1", type="conclusion", data=ConclusionData(title="A", summary="s")),
            GraphNode(id="c2", type="conclusion", data=ConclusionData(title="B", summary="t")),
        ],
        edges=g1.edges,
        metadata=DTGraphMetadata(title="t"),
    )
    d1 = manifest_core_digest(build_manifest_core(g1, _GOLDEN_DECISION_TREE_ID))
    d2 = manifest_core_digest(build_manifest_core(g2, _GOLDEN_DECISION_TREE_ID))
    assert normalize_manifest_text("cafe\u0301") == normalize_manifest_text("caf\u00e9")
    assert d1 == d2


def test_markdown_blind_audit_no_topology_leaks() -> None:
    g = _golden_radio_graph()
    mc = build_manifest_core(g, _GOLDEN_DECISION_TREE_ID)
    md = render_manifest_markdown(
        manifest_core=mc,
        title="T",
        decision_tree_id=_GOLDEN_DECISION_TREE_ID,
        slug="t",
    )
    assert "q1" in md
    assert "Yes" in md
    assert "No" in md
    assert re.search(r"\bedge\s*:", md, re.I) is None
    assert "c1" not in md
    assert "c2" not in md
    assert "manifest_core_digest" not in md
    assert "ir_format_version" not in md
    assert "compiler_version" not in md
    assert "reasoning_capabilities_version" not in md
    assert "## Publish / evaluate alignment" not in md
    assert "## Evidence schema" not in md
    assert '"schema_version"' not in md
    assert "Checkbox" not in md
    assert "OPERATOR_HINTS" not in md


def test_worksheet_payload_too_large_detects_oversize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "smeme.mcp.reasoning_template_worksheet.REASONING_TEMPLATE_SUCCESS_MAX_UTF8_BYTES",
        500,
    )
    tiny = {"manifest_markdown": "x" * 600}
    assert worksheet_payload_too_large(manifest_markdown="x" * 600, success_payload=tiny) is True
    ok = {"manifest_markdown": "hi", "manifest_core_digest": "a" * 64, "in_sync": True}
    assert worksheet_payload_too_large(manifest_markdown="hi", success_payload=ok) is False


def test_constant_default_cap_is_512kib() -> None:
    assert REASONING_TEMPLATE_SUCCESS_MAX_UTF8_BYTES == 512 * 1024


def test_safe_worksheet_slug() -> None:
    assert safe_worksheet_slug("Hello World!") == "hello-world"
    assert safe_worksheet_slug("   ") == "decision_tree"


def test_radio_question_has_options_in_manifest() -> None:
    g = DTGraph(
        nodes=[
            GraphNode(
                id="t1",
                type="question",
                data=QuestionData(
                    text="Explain", type="radio", options=["ok", "no"], required=True
                ),
            ),
            GraphNode(id="c1", type="conclusion", data=ConclusionData(title="A", summary="s")),
            GraphNode(id="c2", type="conclusion", data=ConclusionData(title="B", summary="t")),
        ],
        edges=[
            GraphEdge(source="t1", target="c1", condition="ok"),
            GraphEdge(source="t1", target="c2", condition="no"),
        ],
        metadata=DTGraphMetadata(title="t"),
    )
    m = build_manifest_core(g, _GOLDEN_DECISION_TREE_ID)
    q = m["questions"][0]
    assert q["answer_kind"] == "radio"
    assert q["options"] == ["no", "ok"]
    assert "free_text_hint_id" not in q


def test_manifest_json_canonical_sort_keys_stable() -> None:
    g = _golden_radio_graph()
    m = build_manifest_core(g, _GOLDEN_DECISION_TREE_ID)
    a = json.dumps(m, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    b = json.dumps(m, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert a == b
