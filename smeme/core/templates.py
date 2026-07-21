"""Jinja2 templates configuration with custom filters."""

import re
from typing import Any

from starlette.templating import Jinja2Templates

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
    def show_qnr_generation_region_selector(self) -> bool:
        from smeme.core.config import settings

        return settings.show_qnr_generation_region_selector


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
