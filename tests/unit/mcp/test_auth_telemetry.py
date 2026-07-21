"""MCP inbound auth telemetry helpers (smeme/mcp/auth_telemetry.py)."""

from __future__ import annotations

from smeme.mcp.auth_telemetry import (
    api_key_shape,
    authorization_shape,
    inbound_http_telemetry_dict,
)


def test_authorization_shape_none():
    d = authorization_shape(authorization_value=None)
    assert d["has_authorization_header"] is False
    assert d["authorization_scheme"] == "none"
    assert d["bearer_token_length"] == 0


def test_authorization_shape_bearer():
    d = authorization_shape(authorization_value="Bearer abc.def.ghi")
    assert d["has_authorization_header"] is True
    assert d["authorization_scheme"] == "bearer"
    assert d["bearer_token_length"] == len("abc.def.ghi")


def test_authorization_shape_other_scheme():
    d = authorization_shape(authorization_value="Basic xxxx")
    assert d["authorization_scheme"] == "other"
    assert d["bearer_token_length"] == 0


def test_api_key_shape():
    assert api_key_shape(x_api_key_value=None)["api_key_header_length"] == 0
    assert api_key_shape(x_api_key_value="  secret  ") == {
        "has_api_key_header": True,
        "api_key_header_length": 6,
    }


def test_inbound_http_telemetry_dict_starlette_request():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/v1/mcp/",
        "raw_path": b"/api/v1/mcp/",
        "root_path": "",
        "scheme": "https",
        "query_string": b"",
        "headers": [
            (b"authorization", b"Bearer tok"),
            (b"x-api-key", b"keyval"),
            (b"user-agent", b"TestAgent/1"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 443),
    }
    req = Request(scope)
    d = inbound_http_telemetry_dict(req)
    assert d["stage"] == "inbound_http"
    assert d["method"] == "POST"
    assert d["path"] == "/api/v1/mcp/"
    assert d["authorization_scheme"] == "bearer"
    assert d["bearer_token_length"] == 3
    assert d["has_api_key_header"] is True
    assert d["api_key_header_length"] == 6
    assert d["user_agent_length"] == len("TestAgent/1")
