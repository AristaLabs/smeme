"""FastMCP + Streamable HTTP, mounted as a Starlette sub-app on FastAPI.

Architecture overview
---------------------
MCP is **not** mixed into the HTMX or DecisionTree routers.  Instead, FastMCP creates a
Starlette sub-application that is mounted at ``settings.mcp_http_path`` (default
``/api/v1/mcp``) via ``app.mount()``.  ASGI routing means requests to that prefix
never reach the FastAPI router — they go directly to the FastMCP session manager.

When ``MCP_ENABLED``, ``smeme.main`` also registers ``McpMountPathNormalizeMiddleware``
(outermost) so an exact bare mount path (no trailing slash) is rewritten to the
slash form **before** routing.  That avoids a Starlette **307** that some remote
clients mishandle (POST replay without ``Accept`` → **406**).  See LESSONS_LEARNED
*MCP mount path: 307…*.

Transport: Streamable HTTP (``stateless_http=True``)
    Each MCP request is an independent HTTP transaction; there is no persistent
    WebSocket or long-lived SSE connection between requests.  This is the
    recommended mode for production deployments and is what Cowork / Anthropic's
    remote MCP connectors expect.

Singleton pattern
    ``get_or_create_fastmcp()`` creates exactly one ``FastMCP`` instance per
    process.  The FastMCP session manager lifecycle is bound to the FastAPI app's
    lifespan (see ``mcp_lifespan()``).  Test helpers call
    ``reset_mcp_runtime_for_tests()`` to tear down the singleton between test cases.

Authentication (DR-3 P2 + transport challenge)
    When ``clerk_oauth_issuer`` is set, FastMCP ``AuthSettings`` +
    ``ClerkMcpTokenVerifier`` wrap Streamable HTTP in the MCP SDK's
    ``RequireAuthMiddleware``: unauthenticated requests get **401** and
    ``WWW-Authenticate`` with ``resource_metadata`` (RFC 9728 bootstrap).

    Tools still call ``get_mcp_user`` to map Clerk ``sub`` → local ``User`` (DB).
    JWT verification is shared via ``decode_clerk_oauth_access_token`` in
    ``smeme/mcp/bearer_auth.py``.

    Without Clerk, MCP may mount without transport auth (legacy / P1-Embedded probe).

Tools
-----
- ``smeme_reasoning_capabilities`` — same Bearer + user-row requirements as other reasoning tools.
- ``smeme_reasoning_list`` — lists the caller's deployed + current + MCP-discoverable decision trees (owner-scoped).
- ``smeme_reasoning_validate_answers`` — Phase 1 ingest gate only (provenance envelope + answer checks); no persistence.
- ``smeme_reasoning_evaluate`` — chat Inquire gather **start** (durable session; blind task).
- ``smeme_reasoning_evaluate_continue`` — chat Inquire gather **continue** (admit; next blind task).
- ``smeme_reasoning_evaluate_answers`` — bulk Apply on a worksheet envelope; returns ``report``.
- ``smeme_reasoning_what_if`` — compare baseline vs override assignments; report-vocabulary delta; optional shared reach assumptions.
- ``smeme_reasoning_how_to_reach`` — bounded answer-edit repair plans for a target conclusion.
- ``smeme_reasoning_decisive_support`` — minimal sufficient evidence: inclusion-minimal answered-question supports that force a target conclusion (fixed ``T`` and ``E``).
- ``smeme_reasoning_edit_affects_path`` — would a hypothetical answer change affect the **current** decision path (path entailment under edit + conclusion side-car).
- ``smeme_reasoning_list_conclusions`` — catalog conclusion ids/titles and structural reachability (no answers required).
- ``smeme_reasoning_template_check`` / ``smeme_reasoning_template_get`` — minimal drift/digest probe vs full worksheet markdown (owner, discoverable, deployed).
- ``smeme_reasoning_guidance_check`` / ``smeme_reasoning_guidance_get`` — platform calling contract version/digest vs full stitched guidance markdown (connector-only bootstrap).
- ``smeme_authoring_design_guidance`` / ``smeme_authoring_validate_graph`` /
  ``smeme_authoring_create_draft`` / ``smeme_authoring_get_draft`` /
  ``smeme_authoring_update_draft`` — (optional) chat-authored design standard +
  graph validate → create or revise a dashboard draft; gated by
  ``Settings.mcp_authoring_graph_tools_enabled``.
- On ``{MCP_HTTP_PATH}/orchestrator`` when ``MCP_INQUIRE_TOOLS_ENABLED``:
  ``smeme_inquire_*`` + ``smeme_inquire_guidance_*`` — explicit Inquire protocol
  for isolated-evaluator orchestrators (not the chat gather path).

DR-3 P2 adds Bearer-authenticated reasoning tools.

Expected failures and ``internal_error`` use ``smeme.mcp.tool_contract``; Cowork
skills document recovery. Server-side LangGraph around MCP is deferred.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette
from starlette.types import ASGIApp, Receive, Scope, Send

from smeme.billing.quota import reserve_mcp_quota
from smeme.core.config import Settings, settings
from smeme.core.database import AsyncSessionLocal
from smeme.core.logging import get_logger
from smeme.core.models import DecisionTree, ReasoningCompiledArtifact, User
from smeme.decision_tree.helpers.db_queries import parse_graph_data
from smeme.decision_tree.models import DTGraph
from smeme.mcp._generated_design_guidance import (
    DESIGN_GUIDANCE_DIGEST,
    DESIGN_GUIDANCE_MARKDOWN,
    DESIGN_GUIDANCE_VERSION,
)
from smeme.mcp._generated_guidance import (
    GUIDANCE_CONTENT_DIGEST,
    GUIDANCE_CONTENT_MARKDOWN,
    GUIDANCE_CONTENT_VERSION,
)
from smeme.mcp.assistant_decision_tree_access import (
    assistant_tools_discoverability_violation,
    select_decision_trees_for_assistant_tools_list,
    serialize_decision_trees_for_assistant_list,
)
from smeme.mcp.authoring_graph import (
    AUTHORING_GRAPH_WIRE_SCHEMA,
    create_draft_from_graph,
    editor_url_for_decision_tree,
    get_owner_draft,
    parse_authoring_graph_json,
    update_draft_from_graph,
    validation_payload,
)
from smeme.mcp.bearer_auth import (
    ClerkMcpTokenVerifier,
    MCPAuthError,
    auth_error_tool_json,
    get_mcp_user,
)
from smeme.mcp.inquire_guidance_artifact import (
    INQUIRE_GUIDANCE_CONTENT_DIGEST,
    INQUIRE_GUIDANCE_CONTENT_VERSION,
    inquire_guidance_check_payload,
    inquire_guidance_payload,
)
from smeme.mcp.invocation_telemetry import (
    bind_invocation_id,
    bind_mcp_user,
    get_active_mcp_recorder,
    mcp_invocation_scope,
    request_from_mcp_context,
)
from smeme.mcp.reasoning_template_worksheet import (
    build_manifest_core,
    manifest_core_digest,
    render_manifest_markdown,
    safe_worksheet_slug,
    utc_generated_at_iso_z,
    worksheet_payload_too_large,
)
from smeme.mcp.tool_contract import (
    INTERNAL_ERROR_MESSAGE,
    tool_error_json,
)
from smeme.mcp.urls import (
    mcp_orchestrator_http_path,
    mcp_resource_url,
    transport_security_allowed_hosts,
)
from smeme.reasoning.graph_hash import canonical_graph_hash
from smeme.reasoning.ir.serialize import ir_from_json
from smeme.reasoning.ir.types import IR_FORMAT_VERSION, IRNodeKind
from smeme.reasoning.persistence import persist_reasoning_evaluation_run
from smeme.reasoning.review_metadata import decision_tree_review_warnings
from smeme.reasoning.runtime.analyze import enumerate_conclusion_sat_queries
from smeme.reasoning.runtime.assumptions import (
    AssumptionsError,
    assumptions_from_lists,
)
from smeme.reasoning.runtime.conclusions_catalog import build_conclusions_catalog_wire
from smeme.reasoning.runtime.counterfactual import (
    CounterfactualError,
    find_repairs_for_target,
    how_to_reach_to_wire,
    normalized_from_answers,
    run_what_if,
)
from smeme.reasoning.runtime.decisive_support import (
    DecisiveSupportError,
    find_minimal_decisive_supports,
)
from smeme.reasoning.runtime.evaluate import evaluate_reasoning
from smeme.reasoning.runtime.ingest_codes import HARNESS_NEXT_VALUES
from smeme.reasoning.runtime.ingest_envelope import (
    ReasoningIngestError,
    envelope_to_wire_dict,
    prepare_evaluate_ingest,
)
from smeme.reasoning.runtime.ingest_telemetry import log_reasoning_ingest_hard_reject
from smeme.reasoning.runtime.input_validation import ReasoningInputValidationError
from smeme.reasoning.runtime.path_under_edit import (
    PathUnderEditError,
    run_edit_affects_path,
)
from smeme.reasoning.runtime.report_builder import build_evaluation_report

logger = get_logger(__name__)

# MCP surface version: ``version`` in ``smeme_reasoning_capabilities`` and the
# ``_server_plugin_version`` watermark. Keep in sync with
# ``<!-- installed_plugin_version -->`` in ``agent-skills/smeme-reasoning/SKILL.md``.
REASONING_CAPABILITIES_VERSION = "3.8.0"
REASONING_CAPABILITIES_MCP_SURFACE = "DR-3-transport-reasoning"


def _tool_json(payload: dict[str, Any]) -> str:
    """Serialize a success payload and inject the MCP surface version watermark.

    The ``_server_plugin_version`` field lets agents detect drift against
    ``REASONING_CAPABILITIES_VERSION`` / cached guidance. Error paths use
    ``tool_error_json`` and intentionally do not carry the watermark.

    A shallow copy is made so the caller's dict is not mutated.
    """
    stamped = {**payload, "_server_plugin_version": REASONING_CAPABILITIES_VERSION}
    return json.dumps(stamped)


async def _mcp_auth_user_only(request: Any, db: AsyncSession) -> User | str:
    """Authenticate MCP caller without reserving quota (cheap gates run first)."""
    try:
        return await get_mcp_user(request, db)
    except MCPAuthError as exc:
        return auth_error_tool_json(exc)


async def _mcp_reserve_quota_and_bind(
    request: Any,
    db: AsyncSession,
    user: User,
    *,
    tool_name: str,
) -> str | None:
    """Reserve quota slot and bind telemetry. Returns tool error JSON on failure."""
    oauth_client_id: str | None = getattr(
        getattr(request, "state", None), "mcp_oauth_client_id", None
    )
    result = await reserve_mcp_quota(db, user, tool_name, oauth_client_id=oauth_client_id)
    if isinstance(result, str):
        return result
    bind_mcp_user(user, request=request)
    if isinstance(result, UUID):
        bind_invocation_id(result)
    return None


async def _mcp_authenticate_billable_tool(
    request: Any,
    db: AsyncSession,
    *,
    tool_name: str,
) -> User | str:
    """Authenticate MCP caller; atomically reserve quota slot before binding telemetry.

    Prefer :func:`_mcp_auth_user_only` + owner/discoverability gates + :func:`_mcp_reserve_quota_and_bind`
    when cheap checks can run before quota (A3-d).

    Replaces the former read-only ``mcp_quota_denied_response`` check with
    ``reserve_mcp_quota``: advisory lock → re-check → INSERT outcome='reserved' →
    commit, closing the TOCTOU window (A1).  On success the reserved row UUID is
    stored on the active McpInvocationRecorder so flush() UPDATEs it instead of
    INSERTing a second row.
    """
    user_or_err = await _mcp_auth_user_only(request, db)
    if isinstance(user_or_err, str):
        return user_or_err
    err = await _mcp_reserve_quota_and_bind(request, db, user_or_err, tool_name=tool_name)
    if err is not None:
        return err
    return user_or_err


def reasoning_capabilities_document(
    *,
    cap_settings: Settings | None = None,
    surface: str = "chat",
) -> dict[str, Any]:
    """JSON object returned by ``smeme_reasoning_capabilities`` (tests and release docs).

    ``cap_settings`` should match the ``Settings`` used when building the FastMCP singleton
    (see ``get_or_create_fastmcp``); defaults to the process ``settings`` object.

    ``surface`` is ``\"chat\"`` (default ``/mcp``) or ``\"orchestrator\"`` (Inquire protocol mount).
    """
    s = cap_settings or settings
    if surface == "orchestrator":
        tools: list[str] = [
            "smeme_reasoning_capabilities",
            "smeme_reasoning_list",
            "smeme_inquire_guidance_check",
            "smeme_inquire_guidance_get",
            "smeme_inquire_start",
            "smeme_inquire_next",
            "smeme_inquire_get_task",
            "smeme_inquire_admit",
            "smeme_inquire_verify",
        ]
        return {
            "service": "smeme",
            "version": REASONING_CAPABILITIES_VERSION,
            "latest_plugin_version": REASONING_CAPABILITIES_VERSION,
            "reasoning_mcp_surface": "DR-3-transport-inquire-orchestrator",
            "inquire_guidance": {
                "content_version": INQUIRE_GUIDANCE_CONTENT_VERSION,
                "content_digest": INQUIRE_GUIDANCE_CONTENT_DIGEST,
            },
            "reasoning": {
                "tools": tools,
                "auth": "OAuth 2.1 Bearer (Clerk)",
            },
            "inquire": {
                "protocol": "explicit_orchestration",
                "isolated_evaluations_required": True,
                "task_blindness": "server_enforced",
                "evaluator_isolation": "caller_responsibility",
                "verification_battery": "core",
                "persist_v1": True,
                "pv_authority": "server",
                "tools": [
                    "smeme_inquire_start",
                    "smeme_inquire_next",
                    "smeme_inquire_get_task",
                    "smeme_inquire_admit",
                    "smeme_inquire_verify",
                ],
                "note": (
                    "Explicit Inquire orchestration. VERIFY requires a fresh isolated "
                    "evaluator context per trial. SMEme enforces task-payload blindness "
                    "and Core P_v; evaluator isolation is the caller's responsibility. "
                    "See smeme_inquire_guidance_get."
                ),
            },
            "docs": "docs/guides/inquire-mcp-contract.md",
        }

    tools = [
        "smeme_reasoning_list",
        "smeme_reasoning_validate_answers",
        "smeme_reasoning_evaluate",
        "smeme_reasoning_evaluate_continue",
        "smeme_reasoning_evaluate_answers",
        "smeme_reasoning_what_if",
        "smeme_reasoning_how_to_reach",
        "smeme_reasoning_decisive_support",
        "smeme_reasoning_edit_affects_path",
        "smeme_reasoning_list_conclusions",
    ]
    tools.extend(
        [
            "smeme_reasoning_template_check",
            "smeme_reasoning_template_get",
            "smeme_reasoning_guidance_check",
            "smeme_reasoning_guidance_get",
        ]
    )
    if s.mcp_authoring_graph_tools_enabled:
        tools.extend(
            [
                "smeme_authoring_design_guidance",
                "smeme_authoring_validate_graph",
                "smeme_authoring_create_draft",
                "smeme_authoring_get_draft",
                "smeme_authoring_update_draft",
            ]
        )
    cap: dict[str, Any] = {
        "service": "smeme",
        "version": REASONING_CAPABILITIES_VERSION,
        # Explicit alias for skill-side version comparison.  Skills bake their
        # installed version as a constant and compare against this field.
        "latest_plugin_version": REASONING_CAPABILITIES_VERSION,
        "reasoning_mcp_surface": REASONING_CAPABILITIES_MCP_SURFACE,
        "guidance": {
            "content_version": GUIDANCE_CONTENT_VERSION,
            "content_digest": GUIDANCE_CONTENT_DIGEST,
        },
        "reasoning": {
            "tools": tools,
            "auth": "OAuth 2.1 Bearer (Clerk)",
            "harness_next_enum": list(HARNESS_NEXT_VALUES),
            "ingest_envelope": {
                "provenance_envelope": True,
                "legacy_flat_object": True,
                "evidence_requires_explicit_answers": True,
                "evidence_locator_v1": True,
                "grounding_error_details_v1": True,
            },
            "evaluate_response": {
                "report_v1": True,
                "report_theory_v1": True,
                "decision_tree_warnings_review_v1": True,
                "inquire_chat_facade_v1": True,
            },
            "list_response": {"review_metadata_v1": True},
            "counterfactual": {
                "what_if": True,
                "how_to_reach": True,
                "decisive_support": True,
                "edit_affects_path": True,
                "list_conclusions": True,
                "persist_v1": False,
                "how_to_reach_reach_mode": ["entailed", "possible"],
                "assumptions": {
                    "force_reachable_ids": True,
                    "force_unreachable_ids": True,
                    "tools": [
                        "smeme_reasoning_evaluate_answers",
                        "smeme_reasoning_what_if",
                        "smeme_reasoning_how_to_reach",
                        "smeme_reasoning_decisive_support",
                        "smeme_reasoning_edit_affects_path",
                    ],
                },
            },
            "query_modes": {
                "apply": "smeme_reasoning_evaluate_answers",
                "inquire_chat": ("smeme_reasoning_evaluate / smeme_reasoning_evaluate_continue"),
                "compare": "smeme_reasoning_what_if",
                "path_under_edit": "smeme_reasoning_edit_affects_path",
                "entail": "smeme_reasoning_how_to_reach (reach_mode=entailed)",
                "possible": "smeme_reasoning_how_to_reach (reach_mode=possible)",
                "repair": "smeme_reasoning_how_to_reach (answer-edit plans)",
                "minimal_sufficient_evidence": (
                    "smeme_reasoning_decisive_support (minimal answered supports; not abduction)"
                ),
                "assume": (
                    "force_reachable_ids / force_unreachable_ids on "
                    "evaluate_answers + what_if + how_to_reach + decisive_support + edit_affects_path"
                ),
            },
            "note": (
                "Ordinary chat evaluation: smeme_reasoning_evaluate then "
                "smeme_reasoning_evaluate_continue. Do not use the explicit Inquire "
                "orchestrator protocol from conversational context; that protocol "
                "requires evaluator isolation that ordinary chat does not provide. "
                "Bulk/audit: template_get → validate_answers → evaluate_answers."
            ),
        },
        "docs": "docs/guides/dr3-mcp-oauth-authoritative-sources.md",
    }
    if s.mcp_authoring_graph_tools_enabled:
        cap["authoring_graph"] = {
            "note": (
                "Authoring helpers — not evaluation tools. "
                "Fetch design guidance, validate a chat-built decision tree graph, then create "
                "or revise a dashboard draft (bypasses the generation wizard). "
                "create_draft is strict (requires draft_ready); update_draft is lenient "
                "(may persist intermediate graphs with expected_graph_hash concurrency). "
                "Deploy still happens in the SMEme editor. Prefer authoring_graph.schema + "
                "smeme_authoring_design_guidance over smeme_reasoning_guidance_get when "
                "building trees."
            ),
            "design_guidance": "smeme_authoring_design_guidance",
            "validate": "smeme_authoring_validate_graph",
            "create_draft": "smeme_authoring_create_draft",
            "get_draft": "smeme_authoring_get_draft",
            "update_draft": "smeme_authoring_update_draft",
            "schema": AUTHORING_GRAPH_WIRE_SCHEMA,
        }
        cap["authoring_design"] = {
            "content_version": DESIGN_GUIDANCE_VERSION,
            "content_digest": DESIGN_GUIDANCE_DIGEST,
            "note": (
                "Authoring helper — not an evaluation tool. "
                "Returns the standard for designing branching decision trees in chat."
            ),
        }
    # Inquire protocol tools are on the orchestrator mount only — never listed here.
    return cap


async def _mcp_load_owner_reasoning_context(
    db: AsyncSession,
    *,
    user: User,
    decision_tree_uuid: UUID,
) -> tuple[DecisionTree, ReasoningCompiledArtifact, DTGraph, str] | str:
    """Owner + discoverability + artifact + parsed graph + live graph hash (single DB read).

    Does **not** apply ``stale_theory`` — template tools use ``in_sync`` instead.

    Returns a JSON error string from :func:`~smeme.mcp.tool_contract.tool_error_json` on failure.
    """
    decision_tree_result = await db.execute(
        select(DecisionTree).where(DecisionTree.id == decision_tree_uuid)
    )
    decision_tree = decision_tree_result.scalar_one_or_none()
    if decision_tree is None or decision_tree.author_id != user.id:
        return tool_error_json(
            "not_found",
            "Decision tree not found, or you are not its owner. "
            "Call smeme_reasoning_list to see the decision trees available to your account, "
            "and pass an id from that list.",
        )

    from smeme.billing.access_policy import (
        is_decision_tree_live,
        is_workflow_pick_required,
        mcp_account_downgrade_pending_response,
        mcp_workflow_dormant_response,
    )

    if is_workflow_pick_required(user):
        return mcp_account_downgrade_pending_response(user=user)
    if not is_decision_tree_live(user, decision_tree):
        return mcp_workflow_dormant_response()

    disc_violation = assistant_tools_discoverability_violation(decision_tree)
    if disc_violation:
        code, msg = disc_violation
        return tool_error_json(code, msg)

    from smeme.reasoning.artifact_deploy import load_current_compiled_artifact

    artifact = await load_current_compiled_artifact(db, decision_tree)
    if artifact is None:
        return tool_error_json(
            "no_reasoning_artifact",
            "This decision tree has not been published for reasoning yet. "
            "Publish it from the SMEme editor, then try again.",
        )

    try:
        graph = parse_graph_data(decision_tree)
    except ValidationError as exc:
        return tool_error_json("invalid_graph", f"Graph data invalid: {exc}")

    live_hash = canonical_graph_hash(graph)

    if artifact.ir_format_version != IR_FORMAT_VERSION:
        return tool_error_json(
            "no_reasoning_artifact",
            "This decision tree's published reasoning is outdated. "
            "Re-publish it from the SMEme editor to update it, then try again.",
        )

    return (decision_tree, artifact, graph, live_hash)


async def _mcp_load_owner_compiled_artifact(
    db: AsyncSession,
    *,
    user: User,
    decision_tree_uuid: UUID,
) -> tuple[DecisionTree, ReasoningCompiledArtifact] | str:
    """Owner + discoverability + graph-hash gate + artifact row (shared by evaluate tools).

    Returns a JSON error string from :func:`~smeme.mcp.tool_contract.tool_error_json` on failure.
    """
    loaded = await _mcp_load_owner_reasoning_context(
        db, user=user, decision_tree_uuid=decision_tree_uuid
    )
    if isinstance(loaded, str):
        return loaded
    decision_tree, artifact, _, live_hash = loaded
    if live_hash != artifact.graph_hash:
        return tool_error_json(
            "stale_theory",
            "This decision tree has changed since it was last published. "
            "Re-publish it from the SMEme editor, then retry the same answers.",
            current_hash=live_hash,
            compiled_hash=artifact.graph_hash,
        )
    return (decision_tree, artifact)


# Module-level singletons.  Both are None until the first call to
# get_or_create_fastmcp() / get_mcp_starlette_app().  Cleared by
# reset_mcp_runtime_for_tests() between test cases.
_holder: FastMCP | None = None
_starlette_mcp: Starlette | None = None
_orchestrator_holder: FastMCP | None = None
_starlette_orchestrator_mcp: Starlette | None = None

# Byte-string used to match the Last-Event-ID header in ASGI scope headers.
# Must be bytes because ASGI headers are always (bytes, bytes) pairs.
_LAST_EVENT_ID_HDR = b"last-event-id"


class StripLastEventIdMiddleware:
    """Strip ``Last-Event-ID`` before the MCP Streamable HTTP app.

    **Trigger:** SSE clients (including MCP Inspector on reconnect) send ``Last-Event-ID``.
    **Bug:** In stateless mode the Python ``mcp`` SDK hardcodes ``event_store=None`` on the
    transport; ``_replay_events`` then returns without sending an HTTP body, so Starlette
    surfaces ``RuntimeError: No response returned.`` / 500. See
    `modelcontextprotocol/python-sdk#1648 <https://github.com/modelcontextprotocol/python-sdk/issues/1648>`_,
    `#423 <https://github.com/modelcontextprotocol/python-sdk/issues/423>`_.

    **Mitigation:** Drop the header so the handler takes the normal GET path (no replay).
    Acceptable for dev / Inspector; real resumability needs an ``EventStore`` once stateless
    mode can pass it through (or upstream fixes the no-store early return).

    **Implementation note:** ASGI ``headers`` are a **list** of ``(bytes, bytes)`` items.
    Do not convert to ``dict()``—that drops duplicate names and ``pop(b"last-event-id")``
    misses differently cased keys; filter with ``k.lower()`` instead.

    See LESSONS_LEARNED §MCP Streamable HTTP for the full diagnostic story.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            # Filter out the Last-Event-ID header case-insensitively.
            # scope["headers"] is a list of (bytes, bytes); we MUST NOT convert to dict
            # (would drop duplicate header names) or use pop() (dict-only).
            headers = [
                (k, v) for k, v in scope.get("headers") or () if k.lower() != _LAST_EVENT_ID_HDR
            ]
            # Build a new scope dict (dicts are shared; mutating the original would
            # affect other middleware in the stack).
            scope = {**scope, "headers": headers}
        await self.app(scope, receive, send)


