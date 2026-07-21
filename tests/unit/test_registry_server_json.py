"""Validate registry/server.json for MCP Registry publish."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_JSON = REPO_ROOT / "registry" / "server.json"


def test_registry_server_json_exists():
    assert SERVER_JSON.is_file()


def test_registry_server_json_fields():
    import json

    data = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    assert data["name"] == "ai.smeme/reasoning"
    assert data["title"] == "SMEme"
    assert len(data["description"]) <= 100
    assert data["remotes"][0]["url"] == "https://www.smeme.ai/api/v1/mcp"
    assert data["remotes"][0]["type"] == "streamable-http"


def test_validate_server_json_script():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "validate_server_json.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
