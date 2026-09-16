"""SMEme Apply — no-LLM client against the sample decision tree.

Talks to the **running app** over MCP: OAuth, list, canned ``raw_answers``,
``evaluate_answers``, print a ``report``. Success is a report, not a dashboard
screenshot. The LangGraph interrupt listing is chapter 2.

SaaS is DCR-off: do **not** use bare ``OAuth()``. Pass the public PKCE
``client_id`` (default matches /docs/mcp). FastMCP listens on
``http://localhost:8787/callback`` — that exact URI must be allowed on the
Clerk MCP OAuth application. Bearer, not the browser cookie.

License: source-available / fair-code (SMEme SUL 1.0), not OSS.
Help: https://github.com/AristaLabs/smeme/discussions/30
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

SMEME_MCP_URL = os.environ.get("SMEME_MCP_URL", "https://www.smeme.ai/api/v1/mcp")
# Public PKCE identifier (not a secret). Same value the dashboard / MCP docs use.
SMEME_OAUTH_CLIENT_ID = os.environ.get("SMEME_OAUTH_CLIENT_ID", "NRdsdBvrio0DW9yo")
OAUTH_CALLBACK_PORT = int(os.environ.get("SMEME_OAUTH_CALLBACK_PORT", "8787"))
OAUTH_CALLBACK_HOST = os.environ.get("SMEME_OAUTH_CALLBACK_HOST", "localhost")

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "smeme"
    / "decision_tree"
    / "fixtures"
    / "smeme_sample_v1.json"
)
SAMPLE_FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
SAMPLE_KEY = SAMPLE_FIXTURE["sample_key"]
SAMPLE_TITLE = SAMPLE_FIXTURE["title"]
CANNED_RAW_ANSWERS = SAMPLE_FIXTURE["canned_raw_answers"]

REQUIRED_TOOLS = {
    "smeme_reasoning_list",
    "smeme_reasoning_validate_answers",
    "smeme_reasoning_evaluate_answers",
}


def _oauth() -> Any:
    from fastmcp.client.auth import OAuth

    return OAuth(
        client_id=SMEME_OAUTH_CLIENT_ID,
        callback_port=OAUTH_CALLBACK_PORT,
        callback_host=OAUTH_CALLBACK_HOST,
        additional_client_metadata={"token_endpoint_auth_method": "none"},
    )


def _payload(result: Any) -> Any:
    data = getattr(result, "data", None)
    if data is not None:
        return data
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    content = getattr(result, "content", result)
    if isinstance(content, list):
        content = "".join(
            b.get("text", "") if isinstance(b, dict) else getattr(b, "text", str(b))
            for b in content
        )
    if isinstance(content, dict):
        return content
    try:
        return json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return {"_raw": content}


def _pp(label: str, obj: Any) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(obj, indent=2, default=str)[:8000])


def _pick_tree(trees: list[dict[str, Any]]) -> dict[str, Any] | None:
    for tree in trees:
        if tree.get("sample_key") == SAMPLE_KEY:
            return tree
    return None


def _error(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    return error if isinstance(error, dict) else None


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="OAuth to SMEme MCP, Apply canned answers, print a report."
    )
    parser.parse_args()

    from fastmcp import Client

    print(f"Connecting to {SMEME_MCP_URL}")
    redirect_uri = f"http://{OAUTH_CALLBACK_HOST}:{OAUTH_CALLBACK_PORT}/callback"
    print(f"OAuth redirect_uri={redirect_uri}")
    print("SaaS is DCR-off: public PKCE client id, not bare OAuth().")
    print("If Clerk says redirect_uri mismatch, add that exact URI to the MCP OAuth app.")

    raw_answers_json = json.dumps(CANNED_RAW_ANSWERS)
    async with Client(SMEME_MCP_URL, auth=_oauth()) as client:
        capabilities = _payload(await client.call_tool("smeme_reasoning_capabilities", {}))
        _pp("smeme_reasoning_capabilities", capabilities)
        capability_error = _error(capabilities)
        if capability_error is not None:
            print(
                f"Capabilities failed: {capability_error.get('message', capability_error)}",
                file=sys.stderr,
            )
            return 1
        advertised = set((capabilities.get("reasoning") or {}).get("tools") or [])
        missing = sorted(REQUIRED_TOOLS - advertised)
        if missing:
            print(f"Server does not advertise required tools: {missing}", file=sys.stderr)
            return 1

        listing = _payload(await client.call_tool("smeme_reasoning_list", {}))
        _pp("smeme_reasoning_list", listing)
        listing_error = _error(listing)
        if listing_error is not None:
            print(
                f"List failed: {listing_error.get('message', listing_error)}",
                file=sys.stderr,
            )
            return 1
        trees = listing.get("decision_trees") or []
        chosen = _pick_tree(trees)
        if not chosen or not chosen.get("id"):
            print(
                f"No Listed {SAMPLE_TITLE!r} tree was returned. "
                "Do not apply the canned sample answers to another tree. "
                "Retry list or click Load sample on the dashboard.",
                file=sys.stderr,
            )
            return 1
        tree_id = chosen["id"]
        print(f"\nUsing decision_tree_id={tree_id!r} title={chosen.get('title')!r}")

        validated = _payload(
            await client.call_tool(
                "smeme_reasoning_validate_answers",
                {"decision_tree_id": tree_id, "raw_answers_json": raw_answers_json},
            )
        )
        _pp("smeme_reasoning_validate_answers", validated)
        validation_error = _error(validated)
        if validation_error is not None:
            print(
                f"Answer validation failed: {validation_error.get('message', validation_error)}",
                file=sys.stderr,
            )
            return 1
        if validated.get("harness_next") != "phase_2_ok":
            print(
                "Answers did not pass validation for evaluation: "
                f"harness_next={validated.get('harness_next')!r}",
                file=sys.stderr,
            )
            return 1

        evaluated = _payload(
            await client.call_tool(
                "smeme_reasoning_evaluate_answers",
                {"decision_tree_id": tree_id, "raw_answers_json": raw_answers_json},
            )
        )
        _pp("smeme_reasoning_evaluate_answers", evaluated)
        evaluation_error = _error(evaluated)
        if evaluation_error is not None:
            print(
                f"Evaluation failed: {evaluation_error.get('message', evaluation_error)}",
                file=sys.stderr,
            )
            return 1

    report = evaluated.get("report") if isinstance(evaluated, dict) else None
    if not isinstance(report, dict):
        print("The solver did not return a report.", file=sys.stderr)
        return 1
    kind = report.get("result_kind")
    headline = report.get("headline")
    print(f"\nresult_kind={kind!r}")
    print(f"headline={headline!r}")
    print("the solver returned a report.")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