class McpMountPathNormalizeMiddleware:
    """Map bare MCP mount path(s) to the trailing-slash form Starlette ``Mount`` matches.

    ``Mount`` is registered with ``/api/v1/mcp`` but its path regex only matches
    ``/api/v1/mcp/...`` (``/api/v1/mcp`` alone does not match). Starlette's router
    then issues a **307** to ``/api/v1/mcp/``. Some MCP clients repeat the redirected
    **POST** without the required ``Accept: application/json, text/event-stream``
    header, which yields **406** from the Streamable HTTP stack — not a broken mount.

    Normalizing here avoids the redirect entirely when clients omit the trailing slash
    (Claude Desktop, some OAuth control-plane probes, etc.).

    When Inquire orchestrator is enabled, also normalize
    ``{mcp_path}/orchestrator`` the same way.
    """

    def __init__(
        self,
        app: ASGIApp,
        mcp_path: str = "/api/v1/mcp",
        *,
        orchestrator_path: str | None = None,
    ) -> None:
        self.app = app
        raw = (mcp_path or "/api/v1/mcp").rstrip("/")
        self._prefixes = [raw if raw else "/api/v1/mcp"]
        if orchestrator_path:
            orch = orchestrator_path.rstrip("/")
            if orch:
                self._prefixes.append(orch)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Shallow-copy scope when mutating: ASGI may share the dict across layers.
        if scope["type"] == "http":
            path = scope.get("path")
            if path in self._prefixes:
                scope = {**scope, "path": f"{path}/"}
        await self.app(scope, receive, send)


def reset_mcp_runtime_for_tests() -> None:
    """Clear singletons between tests (avoids stale FastMCP when toggling settings).

    Without this, test A may create a FastMCP instance with MCP_ENABLED=True,
    and test B that expects MCP_ENABLED=False would still get the old instance.
    """
    global _holder, _starlette_mcp, _orchestrator_holder, _starlette_orchestrator_mcp
    _holder = None
    _starlette_mcp = None
    _orchestrator_holder = None
    _starlette_orchestrator_mcp = None


def _build_transport_security(s: Settings) -> TransportSecuritySettings | None:
    """Build DNS rebinding protection settings for the FastMCP transport.

    In development / testing, rebinding protection is disabled so tools like
    MCP Inspector (connecting from localhost) are not blocked by host validation.

    In production the allowed hosts and origins are derived **exclusively from
    ``BASE_URL``** (via :func:`transport_security_allowed_hosts`) and passed to
    FastMCP's transport layer for ``Host`` header validation.  ``ALLOWED_ORIGINS``
    is intentionally **not** unioned in (B0-d): it is a CORS list for the HTMX
    web app and should not widen MCP transport origin validation.

    Raises ``RuntimeError`` if production config would leave DNS-rebinding
    protection disabled (B0-b).
    """
    if s.is_development or s.is_testing:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    hosts, origins = transport_security_allowed_hosts(s)
    if not hosts:
        raise RuntimeError(
            "MCP_ENABLED=true in a non-development environment requires BASE_URL to be a valid "
            "HTTPS origin (e.g. https://www.smeme.ai) so DNS rebinding protection can be enabled. "
            "Set BASE_URL to the production HTTPS origin or disable MCP."
        )
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def validate_mcp_startup_config(s: Settings) -> None:
    """Assert MCP configuration is safe for the current environment.

    Call at startup before mounting MCP.  No-ops when MCP is disabled or the
    environment is development/testing.  Raises ``RuntimeError`` on hard
    misconfigurations; logs a warning on advisory issues.

    Findings closed: A0-a (persist guard), B0-a (Clerk required), B0-c (allowlist warning).
    """
    if not s.mcp_enabled or s.is_development or s.is_testing:
        return

    if not s.clerk_oauth_issuer:
        raise RuntimeError(
            "MCP_ENABLED=true requires Clerk OAuth to be configured in production. "
            "Set CLERK_PUBLISHABLE_KEY (or CLERK_OAUTH_ISSUER) so the MCP transport "
            "enforces Bearer authentication.  Without Clerk, unauthenticated clients "
            "reach the JSON-RPC surface via in-band errors only."
        )

    if not s.mcp_invocation_telemetry_persist:
        raise RuntimeError(
            "MCP_INVOCATION_TELEMETRY_PERSIST=false with MCP_ENABLED=true in a non-development "
            "environment disables quota enforcement — the monthly usage sum stays at zero and "
            "all cap checks pass.  Set MCP_INVOCATION_TELEMETRY_PERSIST=true or disable MCP."
        )

    if not s.mcp_allowed_oauth_client_ids:
        logger.warning(
            "mcp_oauth_client_allowlist_empty",
            extra={
                "detail": (
                    "SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS is empty — any valid Clerk OAuth app "
                    "can call MCP tools.  Set this to the known Cowork/Inspector client IDs "
                    "to restrict token acceptance."
                )
            },
        )


def _fastmcp_clerk_auth(
    cfg: Settings,
) -> tuple[AuthSettings | None, ClerkMcpTokenVerifier | None]:
    """Enable SDK transport auth when Clerk issues OAuth access JWTs for this RS."""
    issuer = (cfg.clerk_oauth_issuer or "").strip()
    if not issuer:
        return None, None
    resource = mcp_resource_url(cfg)
    auth = AuthSettings(
        issuer_url=AnyHttpUrl(issuer.rstrip("/")),
        resource_server_url=AnyHttpUrl(resource),
        required_scopes=None,
    )
    return auth, ClerkMcpTokenVerifier()


def _build_mcp_instructions(cfg: Settings) -> str:
    """Build the MCP server instructions string (shown to LLM clients as system context)."""
    base = (
        "SMEme — deterministic decision tree evaluation over MCP.\n\n"
        "Use these tools when the user mentions evaluating a case, running a "
        "decision tree, checking implications against expert rules, or any task "
        "involving structured decision analysis.\n\n"
        "All tools require OAuth 2.1 Bearer. On auth_error with "
        "auth_reason 'no_local_user_for_clerk_sub': the user needs a SMEme "
        "account — open the signup_url from the error, complete sign-in, then "
        "reconnect. For other auth_error: reconnect the MCP connector once.\n\n"
        "Bootstrap sequence:\n"
        "1. smeme_reasoning_capabilities (check guidance.content_digest)\n"
        "2. If no cached guidance or digest mismatch: smeme_reasoning_guidance_get "
        "(full calling contract — cache it)\n"
        "3. smeme_reasoning_list → smeme_reasoning_evaluate(decision_tree_id) → "
        "loop smeme_reasoning_evaluate_continue until report or "
        "isolated_evaluations_required\n\n"
        "Do not call template_get first for ordinary chat evaluation. "
        "Do not invoke the explicit Inquire orchestrator protocol from this "
        "chat connector; that protocol requires isolated evaluators.\n\n"
        "Bulk/audit worksheet path: smeme_reasoning_template_get → "
        "smeme_reasoning_validate_answers → smeme_reasoning_evaluate_answers.\n\n"
        "smeme_reasoning_list returns only decision trees you can invoke now. "
        "If empty, the user has not yet published/shared a decision tree — "
        "do not guess decision tree ids."
    )
    if cfg.mcp_authoring_graph_tools_enabled:
        base += (
            "\n\nChat authoring: when the user wants to build a decision tree in chat "
            "(not the web wizard), call smeme_authoring_design_guidance once (it includes "
            "optional Research & critique phases), then offer Quick encode vs Research & "
            "critique. On research, use available host data sources (local files, pasted "
            "policy text, fetchable URLs, other MCP connectors, prior prompts/skills the "
            "user points at)—client-side only; do not upload private files to SMEme except "
            "the graph JSON they ask to push. Pause for user feedback on factors, "
            "conclusions, and the Q/branch outline before JSON. Then structure a dt_graph, "
            "call smeme_authoring_validate_graph, fix errors, and only then "
            "smeme_authoring_create_draft. To revise an existing draft: "
            "smeme_authoring_get_draft → edit → smeme_authoring_validate_graph → "
            "smeme_authoring_update_draft with expected_graph_hash; on graph_conflict, "
            "fetch again and retry. Do not auto-Deploy."
        )
    return base


