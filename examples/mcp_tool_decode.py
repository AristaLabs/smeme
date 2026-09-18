"""FastMCP/LangChain MCP result normalization for standalone examples."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def payload(result: Any, _seen_wrappers: set[int] | None = None) -> Any:
    """Decode FastMCP 4 generated models, wrappers, and legacy content."""
    model_dump = getattr(result, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, dict) and set(dumped) == {"result"}:
            return payload(dumped["result"], _seen_wrappers)
        return dumped

    if not isinstance(result, Mapping):
        plain_result = getattr(result, "result", None)
        if plain_result is not None and not callable(plain_result):
            seen = _seen_wrappers or set()
            wrapper_id = id(result)
            if wrapper_id not in seen:
                return payload(plain_result, seen | {wrapper_id})

    data = getattr(result, "data", None)
    if data is not None:
        model_dump = getattr(data, "model_dump", None)
        if callable(model_dump):
            return model_dump(mode="json")
        if isinstance(data, dict):
            return data
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return {"_raw": data}
        seen = _seen_wrappers or set()
        wrapper_id = id(result)
        if wrapper_id not in seen:
            return payload(data, seen | {wrapper_id})
        return {"_raw": data}

    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    content = getattr(result, "content", result)
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else getattr(block, "text", str(block))
            for block in content
        )
    if isinstance(content, dict):
        return content
    try:
        return json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return {"_raw": content}


def decode_tool_message(message: Any) -> Any:
    """Prefer LangChain's MCP artifact, then use generic FastMCP decoding."""
    artifact = getattr(message, "artifact", None)
    if isinstance(artifact, dict):
        for key in ("structured_content", "structuredContent"):
            if key in artifact:
                value = artifact[key]
                if isinstance(value, dict) and set(value) == {"result"}:
                    return payload(value["result"])
                return payload(value)
        if "data" in artifact:
            return payload(artifact["data"])
    return payload(message)


def error_payload(decoded: Any) -> dict[str, Any] | None:
    if not isinstance(decoded, dict):
        return None
    error = decoded.get("error")
    return error if isinstance(error, dict) else None


def transport_is_error(message: Any) -> bool:
    if getattr(message, "status", None) == "error":
        return True
    artifact = getattr(message, "artifact", None)
    return isinstance(artifact, dict) and bool(
        artifact.get("isError", artifact.get("is_error", False))
    )
