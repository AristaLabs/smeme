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
- ``smeme_reasoning_evaluate`` — runs evaluation; persists audit row; returns ``report`` JSON (product memo).
- ``smeme_reasoning_what_if`` — compare baseline vs override assignments; report-vocabulary delta; optional shared reach assumptions.
- ``smeme_reasoning_how_to_reach`` — bounded answer-edit repair plans for a target conclusion.
- ``smeme_reasoning_decisive_support`` — minimal sufficient evidence: inclusion-minimal answered-question supports that force a target conclusion (fixed ``T`` and ``E``).
- ``smeme_reasoning_edit_affects_path`` — would a hypothetical answer change affect the **current** decision path (path entailment under edit + conclusion side-car).
- ``smeme_reasoning_list_conclusions`` — catalog conclusion ids/titles and structural reachability (no answers required).
- ``smeme_reasoning_template_check`` / ``smeme_reasoning_template_get`` — minimal drift/digest probe vs full worksheet markdown (owner, discoverable, deployed).
- ``smeme_reasoning_guidance_check`` / ``smeme_reasoning_guidance_get`` — platform calling contract version/digest vs full stitched guidance markdown (connector-only bootstrap).
- ``smeme_authoring_validate_graph`` / ``smeme_authoring_create_draft`` / ``smeme_authoring_design_guidance`` — (optional) chat-authored design standard + graph validate → dashboard draft; gated by ``Settings.mcp_authoring_graph_tools_enabled``.

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
)
from smeme.mcp.authoring_graph import (
    create_draft_from_graph,
    editor_url_for_decision_tree,
    parse_authoring_graph_json,
    validation_payload,
)
from smeme.mcp.bearer_auth import (
    ClerkMcpTokenVerifier,
    MCPAuthError,
    auth_error_tool_json,
    get_mcp_user,
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
from smeme.mcp.urls import mcp_resource_url, transport_security_allowed_hosts
from smeme.reasoning.graph_hash import canonical_graph_hash
from smeme.reasoning.ir.serialize import ir_from_json
from smeme.reasoning.ir.types import IR_FORMAT_VERSION, IRNodeKind
from smeme.reasoning.persistence import persist_reasoning_evaluation_run
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
REASONING_CAPABILITIES_VERSION = "3.0.0"
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


def reasoning_capabilities_document(*, cap_settings: Settings | None = None) -> dict[str, Any]:
    """JSON object returned by ``smeme_reasoning_capabilities`` (tests and release docs).

    ``cap_settings`` should match the ``Settings`` used when building the FastMCP singleton
    (see ``get_or_create_fastmcp``); defaults to the process ``settings`` object.
    """
    s = cap_settings or settings
    tools: list[str] = [
        "smeme_reasoning_list",
        "smeme_reasoning_validate_answers",
        "smeme_reasoning_evaluate",
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
            },
            "evaluate_response": {
                "report_v1": True,
            },
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
                        "smeme_reasoning_evaluate",
                        "smeme_reasoning_what_if",
                        "smeme_reasoning_how_to_reach",
                        "smeme_reasoning_decisive_support",
                        "smeme_reasoning_edit_affects_path",
                    ],
                },
            },
            "query_modes": {
                "apply": "smeme_reasoning_evaluate",
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
                    "evaluate + what_if + how_to_reach + decisive_support + edit_affects_path"
                ),
            },
        },
        "docs": "docs/guides/dr3-mcp-oauth-authoritative-sources.md",
    }
    if s.mcp_authoring_graph_tools_enabled:
        cap["authoring_graph"] = {
            "note": (
                "Authoring helpers — not evaluation tools. "
                "Fetch design guidance, validate a chat-built decision tree graph, then create a "
                "dashboard draft (bypasses the generation wizard). Deploy still happens in "
                "the SMEme editor."
            ),
            "design_guidance": "smeme_authoring_design_guidance",
            "validate": "smeme_authoring_validate_graph",
            "create_draft": "smeme_authoring_create_draft",
        }
        cap["authoring_design"] = {
            "content_version": DESIGN_GUIDANCE_VERSION,
            "content_digest": DESIGN_GUIDANCE_DIGEST,
            "note": (
                "Authoring helper — not an evaluation tool. "
                "Returns the standard for designing branching decision trees in chat."
            ),
        }
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

    artifact_result = await db.execute(
        select(ReasoningCompiledArtifact).where(
            ReasoningCompiledArtifact.decision_tree_id == decision_tree_uuid
        )
    )
    artifact = artifact_result.scalar_one_or_none()
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
    """Map bare MCP mount path to the trailing-slash form Starlette ``Mount`` matches.

    ``Mount`` is registered with ``/api/v1/mcp`` but its path regex only matches
    ``/api/v1/mcp/...`` (``/api/v1/mcp`` alone does not match). Starlette's router
    then issues a **307** to ``/api/v1/mcp/``. Some MCP clients repeat the redirected
    **POST** without the required ``Accept: application/json, text/event-stream``
    header, which yields **406** from the Streamable HTTP stack — not a broken mount.

    Normalizing here avoids the redirect entirely when clients omit the trailing slash
    (Claude Desktop, some OAuth control-plane probes, etc.).
    """

    def __init__(self, app: ASGIApp, mcp_path: str = "/api/v1/mcp") -> None:
        self.app = app
        raw = (mcp_path or "/api/v1/mcp").rstrip("/")
        self._prefix = raw if raw else "/api/v1/mcp"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Shallow-copy scope when mutating: ASGI may share the dict across layers.
        if scope["type"] == "http" and scope.get("path") == self._prefix:
            scope = {**scope, "path": f"{self._prefix}/"}
        await self.app(scope, receive, send)