def _build_orchestrator_mcp_instructions(_cfg: Settings) -> str:
    """Instructions for the Inquire orchestrator MCP mount."""
    return (
        "SMEme Inquire orchestrator MCP — explicit durable Inquire protocol.\n\n"
        "Not for ordinary chat evaluation. Call smeme_inquire_guidance_get once and "
        "follow VERIFY isolation: each trial in a fresh evaluator context; forward only "
        "{question_id, stem, options}; return observations to smeme_inquire_verify; "
        "never decide Retain yourself. SMEme enforces task blindness and Core P_v; "
        "evaluator isolation is your responsibility.\n\n"
        "Protocol: smeme_inquire_start → get_task → admit/verify with "
        "expected_revision and idempotency_key."
    )


def get_or_create_fastmcp(s: Settings | None = None) -> FastMCP:
    """Create or return the process-level FastMCP singleton.

    The singleton pattern is necessary because FastMCP's ``StreamableHTTPSessionManager``
    maintains state (session tracking, lifespan hooks) that must persist across
    individual HTTP requests.  Creating a new FastMCP per request would leak
    session managers and break the lifespan teardown.

    Tool registrations (``@_holder.tool()``) are executed once inside this function
    the first time it is called, then are cached on ``_holder`` for all subsequent
    calls.  This is why tool functions are defined as closures inside this function
    rather than at module level.

    ``s`` is accepted here for testing so callers can inject a custom ``Settings``
    instance without patching the global ``settings`` object.
    """
    global _holder
    if _holder is None:
        cfg = s or settings
        auth_settings, token_verifier = _fastmcp_clerk_auth(cfg)
        auth_kw: dict[str, Any] = {}
        if auth_settings is not None and token_verifier is not None:
            auth_kw["auth"] = auth_settings
            auth_kw["token_verifier"] = token_verifier

        _holder = FastMCP(
            name="SMEme Reasoning",
            # instructions are shown to LLM clients as system context for tool selection.
            instructions=_build_mcp_instructions(cfg),
            # stateless_http=True: each HTTP request is an independent MCP transaction.
            # The session manager does not maintain persistent session state between
            # requests, which is correct for the current use case (no streaming progress
            # updates, no server-initiated messages).
            stateless_http=True,
            # json_response=False: use the default SSE content type for Streamable HTTP.
            # Setting to True would switch to plain JSON responses (non-streaming), which
            # some clients may not support.
            json_response=False,
            # streamable_http_path="/": the FastMCP sub-application routes all MCP
            # traffic to "/".  The actual URL prefix (/api/v1/mcp) is set by the
            # app.mount() call in mount_mcp_on_app().
            streamable_http_path="/",
            transport_security=_build_transport_security(cfg),
            **auth_kw,
        )

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Check SMEme capabilities",
                readOnlyHint=True,
            )
        )
        async def smeme_reasoning_capabilities(ctx: Context) -> str:
            """Return reasoning MCP service info and available tools.

            Requires the same Bearer token and linked SMEme user as other reasoning tools
            (transport auth + ``get_mcp_user``). Use after OAuth completes.
            """
            request = request_from_mcp_context(ctx)
            try:
                async with mcp_invocation_scope("smeme_reasoning_capabilities", ctx) as rec:
                    async with AsyncSessionLocal() as db:
                        try:
                            user = await get_mcp_user(request, db)
                        except MCPAuthError as exc:
                            out = auth_error_tool_json(exc)
                            rec.note_json_response(out)
                            return out
                        bind_mcp_user(user, request=request)
                    out = _tool_json(reasoning_capabilities_document(cap_settings=cfg))
                    rec.note_json_response(out)
                    return out
            except Exception:
                logger.exception("smeme_reasoning_capabilities failed")
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Check reasoning guidance version",
                readOnlyHint=True,
            )
        )
        async def smeme_reasoning_guidance_check(ctx: Context) -> str:
            """Check guidance content version and digest (cheap cache gate).

            Prefer the digest from smeme_reasoning_capabilities (guidance.content_digest)
            when you call capabilities at session start. Use this tool only when skipping
            capabilities. If digest matches your cached copy, skip smeme_reasoning_guidance_get.
            On mismatch or first use, call smeme_reasoning_guidance_get.

            Requires OAuth Bearer (same auth as all reasoning tools).
            """
            request = request_from_mcp_context(ctx)
            try:
                async with mcp_invocation_scope("smeme_reasoning_guidance_check", ctx) as rec:
                    async with AsyncSessionLocal() as db:
                        user_or_err = await _mcp_auth_user_only(request, db)
                        if isinstance(user_or_err, str):
                            rec.note_json_response(user_or_err)
                            return user_or_err
                    out = _tool_json(
                        {
                            "content_version": GUIDANCE_CONTENT_VERSION,
                            "content_digest": GUIDANCE_CONTENT_DIGEST,
                        }
                    )
                    rec.note_json_response(out)
                    return out
            except Exception:
                logger.exception("smeme_reasoning_guidance_check failed")
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Get reasoning guidance",
                readOnlyHint=True,
            )
        )
        async def smeme_reasoning_guidance_get(ctx: Context) -> str:
            """Fetch the full SMEme reasoning calling contract as markdown.

            Returns platform guidance: calling sequence, provenance envelope shape,
            error recovery, report interpretation. Does NOT return per-decision-tree
            content (use smeme_reasoning_template_get for worksheets).

            Cache the result locally. Refresh when guidance.content_digest from
            capabilities (or smeme_reasoning_guidance_check) no longer matches.

            Requires OAuth Bearer (same auth as all reasoning tools).
            """
            request = request_from_mcp_context(ctx)
            try:
                async with mcp_invocation_scope("smeme_reasoning_guidance_get", ctx) as rec:
                    async with AsyncSessionLocal() as db:
                        user_or_err = await _mcp_auth_user_only(request, db)
                        if isinstance(user_or_err, str):
                            rec.note_json_response(user_or_err)
                            return user_or_err
                    out = _tool_json(
                        {
                            "content_version": GUIDANCE_CONTENT_VERSION,
                            "content_digest": GUIDANCE_CONTENT_DIGEST,
                            "content_markdown": GUIDANCE_CONTENT_MARKDOWN,
                        }
                    )
                    rec.note_json_response(out)
                    return out
            except Exception:
                logger.exception("smeme_reasoning_guidance_get failed")
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        if cfg.mcp_authoring_graph_tools_enabled:

            @_holder.tool(
                annotations=ToolAnnotations(
                    title="Get decision tree design guidance",
                    readOnlyHint=True,
                )
            )
            async def smeme_authoring_design_guidance(ctx: Context) -> str:
                """Get SMEme's standard for designing reasoning decision trees in chat.

                AUTHORING helper (not evaluation). Returns the versioned design standard:
                session fork (Quick encode vs Research & critique), optional host-side
                context intake and factor/conclusion/outline critique pauses, radio-only
                product constraints, conclusion-first outcome sets, anti-funnel branching,
                Unsure/forward-only policy, and a preflight checklist before
                ``smeme_authoring_validate_graph`` / ``smeme_authoring_create_draft``.

                When to call: once at the start of a chat authoring session (Phase B), and
                again if ``content_digest`` changed. Takes NO user data. Cache by digest.

                Requires OAuth Bearer (same auth as all reasoning tools).
                """
                request = request_from_mcp_context(ctx)
                try:
                    async with mcp_invocation_scope("smeme_authoring_design_guidance", ctx) as rec:
                        async with AsyncSessionLocal() as db:
                            user_or_err = await _mcp_auth_user_only(request, db)
                            if isinstance(user_or_err, str):
                                rec.note_json_response(user_or_err)
                                return user_or_err
                        out = _tool_json(
                            {
                                "content_version": DESIGN_GUIDANCE_VERSION,
                                "content_digest": DESIGN_GUIDANCE_DIGEST,
                                "content_markdown": DESIGN_GUIDANCE_MARKDOWN,
                            }
                        )
                        rec.note_json_response(out)
                        return out
                except Exception:
                    logger.exception("smeme_authoring_design_guidance failed")
                    return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

            @_holder.tool(
                annotations=ToolAnnotations(
                    title="Validate decision tree graph",
                    readOnlyHint=True,
                )
            )
            async def smeme_authoring_validate_graph(
                dt_graph_json: str,
                ctx: Context,
            ) -> str:
                """Validate a chat-authored decision tree graph (draft readiness).

                AUTHORING helper (not evaluation). Pass ``dt_graph_json`` as a serialized
                JSON object: either a raw graph ``{nodes, edges, metadata}`` or a SMEme
                ``.smeme.json`` export envelope (``decision_tree.graph``).

                Returns ``is_valid``, ``errors``, ``warnings``, and ``draft_ready``.
                ``draft_ready`` true means safe to call ``smeme_authoring_create_draft``.
                Deploy readiness is separate — always false here; Deploy in the SMEme editor.

                When to call: after the user agrees the plain-language tree is ready, and
                after each fix pass until ``draft_ready`` is true.

                Requires OAuth Bearer (same auth as all reasoning tools).
                """
                request = request_from_mcp_context(ctx)
                try:
                    async with mcp_invocation_scope("smeme_authoring_validate_graph", ctx) as rec:
                        async with AsyncSessionLocal() as db:
                            user_or_err = await _mcp_auth_user_only(request, db)
                            if isinstance(user_or_err, str):
                                rec.note_json_response(user_or_err)
                                return user_or_err
                        parsed = parse_authoring_graph_json(dt_graph_json)
                        if isinstance(parsed, str):
                            rec.note_json_response(parsed)
                            return parsed
                        from smeme.decision_tree.helpers.validation import (
                            validate_graph_for_agent_authoring,
                        )

                        result = validate_graph_for_agent_authoring(parsed)
                        out = _tool_json(validation_payload(parsed, result))
                        rec.note_json_response(out)
                        return out
                except Exception:
                    logger.exception("smeme_authoring_validate_graph failed")
                    return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

            @_holder.tool(
                annotations=ToolAnnotations(
                    title="Create decision tree draft",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                )
            )
            async def smeme_authoring_create_draft(
                dt_graph_json: str,
                ctx: Context,
                title: str | None = None,
            ) -> str:
                """Create a dashboard draft from a validated decision tree graph.

                AUTHORING helper (not evaluation). Creates a new unpublished decision tree owned
                by the authenticated user. Requires edit-valid graph (same gate as
                ``smeme_authoring_validate_graph`` with ``draft_ready`` true). Does **not**
                Deploy / publish for MCP evaluate — tell the user to open the editor URL
                and Deploy when ready.

                ``dt_graph_json``: same shapes as validate (raw graph or export envelope).
                Optional ``title`` overrides ``metadata.title``.

                Enforces the plan's active-decision-tree cap (``quota_exceeded`` / dimension
                ``decision trees``). Does not consume monthly MCP weighted quota.

                Requires OAuth Bearer.
                """
                request = request_from_mcp_context(ctx)
                try:
                    async with (
                        mcp_invocation_scope("smeme_authoring_create_draft", ctx) as rec,
                        AsyncSessionLocal() as db,
                    ):
                        user_or_err = await _mcp_auth_user_only(request, db)
                        if isinstance(user_or_err, str):
                            rec.note_json_response(user_or_err)
                            return user_or_err
                        parsed = parse_authoring_graph_json(dt_graph_json)
                        if isinstance(parsed, str):
                            rec.note_json_response(parsed)
                            return parsed
                        created = await create_draft_from_graph(
                            db,
                            user=user_or_err,
                            graph=parsed,
                            title_override=title,
                        )
                        if isinstance(created, str):
                            rec.note_json_response(created)
                            return created
                        decision_tree, result, graph_hash = created
                        rec.note_decision_tree_id(str(decision_tree.id))
                        editor_url = editor_url_for_decision_tree(
                            decision_tree.id, base_url=cfg.effective_base_url
                        )
                        out = _tool_json(
                            {
                                "decision_tree_id": str(decision_tree.id),
                                "title": decision_tree.title,
                                "editor_url": editor_url,
                                "status": "draft",
                                "graph_hash": graph_hash,
                                "warnings": list(result["warnings"]),
                                "deployed": False,
                                "mcp_discoverable": False,
                                "next_step": (
                                    "Open editor_url in the SMEme web app to polish "
                                    "and Deploy. Until Deployed + Listed, this decision tree "
                                    "will not appear in smeme_reasoning_list. "
                                    "To revise in chat, pass graph_hash as "
                                    "expected_graph_hash to smeme_authoring_update_draft."
                                ),
                            }
                        )
                        rec.note_json_response(out)
                        return out
                except Exception:
                    logger.exception("smeme_authoring_create_draft failed")
                    return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

            @_holder.tool(
                annotations=ToolAnnotations(
                    title="Get decision tree draft",
                    readOnlyHint=True,
                )
            )
            async def smeme_authoring_get_draft(
                decision_tree_id: str,
                ctx: Context,
            ) -> str:
                """Fetch the owner's current saved decision-tree graph for chat revision.

                AUTHORING helper (not evaluation). Returns ``graph``, ``graph_hash``,
                current validation (``errors`` / ``warnings`` / ``draft_ready``),
                ``deployment_sync`` (``not_built`` / ``live`` / ``stale``), and
                ``editable``. Does **not** require Listed or a Deployed artifact.

                Use ``graph_hash`` as ``expected_graph_hash`` for
                ``smeme_authoring_update_draft``. Prefer validate before update.

                Requires OAuth Bearer.
                """
                request = request_from_mcp_context(ctx)
                try:
                    async with (
                        mcp_invocation_scope("smeme_authoring_get_draft", ctx) as rec,
                        AsyncSessionLocal() as db,
                    ):
                        user_or_err = await _mcp_auth_user_only(request, db)
                        if isinstance(user_or_err, str):
                            rec.note_json_response(user_or_err)
                            return user_or_err
                        try:
                            decision_tree_uuid = UUID(decision_tree_id)
                        except ValueError:
                            err = tool_error_json(
                                "invalid_decision_tree_id",
                                "decision_tree_id must be a valid UUID.",
                            )
                            rec.note_json_response(err)
                            return err
                        loaded = await get_owner_draft(
                            db,
                            user=user_or_err,
                            decision_tree_id=decision_tree_uuid,
                            base_url=cfg.effective_base_url,
                        )
                        if isinstance(loaded, str):
                            rec.note_json_response(loaded)
                            return loaded
                        rec.note_decision_tree_id(str(decision_tree_uuid))
                        out = _tool_json(loaded)
                        rec.note_json_response(out)
                        return out
                except Exception:
                    logger.exception("smeme_authoring_get_draft failed")
                    return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

            @_holder.tool(
                annotations=ToolAnnotations(
                    title="Update decision tree draft",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                )
            )
            async def smeme_authoring_update_draft(
                decision_tree_id: str,
                dt_graph_json: str,
                expected_graph_hash: str,
                ctx: Context,
                title: str | None = None,
            ) -> str:
                """Replace the owner's saved decision-tree graph (lenient draft save).

                AUTHORING helper (not evaluation). Requires ``expected_graph_hash`` from
                ``smeme_authoring_get_draft`` or ``smeme_authoring_create_draft``. Returns
                ``graph_conflict`` if the graph changed first (atomic row lock + hash check).

                Persists schema-valid graphs even when ``draft_ready`` is false (same
                incremental-save posture as the web editor). Prefer calling
                ``smeme_authoring_validate_graph`` before update. Does **not** Deploy,
                List, or mutate the compiled reasoning artifact — deployed trees become
                ``stale`` until Redeploy in the editor.

                Optional ``title`` overrides ``metadata.title``. Does not consume the
                decision-tree plan cap or monthly MCP weighted quota.

                Requires OAuth Bearer.
                """
                request = request_from_mcp_context(ctx)
                try:
                    async with (
                        mcp_invocation_scope("smeme_authoring_update_draft", ctx) as rec,
                        AsyncSessionLocal() as db,
                    ):
                        user_or_err = await _mcp_auth_user_only(request, db)
                        if isinstance(user_or_err, str):
                            rec.note_json_response(user_or_err)
                            return user_or_err
                        try:
                            decision_tree_uuid = UUID(decision_tree_id)
                        except ValueError:
                            err = tool_error_json(
                                "invalid_decision_tree_id",
                                "decision_tree_id must be a valid UUID.",
                            )
                            rec.note_json_response(err)
                            return err
                        parsed = parse_authoring_graph_json(dt_graph_json)
                        if isinstance(parsed, str):
                            rec.note_json_response(parsed)
                            return parsed
                        updated = await update_draft_from_graph(
                            db,
                            user=user_or_err,
                            decision_tree_id=decision_tree_uuid,
                            graph=parsed,
                            expected_graph_hash=expected_graph_hash,
                            title_override=title,
                            base_url=cfg.effective_base_url,
                        )
                        if isinstance(updated, str):
                            rec.note_json_response(updated)
                            return updated
                        rec.note_decision_tree_id(str(decision_tree_uuid))
                        out = _tool_json(updated)
                        rec.note_json_response(out)
                        return out
                except Exception:
                    logger.exception("smeme_authoring_update_draft failed")
                    return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        @_holder.tool(
            annotations=ToolAnnotations(
                title="List decision trees",
                readOnlyHint=True,
            )
        )
        async def smeme_reasoning_list(ctx: Context) -> str:
            """List the authenticated user's published decision trees that are discoverable for MCP tools.

            Returns a JSON object with a ``decision_trees`` array and a ``count``. Each entry includes:
            - ``id`` — decision tree UUID (pass to smeme_reasoning_evaluate / template tools)
            - ``title``, ``is_public``, ``reasoning_status`` (``compiled`` in this list)
            - optional ``effective_date``, ``review_by``, and ``warnings``; surface
              ``review_overdue`` instead of silently treating stale rules as current

            A decision tree appears only when the owner has (1) published it for reasoning and
            (2) set it to **Listed** on the SMEme dashboard. When ``count`` is ``0`` the response
            includes a ``hint`` describing how the owner makes a decision tree appear — surface it to the
            user instead of guessing a decision tree id.

            Requires ``Authorization: Bearer <Clerk OAuth token>``.

            Errors use ``{"error": {"code", "message"}}`` — see ``smeme.mcp.tool_contract``.
            """
            request = request_from_mcp_context(ctx)
            try:
                async with mcp_invocation_scope("smeme_reasoning_list", ctx) as rec:
                    async with AsyncSessionLocal() as db:
                        try:
                            user = await get_mcp_user(request, db)
                        except MCPAuthError as exc:
                            out = auth_error_tool_json(exc)
                            rec.note_json_response(out)
                            return out
                        bind_mcp_user(user, request=request)

                        result = await db.execute(
                            select_decision_trees_for_assistant_tools_list(user.id)
                        )
                        listed_rows = result.scalars().all()
                        decision_trees = serialize_decision_trees_for_assistant_list(
                            user, listed_rows
                        )

                    payload: dict[str, Any] = {
                        "decision_trees": decision_trees,
                        "count": len(decision_trees),
                    }
                    if not decision_trees:
                        hint = (
                            "No decision trees are currently discoverable for your account. "
                            "This is not an error. In the SMEme web app, make sure the decision tree is "
                            "(1) published for reasoning from the editor and (2) set to Listed (not hidden) "
                            "on your dashboard (Listed column), then try again. Do not guess a decision tree id."
                        )
                        if cfg.mcp_authoring_graph_tools_enabled:
                            hint += (
                                " Tip: to build a new decision tree in chat, iterate the decision tree "
                                "in plain language, then smeme_authoring_validate_graph → "
                                "smeme_authoring_create_draft."
                            )
                        payload["hint"] = hint
                    out = _tool_json(payload)
                    rec.note_json_response(out)
                    return out
            except Exception:
                logger.exception("smeme_reasoning_list failed")
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Validate answers",
                readOnlyHint=True,
            )
        )
        async def smeme_reasoning_validate_answers(
            decision_tree_id: str,
            raw_answers_json: str,
            ctx: Context,
        ) -> str:
            """Phase 1 — validate provenance ingest + answers (no DB audit row).

            Same auth and load gates as ``smeme_reasoning_evaluate``. On success returns
            ``status``, ``warnings`` (deterministic order), and ``harness_next`` (see capabilities).

            ``harness_next: phase_2_ok`` means the envelope is structurally valid **and**
            answers ground into canonical facts (same Stage A path evaluate uses). It does
            **not** run the solver or promise a conclusion.
            """
            try:
                async with mcp_invocation_scope("smeme_reasoning_validate_answers", ctx) as rec:
                    rec.note_decision_tree_id(decision_tree_id)
                    out = await _smeme_reasoning_validate_answers_body(
                        decision_tree_id=decision_tree_id,
                        raw_answers_json=raw_answers_json,
                        ctx=ctx,
                    )
                    rec.note_json_response(out)
                    return out
            except Exception:
                logger.exception(
                    "smeme_reasoning_validate_answers failed",
                    extra={"decision_tree_id": decision_tree_id},
                )
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        async def _smeme_reasoning_validate_answers_body(
            decision_tree_id: str,
            raw_answers_json: str,
            ctx: Context,
        ) -> str:
            try:
                payload: dict[str, Any] = json.loads(raw_answers_json)
            except json.JSONDecodeError as exc:
                log_reasoning_ingest_hard_reject(
                    logger,
                    code="invalid_answers_json",
                    message=f"raw_answers_json must be valid JSON: {exc}",
                    decision_tree_id=decision_tree_id,
                    transport="mcp",
                )
                return tool_error_json(
                    "invalid_answers_json",
                    f"raw_answers_json must be valid JSON: {exc}",
                )
            if not isinstance(payload, dict):
                log_reasoning_ingest_hard_reject(
                    logger,
                    code="invalid_answers_json",
                    message="raw_answers_json must be a JSON object",
                    decision_tree_id=decision_tree_id,
                    transport="mcp",
                )
                return tool_error_json(
                    "invalid_answers_json", "raw_answers_json must be a JSON object"
                )

            try:
                decision_tree_uuid = UUID(decision_tree_id)
            except ValueError:
                return tool_error_json(
                    "invalid_decision_tree_id",
                    f"decision_tree_id must be a valid UUID, got {decision_tree_id!r}",
                )

            request = request_from_mcp_context(ctx)
            async with AsyncSessionLocal() as db:
                user_or_err = await _mcp_auth_user_only(request, db)
                if isinstance(user_or_err, str):
                    return user_or_err
                user = user_or_err

                loaded = await _mcp_load_owner_reasoning_context(
                    db, user=user, decision_tree_uuid=decision_tree_uuid
                )
                if isinstance(loaded, str):
                    return loaded
                _decision_tree, artifact, graph, live_hash = loaded
                if live_hash != artifact.graph_hash:
                    return tool_error_json(
                        "stale_theory",
                        "This decision tree has changed since it was last published. "
                        "Re-publish it from the SMEme editor, then retry the same answers.",
                    )

                quota_err = await _mcp_reserve_quota_and_bind(
                    request,
                    db,
                    user,
                    tool_name="smeme_reasoning_validate_answers",
                )
                if quota_err is not None:
                    return quota_err

                try:
                    ir = ir_from_json(artifact.ir_json)
                except (KeyError, ValueError, TypeError) as exc:
                    return tool_error_json(
                        "invalid_graph", f"Published reasoning data could not be read: {exc}"
                    )

                rec = get_active_mcp_recorder()
                if rec:
                    rec.note_ir_shape(
                        question_count=sum(1 for n in ir.nodes if n.kind == IRNodeKind.QUESTION),
                        edge_count=len(ir.edges),
                    )

                try:
                    _flat, _env, warnings, harness_next = await asyncio.to_thread(
                        prepare_evaluate_ingest, ir, payload
                    )
                except ReasoningIngestError as exc:
                    log_reasoning_ingest_hard_reject(
                        logger,
                        code=exc.code.value,
                        message=exc.message,
                        decision_tree_id=decision_tree_uuid,
                        caller_user_id=user.id,
                        transport="mcp",
                    )
                    return tool_error_json(exc.code.value, exc.message, **exc.details)

            return _tool_json(
                {
                    "status": "ok",
                    "warnings": warnings,
                    "harness_next": harness_next,
                }
            )

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Start guided case evaluation",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
            )
        )
        async def smeme_reasoning_evaluate(
            decision_tree_id: str,
            ctx: Context,
        ) -> str:
            """Start guided Inquire gather on a deployed decision tree (chat default).

            Starts from empty admitted evidence. Returns a blind task
            ``{question_id, stem, options}`` plus ``inquiry_session_id``, or a
            terminal ``report`` if Inquire already STOPs, or
            ``isolated_evaluations_required`` if VERIFY is needed (session stays
            ACTIVE — do not fake VERIFY in chat).

            Continue with ``smeme_reasoning_evaluate_continue``. Do **not** call
            ``template_get`` first. For bulk worksheet Apply use
            ``smeme_reasoning_evaluate_answers``.
            """
            from smeme.decision_tree.helpers.db_queries import parse_graph_data
            from smeme.mcp.inquire.chat_facade import (
                admitted_flat_answers_for_session,
                chat_evaluate_start,
                flat_answers_to_legacy_raw_json,
            )
            from smeme.mcp.inquire.handlers import InquireHandlerError

            try:
                async with mcp_invocation_scope("smeme_reasoning_evaluate", ctx) as rec:
                    rec.note_decision_tree_id(decision_tree_id)
                    try:
                        decision_tree_uuid = UUID(decision_tree_id)
                    except ValueError:
                        out = tool_error_json(
                            "invalid_decision_tree_id",
                            f"decision_tree_id must be a valid UUID, got {decision_tree_id!r}",
                        )
                        rec.note_json_response(out)
                        return out
                    request = request_from_mcp_context(ctx)
                    async with AsyncSessionLocal() as db:
                        user_or_err = await _mcp_auth_user_only(request, db)
                        if isinstance(user_or_err, str):
                            rec.note_json_response(user_or_err)
                            return user_or_err
                        user = user_or_err
                        loaded = await _mcp_load_owner_compiled_artifact(
                            db, user=user, decision_tree_uuid=decision_tree_uuid
                        )
                        if isinstance(loaded, str):
                            rec.note_json_response(loaded)
                            return loaded
                        decision_tree, artifact = loaded
                        try:
                            graph = parse_graph_data(decision_tree)
                        except Exception as exc:
                            out = tool_error_json("invalid_graph", f"Graph data invalid: {exc}")
                            rec.note_json_response(out)
                            return out
                        quota_err = await _mcp_reserve_quota_and_bind(
                            request,
                            db,
                            user,
                            tool_name="smeme_reasoning_evaluate",
                        )
                        if quota_err is not None:
                            rec.note_json_response(quota_err)
                            return quota_err
                        try:
                            facade = await chat_evaluate_start(
                                db,
                                user=user,
                                decision_tree=decision_tree,
                                artifact=artifact,
                                graph=graph,
                            )
                        except InquireHandlerError as exc:
                            out = tool_error_json(exc.code, exc.message)
                            rec.note_json_response(out)
                            return out
                        if "error" in facade:
                            out = _tool_json(facade)
                            rec.note_json_response(out)
                            return out
                        if facade.get("_chat_stop"):
                            session_id = UUID(str(facade["inquiry_session_id"]))
                            flat = await admitted_flat_answers_for_session(
                                db,
                                user=user,
                                inquiry_session_id=session_id,
                            )
                            apply_out = await _smeme_reasoning_evaluate_body(
                                decision_tree_id=decision_tree_id,
                                raw_answers_json=flat_answers_to_legacy_raw_json(flat),
                                ctx=ctx,
                                persist=True,
                            )
                            # Merge stop_reason onto Apply success when possible
                            try:
                                apply_payload = json.loads(apply_out)
                            except json.JSONDecodeError:
                                rec.note_json_response(apply_out)
                                return apply_out
                            if isinstance(apply_payload, dict) and "error" not in apply_payload:
                                apply_payload["inquiry_session_id"] = str(session_id)
                                apply_payload["stop_reason"] = facade.get("stop_reason")
                                apply_payload["status"] = "STOPPED"
                                apply_out = _tool_json(apply_payload)
                            rec.note_json_response(apply_out)
                            return apply_out
                        out = _tool_json(facade)
                        rec.note_json_response(out)
                        return out
            except Exception:
                logger.exception(
                    "smeme_reasoning_evaluate failed",
                    extra={"decision_tree_id": decision_tree_id},
                )
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Continue guided case evaluation",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
            )
        )
        async def smeme_reasoning_evaluate_continue(
            inquiry_session_id: str,
            question_id: str,
            ctx: Context,
            selected_option: str | None = None,
            provenance_id: str | None = None,
        ) -> str:
            """Continue guided Inquire gather: admit one answer, return next blind task.

            Pass ``inquiry_session_id`` from ``smeme_reasoning_evaluate``. Provide
            ``selected_option`` + ``provenance_id`` to admit, or omit option to abstain.
            Never runs VERIFY — if the server needs isolated verification, returns
            ``isolated_evaluations_required`` and leaves the session ACTIVE.
            """
            from smeme.mcp.inquire.chat_facade import (
                admitted_flat_answers_for_session,
                chat_evaluate_continue,
                flat_answers_to_legacy_raw_json,
            )
            from smeme.mcp.inquire.handlers import InquireHandlerError

            try:
                async with mcp_invocation_scope("smeme_reasoning_evaluate_continue", ctx) as rec:
                    try:
                        session_uuid = UUID(inquiry_session_id)
                    except ValueError:
                        out = tool_error_json(
                            "inquire_invalid_payload",
                            f"inquiry_session_id must be a valid UUID, got {inquiry_session_id!r}",
                        )
                        rec.note_json_response(out)
                        return out
                    request = request_from_mcp_context(ctx)
                    async with AsyncSessionLocal() as db:
                        user_or_err = await _mcp_auth_user_only(request, db)
                        if isinstance(user_or_err, str):
                            rec.note_json_response(user_or_err)
                            return user_or_err
                        user = user_or_err
                        quota_err = await _mcp_reserve_quota_and_bind(
                            request,
                            db,
                            user,
                            tool_name="smeme_reasoning_evaluate_continue",
                        )
                        if quota_err is not None:
                            rec.note_json_response(quota_err)
                            return quota_err
                        try:
                            facade = await chat_evaluate_continue(
                                db,
                                user=user,
                                inquiry_session_id=session_uuid,
                                question_id=question_id,
                                selected_option=selected_option,
                                provenance_id=provenance_id,
                            )
                        except InquireHandlerError as exc:
                            out = tool_error_json(exc.code, exc.message)
                            rec.note_json_response(out)
                            return out
                        if "error" in facade:
                            out = _tool_json(facade)
                            rec.note_json_response(out)
                            return out
                        if facade.get("_chat_stop"):
                            from smeme.reasoning.orchestration.inquire.persist.auth import (
                                load_owned_session,
                            )

                            session_row = await load_owned_session(
                                db,
                                user=user,
                                inquiry_session_id=session_uuid,
                                for_update=False,
                            )
                            tree_id = str(session_row.decision_tree_id)
                            flat = await admitted_flat_answers_for_session(
                                db,
                                user=user,
                                inquiry_session_id=session_uuid,
                            )
                            apply_out = await _smeme_reasoning_evaluate_body(
                                decision_tree_id=tree_id,
                                raw_answers_json=flat_answers_to_legacy_raw_json(flat),
                                ctx=ctx,
                                persist=True,
                            )
                            try:
                                apply_payload = json.loads(apply_out)
                            except json.JSONDecodeError:
                                rec.note_json_response(apply_out)
                                return apply_out
                            if isinstance(apply_payload, dict) and "error" not in apply_payload:
                                apply_payload["inquiry_session_id"] = str(session_uuid)
                                apply_payload["stop_reason"] = facade.get("stop_reason")
                                apply_payload["status"] = "STOPPED"
                                apply_out = _tool_json(apply_payload)
                            rec.note_json_response(apply_out)
                            return apply_out
                        out = _tool_json(facade)
                        rec.note_json_response(out)
                        return out
            except Exception:
                logger.exception("smeme_reasoning_evaluate_continue failed")
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Apply answers (bulk)",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
            )
        )
        async def smeme_reasoning_evaluate_answers(
            decision_tree_id: str,
            raw_answers_json: str,
            ctx: Context,
            persist: bool = True,
            force_reachable_ids: list[str] | None = None,
            force_unreachable_ids: list[str] | None = None,
        ) -> str:
            """Bulk Apply: evaluate a published decision tree from a worksheet answer envelope.

            Prefer ``smeme_reasoning_evaluate`` / ``smeme_reasoning_evaluate_continue`` for
            ordinary chat case evaluation (targeted evidence gather). Use this tool for
            intentional bulk/audit snapshots after ``template_get`` + ``validate_answers``.

            Args:
                decision_tree_id: UUID of the decision tree (from smeme_reasoning_list).
                raw_answers_json: JSON-encoded **legacy flat answers** or **provenance envelope** object:
                    ``{"answers": {...}, "evidence_items": [...], "evidence_refs": {...}}``.
                    If ``evidence_items`` or ``evidence_refs`` is present, ``answers`` is required.
                    Legacy example: ``{"Q1": "Yes"}``.

                    IMPORTANT: pass the bare JSON object, e.g. ``{}``, NOT the string
                    ``"{}"`` — MCP Inspector wraps string parameters in JSON quotes, so
                    passing ``"{}"`` would arrive as ``"\\\"{}\\\""``.

                persist: When true (default), save the evaluation run for audit
                    (``reasoning_evaluation_runs`` table).  Set false for ad-hoc exploration
                    or testing where you do not want to create an audit trail.
                force_reachable_ids: Optional IR node ids that must stay on the path
                    (from ``template_get`` / ``list_conclusions``).
                force_unreachable_ids: Optional IR node ids assumed off-path
                    (“assume this branch is dead”).

            Returns JSON with:
            - ``report``: server-generated product memo (``result_kind``, ``headline``,
              ``brief_memo``, ``reasoning_path``, ``candidates``, ``answer_sheet``)
            - ``evaluation_run_id``: persisted audit row ID (when persist=true), else null
            - ``warnings``: ingest hygiene (provenance envelope); deterministic order
            - ``decision_tree_warnings``: author review/freshness advisories
            - ``harness_next``: routing hint when ingest succeeded (see capabilities)
            - ``assumptions``: echoed when force lists were non-empty

            Requires ``Authorization: Bearer <Clerk OAuth token>``.

            Error codes returned in the JSON payload:
            - ``auth_error``          — Bearer token invalid or user not found
            - ``invalid_answers_json`` — raw_answers_json is not valid JSON or not an object
            - ``invalid_decision_tree_id``      — decision_tree_id is not a valid UUID
            - ``not_found``           — decision tree not found or caller is not the owner
            - ``not_discoverable``    — decision tree exists but is hidden from MCP (set it Listed)
            - ``no_reasoning_artifact`` — decision tree has not been published for reasoning
            - ``invalid_graph``       — decision tree data is structurally invalid (rare)
            - ``stale_theory``        — decision tree changed since last publish; re-publish needed
            - ``invalid_answers``     — answer values fail reasoning input validation rules
            - ``invalid_assumption_node_id`` / ``conflicting_assumptions`` / ``assumptions_cap_exceeded``
            - ``ingest_*``            — provenance envelope hard rejects (see tool_contract)
            - ``internal_error``      — unexpected server failure; retry once, then escalate

            """
            try:
                async with mcp_invocation_scope("smeme_reasoning_evaluate_answers", ctx) as rec:
                    rec.note_decision_tree_id(decision_tree_id)
                    out = await _smeme_reasoning_evaluate_body(
                        decision_tree_id=decision_tree_id,
                        raw_answers_json=raw_answers_json,
                        ctx=ctx,
                        persist=persist,
                        force_reachable_ids=force_reachable_ids,
                        force_unreachable_ids=force_unreachable_ids,
                    )
                    rec.note_json_response(out)
                    return out
            except Exception:
                logger.exception(
                    "smeme_reasoning_evaluate_answers failed",
                    extra={"decision_tree_id": decision_tree_id},
                )
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        async def _smeme_reasoning_evaluate_body(
            decision_tree_id: str,
            raw_answers_json: str,
            ctx: Context,
            persist: bool,
            force_reachable_ids: list[str] | None = None,
            force_unreachable_ids: list[str] | None = None,
        ) -> str:
            # ---- Step 1: Parse and validate inputs BEFORE opening the DB session ----
            # Fail fast on bad inputs without consuming a connection.

            # raw_answers_json is a string because MCP tools only accept primitive types.
            # We parse it ourselves to get the actual dict.
            try:
                payload: dict[str, Any] = json.loads(raw_answers_json)
            except json.JSONDecodeError as exc:
                log_reasoning_ingest_hard_reject(
                    logger,
                    code="invalid_answers_json",
                    message=f"raw_answers_json must be valid JSON: {exc}",
                    decision_tree_id=decision_tree_id,
                    transport="mcp",
                )
                return tool_error_json(
                    "invalid_answers_json",
                    f"raw_answers_json must be valid JSON: {exc}",
                )
            # Ensure it's a JSON object (dict), not an array or primitive.
            if not isinstance(payload, dict):
                log_reasoning_ingest_hard_reject(
                    logger,
                    code="invalid_answers_json",
                    message="raw_answers_json must be a JSON object",
                    decision_tree_id=decision_tree_id,
                    transport="mcp",
                )
                return tool_error_json(
                    "invalid_answers_json", "raw_answers_json must be a JSON object"
                )

            # UUID validation: FastAPI would do this automatically on REST routes;
            # here we do it manually since this is an MCP tool, not a route handler.
            try:
                decision_tree_uuid = UUID(decision_tree_id)
            except ValueError:
                return tool_error_json(
                    "invalid_decision_tree_id",
                    f"decision_tree_id must be a valid UUID, got {decision_tree_id!r}",
                )

            phi = assumptions_from_lists(force_reachable_ids, force_unreachable_ids)

            # ---- Step 2: Open DB session, authenticate, load artifacts ----
            request = request_from_mcp_context(ctx)
            async with AsyncSessionLocal() as db:
                user_or_err = await _mcp_auth_user_only(request, db)
                if isinstance(user_or_err, str):
                    return user_or_err
                user = user_or_err

                loaded = await _mcp_load_owner_reasoning_context(
                    db, user=user, decision_tree_uuid=decision_tree_uuid
                )
                if isinstance(loaded, str):
                    return loaded
                _decision_tree, artifact, graph, live_hash = loaded
                if live_hash != artifact.graph_hash:
                    return tool_error_json(
                        "stale_theory",
                        "This decision tree has changed since it was last published. "
                        "Re-publish it from the SMEme editor, then retry the same answers.",
                    )

                quota_err = await _mcp_reserve_quota_and_bind(
                    request,
                    db,
                    user,
                    tool_name="smeme_reasoning_evaluate_answers",
                )
                if quota_err is not None:
                    return quota_err

                try:
                    ir = ir_from_json(artifact.ir_json)
                except (KeyError, ValueError, TypeError) as exc:
                    return tool_error_json(
                        "invalid_graph", f"Published reasoning data could not be read: {exc}"
                    )

                try:
                    (
                        flat_answers,
                        ingest_env,
                        ingest_warnings,
                        harness_next,
                    ) = await asyncio.to_thread(prepare_evaluate_ingest, ir, payload)
                except ReasoningIngestError as exc:
                    log_reasoning_ingest_hard_reject(
                        logger,
                        code=exc.code.value,
                        message=exc.message,
                        decision_tree_id=decision_tree_uuid,
                        caller_user_id=user.id,
                        transport="mcp",
                    )
                    return tool_error_json(exc.code.value, exc.message, **exc.details)

                rec = get_active_mcp_recorder()
                if rec:
                    rec.note_ir_shape(
                        question_count=sum(1 for n in ir.nodes if n.kind == IRNodeKind.QUESTION),
                        edge_count=len(ir.edges),
                        answered_count=len(flat_answers),
                    )

                reasoning_started = time.perf_counter()
                try:
                    eval_result, audit = await asyncio.to_thread(
                        evaluate_reasoning,
                        ir,
                        raw_answers=flat_answers,
                        skip_ir_validation=True,
                        assumptions=phi,
                    )
                except AssumptionsError as exc:
                    return tool_error_json(exc.code, exc.message, **exc.details)
                except ReasoningInputValidationError as exc:
                    return tool_error_json("invalid_answers", str(exc))
                if rec:
                    rec.note_reasoning_ms(int((time.perf_counter() - reasoning_started) * 1000))

                ingest_wire = envelope_to_wire_dict(ingest_env)
                report = await asyncio.to_thread(
                    build_evaluation_report,
                    graph=graph,
                    envelope=ingest_env,
                    eval_result=eval_result,
                )
                from smeme.reasoning.artifact_identity import theory_stamp_from_artifact

                report["theory"] = theory_stamp_from_artifact(artifact)

                run_id: UUID | None = None
                if persist:
                    row = await persist_reasoning_evaluation_run(
                        db,
                        decision_tree_id=decision_tree_uuid,
                        result=eval_result,
                        audit=audit,
                        caller_user_id=user.id,
                        ingest_warnings=ingest_warnings,
                        report=report,
                        ingest_envelope=ingest_wire,
                        artifact=artifact,
                    )
                    run_id = row.id

            payload_out: dict[str, Any] = {
                "report": report,
                "evaluation_run_id": str(run_id) if run_id else None,
                "warnings": ingest_warnings,
                "decision_tree_warnings": decision_tree_review_warnings(graph),
                "harness_next": harness_next,
            }
            wire_assumptions = phi.to_wire()
            if wire_assumptions is not None:
                payload_out["assumptions"] = wire_assumptions
            return _tool_json(payload_out)

        def _mcp_parse_json_object(
            raw_json: str,
            *,
            field_name: str,
            decision_tree_id: str | None = None,
        ) -> dict[str, Any] | str:
            try:
                payload = json.loads(raw_json)
            except json.JSONDecodeError as exc:
                log_reasoning_ingest_hard_reject(
                    logger,
                    code="invalid_answers_json",
                    message=f"{field_name} must be valid JSON: {exc}",
                    decision_tree_id=decision_tree_id,
                    transport="mcp",
                )
                return tool_error_json(
                    "invalid_answers_json",
                    f"{field_name} must be valid JSON: {exc}",
                )
            if not isinstance(payload, dict):
                log_reasoning_ingest_hard_reject(
                    logger,
                    code="invalid_answers_json",
                    message=f"{field_name} must be a JSON object",
                    decision_tree_id=decision_tree_id,
                    transport="mcp",
                )
                return tool_error_json(
                    "invalid_answers_json",
                    f"{field_name} must be a JSON object",
                )
            return payload

        def _mcp_counterfactual_persist_gate(persist: bool) -> str | None:
            if persist:
                return tool_error_json(
                    "persist_not_implemented",
                    "persist=true is not supported for counterfactual tools in v1. "
                    "Call again with persist=false (default).",
                )
            return None

        async def _smeme_reasoning_what_if_body(
            decision_tree_id: str,
            base_raw_answers_json: str,
            override_raw_answers_json: str,
            ctx: Context,
            persist: bool,
            force_reachable_ids: list[str] | None = None,
            force_unreachable_ids: list[str] | None = None,
        ) -> str:
            persist_err = _mcp_counterfactual_persist_gate(persist)
            if persist_err is not None:
                return persist_err

            base_payload = _mcp_parse_json_object(
                base_raw_answers_json,
                field_name="base_raw_answers_json",
                decision_tree_id=decision_tree_id,
            )
            if isinstance(base_payload, str):
                return base_payload
            override_payload = _mcp_parse_json_object(
                override_raw_answers_json,
                field_name="override_raw_answers_json",
                decision_tree_id=decision_tree_id,
            )
            if isinstance(override_payload, str):
                return override_payload

            try:
                decision_tree_uuid = UUID(decision_tree_id)
            except ValueError:
                return tool_error_json(
                    "invalid_decision_tree_id",
                    f"decision_tree_id must be a valid UUID, got {decision_tree_id!r}",
                )

            request = request_from_mcp_context(ctx)
            async with AsyncSessionLocal() as db:
                user_or_err = await _mcp_auth_user_only(request, db)
                if isinstance(user_or_err, str):
                    return user_or_err
                user = user_or_err

                loaded = await _mcp_load_owner_reasoning_context(
                    db, user=user, decision_tree_uuid=decision_tree_uuid
                )
                if isinstance(loaded, str):
                    return loaded
                _decision_tree, artifact, graph, live_hash = loaded
                if live_hash != artifact.graph_hash:
                    return tool_error_json(
                        "stale_theory",
                        "This decision tree has changed since it was last published. "
                        "Re-publish it from the SMEme editor, then retry the same answers.",
                    )

                quota_err = await _mcp_reserve_quota_and_bind(
                    request,
                    db,
                    user,
                    tool_name="smeme_reasoning_what_if",
                )
                if quota_err is not None:
                    return quota_err

                try:
                    ir = ir_from_json(artifact.ir_json)
                except (KeyError, ValueError, TypeError) as exc:
                    return tool_error_json(
                        "invalid_graph", f"Published reasoning data could not be read: {exc}"
                    )

                phi = assumptions_from_lists(force_reachable_ids, force_unreachable_ids)
                try:
                    result = await asyncio.to_thread(
                        run_what_if,
                        ir,
                        graph,
                        base_payload=base_payload,
                        override_payload=override_payload,
                        assumptions=phi,
                    )
                except AssumptionsError as exc:
                    return tool_error_json(exc.code, exc.message, **exc.details)
                except ReasoningIngestError as exc:
                    log_reasoning_ingest_hard_reject(
                        logger,
                        code=exc.code.value,
                        message=exc.message,
                        decision_tree_id=decision_tree_uuid,
                        caller_user_id=user.id,
                        transport="mcp",
                    )
                    return tool_error_json(exc.code.value, exc.message, **exc.details)
                except ReasoningInputValidationError as exc:
                    return tool_error_json("invalid_answers", str(exc))

            payload_out: dict[str, Any] = {
                "before": {"report": result.before_report},
                "after": {"report": result.after_report},
                "delta": result.delta,
                "evaluation_run_ids": {"before": None, "after": None},
                "warnings": result.warnings,
            }
            wire_assumptions = result.assumptions.to_wire()
            if wire_assumptions is not None:
                payload_out["assumptions"] = wire_assumptions
            return _tool_json(payload_out)

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Compare counterfactual answers",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
            )
        )
        async def smeme_reasoning_what_if(
            decision_tree_id: str,
            base_raw_answers_json: str,
            override_raw_answers_json: str,
            ctx: Context,
            persist: bool = False,
            force_reachable_ids: list[str] | None = None,
            force_unreachable_ids: list[str] | None = None,
        ) -> str:
            """Compare baseline vs hypothetical assignments on the same published decision tree.

            Ingests ``base_raw_answers_json`` and ``override_raw_answers_json`` independently
            (same provenance envelope shape as ``smeme_reasoning_evaluate_answers``), merges answers
            with override winning per ``question_id``, and returns ``before`` / ``after`` reports
            plus a structured ``delta`` in report vocabulary only.

            Optional ``force_reachable_ids`` / ``force_unreachable_ids`` assert the same path
            assumptions on both evaluate passes (ALGEBRA §18). Empty / omitted = identity.

            Args:
                decision_tree_id: UUID from ``smeme_reasoning_list``.
                base_raw_answers_json: Baseline provenance envelope JSON object.
                override_raw_answers_json: Override provenance envelope JSON object.
                persist: v1 supports ``false`` only; ``true`` returns ``persist_not_implemented``.
                force_reachable_ids: Optional IR node ids that must stay on the path
                    (applied to both before and after).
                force_unreachable_ids: Optional IR node ids assumed off-path
                    (applied to both before and after).

            Requires ``Authorization: Bearer <Clerk OAuth token>``.

            Error codes include shared evaluate/ingest codes plus ``persist_not_implemented``,
            ``invalid_assumption_node_id``, ``conflicting_assumptions``, ``assumptions_cap_exceeded``.
            """
            try:
                async with mcp_invocation_scope("smeme_reasoning_what_if", ctx) as rec:
                    rec.note_decision_tree_id(decision_tree_id)
                    out = await _smeme_reasoning_what_if_body(
                        decision_tree_id=decision_tree_id,
                        base_raw_answers_json=base_raw_answers_json,
                        override_raw_answers_json=override_raw_answers_json,
                        ctx=ctx,
                        persist=persist,
                        force_reachable_ids=force_reachable_ids,
                        force_unreachable_ids=force_unreachable_ids,
                    )
                    rec.note_json_response(out)
                    return out
            except Exception:
                logger.exception(
                    "smeme_reasoning_what_if failed", extra={"decision_tree_id": decision_tree_id}
                )
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        async def _smeme_reasoning_how_to_reach_body(
            decision_tree_id: str,
            base_raw_answers_json: str,
            target_conclusion_id: str,
            ctx: Context,
            locked_question_ids: list[str] | None = None,
            max_changes: int = 3,
            top_k: int = 3,
            persist: bool = False,
            reach_mode: str = "entailed",
            force_reachable_ids: list[str] | None = None,
            force_unreachable_ids: list[str] | None = None,
        ) -> str:
            persist_err = _mcp_counterfactual_persist_gate(persist)
            if persist_err is not None:
                return persist_err

            base_payload = _mcp_parse_json_object(
                base_raw_answers_json,
                field_name="base_raw_answers_json",
                decision_tree_id=decision_tree_id,
            )
            if isinstance(base_payload, str):
                return base_payload

            try:
                decision_tree_uuid = UUID(decision_tree_id)
            except ValueError:
                return tool_error_json(
                    "invalid_decision_tree_id",
                    f"decision_tree_id must be a valid UUID, got {decision_tree_id!r}",
                )

            request = request_from_mcp_context(ctx)
            async with AsyncSessionLocal() as db:
                user_or_err = await _mcp_auth_user_only(request, db)
                if isinstance(user_or_err, str):
                    return user_or_err
                user = user_or_err

                loaded = await _mcp_load_owner_reasoning_context(
                    db, user=user, decision_tree_uuid=decision_tree_uuid
                )
                if isinstance(loaded, str):
                    return loaded
                _decision_tree, artifact, graph, live_hash = loaded
                if live_hash != artifact.graph_hash:
                    return tool_error_json(
                        "stale_theory",
                        "This decision tree has changed since it was last published. "
                        "Re-publish it from the SMEme editor, then retry the same answers.",
                    )

                quota_err = await _mcp_reserve_quota_and_bind(
                    request,
                    db,
                    user,
                    tool_name="smeme_reasoning_how_to_reach",
                )
                if quota_err is not None:
                    return quota_err

                try:
                    ir = ir_from_json(artifact.ir_json)
                except (KeyError, ValueError, TypeError) as exc:
                    return tool_error_json(
                        "invalid_graph", f"Published reasoning data could not be read: {exc}"
                    )

                try:
                    flat_answers, ingest_env, ingest_warnings, _ = await asyncio.to_thread(
                        prepare_evaluate_ingest, ir, base_payload
                    )
                except ReasoningIngestError as exc:
                    log_reasoning_ingest_hard_reject(
                        logger,
                        code=exc.code.value,
                        message=exc.message,
                        decision_tree_id=decision_tree_uuid,
                        caller_user_id=user.id,
                        transport="mcp",
                    )
                    return tool_error_json(exc.code.value, exc.message, **exc.details)

                base_norm = normalized_from_answers(flat_answers)

                try:
                    phi = assumptions_from_lists(force_reachable_ids, force_unreachable_ids)
                    htr = await asyncio.to_thread(
                        find_repairs_for_target,
                        ir,
                        graph,
                        base_norm=base_norm,
                        base_envelope=ingest_env,
                        target_conclusion_id=target_conclusion_id,
                        locked_question_ids=locked_question_ids or [],
                        max_changes=max_changes,
                        top_k=top_k,
                        reach_mode=reach_mode,
                        assumptions=phi,
                    )
                except CounterfactualError as exc:
                    return tool_error_json(exc.code, exc.message, **exc.details)
                except AssumptionsError as exc:
                    return tool_error_json(exc.code, exc.message, **exc.details)
                except ReasoningInputValidationError as exc:
                    return tool_error_json("invalid_answers", str(exc))

                htr.warnings = ingest_warnings

            return _tool_json(how_to_reach_to_wire(htr))

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Find answers to reach a conclusion",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
            )
        )
        async def smeme_reasoning_how_to_reach(
            decision_tree_id: str,
            base_raw_answers_json: str,
            target_conclusion_id: str,
            ctx: Context,
            locked_question_ids: list[str] | None = None,
            max_changes: int = 3,
            top_k: int = 3,
            persist: bool = False,
            reach_mode: str = "entailed",
            force_reachable_ids: list[str] | None = None,
            force_unreachable_ids: list[str] | None = None,
        ) -> str:
            """Find cardinality-minimal answer-edit plans that would reach a target outcome.

            ``target_conclusion_id`` must come from ``smeme_reasoning_list_conclusions`` for the
            same decision tree — not from evaluate ``report`` output. Returns up to ``top_k`` plans with
            ``preview_report`` per plan.

            ``reach_mode`` (default ``entailed``):
            - ``entailed`` — baseline/plans must force the target under every completion of
              unanswered questions.
            - ``possible`` — baseline/plans only need some completing assignment that can
              still reach the target (weaker; useful for research probes).

            Optional ``force_reachable_ids`` / ``force_unreachable_ids`` assert path assumptions
            (same as evaluate). ``locked_question_ids`` still control which answered questions
            may be edited.

            When the ``satisfiable`` field is false, read ``blockers.code`` (``no_plan_within_max_changes``
            or ``search_cap_exceeded``) — same semantics as skill error tables.

            Args:
                decision_tree_id: UUID from ``smeme_reasoning_list``.
                base_raw_answers_json: Baseline provenance envelope JSON object.
                target_conclusion_id: IR conclusion node id from ``smeme_reasoning_list_conclusions``.
                locked_question_ids: Question ids that must not be edited.
                max_changes: Server cap ≤ 5 (default 3).
                top_k: Server cap ≤ 10 (default 3).
                persist: v1 supports ``false`` only.
                reach_mode: ``entailed`` (default) or ``possible``.
                force_reachable_ids: Optional IR node ids that must stay on the path.
                force_unreachable_ids: Optional IR node ids assumed off-path.

            Requires ``Authorization: Bearer <Clerk OAuth token>``.

            Error codes: ``invalid_target_conclusion_id``, ``invalid_locked_question_id``,
            ``invalid_reach_mode``, ``invalid_assumption_node_id``, ``conflicting_assumptions``,
            ``assumptions_cap_exceeded``, ``target_not_reachable_under_locks``, ``solver_timeout``,
            ``persist_not_implemented``, plus shared ingest/evaluate codes.
            """
            try:
                async with mcp_invocation_scope("smeme_reasoning_how_to_reach", ctx) as rec:
                    rec.note_decision_tree_id(decision_tree_id)
                    out = await _smeme_reasoning_how_to_reach_body(
                        decision_tree_id=decision_tree_id,
                        base_raw_answers_json=base_raw_answers_json,
                        target_conclusion_id=target_conclusion_id,
                        ctx=ctx,
                        locked_question_ids=locked_question_ids,
                        max_changes=max_changes,
                        top_k=top_k,
                        persist=persist,
                        reach_mode=reach_mode,
                        force_reachable_ids=force_reachable_ids,
                        force_unreachable_ids=force_unreachable_ids,
                    )
                    rec.note_json_response(out)
                    return out
            except Exception:
                logger.exception(
                    "smeme_reasoning_how_to_reach failed",
                    extra={"decision_tree_id": decision_tree_id},
                )
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        async def _smeme_reasoning_decisive_support_body(
            decision_tree_id: str,
            base_raw_answers_json: str,
            target_conclusion_id: str,
            ctx: Context,
            top_k: int = 3,
            persist: bool = False,
            force_reachable_ids: list[str] | None = None,
            force_unreachable_ids: list[str] | None = None,
        ) -> str:
            persist_err = _mcp_counterfactual_persist_gate(persist)
            if persist_err is not None:
                return persist_err

            base_payload = _mcp_parse_json_object(
                base_raw_answers_json,
                field_name="base_raw_answers_json",
                decision_tree_id=decision_tree_id,
            )
            if isinstance(base_payload, str):
                return base_payload

            try:
                decision_tree_uuid = UUID(decision_tree_id)
            except ValueError:
                return tool_error_json(
                    "invalid_decision_tree_id",
                    f"decision_tree_id must be a valid UUID, got {decision_tree_id!r}",
                )

            request = request_from_mcp_context(ctx)
            async with AsyncSessionLocal() as db:
                user_or_err = await _mcp_auth_user_only(request, db)
                if isinstance(user_or_err, str):
                    return user_or_err
                user = user_or_err

                loaded = await _mcp_load_owner_reasoning_context(
                    db, user=user, decision_tree_uuid=decision_tree_uuid
                )
                if isinstance(loaded, str):
                    return loaded
                _decision_tree, artifact, graph, live_hash = loaded
                if live_hash != artifact.graph_hash:
                    return tool_error_json(
                        "stale_theory",
                        "This decision tree has changed since it was last published. "
                        "Re-publish it from the SMEme editor, then retry the same answers.",
                    )

                quota_err = await _mcp_reserve_quota_and_bind(
                    request,
                    db,
                    user,
                    tool_name="smeme_reasoning_decisive_support",
                )
                if quota_err is not None:
                    return quota_err

                try:
                    ir = ir_from_json(artifact.ir_json)
                except (KeyError, ValueError, TypeError) as exc:
                    return tool_error_json(
                        "invalid_graph", f"Published reasoning data could not be read: {exc}"
                    )

                try:
                    flat_answers, _ingest_env, ingest_warnings, _ = await asyncio.to_thread(
                        prepare_evaluate_ingest, ir, base_payload
                    )
                except ReasoningIngestError as exc:
                    log_reasoning_ingest_hard_reject(
                        logger,
                        code=exc.code.value,
                        message=exc.message,
                        decision_tree_id=decision_tree_uuid,
                        caller_user_id=user.id,
                        transport="mcp",
                    )
                    return tool_error_json(exc.code.value, exc.message, **exc.details)

                base_norm = normalized_from_answers(flat_answers)
                phi = assumptions_from_lists(force_reachable_ids, force_unreachable_ids)
                try:
                    result = await asyncio.to_thread(
                        find_minimal_decisive_supports,
                        ir,
                        graph,
                        base_norm=base_norm,
                        target_conclusion_id=target_conclusion_id,
                        top_k=top_k,
                        assumptions=phi,
                    )
                except DecisiveSupportError as exc:
                    return tool_error_json(exc.code, exc.message, **exc.details)
                except AssumptionsError as exc:
                    return tool_error_json(exc.code, exc.message, **exc.details)
                except ReasoningInputValidationError as exc:
                    return tool_error_json("invalid_answers", str(exc))

                result.warnings = ingest_warnings

            return _tool_json(result.to_wire())

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Minimal answers that force a conclusion",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
            )
        )
        async def smeme_reasoning_decisive_support(
            decision_tree_id: str,
            base_raw_answers_json: str,
            target_conclusion_id: str,
            ctx: Context,
            top_k: int = 3,
            persist: bool = False,
            force_reachable_ids: list[str] | None = None,
            force_unreachable_ids: list[str] | None = None,
        ) -> str:
            """Find minimal sufficient answered-question supports that force a conclusion.

            Requires the current answers (plus optional path assumptions) to already force
            ``target_conclusion_id``. Returns worksheet-vocabulary supports only (question ids
            and option strings) — not branch rules or graph topology. ``T`` and ``E`` are not
            rewritten; only a subset ``S ⊆ E`` is searched.

            This is **minimal sufficient evidence**, not abduction under incomplete or
            conflicting answers. Use after a concluded evaluate when the user asks which
            answers mattered. When the target is not yet forced, use
            ``smeme_reasoning_how_to_reach`` (repair) instead. Do not call this to repair
            inconsistent answers.

            Args:
                decision_tree_id: UUID from ``smeme_reasoning_list``.
                base_raw_answers_json: Provenance envelope JSON object (same as evaluate).
                target_conclusion_id: From ``smeme_reasoning_list_conclusions``.
                top_k: Max inclusion-minimal supports to return (default 3, hard cap 10).
                persist: v1 supports ``false`` only; ``true`` returns ``persist_not_implemented``.
                force_reachable_ids: Optional IR node ids that must stay on the path.
                force_unreachable_ids: Optional IR node ids assumed off-path.

            Requires ``Authorization: Bearer <Clerk OAuth token>``.

            Error codes include ``target_not_entailed``, ``invalid_target_conclusion_id``,
            ``invalid_assumption_node_id``, ``conflicting_assumptions``, ``assumptions_cap_exceeded``,
            ``solver_timeout``, ``search_cap_exceeded``, ``persist_not_implemented``.
            """
            try:
                async with mcp_invocation_scope("smeme_reasoning_decisive_support", ctx) as rec:
                    rec.note_decision_tree_id(decision_tree_id)
                    out = await _smeme_reasoning_decisive_support_body(
                        decision_tree_id=decision_tree_id,
                        base_raw_answers_json=base_raw_answers_json,
                        target_conclusion_id=target_conclusion_id,
                        ctx=ctx,
                        top_k=top_k,
                        persist=persist,
                        force_reachable_ids=force_reachable_ids,
                        force_unreachable_ids=force_unreachable_ids,
                    )
                    rec.note_json_response(out)
                    return out
            except Exception:
                logger.exception(
                    "smeme_reasoning_decisive_support failed",
                    extra={"decision_tree_id": decision_tree_id},
                )
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        async def _smeme_reasoning_edit_affects_path_body(
            decision_tree_id: str,
            base_raw_answers_json: str,
            override_raw_answers_json: str,
            ctx: Context,
            persist: bool,
            force_reachable_ids: list[str] | None = None,
            force_unreachable_ids: list[str] | None = None,
        ) -> str:
            persist_err = _mcp_counterfactual_persist_gate(persist)
            if persist_err is not None:
                return persist_err

            base_payload = _mcp_parse_json_object(
                base_raw_answers_json,
                field_name="base_raw_answers_json",
                decision_tree_id=decision_tree_id,
            )
            if isinstance(base_payload, str):
                return base_payload
            override_payload = _mcp_parse_json_object(
                override_raw_answers_json,
                field_name="override_raw_answers_json",
                decision_tree_id=decision_tree_id,
            )
            if isinstance(override_payload, str):
                return override_payload

            try:
                decision_tree_uuid = UUID(decision_tree_id)
            except ValueError:
                return tool_error_json(
                    "invalid_decision_tree_id",
                    f"decision_tree_id must be a valid UUID, got {decision_tree_id!r}",
                )

            request = request_from_mcp_context(ctx)
            async with AsyncSessionLocal() as db:
                user_or_err = await _mcp_auth_user_only(request, db)
                if isinstance(user_or_err, str):
                    return user_or_err
                user = user_or_err

                loaded = await _mcp_load_owner_reasoning_context(
                    db, user=user, decision_tree_uuid=decision_tree_uuid
                )
                if isinstance(loaded, str):
                    return loaded
                _decision_tree, artifact, graph, live_hash = loaded
                if live_hash != artifact.graph_hash:
                    return tool_error_json(
                        "stale_theory",
                        "This decision tree has changed since it was last published. "
                        "Re-publish it from the SMEme editor, then retry the same answers.",
                    )

                quota_err = await _mcp_reserve_quota_and_bind(
                    request,
                    db,
                    user,
                    tool_name="smeme_reasoning_edit_affects_path",
                )
                if quota_err is not None:
                    return quota_err

                try:
                    ir = ir_from_json(artifact.ir_json)
                except (KeyError, ValueError, TypeError) as exc:
                    return tool_error_json(
                        "invalid_graph", f"Published reasoning data could not be read: {exc}"
                    )

                phi = assumptions_from_lists(force_reachable_ids, force_unreachable_ids)
                try:
                    result = await asyncio.to_thread(
                        run_edit_affects_path,
                        ir,
                        graph,
                        base_payload=base_payload,
                        override_payload=override_payload,
                        assumptions=phi,
                    )
                except PathUnderEditError as exc:
                    return tool_error_json(exc.code, exc.message, **exc.details)
                except AssumptionsError as exc:
                    return tool_error_json(exc.code, exc.message, **exc.details)
                except ReasoningIngestError as exc:
                    log_reasoning_ingest_hard_reject(
                        logger,
                        code=exc.code.value,
                        message=exc.message,
                        decision_tree_id=decision_tree_uuid,
                        caller_user_id=user.id,
                        transport="mcp",
                    )
                    return tool_error_json(exc.code.value, exc.message, **exc.details)
                except ReasoningInputValidationError as exc:
                    return tool_error_json("invalid_answers", str(exc))

            return _tool_json(result.to_wire())

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Does an edit affect the current path",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
            )
        )
        async def smeme_reasoning_edit_affects_path(
            decision_tree_id: str,
            base_raw_answers_json: str,
            override_raw_answers_json: str,
            ctx: Context,
            persist: bool = False,
            force_reachable_ids: list[str] | None = None,
            force_unreachable_ids: list[str] | None = None,
        ) -> str:
            """Check whether a hypothetical answer change would affect the current decision path (does the path stay forced?). Use ``smeme_reasoning_what_if`` instead when the user wants to see the alternate world after the change. Not for “which current answers were sufficient” — that is ``smeme_reasoning_decisive_support``.

            Returns whether the baseline path remains forced under the merged override, which path
            steps (if any) are no longer forced, and a conclusion-entailment side-car (still /
            newly / no longer forced). Optional ``force_reachable_ids`` /
            ``force_unreachable_ids`` apply the same path assumptions as evaluate.

            When the user asks both “what if X?” and “does that affect this path?”, call
            ``smeme_reasoning_what_if`` and this tool with the same base + override — do not
            collapse into one call.

            Args:
                decision_tree_id: UUID from ``smeme_reasoning_list``.
                base_raw_answers_json: Provenance envelope JSON object (same as evaluate).
                override_raw_answers_json: Provenance envelope with hypothetical answer changes
                    (override wins per question id).
                persist: v1 supports ``false`` only; ``true`` returns ``persist_not_implemented``.
                force_reachable_ids: Optional IR node ids that must stay on the path.
                force_unreachable_ids: Optional IR node ids assumed off-path.

            Requires ``Authorization: Bearer <Clerk OAuth token>``.

            Error codes include ``path_not_entailed_at_baseline``, ``invalid_assumption_node_id``,
            ``conflicting_assumptions``, ``assumptions_cap_exceeded``, ``solver_timeout``,
            ``search_cap_exceeded``, ``persist_not_implemented``.
            """
            try:
                async with mcp_invocation_scope("smeme_reasoning_edit_affects_path", ctx) as rec:
                    rec.note_decision_tree_id(decision_tree_id)
                    out = await _smeme_reasoning_edit_affects_path_body(
                        decision_tree_id=decision_tree_id,
                        base_raw_answers_json=base_raw_answers_json,
                        override_raw_answers_json=override_raw_answers_json,
                        ctx=ctx,
                        persist=persist,
                        force_reachable_ids=force_reachable_ids,
                        force_unreachable_ids=force_unreachable_ids,
                    )
                    rec.note_json_response(out)
                    return out
            except Exception:
                logger.exception(
                    "smeme_reasoning_edit_affects_path failed",
                    extra={"decision_tree_id": decision_tree_id},
                )
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        @_holder.tool(
            annotations=ToolAnnotations(
                title="List possible conclusions",
                readOnlyHint=True,
            )
        )
        async def smeme_reasoning_list_conclusions(decision_tree_id: str, ctx: Context) -> str:
            """List the possible conclusions for a published decision tree (no answers required).

            Returns each conclusion's ``conclusion_id`` and ``conclusion_title`` plus whether it is
            **reachable** under the published branching rules. Use this before probing with
            ``smeme_reasoning_evaluate`` / ``smeme_reasoning_evaluate_answers`` when the user asks what outcomes exist, or to obtain
            ``target_conclusion_id`` values for ``smeme_reasoning_how_to_reach`` or
            ``smeme_reasoning_decisive_support``.

            Reachability is **structural** (whether some valid answer path can reach the conclusion),
            not case-specific. For a particular user's answers, call ``smeme_reasoning_evaluate``
            (guided) or ``smeme_reasoning_evaluate_answers`` (bulk worksheet).

            Args:
                decision_tree_id: UUID from ``smeme_reasoning_list``.

            Requires ``Authorization: Bearer <Clerk OAuth token>``.
            """
            try:
                async with mcp_invocation_scope("smeme_reasoning_list_conclusions", ctx) as rec:
                    rec.note_decision_tree_id(decision_tree_id)
                    try:
                        decision_tree_uuid = UUID(decision_tree_id)
                    except ValueError:
                        err = tool_error_json(
                            "invalid_decision_tree_id",
                            f"decision_tree_id must be a valid UUID, got {decision_tree_id!r}",
                        )
                        rec.note_json_response(err)
                        return err

                    request = request_from_mcp_context(ctx)
                    async with AsyncSessionLocal() as db:
                        user_or_err = await _mcp_auth_user_only(request, db)
                        if isinstance(user_or_err, str):
                            rec.note_json_response(user_or_err)
                            return user_or_err

                        loaded = await _mcp_load_owner_reasoning_context(
                            db, user=user_or_err, decision_tree_uuid=decision_tree_uuid
                        )
                        if isinstance(loaded, str):
                            rec.note_json_response(loaded)
                            return loaded
                        decision_tree, artifact, graph, live_hash = loaded
                        if live_hash != artifact.graph_hash:
                            err = tool_error_json(
                                "stale_theory",
                                "This decision tree has changed since it was last published. "
                                "Re-publish it from the SMEme editor, then try again.",
                            )
                            rec.note_json_response(err)
                            return err

                        try:
                            ir = ir_from_json(artifact.ir_json)
                        except (KeyError, ValueError, TypeError) as exc:
                            err = tool_error_json(
                                "invalid_graph",
                                f"Published reasoning data could not be read: {exc}",
                            )
                            rec.note_json_response(err)
                            return err

                        enumeration = await asyncio.to_thread(
                            enumerate_conclusion_sat_queries, ir, validate=False
                        )
                        payload = _tool_json(
                            build_conclusions_catalog_wire(
                                decision_tree_id=decision_tree.id,
                                graph=graph,
                                enumeration=enumeration,
                            )
                        )
                        rec.note_json_response(payload)
                        return payload
            except Exception:
                logger.exception(
                    "smeme_reasoning_list_conclusions failed",
                    extra={"decision_tree_id": decision_tree_id},
                )
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        async def _reasoning_template_load(
            decision_tree_id: str, ctx: Context
        ) -> dict[str, Any] | str:
            try:
                decision_tree_uuid = UUID(decision_tree_id)
            except ValueError:
                return tool_error_json(
                    "invalid_decision_tree_id",
                    f"decision_tree_id must be a valid UUID, got {decision_tree_id!r}",
                )
            request = request_from_mcp_context(ctx)
            async with AsyncSessionLocal() as db:
                try:
                    user = await get_mcp_user(request, db)
                except MCPAuthError as exc:
                    return auth_error_tool_json(exc)
                bind_mcp_user(user, request=request)

                loaded = await _mcp_load_owner_reasoning_context(
                    db, user=user, decision_tree_uuid=decision_tree_uuid
                )
                if isinstance(loaded, str):
                    return loaded
                decision_tree, artifact, graph, live_hash = loaded
                manifest_core = build_manifest_core(graph, decision_tree.id)
                digest = manifest_core_digest(manifest_core)
                generated_at = utc_generated_at_iso_z()
                slug = safe_worksheet_slug(decision_tree.title)
                return {
                    "decision_tree_id": decision_tree.id,
                    "decision_tree_title": decision_tree.title,
                    "intended_audience": decision_tree.intended_audience,
                    "use_case": decision_tree.use_case,
                    "compiled_graph_hash": artifact.graph_hash,
                    "live_hash": live_hash,
                    "manifest_core": manifest_core,
                    "digest": digest,
                    "generated_at": generated_at,
                    "slug": slug,
                }

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Check worksheet sync",
                readOnlyHint=True,
            )
        )
        async def smeme_reasoning_template_check(decision_tree_id: str, ctx: Context) -> str:
            """Is my reasoning worksheet up to date for this decision tree? — minimal agent-facing probe.

            Same auth and gates as ``smeme_reasoning_evaluate`` (owner, ``mcp_discoverable``, compiled artifact).
            Returns ``decision_tree_id``, ``slug`` (filesystem-safe fragment from the decision tree title, aligned with
            ``template_get``'s suggested path), ``in_sync``, and ``manifest_core_digest`` so clients
            can (a) detect live vs last-published graph drift, (b) name local worksheet files, and
            (c) skip ``template_get`` when a cached digest still matches — without exposing compiler /
            CEVI / graph-hash telemetry to the LLM surface.

            When ``in_sync`` is false, the user should re-publish from the SMEme web app; direction of
            drift is intentionally omitted. Does **not** return ``stale_theory`` when the live graph
            differs — use ``in_sync: false`` (Option A).

            Args:
                decision_tree_id: UUID string for the decision tree.

            Requires ``Authorization: Bearer <Clerk OAuth token>``.
            """
            try:
                async with mcp_invocation_scope("smeme_reasoning_template_check", ctx) as rec:
                    rec.note_decision_tree_id(decision_tree_id)
                    loaded = await _reasoning_template_load(decision_tree_id, ctx)
                    if isinstance(loaded, str):
                        rec.note_json_response(loaded)
                        return loaded
                    out = _tool_json(
                        {
                            "decision_tree_id": str(loaded["decision_tree_id"]).lower(),
                            "slug": loaded["slug"],
                            "in_sync": loaded["live_hash"] == loaded["compiled_graph_hash"],
                            "manifest_core_digest": loaded["digest"],
                        }
                    )
                    rec.note_json_response(out)
                    return out
            except Exception:
                logger.exception(
                    "smeme_reasoning_template_check failed",
                    extra={"decision_tree_id": decision_tree_id},
                )
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Get reasoning worksheet",
                readOnlyHint=True,
            )
        )
        async def smeme_reasoning_template_get(decision_tree_id: str, ctx: Context) -> str:
            """Download the per-decision-tree reasoning worksheet — markdown prompt for slot-filling answers.

            Returns ``manifest_markdown`` (question ids, labels, and allowed option strings) plus
            a small envelope: ``manifest_core_digest``, ``in_sync``, ``suggested_relative_path``.
            No duplicate ``manifest_core`` JSON on the wire — use the markdown body only.
            On oversized worksheets, returns ``payload_too_large`` with **no** partial body.

            Args:
                decision_tree_id: UUID string for the decision tree.

            Requires ``Authorization: Bearer <Clerk OAuth token>``.
            """
            try:
                async with mcp_invocation_scope("smeme_reasoning_template_get", ctx) as rec:
                    rec.note_decision_tree_id(decision_tree_id)
                    loaded = await _reasoning_template_load(decision_tree_id, ctx)
                    if isinstance(loaded, str):
                        rec.note_json_response(loaded)
                        return loaded
                    in_sync = loaded["live_hash"] == loaded["compiled_graph_hash"]
                    slug = loaded["slug"]
                    md = render_manifest_markdown(
                        manifest_core=loaded["manifest_core"],
                        title=loaded["decision_tree_title"],
                        decision_tree_id=loaded["decision_tree_id"],
                        slug=slug,
                        intended_audience=loaded["intended_audience"],
                        use_case=loaded["use_case"],
                    )
                    out: dict[str, Any] = {
                        "manifest_markdown": md,
                        "manifest_core_digest": loaded["digest"],
                        "in_sync": in_sync,
                        "suggested_relative_path": f"decision_tree_specific_skills/smeme-reasoning-worksheet-{slug}.md",
                    }
                    if worksheet_payload_too_large(manifest_markdown=md, success_payload=out):
                        err = tool_error_json(
                            "payload_too_large",
                            "Worksheet exceeds the maximum size for this server version; shorten the "
                            "decision tree or split it into smaller decision trees, then retry.",
                        )
                        rec.note_json_response(err)
                        return err
                    payload = _tool_json(out)
                    rec.note_json_response(payload)
                    return payload
            except Exception:
                logger.exception(
                    "smeme_reasoning_template_get failed",
                    extra={"decision_tree_id": decision_tree_id},
                )
                return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

    return _holder


