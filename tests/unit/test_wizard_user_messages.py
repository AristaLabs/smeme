"""User-facing wizard error copy."""

from jinja2 import TemplateSyntaxError

from smeme.decision_tree.generation.agentic.routes._helpers import wizard_generation_error_recoverable
from smeme.decision_tree.generation.agentic.user_messages import (
    sanitize_wizard_error_for_user,
    wizard_error_page_message,
    wizard_render_error_message,
)


def test_wizard_error_page_openai_recoverable():
    msg = wizard_error_page_message(
        Exception("Error code: 429 insufficient_quota"),
        recoverable=True,
    )
    assert "in-progress workflows" in msg
    assert "api key" not in msg.lower()
    assert "openai" not in msg.lower()


def test_sanitize_strips_exception_blob():
    raw = "Error code: 500 - {'error': {'message': 'internal'}}"
    assert "Error code" not in sanitize_wizard_error_for_user(raw)
    assert sanitize_wizard_error_for_user(raw) == "Something went wrong. Please try again."


def test_wizard_generation_error_recoverable_for_jinja_template_error():
    err = TemplateSyntaxError(
        "Encountered unknown tag 'endif'.",
        lineno=74,
        name="smeme/templates/decision-trees/generation/_main_design_edit.html",
    )
    assert wizard_generation_error_recoverable(err) is True


def test_wizard_render_error_message_includes_resume_link():
    assert "in-progress workflows" in wizard_render_error_message()
