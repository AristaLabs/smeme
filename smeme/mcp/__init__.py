"""Remote MCP (Streamable HTTP) and OAuth discovery stubs (DR-3)."""

from __future__ import annotations

from typing import Any

__all__ = ["mcp_lifespan", "mount_mcp_on_app"]


def __getattr__(name: str) -> Any:
    if name == "mcp_lifespan":
        from smeme.mcp.reasoning_fastmcp import mcp_lifespan

        return mcp_lifespan
    if name == "mount_mcp_on_app":
        from smeme.mcp.reasoning_fastmcp import mount_mcp_on_app

        return mount_mcp_on_app
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
