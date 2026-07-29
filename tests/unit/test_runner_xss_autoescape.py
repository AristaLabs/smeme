"""Regression tests for stored XSS in the decision-tree runner (H-02)."""

from __future__ import annotations

from uuid import uuid4

from smeme.decision_tree.models import ConclusionData, QuestionData
from smeme.decision_tree.workflow import _html_error, jinja_env

XSS_PAYLOAD = '<img src=x onerror="alert(1)"><script>alert(1)</script>'


def test_runner_jinja_env_autoescapes_html():
    assert jinja_env.autoescape is True


def test_question_template_escapes_malicious_node_fields():
    q = QuestionData(
        text=XSS_PAYLOAD,
        type="radio",
        options=[XSS_PAYLOAD, "Safe option"],
        required=True,
        help_text=XSS_PAYLOAD,
    )
    html_out = jinja_env.get_template("decision_tree/_question.html").render(
        q=q,
        question_node_id="q1",
        session_id=str(uuid4()),
        previous_answer="",
        can_go_previous=False,
        is_last_question=False,
        can_skip=False,
        navigation_warning=XSS_PAYLOAD,
    )

    assert XSS_PAYLOAD not in html_out
    assert "<script>alert(1)</script>" not in html_out
    assert '<img src=x onerror="alert(1)">' not in html_out
    assert "&lt;script&gt;" in html_out
    assert "Safe option" in html_out


def test_conclusion_template_escapes_malicious_node_fields():
    c = ConclusionData(
        title=XSS_PAYLOAD,
        summary=XSS_PAYLOAD,
        recommendations=[XSS_PAYLOAD],
        severity="info",
    )
    html_out = jinja_env.get_template("decision_tree/_conclusion.html").render(
        conclusion=c,
        conclusion_id="c1",
        session_id=str(uuid4()),
        can_go_previous=False,
        navigation_warning=XSS_PAYLOAD,
    )

    assert XSS_PAYLOAD not in html_out
    assert "<script>alert(1)</script>" not in html_out
    assert '<img src=x onerror="alert(1)">' not in html_out
    assert "&lt;script&gt;" in html_out


def test_html_error_escapes_dynamic_message():
    out = _html_error(f"Node {XSS_PAYLOAD} not found")
    assert XSS_PAYLOAD not in out
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out
    assert "Error:" in out
