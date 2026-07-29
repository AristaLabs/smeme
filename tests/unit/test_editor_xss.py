"""Regression coverage for editor HTML and JavaScript-context XSS (M-05)."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from smeme.core.templates import templates
from smeme.decision_tree.models import DTGraph, GraphEdge, GraphNode
from smeme.decision_tree.viewer.models import GraphVisualization, NodePosition, VisualNode
from smeme.mcp.authoring_graph import parse_authoring_graph_json

SCRIPT_BREAKOUT = "</script><script>alert('m05')</script>"
EVENT_HANDLER = '<img src=x onerror="alert(1)"><svg onload="alert(2)">'


def _graph_payload(node_id: str = "Question-1", conclusion_id: str = "conclusion_final_2") -> dict:
    return {
        "nodes": [
            {
                "id": node_id,
                "type": "question",
                "data": {
                    "text": EVENT_HANDLER,
                    "type": "radio",
                    "options": ["Yes", "No"],
                    "required": True,
                },
            },
            {
                "id": conclusion_id,
                "type": "conclusion",
                "data": {
                    "title": SCRIPT_BREAKOUT,
                    "summary": EVENT_HANDLER,
                    "recommendations": [],
                    "severity": "info",
                },
            },
        ],
        "edges": [{"source": node_id, "target": conclusion_id, "condition": "Yes"}],
        "metadata": {"title": SCRIPT_BREAKOUT},
    }


@pytest.mark.parametrize(
    "node_id",
    [
        "q1",
        "Q_1",
        "question-one",
        "question_one-2",
        "conclusion_final_2",
        "q_0123456789abcdef",
    ],
)
def test_legitimate_existing_node_id_formats_are_retained(node_id: str):
    node = GraphNode.model_validate(
        {
            "id": node_id,
            "type": "question",
            "data": {"text": "Safe?", "type": "radio", "options": ["Yes"]},
        }
    )
    assert node.id == node_id


@pytest.mark.parametrize(
    "node_id",
    [
        "",
        "1question",
        "question id",
        "q'quote",
        'q"quote',
        "q`tick",
        r"q\slash",
        "<img src=x onerror=alert(1)>",
        SCRIPT_BREAKOUT,
    ],
)
def test_node_ids_reject_html_and_javascript_delimiters(node_id: str):
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        GraphNode.model_validate(
            {
                "id": node_id,
                "type": "question",
                "data": {"text": "Safe?", "type": "radio", "options": ["Yes"]},
            }
        )


def test_edge_node_references_use_the_same_identifier_grammar():
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        GraphEdge(source="q1", target=SCRIPT_BREAKOUT, condition="Yes")


def test_imported_export_rejects_malicious_node_ids():
    payload = {
        "smeme_export_version": "2",
        "decision_tree": {"graph": _graph_payload(node_id=SCRIPT_BREAKOUT)},
    }
    result = parse_authoring_graph_json(json.dumps(payload))

    assert isinstance(result, str)
    error = json.loads(result)
    assert error["error"]["code"] == "invalid_graph"
    assert any("nodes.0.id" in item for item in error["error"]["errors"])


def test_retained_export_with_documented_node_ids_still_imports():
    payload = {
        "smeme_export_version": "2",
        "decision_tree": {"graph": _graph_payload()},
    }
    result = parse_authoring_graph_json(json.dumps(payload))

    assert isinstance(result, DTGraph)
    assert result.node_ids == {"Question-1", "conclusion_final_2"}


def test_ai_generated_graph_rejects_malicious_node_ids_at_schema_boundary():
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        DTGraph.model_validate(_graph_payload(node_id=EVENT_HANDLER))


@pytest.mark.parametrize("payload", [EVENT_HANDLER, SCRIPT_BREAKOUT, '"quoted" & <b>html</b>'])
def test_title_htmx_fragments_autoescape_stored_titles(payload: str):
    edit_html = templates.env.get_template("decision_tree/_title_edit_form.html").render(
        decision_tree_id=uuid4(),
        title=payload,
    )
    display_html = templates.env.get_template("decision_tree/_title_display.html").render(
        decision_tree_id=uuid4(),
        title=payload,
    )

    for rendered in (edit_html, display_html):
        assert payload not in rendered
        assert "<script>" not in rendered
        assert "<img " not in rendered
        assert "<svg onload=" not in rendered


def test_graph_svg_keeps_untrusted_ids_and_labels_out_of_javascript():
    hostile_id = "q'\"`\\</script><script>alert(1)</script>"
    visualization = GraphVisualization(
        nodes=[
            VisualNode(
                id=hostile_id,
                label=EVENT_HANDLER,
                tooltip=SCRIPT_BREAKOUT,
                position=NodePosition(x=10, y=20, layer=0),
            )
        ],
        edges=[],
        width=300,
        height=200,
    )

    rendered = templates.env.get_template("decision_tree/_graph_svg.html").render(
        visualization=visualization,
        decision_tree_id=uuid4(),
        is_public=False,
    )

    assert "onclick=" not in rendered
    assert "nodeInput.value" not in rendered
    assert "<script>" not in rendered
    assert "<img " not in rendered
    assert "<svg onload=" not in rendered
    assert "data-node-id=" in rendered


def test_edge_forms_autoescape_imported_labels_and_conditions():
    graph = DTGraph.model_validate(_graph_payload())
    hostile_condition = '" onfocus="alert(1)"><script>alert(2)</script>'

    create_html = templates.env.get_template("decision_tree/_create_edge_form.html").render(
        decision_tree_id=uuid4(),
        source_node_id="Question-1",
        graph=graph,
    )
    update_html = templates.env.get_template("decision_tree/_update_edge_form.html").render(
        decision_tree_id=uuid4(),
        source="Question-1",
        target="conclusion_final_2",
        condition=hostile_condition,
        target_node=graph.get_node("conclusion_final_2"),
        graph=graph,
    )

    for rendered in (create_html, update_html):
        assert "<script>" not in rendered
        assert "<img " not in rendered
        assert "<svg onload=" not in rendered
    assert hostile_condition not in update_html
    assert 'onfocus="alert(1)"' not in update_html


def test_edge_item_uses_inert_form_fields_instead_of_dynamic_hx_vals():
    graph = DTGraph.model_validate(_graph_payload())
    edge = graph.edges[0].model_copy(
        update={"condition": '" onmouseover="alert(1)"><script>alert(2)</script>'}
    )
    wrapper = templates.env.from_string(
        "{% for edge in edges %}{% set edge_index = loop.index %}"
        "{% include 'decision_tree/_edge_item.html' with context %}{% endfor %}"
    )
    rendered = wrapper.render(
        edges=[edge],
        decision_tree_id=uuid4(),
        is_public=False,
    )

    assert "hx-vals=" not in rendered
    assert "<script>" not in rendered
    assert 'onmouseover="alert(1)"' not in rendered
    assert 'name="condition"' in rendered


def test_editor_error_fragment_autoescapes_event_handler_payloads():
    rendered = templates.env.get_template("decision_tree/_editor_error.html").render(
        message=EVENT_HANDLER
    )
    assert EVENT_HANDLER not in rendered
    assert "<img " not in rendered
    assert "<svg onload=" not in rendered