def reset_mcp_runtime_for_tests() -> None:
    """Clear singletons between tests (avoids stale FastMCP when toggling settings).

    Without this, test A may create a FastMCP instance with MCP_ENABLED=True,
    and test B that expects MCP_ENABLED=False would still get the old instance.
    """
    global _holder, _starlette_mcp
    _holder = None
    _starlette_mcp = None


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
        "3. smeme_reasoning_list → smeme_reasoning_template_get → build answers → "
        "smeme_reasoning_validate_answers → "
        "smeme_reasoning_evaluate\n\n"
        "smeme_reasoning_list returns only decision trees you can invoke now. "
        "If empty, the user has not yet published/shared a decision tree — "
        "do not guess decision tree ids."
    )
    if cfg.mcp_authoring_graph_tools_enabled:
        base += (
            "\n\nChat authoring: when the user wants to build a decision tree in chat "
            "(not the web wizard), call smeme_authoring_design_guidance once, iterate "
            "questions/options/branches in plain language until they say they are ready, "
            "then structure a dt_graph, call smeme_authoring_validate_graph, fix errors, "
            "and only then smeme_authoring_create_draft. Do not auto-Deploy."
        )
    return base


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
                radio-only product constraints, conclusion-first outcome sets, anti-funnel
                branching, Unsure/forward-only policy, and a preflight checklist before
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
                            validate_graph_for_editing,
                        )

                        result = validate_graph_for_editing(parsed)
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
                        decision_tree, result = created
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
                                "warnings": list(result["warnings"]),
                                "deployed": False,
                                "mcp_discoverable": False,
                                "next_step": (
                                    "Open editor_url in the SMEme web app to polish "
                                    "and Deploy. Until Deployed + Listed, this decision tree "
                                    "will not appear in smeme_reasoning_list."
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
                title="List decision trees",
                readOnlyHint=True,
            )
        )
        async def smeme_reasoning_list(ctx: Context) -> str:
            """List the authenticated user's published decision trees that are discoverable for MCP tools.

            Returns a JSON object with a ``decision_trees`` array and a ``count``. Each entry includes:
            - ``id`` — decision tree UUID (pass to smeme_reasoning_evaluate / template tools)
            - ``title``, ``is_public``, ``reasoning_status`` (``compiled`` in this list)

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

                        from smeme.billing.access_policy import (
                            is_decision_tree_live,
                            is_workflow_pick_required,
                        )

                        result = await db.execute(
                            select_decision_trees_for_assistant_tools_list(user.id)
                        )
                        decision_trees = result.scalars().all()

                        decision_trees: list[dict[str, Any]] = []
                        for q in decision_trees:
                            entry: dict[str, Any] = {
                                "id": str(q.id),
                                "title": q.title,
                                "is_public": q.is_public,
                                "reasoning_status": q.reasoning_status,
                                "intended_audience": q.intended_audience,
                                "use_case": q.use_case,
                            }
                            if is_workflow_pick_required(user) or not is_decision_tree_live(
                                user, q
                            ):
                                entry["accessible"] = False
                                entry["status"] = "account_downgrade_pending"
                            decision_trees.append(entry)

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
                    return tool_error_json(exc.code.value, exc.message)

            return _tool_json(
                {
                    "status": "ok",
                    "warnings": warnings,
                    "harness_next": harness_next,
                }
            )

        @_holder.tool(
            annotations=ToolAnnotations(
                title="Run reasoning evaluation",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
            )
        )
        async def smeme_reasoning_evaluate(
            decision_tree_id: str,
            raw_answers_json: str,
            ctx: Context,
            persist: bool = True,
            force_reachable_ids: list[str] | None = None,
            force_unreachable_ids: list[str] | None = None,
        ) -> str:
            """Evaluate a published decision tree using its deployed reasoning model.

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
                async with mcp_invocation_scope("smeme_reasoning_evaluate", ctx) as rec:
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
                    "smeme_reasoning_evaluate failed", extra={"decision_tree_id": decision_tree_id}
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
                    tool_name="smeme_reasoning_evaluate",
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
                    return tool_error_json(exc.code.value, exc.message)

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
                    )
                    run_id = row.id

            payload_out: dict[str, Any] = {
                "report": report,
                "evaluation_run_id": str(run_id) if run_id else None,
                "warnings": ingest_warnings,
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
                    return tool_error_json(exc.code.value, exc.message)
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
            (same provenance envelope shape as ``smeme_reasoning_evaluate``), merges answers
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
                    return tool_error_json(exc.code.value, exc.message)

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
                    return tool_error_json(exc.code.value, exc.message)

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
                    return tool_error_json(exc.code.value, exc.message)
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
            ``smeme_reasoning_evaluate`` when the user asks what outcomes exist, or to obtain
            ``target_conclusion_id`` values for ``smeme_reasoning_how_to_reach`` or
            ``smeme_reasoning_decisive_support``.

            Reachability is **structural** (whether some valid answer path can reach the conclusion),
            not case-specific. For a particular user's answers, call ``smeme_reasoning_evaluate``.

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
    """Drive the FastMCP session manager lifecycle.

    ``StreamableHTTPSessionManager.run()`` must be active for the duration of the
    process even in stateless mode — it initializes internal state and runs cleanup
    hooks.  Without this, the first MCP request may fail with an "uninitialized
    session manager" error.

    Usage: include this in the FastAPI app's lifespan context manager.
    See ``smeme/main.py`` for the integration.
    """
    fm = get_or_create_fastmcp()
    async with fm.session_manager.run():
        yield


def mount_mcp_on_app(app: FastAPI, s: Settings | None = None) -> None:
    """Mount the MCP Streamable HTTP sub-app onto the FastAPI app.

    The mount path (e.g. ``/api/v1/mcp``) is taken from ``settings.mcp_http_path``.
    The ``StripLastEventIdMiddleware`` is wrapped around the Starlette sub-app to
    prevent 500 errors when SSE clients reconnect with a ``Last-Event-ID`` header.

    When Clerk auth is enabled, FastMCP also registers RFC 9728 routes on the
    **inner** Starlette app under the mount prefix; clients should use the
    **FastAPI** handlers in ``discovery_routes.py`` (unchanged).

    **Trailing slash:** Starlette ``Mount`` matches ``{path}/…`` only. Bare
    ``{path}`` is normalized on the **parent** app by ``McpMountPathNormalizeMiddleware``
    in ``smeme.main`` (not inside this mount) so clients are not forced through a
    redirect that drops Streamable HTTP ``Accept`` headers.

    FastAPI's ``app.mount()`` uses Starlette's routing — all requests whose path
    starts with ``mcp_http_path`` are routed to the MCP sub-app directly, bypassing
    FastAPI's OpenAPI router.  This is intentional: MCP uses JSON-RPC over HTTP,
    not REST, and should not appear in the OpenAPI schema.
    """
    cfg = s or settings
    path = cfg.mcp_http_path.rstrip("/") or "/api/v1/mcp"
    starlette_app = get_mcp_starlette_app(cfg)
    # Wrap with StripLastEventIdMiddleware before mounting.
    # The middleware only affects the MCP sub-app, not the rest of the FastAPI app.
    app.mount(path, StripLastEventIdMiddleware(starlette_app))
