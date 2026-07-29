"""Jinja2 templates configuration with custom filters."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from starlette.requests import Request
from starlette.templating import Jinja2Templates as StarletteJinja2Templates

from smeme.core.theme import theme_context_processor
from smeme.docs.context import docs_context_processor


def natural_sort_key(s: str) -> list[int | str]:
    """
    Generate a sort key for natural sorting (human-friendly ordering).

    Examples:
        "q1" < "q2" < "q10" < "q20"
        "item1" < "item2" < "item10"

    This splits strings into numeric and non-numeric parts and sorts
    numbers as integers rather than strings.
    """
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", str(s))]


def natsort(items: list[Any], attribute: str | None = None, reverse: bool = False) -> list[Any]:
    """
    Jinja2 filter for natural sorting.

    Usage in templates:
        {{ items|natsort }}
        {{ items|natsort(attribute='id') }}
        {{ items|natsort(attribute='name', reverse=True) }}
    """
    if attribute:
        return sorted(
            items,
            key=lambda x: natural_sort_key(getattr(x, attribute, "")),
            reverse=reverse,
        )
    return sorted(items, key=lambda x: natural_sort_key(str(x)), reverse=reverse)


class Jinja2Templates(StarletteJinja2Templates):
    """Starlette 1.x templates with legacy ``TemplateResponse(name, context)`` support.

    Starlette >=1 requires ``TemplateResponse(request, name, context)``. Most SMEme
    call sites still use the pre-1.0 ``(name, context)`` form where ``request`` lives
    in the context dict. Accept both during the H-04 FastAPI/Starlette upgrade.
    """

    def TemplateResponse(self, *args: Any, **kwargs: Any):  # noqa: N802 - Starlette API name
        if args and isinstance(args[0], Request):
            return super().TemplateResponse(*args, **kwargs)

        if not args or not isinstance(args[0], str):
            return super().TemplateResponse(*args, **kwargs)

        name = args[0]
        status_code = kwargs.pop("status_code", 200)
        headers = kwargs.pop("headers", None)
        media_type = kwargs.pop("media_type", None)
        background = kwargs.pop("background", None)

        if len(args) >= 2 and isinstance(args[1], Mapping):
            context = dict(args[1])
            if len(args) >= 3 and isinstance(args[2], int):
                status_code = args[2]
        else:
            context = dict(kwargs.pop("context", None) or {})

        if kwargs:
            leftover = ", ".join(sorted(kwargs))
            msg = f"Unexpected TemplateResponse kwargs: {leftover}"
            raise TypeError(msg)

        request = context.get("request")
        if not isinstance(request, Request):
            msg = (
                "Legacy TemplateResponse(name, context) requires context['request'] "
                "to be a Starlette Request"
            )
            raise TypeError(msg)

        return super().TemplateResponse(
            request,
            name,
            context,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
        )


# Create shared templates instance with custom filters
templates = Jinja2Templates(
    directory="smeme/templates",
    context_processors=[theme_context_processor, docs_context_processor],
)

# Register custom filters
templates.env.filters["natsort"] = natsort


class CreatorUiTemplateFlags:
    """Jinja namespace: reads current ``settings`` so tests can monkeypatch flags."""

    @property
    def ai_generation_enabled(self) -> bool:
        from smeme.core.config import settings

        return settings.smeme_ai_generation_enabled

    @property
    def mcp_authoring_available(self) -> bool:
        from smeme.core.config import settings

        return settings.mcp_enabled and settings.mcp_authoring_graph_tools_enabled

    @property
    def show_decision_tree_generation_region_selector(self) -> bool:
        from smeme.core.config import settings

        return settings.show_decision_tree_generation_region_selector


class BrandTemplateAssets:
    """Jinja namespace: brand static assets (logo paths)."""

    @property
    def dark_logo_src(self) -> str:
        from smeme.core.theme import dark_logo_src

        return dark_logo_src()


class AnalyticsTemplateFlags:
    """Jinja namespace: privacy-respecting analytics config (reads current ``settings``)."""

    @property
    def plausible_domain(self) -> str | None:
        from smeme.core.config import settings

        return settings.plausible_domain

    @property
    def plausible_script_url(self) -> str:
        from smeme.core.config import settings

        return settings.plausible_script_url

    @property
    def plausible_uses_custom_script(self) -> bool:
        """True when ``PLAUSIBLE_SCRIPT_URL`` is a site-specific ``pa-*.js`` loader."""
        return "/pa-" in self.plausible_script_url

    @property
    def enabled(self) -> bool:
        """Emit analytics when domain is set or a site-specific Plausible loader URL is configured."""
        return bool(self.plausible_domain) or self.plausible_uses_custom_script


templates.env.globals["creator_ui"] = CreatorUiTemplateFlags()
templates.env.globals["brand"] = BrandTemplateAssets()
templates.env.globals["analytics"] = AnalyticsTemplateFlags()
