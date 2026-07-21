"""Render design-system callouts from Python (HTMX fragments, error handlers)."""

from __future__ import annotations

from smeme.core.templates import templates

CalloutType = str  # info | success | warning | error
CalloutVariant = str  # default | prominent | compact | accent-left


def render_callout_html(
    *,
    body: str,
    type: CalloutType = "info",
    title: str = "",
    role: str = "alert",
    variant: CalloutVariant = "default",
    show_icon: bool = True,
    id: str = "",
    extra_class: str = "",
) -> str:
    """Return an HTML callout fragment using the shared Jinja macro."""
    template = templates.env.get_template("components/_callout_fragment.html")
    return template.render(
        body=body,
        type=type,
        title=title,
        role=role,
        variant=variant,
        show_icon=show_icon,
        id=id,
        extra_class=extra_class,
    )
