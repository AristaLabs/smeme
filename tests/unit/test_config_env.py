"""Settings env parsing edge cases (Render blank vars)."""

from __future__ import annotations

import os
from unittest.mock import patch

from smeme.core.config import Settings


def test_blank_bool_env_var_uses_default():
    """Render sometimes sets feature flags to empty string instead of omitting them."""
    with patch.dict(os.environ, {"MCP_AUTHORING_GRAPH_TOOLS_ENABLED": ""}, clear=False):
        settings = Settings()
    assert settings.mcp_authoring_graph_tools_enabled is True