def get_or_create_orchestrator_fastmcp(s: Settings | None = None) -> FastMCP | None:
    """Create Inquire orchestrator FastMCP when ``MCP_INQUIRE_TOOLS_ENABLED``.

    Mounted at ``{mcp_http_path}/orchestrator``. Returns None when the flag is off.
    """
    global _orchestrator_holder
    cfg = s or settings
    if not cfg.mcp_inquire_tools_enabled:
        return None
    if _orchestrator_holder is not None:
        return _orchestrator_holder

    auth_settings, token_verifier = _fastmcp_clerk_auth(cfg)
    auth_kw: dict[str, Any] = {}
    if auth_settings is not None and token_verifier is not None:
        auth_kw["auth"] = auth_settings
        auth_kw["token_verifier"] = token_verifier

    transport_security = _build_transport_security(cfg)
    _orch = FastMCP(
        name="smeme-inquire-orchestrator",
        instructions=_build_orchestrator_mcp_instructions(cfg),
        stateless_http=True,
        transport_security=transport_security,
        **auth_kw,
    )

    @_orch.tool(
        annotations=ToolAnnotations(
            title="Reasoning capabilities (orchestrator)",
            readOnlyHint=True,
        )
    )
    async def smeme_reasoning_capabilities(ctx: Context) -> str:
        """Orchestrator surface capabilities (Inquire protocol contract)."""
        request = request_from_mcp_context(ctx)
        try:
            async with mcp_invocation_scope("smeme_reasoning_capabilities", ctx) as rec:
                async with AsyncSessionLocal() as db:
                    user_or_err = await _mcp_auth_user_only(request, db)
                    if isinstance(user_or_err, str):
                        rec.note_json_response(user_or_err)
                        return user_or_err
                out = _tool_json(
                    reasoning_capabilities_document(cap_settings=cfg, surface="orchestrator")
                )
                rec.note_json_response(out)
                return out
        except Exception:
            logger.exception("orchestrator smeme_reasoning_capabilities failed")
            return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

    @_orch.tool(
        annotations=ToolAnnotations(
            title="List decision trees",
            readOnlyHint=True,
        )
    )
    async def smeme_reasoning_list(ctx: Context) -> str:
        """List the caller's Listed + deployed decision trees (owner-scoped)."""
        request = request_from_mcp_context(ctx)
        try:
            async with (
                mcp_invocation_scope("smeme_reasoning_list", ctx) as rec,
                AsyncSessionLocal() as db,
            ):
                user_or_err = await _mcp_auth_user_only(request, db)
                if isinstance(user_or_err, str):
                    rec.note_json_response(user_or_err)
                    return user_or_err
                user = user_or_err
                result = await db.execute(select_decision_trees_for_assistant_tools_list(user.id))
                listed_rows = result.scalars().all()
                decision_trees = serialize_decision_trees_for_assistant_list(user, listed_rows)
                payload: dict[str, Any] = {
                    "decision_trees": decision_trees,
                    "count": len(decision_trees),
                }
                if not decision_trees:
                    payload["hint"] = (
                        "No decision trees are currently discoverable for your account. "
                        "Publish for reasoning and set Listed on the dashboard."
                    )
                out = _tool_json(payload)
                rec.note_json_response(out)
                return out
        except Exception:
            logger.exception("orchestrator smeme_reasoning_list failed")
            return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

    @_orch.tool(
        annotations=ToolAnnotations(
            title="Inquire guidance digest",
            readOnlyHint=True,
        )
    )
    async def smeme_inquire_guidance_check(ctx: Context) -> str:
        """Return Inquire orchestrator guidance content_version + content_digest."""
        request = request_from_mcp_context(ctx)
        try:
            async with mcp_invocation_scope("smeme_inquire_guidance_check", ctx) as rec:
                async with AsyncSessionLocal() as db:
                    user_or_err = await _mcp_auth_user_only(request, db)
                    if isinstance(user_or_err, str):
                        rec.note_json_response(user_or_err)
                        return user_or_err
                out = _tool_json(inquire_guidance_check_payload())
                rec.note_json_response(out)
                return out
        except Exception:
            logger.exception("smeme_inquire_guidance_check failed")
            return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

    @_orch.tool(
        annotations=ToolAnnotations(
            title="Inquire orchestrator guidance",
            readOnlyHint=True,
        )
    )
    async def smeme_inquire_guidance_get(ctx: Context) -> str:
        """Fetch the Inquire orchestrator protocol contract (VERIFY isolation)."""
        request = request_from_mcp_context(ctx)
        try:
            async with mcp_invocation_scope("smeme_inquire_guidance_get", ctx) as rec:
                async with AsyncSessionLocal() as db:
                    user_or_err = await _mcp_auth_user_only(request, db)
                    if isinstance(user_or_err, str):
                        rec.note_json_response(user_or_err)
                        return user_or_err
                out = _tool_json(inquire_guidance_payload())
                rec.note_json_response(out)
                return out
        except Exception:
            logger.exception("smeme_inquire_guidance_get failed")
            return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

    from smeme.mcp.inquire.handlers import InquireHandlerError
    from smeme.reasoning.orchestration.inquire.persist import (
        admit_to_session,
        get_task_for_session,
        next_directive,
        start_inquiry,
        verify_session,
    )

    @_orch.tool(
        annotations=ToolAnnotations(
            title="Inquire: start session",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
        )
    )
    async def smeme_inquire_start(
        decision_tree_id: str,
        ctx: Context,
        force_reachable_ids: list[str] | None = None,
        force_unreachable_ids: list[str] | None = None,
    ) -> str:
        """Trusted orchestrator: start a durable Inquire session on a deployed tree.

        Loads the current compiled artifact (in-sync), freezes worksheet catalog
        and artifact identity, runs ANALYZE, and returns inquiry_session_id,
        revision, and directive. Later calls carry only the session id.
        """
        try:
            async with mcp_invocation_scope("smeme_inquire_start", ctx) as rec:
                try:
                    decision_tree_uuid = UUID(decision_tree_id)
                except ValueError:
                    out = tool_error_json(
                        "invalid_decision_tree_id",
                        f"decision_tree_id must be a valid UUID, got {decision_tree_id!r}",
                    )
                    rec.note_json_response(out)
                    return out
                request = request_from_mcp_context(ctx)
                async with AsyncSessionLocal() as db:
                    user_or_err = await _mcp_auth_user_only(request, db)
                    if isinstance(user_or_err, str):
                        rec.note_json_response(user_or_err)
                        return user_or_err
                    user = user_or_err
                    loaded = await _mcp_load_owner_compiled_artifact(
                        db, user=user, decision_tree_uuid=decision_tree_uuid
                    )
                    if isinstance(loaded, str):
                        rec.note_json_response(loaded)
                        return loaded
                    decision_tree, artifact = loaded
                    try:
                        graph = parse_graph_data(decision_tree)
                    except Exception as exc:
                        out = tool_error_json("invalid_graph", f"Graph data invalid: {exc}")
                        rec.note_json_response(out)
                        return out
                    quota_err = await _mcp_reserve_quota_and_bind(
                        request,
                        db,
                        user,
                        tool_name="smeme_inquire_start",
                    )
                    if quota_err is not None:
                        rec.note_json_response(quota_err)
                        return quota_err
                    try:
                        payload = await start_inquiry(
                            db,
                            user=user,
                            decision_tree=decision_tree,
                            artifact=artifact,
                            graph=graph,
                            force_reachable_ids=force_reachable_ids,
                            force_unreachable_ids=force_unreachable_ids,
                        )
                    except InquireHandlerError as exc:
                        out = tool_error_json(exc.code, exc.message)
                        rec.note_json_response(out)
                        return out
                out = _tool_json(payload)
                rec.note_json_response(out)
                return out
        except Exception:
            logger.exception("smeme_inquire_start failed")
            return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

    @_orch.tool(
        annotations=ToolAnnotations(
            title="Inquire: next directive",
            readOnlyHint=True,
        )
    )
    async def smeme_inquire_next(
        inquiry_session_id: str,
        ctx: Context,
        expected_revision: int | None = None,
    ) -> str:
        """Trusted orchestrator: re-ANALYZE persisted session state (read-only).

        Does not mutate session status or revision. Returns directive and
        optional evaluations[] when VERIFY.
        """
        try:
            async with mcp_invocation_scope("smeme_inquire_next", ctx) as rec:
                try:
                    session_uuid = UUID(inquiry_session_id)
                except ValueError:
                    out = tool_error_json(
                        "inquire_invalid_payload",
                        "inquiry_session_id must be a valid UUID",
                    )
                    rec.note_json_response(out)
                    return out
                request = request_from_mcp_context(ctx)
                async with AsyncSessionLocal() as db:
                    user_or_err = await _mcp_auth_user_only(request, db)
                    if isinstance(user_or_err, str):
                        rec.note_json_response(user_or_err)
                        return user_or_err
                    try:
                        payload = await next_directive(
                            db,
                            user=user_or_err,
                            inquiry_session_id=session_uuid,
                            expected_revision=expected_revision,
                        )
                    except InquireHandlerError as exc:
                        out = tool_error_json(exc.code, exc.message)
                        rec.note_json_response(out)
                        return out
                out = _tool_json(payload)
                rec.note_json_response(out)
                return out
        except Exception:
            logger.exception("smeme_inquire_next failed")
            return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

    @_orch.tool(
        annotations=ToolAnnotations(
            title="Inquire: get blind extraction task",
            readOnlyHint=True,
        )
    )
    async def smeme_inquire_get_task(
        inquiry_session_id: str,
        question_id: str,
        ctx: Context,
    ) -> str:
        """Trusted orchestrator: render one blind worksheet question.

        Catalog comes from the session's frozen snapshot. Returns only
        ``{question_id, stem, options}``. Safe to forward to an extractor.
        """
        try:
            async with mcp_invocation_scope("smeme_inquire_get_task", ctx) as rec:
                try:
                    session_uuid = UUID(inquiry_session_id)
                except ValueError:
                    out = tool_error_json(
                        "inquire_invalid_payload",
                        "inquiry_session_id must be a valid UUID",
                    )
                    rec.note_json_response(out)
                    return out
                request = request_from_mcp_context(ctx)
                async with AsyncSessionLocal() as db:
                    user_or_err = await _mcp_auth_user_only(request, db)
                    if isinstance(user_or_err, str):
                        rec.note_json_response(user_or_err)
                        return user_or_err
                    try:
                        payload = await get_task_for_session(
                            db,
                            user=user_or_err,
                            inquiry_session_id=session_uuid,
                            question_id=question_id,
                        )
                    except InquireHandlerError as exc:
                        out = tool_error_json(exc.code, exc.message)
                        rec.note_json_response(out)
                        return out
                out = _tool_json(payload)
                rec.note_json_response(out)
                return out
        except Exception:
            logger.exception("smeme_inquire_get_task failed")
            return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

    @_orch.tool(
        annotations=ToolAnnotations(
            title="Inquire: admit extraction",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
        )
    )
    async def smeme_inquire_admit(
        inquiry_session_id: str,
        expected_revision: int,
        question_id: str,
        idempotency_key: str,
        ctx: Context,
        selected_option: str | None = None,
        provenance_id: str | None = None,
    ) -> str:
        """Trusted orchestrator: admit an ACQUIRE answer (or abstain) on a session.

        Requires expected_revision and idempotency_key. Returns updated revision
        and the next directive from post-mutation ANALYZE.
        """
        try:
            async with mcp_invocation_scope("smeme_inquire_admit", ctx) as rec:
                try:
                    session_uuid = UUID(inquiry_session_id)
                except ValueError:
                    out = tool_error_json(
                        "inquire_invalid_payload",
                        "inquiry_session_id must be a valid UUID",
                    )
                    rec.note_json_response(out)
                    return out
                request = request_from_mcp_context(ctx)
                async with AsyncSessionLocal() as db:
                    user_or_err = await _mcp_auth_user_only(request, db)
                    if isinstance(user_or_err, str):
                        rec.note_json_response(user_or_err)
                        return user_or_err
                    user = user_or_err
                    quota_err = await _mcp_reserve_quota_and_bind(
                        request,
                        db,
                        user,
                        tool_name="smeme_inquire_admit",
                    )
                    if quota_err is not None:
                        rec.note_json_response(quota_err)
                        return quota_err
                    try:
                        payload = await admit_to_session(
                            db,
                            user=user,
                            inquiry_session_id=session_uuid,
                            expected_revision=expected_revision,
                            question_id=question_id,
                            selected_option=selected_option,
                            provenance_id=provenance_id,
                            idempotency_key=idempotency_key,
                        )
                    except InquireHandlerError as exc:
                        out = tool_error_json(exc.code, exc.message)
                        rec.note_json_response(out)
                        return out
                out = _tool_json(payload)
                rec.note_json_response(out)
                return out
        except Exception:
            logger.exception("smeme_inquire_admit failed")
            return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

    @_orch.tool(
        annotations=ToolAnnotations(
            title="Inquire: verify observation transcript",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
        )
    )
    async def smeme_inquire_verify(
        inquiry_session_id: str,
        expected_revision: int,
        verification_key_json: str,
        observations_json: str,
        idempotency_key: str,
        ctx: Context,
    ) -> str:
        """Submit VERIFY observations; Core runs P_v. Do not decide Retain.

        Isolation required: each evaluations[] trial in a fresh evaluator
        context; forward only {question_id, stem, options}; no prior answers,
        verification_key, or sibling trial results in that context.
        """
        try:
            async with mcp_invocation_scope("smeme_inquire_verify", ctx) as rec:
                try:
                    session_uuid = UUID(inquiry_session_id)
                except ValueError:
                    out = tool_error_json(
                        "inquire_invalid_payload",
                        "inquiry_session_id must be a valid UUID",
                    )
                    rec.note_json_response(out)
                    return out
                import json as _json

                try:
                    verification_key = _json.loads(verification_key_json)
                    observations = _json.loads(observations_json)
                except _json.JSONDecodeError as exc:
                    out = tool_error_json(
                        "inquire_invalid_payload",
                        f"verification_key_json or observations_json invalid: {exc}",
                    )
                    rec.note_json_response(out)
                    return out
                if not isinstance(verification_key, dict):
                    out = tool_error_json(
                        "inquire_invalid_payload",
                        "verification_key_json must be a JSON object",
                    )
                    rec.note_json_response(out)
                    return out
                if not isinstance(observations, list):
                    out = tool_error_json(
                        "inquire_invalid_payload",
                        "observations_json must be a JSON array",
                    )
                    rec.note_json_response(out)
                    return out
                request = request_from_mcp_context(ctx)
                async with AsyncSessionLocal() as db:
                    user_or_err = await _mcp_auth_user_only(request, db)
                    if isinstance(user_or_err, str):
                        rec.note_json_response(user_or_err)
                        return user_or_err
                    user = user_or_err
                    quota_err = await _mcp_reserve_quota_and_bind(
                        request,
                        db,
                        user,
                        tool_name="smeme_inquire_verify",
                    )
                    if quota_err is not None:
                        rec.note_json_response(quota_err)
                        return quota_err
                    try:
                        payload = await verify_session(
                            db,
                            user=user,
                            inquiry_session_id=session_uuid,
                            expected_revision=expected_revision,
                            verification_key=verification_key,
                            observations=observations,
                            idempotency_key=idempotency_key,
                        )
                    except InquireHandlerError as exc:
                        out = tool_error_json(exc.code, exc.message)
                        rec.note_json_response(out)
                        return out
                out = _tool_json(payload)
                rec.note_json_response(out)
                return out
        except Exception:
            logger.exception("smeme_inquire_verify failed")
            return tool_error_json("internal_error", INTERNAL_ERROR_MESSAGE)

    _orchestrator_holder = _orch
    return _orchestrator_holder


