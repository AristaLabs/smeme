"""Tests for design-system callout rendering."""

from smeme.core.callout_html import render_callout_html


def test_render_callout_html_info_dark_classes():
    html = render_callout_html(
        title="Recommended",
        body="<p>Body text</p>",
        type="info",
        role="note",
    )
    assert "dark:bg-info-950" in html
    assert "dark:text-info-100" in html
    assert "Recommended" in html
    assert 'role="note"' in html


def test_render_callout_html_error_prominent():
    html = render_callout_html(
        body="<p>Limit reached</p>",
        type="error",
        variant="prominent",
    )
    assert "dark:bg-danger-950" in html
    assert "border-2" in html


def test_alert_macro_via_fragment_matches_callout():
    from smeme.core.templates import templates

    out = templates.env.get_template("components/_callout_fragment.html").render(
        body="<p class=\"text-sm font-medium\">Saved</p>",
        type="success",
        title="",
        role="alert",
        variant="default",
        show_icon=True,
        id="",
        extra_class="",
    )
    assert "dark:bg-success-950" in out
    assert "Saved" in out
