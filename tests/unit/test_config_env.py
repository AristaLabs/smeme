"""Settings env parsing edge cases (Render blank vars)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from smeme.core.config import Settings


def test_blank_bool_env_var_uses_default():
    """Render sometimes sets feature flags to empty string instead of omitting them."""
    with patch.dict(os.environ, {"MCP_AUTHORING_GRAPH_TOOLS_ENABLED": ""}, clear=False):
        settings = Settings()
    assert settings.mcp_authoring_graph_tools_enabled is True


def test_inquire_support_budget_env_override_and_hard_ceiling():
    with patch.dict(
        os.environ,
        {
            "SMEME_INQUIRE_RESOLVING_SUPPORT_MAX_SAT_CALLS": "4321",
            "SMEME_INQUIRE_RESOLVING_SUPPORT_TIMEOUT_MS": "6789",
        },
        clear=False,
    ):
        settings = Settings()
    assert settings.inquire_resolving_support_max_sat_calls == 4321
    assert settings.inquire_resolving_support_timeout_ms == 6789

    with (
        patch.dict(
            os.environ,
            {"SMEME_INQUIRE_RESOLVING_SUPPORT_MAX_SAT_CALLS": "10001"},
            clear=False,
        ),
        pytest.raises(ValidationError),
    ):
        Settings()