def get_orchestrator_mcp_starlette_app(s: Settings | None = None) -> Starlette | None:
    """Starlette sub-app for the Inquire orchestrator mount, or None if disabled."""
    global _starlette_orchestrator_mcp
    fm = get_or_create_orchestrator_fastmcp(s)
    if fm is None:
        return None
    if _starlette_orchestrator_mcp is None:
        _starlette_orchestrator_mcp = fm.streamable_http_app()
    return _starlette_orchestrator_mcp


def get_mcp_starlette_app(s: Settings | None = None) -> Starlette:
    """Return the Starlette sub-app for Streamable HTTP MCP transport.

    FastMCP generates this app via ``fm.streamable_http_app()``.  It exposes a
    single route at ``"/"`` (which maps to ``settings.mcp_http_path`` after mount).

    The result is cached in ``_starlette_mcp`` so the same Starlette app instance
    is used for all requests (consistent with the singleton FastMCP).
    """
    global _starlette_mcp
    fm = get_or_create_fastmcp(s)
    if _starlette_mcp is None:
        _starlette_mcp = fm.streamable_http_app()
    return _starlette_mcp


@asynccontextmanager
async def mcp_lifespan() -> AsyncIterator[None]:
    """Drive FastMCP session manager lifecycle(s).

    ``StreamableHTTPSessionManager.run()`` must be active for the duration of the
    process even in stateless mode — it initializes internal state and runs cleanup
    hooks.  Without this, the first MCP request may fail with an "uninitialized
    session manager" error.

    When Inquire orchestrator is enabled, both chat and orchestrator session
    managers run for the process lifetime.
    """
    fm = get_or_create_fastmcp()
    orch = get_or_create_orchestrator_fastmcp()
    if orch is None:
        async with fm.session_manager.run():
            yield
        return
    async with fm.session_manager.run(), orch.session_manager.run():
        yield


def mount_mcp_on_app(app: FastAPI, s: Settings | None = None) -> None:
    """Mount chat MCP and (optionally) Inquire orchestrator MCP sub-apps.

    Register the **longer** orchestrator path first so ``/api/v1/mcp`` does not
    swallow ``/api/v1/mcp/orchestrator``.
    """
    cfg = s or settings
    path = cfg.mcp_http_path.rstrip("/") or "/api/v1/mcp"
    orch_app = get_orchestrator_mcp_starlette_app(cfg)
    if orch_app is not None:
        orch_path = mcp_orchestrator_http_path(cfg)
        app.mount(orch_path, StripLastEventIdMiddleware(orch_app))
    starlette_app = get_mcp_starlette_app(cfg)
    app.mount(path, StripLastEventIdMiddleware(starlette_app))
