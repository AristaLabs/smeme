"""effective_base_url: custom domain BASE_URL vs Render RENDER_EXTERNAL_URL."""

from __future__ import annotations

from smeme.core.config import settings as process_settings


def test_base_url_wins_over_render_external_for_custom_domain() -> None:
    s = process_settings.model_copy(
        update={
            "base_url": "https://core.example.com",
            "render_external_url": "https://platform-host.example",
        }
    )
    assert s.effective_base_url == "https://core.example.com"


def test_render_external_used_when_base_url_is_default_localhost() -> None:
    s = process_settings.model_copy(
        update={
            "base_url": "http://localhost:8000",
            "render_external_url": "https://platform-host.example",
        }
    )
    assert s.effective_base_url == "https://platform-host.example"


def test_base_url_used_when_no_render_external() -> None:
    s = process_settings.model_copy(
        update={
            "base_url": "https://api.example.com",
            "render_external_url": None,
        }
    )
    assert s.effective_base_url == "https://api.example.com"
