"""Focused tests for agentic generation route helpers."""

from uuid import uuid4

from starlette.requests import Request

from smeme.core.templates import templates
from smeme.decision_tree.generation.agentic.routes.utility import _redirect_to_editor_response


def _request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/decision-trees/agentic/generations/test",
            "headers": headers or [],
        }
    )


def test_editor_redirect_uses_http_redirect_for_normal_navigation():
    decision_tree_id = uuid4()

    response = _redirect_to_editor_response(_request(), str(decision_tree_id))

    assert response.status_code == 303
    assert response.headers["location"] == f"/decision-trees/{decision_tree_id}/editor"


def test_editor_redirect_uses_hx_redirect_for_htmx_navigation():
    decision_tree_id = uuid4()

    response = _redirect_to_editor_response(
        _request([(b"hx-request", b"true")]),
        str(decision_tree_id),
    )

    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == f"/decision-trees/{decision_tree_id}/editor"


def test_build_retry_uses_htmx_instead_of_replacing_document_body():
    html = templates.env.get_template("decision_tree/generation/_build_error.html").render(
        {
            "thread_id": "thread-1",
            "build_source": "llm_failed",
            "validation_errors": [],
            "current_phase": "build",
        }
    )

    assert 'hx-post="/decision-trees/agentic/retry-build"' in html
    assert 'hx-target="closest .main-panel-content"' in html
    assert "document.body.innerHTML" not in html
