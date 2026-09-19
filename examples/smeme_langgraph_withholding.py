# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "fastmcp==4.0.3",
#   "langchain[mcp]==1.4.0",
#   "langchain-openai==1.6.2",
#   "langgraph==1.2.11",
# ]
# ///
"""SMEme + langchain.mcp — withholding LangGraph host graph.

Same tree and matter as *Introducing SMEme*: the deployed cross-border tax
withholding decision tree, run on ACME, Inc.'s sale of asset X to party D
(CRM matter #123). That post ran Inquire from ordinary chat. This listing is
the same loop as a controlled LangGraph graph.

Without ``--case-bundle``, the ACME file is only a **prose** case. With the
frozen public-distribution ZIP, the host safely loads one fictional matter and
requires the optional model to cite a verbatim source excerpt. Live Listed
trees on an account may still be a different matter — pass ``decision_tree_id``
(list item ``id``) deliberately.

Pins: langchain==1.4.0 (langchain.mcp is BETA), fastmcp==4.0.3.

The claim, in the graph itself:
  the human interrupt sits BEFORE evaluate_continue, the next question comes
  FROM the solver (not from the LangGraph router), and a rejection never
  reaches MCP.

  bootstrap: list items are keyed by id; pass that UUID to
             evaluate(decision_tree_id). The server returns one blind task
             {question_id, stem, options} with options a list of strings.
  propose:   host or optional model proposes EXACTLY ONE offered option
  admit:     interrupt() — counsel admits / edits (among the same options) / rejects
  continue:  evaluate_continue(inquiry_session_id, question_id,
                               selected_option, provenance_id)
  ANALYZE:   report, isolated_evaluations_required / error, or the next task
             (harness_next: continue_evaluate). The solver chooses the next question.

Auth: OAuth 2.1 Bearer via RFC 9728 discovery — not the browser cookie session.
On SaaS, Clerk is the authorization server (the flow opens a browser). SaaS is
DCR-off: pass the pre-registered public PKCE client_id. FastMCP then uses
http://localhost:8787/callback; that URI must stay on the production Clerk MCP
OAuth app. Tokens are in-memory; each run re-opens the browser. Self-host with
DCR off also needs a pre-registered client_id.

Answers are radio-only: selected_option must be an EXACT option string from the
task, and an admitted option requires a non-empty provenance_id. SMEme does
not verify that the cited source supports the option — that remains counsel's
judgment at the interrupt.

Data boundary: matter_context stays in graph state (the agreement, intake memo,
email, CRM excerpt — whatever the host already gathered). Only the admitted
option and its provenance reach the server.

Hugging Face (the model, not the reasoner): ChatOpenAI is OpenAI-compatible on
purpose. Point OPENAI_BASE_URL + MODEL_ID at a Hugging Face Inference Endpoint /
TGI / vLLM. That is a config change, not a feature. Do not upload trees or
matter files to the Hub as training data.

This listing does not use MCP elicitation or sampling. The gate is a host
interrupt before the tool call.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import io
import json
import os
import stat
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, TypedDict
from zipfile import BadZipFile, ZipFile

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from mcp_tool_decode import decode_tool_message, error_payload, transport_is_error

SMEME_MCP_URL = os.environ.get("SMEME_MCP_URL", "https://www.smeme.ai/api/v1/mcp")
# Public PKCE identifier (not a secret). Same value the dashboard / MCP docs use.
SMEME_OAUTH_CLIENT_ID = os.environ.get("SMEME_OAUTH_CLIENT_ID", "NRdsdBvrio0DW9yo")
OAUTH_CALLBACK_PORT = int(os.environ.get("SMEME_OAUTH_CALLBACK_PORT", "8787"))
OAUTH_CALLBACK_HOST = os.environ.get("SMEME_OAUTH_CALLBACK_HOST", "localhost")

ACME_DATASET_SHA256 = "96b8534209b11ca64899be4f054077ca6000ead1059437cd6343968554add560"
ACME_SAMPLE_KEY = "smeme_acme_xborder_withholding_v1"
MAX_ARCHIVE_MEMBERS = 256
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 10 * 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024

REQUIRED_TOOLS = {
    "smeme_reasoning_capabilities",
    "smeme_reasoning_list",
    "smeme_reasoning_evaluate",
    "smeme_reasoning_evaluate_continue",
}
ADVERTISED_REQUIRED_TOOLS = REQUIRED_TOOLS - {"smeme_reasoning_capabilities"}


class IntegrationError(RuntimeError):
    """Actionable hosted-client contract failure."""


def _fail(message: str, cause: Exception | None = None) -> NoReturn:
    if cause is not None:
        raise IntegrationError(message) from cause
    raise IntegrationError(message)


@dataclass(frozen=True)
class PublicSource:
    """One neutral source from the public synthetic case bundle."""

    source_id: str
    title: str
    relative_locator: str
    content: str


@dataclass(frozen=True)
class PublicCaseBundle:
    """Validated host-side source material for one fictional matter."""

    case_id: str
    sample_key: str
    sha256: str
    sources: tuple[PublicSource, ...]

    def source_catalog(self) -> dict[str, dict[str, str]]:
        return {
            source.source_id: {
                "title": source.title,
                "relative_locator": source.relative_locator,
                "content": source.content,
            }
            for source in self.sources
        }

    def matter_context(self) -> str:
        sections = [
            (
                f"SOURCE {source.source_id}\n"
                f"Title: {source.title}\n"
                f"Locator: {source.relative_locator}\n"
                f"Content:\n{source.content}"
            )
            for source in self.sources
        ]
        return (
            f"Fictional synthetic case {self.case_id}. "
            "Use only the sources below. Source identifiers are attributions, not truth claims.\n\n"
            + "\n\n---\n\n".join(sections)
        )


class WithholdingState(TypedDict, total=False):
    matter_context: str  # ACME file: agreement, intake memo, email, CRM #123
    source_catalog: dict[str, dict[str, str]]  # public source id -> title/locator/content
    case_id: str
    dataset_sha256: str
    sample_key: str
    decision_tree_id: str  # list item id; pass to evaluate as decision_tree_id
    inquiry_session_id: str
    open_task: dict  # {question_id, stem, options} — from the SOLVER
    proposed_answer: dict  # {question_id, raw, options}
    admission: str  # "admitted" | "rejected"
    selected_option: str  # exact option string
    provenance_id: str  # non-empty when admitted; citation ref (not a check)
    report: dict | None  # also carries terminal non-report payloads; see evaluate
    terminal_payload: dict | None  # complete terminal envelope, including qualifications


ProposalProvider = Callable[
    [WithholdingState],
    dict[str, Any] | Awaitable[dict[str, Any]],
]
EventSink = Callable[[dict[str, Any]], None]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_zip_infos(zf: ZipFile) -> dict[str, Any]:
    infos = zf.infolist()
    if len(infos) > MAX_ARCHIVE_MEMBERS:
        _fail(f"Case bundle has {len(infos)} members; maximum is {MAX_ARCHIVE_MEMBERS}")
    total_size = sum(info.file_size for info in infos)
    if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        _fail(f"Case bundle uncompressed size exceeds {MAX_ARCHIVE_UNCOMPRESSED_BYTES} bytes")
    by_name: dict[str, Any] = {}
    for info in infos:
        member = PurePosixPath(info.filename)
        if member.is_absolute() or ".." in member.parts:
            _fail(f"Case bundle contains unsafe path {info.filename!r}")
        if stat.S_ISLNK(info.external_attr >> 16):
            _fail(f"Case bundle contains symlink {info.filename!r}")
        if info.flag_bits & 0x1:
            _fail(f"Case bundle contains encrypted member {info.filename!r}")
        if info.filename in by_name:
            _fail(f"Case bundle contains duplicate member {info.filename!r}")
        by_name[info.filename] = info
    bad_member = zf.testzip()
    if bad_member is not None:
        _fail(f"Case bundle failed ZIP integrity at {bad_member!r}")
    return by_name


def _manifest_object(zf: ZipFile, members: dict[str, Any]) -> dict[str, Any]:
    info = members.get("dataset_manifest.json")
    if info is None or info.is_dir():
        raise IntegrationError("Case bundle is missing dataset_manifest.json")
    if info.file_size > MAX_SOURCE_BYTES:
        raise IntegrationError("dataset_manifest.json exceeds the per-file size limit")
    try:
        manifest = json.loads(zf.read(info))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrationError("dataset_manifest.json is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise IntegrationError("dataset_manifest.json must contain an object")
    return manifest


def load_public_case_bundle(
    path: Path,
    case_id: str,
    *,
    expected_sha256: str = ACME_DATASET_SHA256,
) -> PublicCaseBundle:
    """Load one case from the frozen public ZIP without extracting it."""
    encoded = path.read_bytes()
    digest = _sha256_bytes(encoded)
    if expected_sha256 and digest != expected_sha256:
        _fail(f"Case bundle SHA-256 is {digest}; expected {expected_sha256}")
    try:
        with ZipFile(io.BytesIO(encoded)) as zf:
            members = _safe_zip_infos(zf)
            manifest = _manifest_object(zf, members)
            sample_key = manifest.get("sample_key")
            if sample_key != ACME_SAMPLE_KEY:
                _fail(f"Case bundle sample_key is {sample_key!r}; expected {ACME_SAMPLE_KEY!r}")
            cases = manifest.get("cases")
            if not isinstance(cases, list):
                raise IntegrationError("Case bundle manifest has no cases list")
            case = next(
                (
                    candidate
                    for candidate in cases
                    if isinstance(candidate, dict) and candidate.get("case_id") == case_id
                ),
                None,
            )
            if case is None:
                _fail(f"Case bundle has no case_id {case_id!r}")
            source_rows = case.get("sources")
            if not isinstance(source_rows, list) or not source_rows:
                _fail(f"Case {case_id!r} has no sources")
            sources: list[PublicSource] = []
            seen_source_ids: set[str] = set()
            for row in source_rows:
                if not isinstance(row, dict):
                    _fail(f"Case {case_id!r} contains malformed source metadata")
                source_id = row.get("source_id")
                title = row.get("title")
                locator = row.get("relative_locator")
                if not all(
                    isinstance(value, str) and value.strip()
                    for value in (source_id, title, locator)
                ):
                    _fail(f"Case {case_id!r} contains incomplete source metadata")
                if source_id in seen_source_ids:
                    _fail(f"Case {case_id!r} repeats source_id {source_id!r}")
                seen_source_ids.add(source_id)
                info = members.get(locator)
                if info is None or info.is_dir():
                    _fail(f"Source {source_id!r} locator {locator!r} is missing")
                if info.file_size > MAX_SOURCE_BYTES:
                    _fail(f"Source {source_id!r} exceeds the per-file size limit")
                try:
                    content = zf.read(info).decode()
                except UnicodeDecodeError as exc:
                    _fail(f"Source {source_id!r} is not UTF-8 text", exc)
                sources.append(
                    PublicSource(
                        source_id=source_id,
                        title=title,
                        relative_locator=locator,
                        content=content,
                    )
                )
    except BadZipFile as exc:
        raise IntegrationError("Case bundle is not a valid ZIP archive") from exc
    return PublicCaseBundle(
        case_id=case_id,
        sample_key=ACME_SAMPLE_KEY,
        sha256=digest,
        sources=tuple(sources),
    )


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def _observed_payload(payload: dict[str, Any]) -> dict[str, Any]:
    report = payload.get("report")
    warnings = payload.get("warnings")
    return {
        "status": payload.get("status"),
        "harness_next": payload.get("harness_next"),
        "has_task": isinstance(payload.get("task"), dict),
        "result_kind": report.get("result_kind") if isinstance(report, dict) else None,
        "headline": report.get("headline") if isinstance(report, dict) else None,
        "stop_reason": payload.get("stop_reason"),
        "inquire_stop_reason": payload.get("inquire_stop_reason"),
        "warning_codes": [
            warning.get("code")
            for warning in warnings or []
            if isinstance(warning, dict) and isinstance(warning.get("code"), str)
        ],
        "error_code": (
            payload["error"].get("code") if isinstance(payload.get("error"), dict) else None
        ),
    }


def _require_payload(
    message: Any,
    label: str,
    *,
    allow_semantic_error: bool = False,
) -> dict[str, Any]:
    decoded = decode_tool_message(message)
    error = error_payload(decoded)
    if error is not None and not allow_semantic_error:
        code = error.get("code", "unknown_error")
        detail = error.get("message") or error.get("detail") or error
        msg = f"{label} returned semantic error {code}: {detail}"
        raise IntegrationError(msg)
    if transport_is_error(message):
        msg = f"{label} returned an MCP tool error without a structured error payload"
        raise IntegrationError(msg)
    if not isinstance(decoded, dict) or "_raw" in decoded:
        msg = f"{label} returned a malformed payload: {decoded!r}"
        raise IntegrationError(msg)
    return decoded


def _is_continue(payload: dict) -> bool:
    return payload.get("harness_next") == "continue_evaluate" and isinstance(
        payload.get("task"), dict
    )


def _oauth() -> Any:
    from fastmcp.client.auth import OAuth  # type: ignore[import-not-found]

    return OAuth(
        client_id=SMEME_OAUTH_CLIENT_ID,
        callback_port=OAUTH_CALLBACK_PORT,
        callback_host=OAUTH_CALLBACK_HOST,
        additional_client_metadata={"token_endpoint_auth_method": "none"},
    )


def verify_required_tools(tools: dict[str, Any]) -> None:
    missing = sorted(REQUIRED_TOOLS - set(tools))
    if missing:
        msg = f"MCP server is missing required tools: {', '.join(missing)}"
        raise IntegrationError(msg)


def _advertised_tools(payload: dict[str, Any]) -> set[str]:
    reasoning = payload.get("reasoning")
    if not isinstance(reasoning, dict):
        return set()
    value = reasoning.get("tools")
    if not isinstance(value, list):
        capabilities = reasoning.get("capabilities")
        value = capabilities.get("tools") if isinstance(capabilities, dict) else None
    return {name for name in value or [] if isinstance(name, str)}


def _listed_trees(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("decision_trees")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


async def _manual_proposal(state: WithholdingState) -> dict[str, Any]:
    return {
        "question_id": state["open_task"]["question_id"],
        "raw": "No model proposal; operator selection required.",
        "value": None,
    }


def _message_text(message: Any) -> str:
    raw = getattr(message, "content", message)
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, list):
        blocks = [
            block.get("text", "")
            for block in raw
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(blocks).strip()
    return str(raw).strip()


def _validated_source_proposal(
    text: str,
    task: dict[str, Any],
    source_catalog: dict[str, dict[str, str]],
) -> dict[str, Any]:
    try:
        candidate = json.loads(text)
    except json.JSONDecodeError:
        return {
            "raw": text,
            "value": None,
            "proposal_error": "model_response_not_json",
        }
    if not isinstance(candidate, dict):
        return {
            "raw": text,
            "value": None,
            "proposal_error": "model_response_not_object",
        }
    value = candidate.get("option")
    source_id = candidate.get("source_id")
    excerpt = candidate.get("excerpt")
    if value not in task["options"]:
        return {
            "raw": text,
            "value": None,
            "proposal_error": "option_not_offered",
        }
    source = source_catalog.get(source_id) if isinstance(source_id, str) else None
    if source is None:
        return {
            "raw": text,
            "value": None,
            "proposal_error": "source_not_in_case",
        }
    if not isinstance(excerpt, str) or not excerpt.strip():
        return {
            "raw": text,
            "value": None,
            "proposal_error": "excerpt_missing",
        }
    excerpt_validation = "exact"
    if excerpt not in source["content"]:
        normalized_excerpt = " ".join(excerpt.split())
        normalized_source = " ".join(source["content"].split())
        if normalized_excerpt in normalized_source:
            excerpt_validation = "normalized_whitespace"
        else:
            return {
                "raw": text,
                "value": None,
                "candidate_value": value,
                "source_id": source_id,
                "source_title": source["title"],
                "source_locator": source["relative_locator"],
                "excerpt": excerpt,
                "excerpt_verified": False,
                "proposal_error": "excerpt_not_found_in_source",
            }
    return {
        "raw": text,
        "value": value,
        "source_id": source_id,
        "source_title": source["title"],
        "source_locator": source["relative_locator"],
        "excerpt": excerpt,
        "excerpt_verified": True,
        "excerpt_validation": excerpt_validation,
    }


def make_openai_proposal_provider(
    model_factory: Callable[[], Any] | None = None,
) -> ProposalProvider:
    """Create a lazy OpenAI-compatible proposal provider."""
    model: Any | None = None

    async def propose(state: WithholdingState) -> dict[str, Any]:
        nonlocal model
        if model is None:
            if model_factory is not None:
                model = model_factory()
            else:
                from langchain_openai import ChatOpenAI  # type: ignore[import-not-found]

                model = ChatOpenAI(
                    base_url=os.environ.get("OPENAI_BASE_URL"),
                    model=os.environ.get(
                        "MODEL_ID",
                        "meta-llama/Llama-3.3-70B-Instruct",
                    ),
                    temperature=0,
                )
        task = state["open_task"]
        source_catalog = state.get("source_catalog") or {}
        if source_catalog:
            prompt = (
                "Using only the supplied fictional case sources, propose an answer to the "
                "question. Return exactly one JSON object with keys option, source_id, and "
                "excerpt. option must exactly match one offered option. source_id must exactly "
                "match one supplied SOURCE identifier. excerpt must be a short verbatim "
                "substring copied from that source. Do not use outside knowledge. If the sources "
                "do not support an offered option, return "
                '{"option":null,"source_id":null,"excerpt":null}.\n'
                f"Question: {task['stem']}\n"
                f"Options: {json.dumps(task['options'])}\n---\n{state['matter_context']}"
            )
        else:
            prompt = (
                "Return exactly one offered option and no other text. "
                "The operator will separately admit it and attach provenance.\n"
                f"Question: {task['stem']}\n"
                f"Options: {task['options']}\n---\n{state['matter_context']}"
            )
        if source_catalog:
            text = _message_text(await model.ainvoke(prompt))
            proposal = _validated_source_proposal(text, task, source_catalog)
            if proposal.get("value") is None:
                correction_prompt = (
                    f"{prompt}\n\n"
                    "Your previous response failed local validation with "
                    f"{proposal.get('proposal_error', 'unknown_error')}. "
                    "Return a corrected JSON object only. The excerpt must be one contiguous "
                    "verbatim substring copied character-for-character from the Content of the "
                    "source identified by source_id; do not summarize, concatenate, or normalize "
                    f"it.\nPrevious response: {text}"
                )
                text = _message_text(await model.ainvoke(correction_prompt))
                proposal = _validated_source_proposal(text, task, source_catalog)
        else:
            text = _message_text(await model.ainvoke(prompt))
            proposal = {
                "raw": text,
                "value": text if text in task["options"] else None,
            }
        return {"question_id": task["question_id"], **proposal}

    return propose


def make_nodes(
    tools: dict[str, Any],
    proposal_provider: ProposalProvider | None = None,
    event_sink: EventSink | None = None,
) -> tuple[Callable[..., Any], Callable[..., Any], Callable[..., Any], Callable[..., Any]]:
    """Nodes close over the tool catalog resolved once at bootstrap."""
    verify_required_tools(tools)
    provider = proposal_provider or _manual_proposal

    async def bootstrap(state: WithholdingState) -> WithholdingState:
        tree_id = (state.get("decision_tree_id") or "").strip()
        if not tree_id:
            raise IntegrationError(
                "decision_tree_id is required; copy the id from smeme_reasoning_list"
            )
        capabilities = _require_payload(
            await tools["smeme_reasoning_capabilities"].ainvoke({}),
            "smeme_reasoning_capabilities",
        )
        if event_sink:
            event_sink(
                {
                    "event": "tool_result",
                    "tool_name": "smeme_reasoning_capabilities",
                    "observed": _observed_payload(capabilities),
                }
            )
        missing = sorted(ADVERTISED_REQUIRED_TOOLS - _advertised_tools(capabilities))
        if missing:
            msg = f"Hosted capabilities do not advertise required tools: {', '.join(missing)}"
            raise IntegrationError(msg)
        listing = _require_payload(
            await tools["smeme_reasoning_list"].ainvoke({}),
            "smeme_reasoning_list",
        )
        if event_sink:
            event_sink(
                {
                    "event": "tool_result",
                    "tool_name": "smeme_reasoning_list",
                    "listed_tree_count": len(_listed_trees(listing)),
                    "observed": _observed_payload(listing),
                }
            )
        trees = _listed_trees(listing)
        if not trees:
            raise IntegrationError(
                "No Listed decision trees are available; load or List a tree in the dashboard"
            )
        selected = next((row for row in trees if row.get("id") == tree_id), None)
        if selected is None:
            msg = f"decision_tree_id {tree_id!r} is not present in the Listed tree response"
            raise IntegrationError(msg)
        started = _require_payload(
            await tools["smeme_reasoning_evaluate"].ainvoke({"decision_tree_id": tree_id}),
            "smeme_reasoning_evaluate",
        )
        if event_sink:
            event_sink(
                {
                    "event": "tool_result",
                    "tool_name": "smeme_reasoning_evaluate",
                    "observed": _observed_payload(started),
                    "task": (
                        {
                            "question_id": started["task"].get("question_id"),
                            "option_count": len(started["task"].get("options", [])),
                        }
                        if isinstance(started.get("task"), dict)
                        else None
                    ),
                }
            )
        if _is_continue(started):
            return {
                "decision_tree_id": tree_id,
                "inquiry_session_id": started["inquiry_session_id"],
                "open_task": started["task"],
            }
        return {
            "decision_tree_id": tree_id,
            "report": started.get("report") or started,
            "terminal_payload": started,
        }

    async def propose(state: WithholdingState) -> WithholdingState:
        task = state["open_task"]
        proposed = provider(state)
        if inspect.isawaitable(proposed):
            proposed = await proposed
        value = proposed.get("value")
        if value not in task["options"]:
            value = None
        answer = {
            "question_id": task["question_id"],
            "stem": task.get("stem"),
            "raw": proposed.get("raw"),
            "value": value,
            "options": task["options"],
        }
        for key in (
            "source_id",
            "source_title",
            "source_locator",
            "excerpt",
            "excerpt_verified",
            "excerpt_validation",
            "candidate_value",
            "proposal_error",
        ):
            if key in proposed:
                answer[key] = proposed[key]
        return {"proposed_answer": answer}

    def admit(state: WithholdingState) -> WithholdingState:
        """THE GATE — host interrupt before evaluate_continue, always.

        Rejection never reaches MCP. Invalid or cancelled admissions re-propose
        without being recorded as human rejection.
        """
        decision = interrupt({"type": "admission_required", "proposal": state["proposed_answer"]})
        if not decision.get("admit"):
            return {"admission": "rejected" if decision.get("rejected") is True else "cancelled"}
        value = decision.get("value")
        prov = (decision.get("provenance_id") or "").strip()
        # Radio-only, enforced. An out-of-set value is not an admission.
        if value not in state["proposed_answer"]["options"] or not prov:
            return {"admission": "invalid"}
        return {
            "admission": "admitted",
            "selected_option": value,  # exact option string
            "provenance_id": prov,  # citation ref; SMEme does not check support
        }

    async def evaluate(state: WithholdingState) -> WithholdingState:
        """Admitted option in; the SOLVER decides what comes back."""
        result = _require_payload(
            await tools["smeme_reasoning_evaluate_continue"].ainvoke(
                {
                    "inquiry_session_id": state["inquiry_session_id"],
                    "question_id": state["proposed_answer"]["question_id"],
                    "selected_option": state["selected_option"],
                    "provenance_id": state["provenance_id"],
                }
            ),
            "smeme_reasoning_evaluate_continue",
            allow_semantic_error=True,
        )
        if event_sink:
            event_sink(
                {
                    "event": "tool_result",
                    "tool_name": "smeme_reasoning_evaluate_continue",
                    "observed": _observed_payload(result),
                    "task": (
                        {
                            "question_id": result["task"].get("question_id"),
                            "option_count": len(result["task"].get("options", [])),
                        }
                        if isinstance(result.get("task"), dict)
                        else None
                    ),
                }
            )
        if _is_continue(result):
            return {
                "inquiry_session_id": result["inquiry_session_id"],
                "open_task": result["task"],
                "report": None,
            }
        # Terminal: report, isolated_evaluations_required, or error.
        # Branch on report.result_kind downstream. Do not invent VERIFY.
        return {
            "report": result.get("report") or result,
            "terminal_payload": result,
        }

    return bootstrap, propose, admit, evaluate


def build_graph(
    tools: dict[str, Any],
    proposal_provider: ProposalProvider | None = None,
    event_sink: EventSink | None = None,
) -> Any:
    bootstrap, propose, admit, evaluate = make_nodes(
        tools,
        proposal_provider,
        event_sink,
    )

    g = StateGraph(WithholdingState)
    g.add_node("bootstrap", bootstrap)
    g.add_node("propose", propose)
    g.add_node("admit", admit)
    g.add_node("evaluate", evaluate)

    g.set_entry_point("bootstrap")
    g.add_conditional_edges(
        "bootstrap",
        lambda s: "done" if s.get("report") else "propose",
        {"propose": "propose", "done": END},
    )
    g.add_edge("propose", "admit")
    # Rejection never reaches the solver.
    g.add_conditional_edges(
        "admit",
        lambda s: "evaluate" if s.get("admission") == "admitted" else "propose",
        {"evaluate": "evaluate", "propose": "propose"},
    )
    g.add_conditional_edges(
        "evaluate",
        lambda s: "done" if s.get("report") else "propose",
        {"propose": "propose", "done": END},
    )
    return g.compile(checkpointer=InMemorySaver())  # required for interrupt()


async def run(
    matter_context: str,
    decision_tree_id: str,
    thread_id: str = "acme-123",
    *,
    case_bundle: PublicCaseBundle | None = None,
    proposal_provider: ProposalProvider | None = None,
    mechanical_first_option: bool = False,
    input_fn: Callable[[str], str] = input,
    evidence_output: Path | None = None,
    stop_after_admitted_continuations: int | None = None,
    reviewed_admission: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """Run until terminal output, pausing for a real operator by default."""
    tree_id = decision_tree_id.strip()
    if not tree_id:
        raise IntegrationError(
            "decision_tree_id is required; pass --decision-tree-id or SMEME_DECISION_TREE_ID"
        )
    from fastmcp import Client  # type: ignore[import-not-found]
    from langchain.mcp import MCPAdapter  # type: ignore[import-not-found]

    evidence: dict[str, Any] = {
        "schema_version": 1,
        "sanitized": True,
        "endpoint": SMEME_MCP_URL,
        "decision_tree_id": tree_id,
        "package_versions": {
            name: _package_version(name)
            for name in ("fastmcp", "langchain", "langchain-openai", "langgraph")
        },
        "events": [],
    }
    if case_bundle is not None:
        evidence["dataset"] = {
            "case_id": case_bundle.case_id,
            "sample_key": case_bundle.sample_key,
            "sha256": case_bundle.sha256,
            "source_count": len(case_bundle.sources),
        }
    if proposal_provider is not None:
        evidence["proposal_model"] = {
            "model_id": os.environ.get("MODEL_ID", "provider-injected"),
            "openai_compatible_base_url_configured": bool(os.environ.get("OPENAI_BASE_URL")),
        }

    def record(event: dict[str, Any]) -> None:
        evidence["events"].append(event)

    async with MCPAdapter(Client(SMEME_MCP_URL, auth=_oauth())) as adapter:
        tools = {t.name: t for t in await adapter.list_tools()}
        verify_required_tools(tools)
        record({"event": "tool_inventory", "tools": sorted(tools)})
        app = build_graph(tools, proposal_provider, record)
        config = {"configurable": {"thread_id": thread_id}}

        initial_state: WithholdingState = {
            "matter_context": matter_context,
            "decision_tree_id": tree_id,
        }
        if case_bundle is not None:
            initial_state.update(
                {
                    "source_catalog": case_bundle.source_catalog(),
                    "case_id": case_bundle.case_id,
                    "dataset_sha256": case_bundle.sha256,
                    "sample_key": case_bundle.sample_key,
                }
            )
        paused = await app.ainvoke(initial_state, config)
        admitted_continuations = 0
        while paused.get("__interrupt__"):
            proposal = paused["__interrupt__"][0].value["proposal"]
            record(
                {
                    "event": "interrupt",
                    "question_id": proposal.get("question_id"),
                    "option_count": len(proposal.get("options", [])),
                    "dataset_source_id": (
                        proposal.get("source_id") if case_bundle is not None else None
                    ),
                    "excerpt_verified": (
                        proposal.get("excerpt_verified") if case_bundle is not None else None
                    ),
                    "excerpt_validation": (
                        proposal.get("excerpt_validation") if case_bundle is not None else None
                    ),
                    "proposal_error": proposal.get("proposal_error"),
                }
            )
            if (
                stop_after_admitted_continuations is not None
                and admitted_continuations >= stop_after_admitted_continuations
            ):
                break
            if reviewed_admission is not None:
                decision = reviewed_admission_decision(proposal, *reviewed_admission)
                print("OUT-OF-BAND HUMAN REVIEW: admitting the exact reviewed option/source pair.")
            elif mechanical_first_option:
                print("MECHANICAL DEMONSTRATION ONLY: admitting the first option.")
                decision = {
                    "admit": True,
                    "value": proposal["options"][0],
                    "provenance_id": "mechanical-demo-provenance",
                }
            else:
                decision = prompt_admission(proposal, input_fn)
            record(
                {
                    "event": "admission",
                    "action": (
                        "admitted"
                        if decision.get("admit")
                        else ("rejected" if decision.get("rejected") else "cancelled")
                    ),
                    "continuation_called": bool(decision.get("admit")),
                    "review_mode": (
                        "out_of_band_exact_match" if reviewed_admission is not None else "prompt"
                    ),
                }
            )
            paused = await app.ainvoke(
                Command(resume=decision),
                config,
            )
            if decision.get("admit"):
                admitted_continuations += 1
        if evidence_output is not None:
            _write_sanitized_evidence(evidence_output, evidence)
        return dict(paused)


def _write_sanitized_evidence(path: Path, evidence: dict[str, Any]) -> None:
    encoded = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode()
    lowered = encoded.lower()
    forbidden = (b"authorization", b"bearer ", b"access_token", b"refresh_token")
    if any(value in lowered for value in forbidden):
        raise IntegrationError("Refusing to write hosted evidence containing credential fields")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(encoded)
    temporary.chmod(0o600)
    temporary.replace(path)


def _terminal_summary(state: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"paused": bool(state.get("__interrupt__"))}
    payload = state.get("terminal_payload")
    if not isinstance(payload, dict):
        payload = state.get("report") if isinstance(state.get("report"), dict) else {}
    nested_report = payload.get("report")
    report = nested_report if isinstance(nested_report, dict) else None
    if report is None and (
        payload.get("result_kind") is not None or payload.get("headline") is not None
    ):
        report = payload
    if isinstance(report, dict):
        summary["report"] = {
            "result_kind": report.get("result_kind"),
            "headline": report.get("headline"),
        }
    error = payload.get("error")
    if isinstance(error, dict):
        error_summary = {
            "code": error.get("code"),
            "message": error.get("message"),
            "status": error.get("status"),
        }
        if error.get("code") == "isolated_evaluations_required":
            summary["verification_required"] = error_summary
        else:
            summary["terminal_error"] = {
                "code": error.get("code"),
                "message": error.get("message"),
                "status": error.get("status"),
            }
    for key in ("status", "harness_next", "stop_reason", "inquire_stop_reason"):
        if payload.get(key) is not None:
            summary[key] = payload[key]
    warnings = payload.get("warnings")
    if isinstance(warnings, list) and warnings:
        summary["warnings"] = warnings
    if state.get("__interrupt__"):
        proposal = state["__interrupt__"][0].value.get("proposal", {})
        summary["next_interrupt"] = {
            "question_id": proposal.get("question_id"),
            "option_count": len(proposal.get("options", [])),
        }
    return summary


def prompt_admission(
    proposal: dict[str, Any],
    input_fn: Callable[[str], str] = input,
) -> dict[str, Any]:
    print(f"\nQuestion: {proposal.get('stem') or '[stem unavailable]'}")
    options = proposal["options"]
    proposed_value = proposal.get("value")
    has_proposal = proposed_value in options
    if has_proposal:
        print(f"Proposed option: {proposed_value}")
    else:
        print("Selection mode: manual operator selection")
        if proposal.get("proposal_error"):
            print(f"Model proposal rejected locally: {proposal['proposal_error']}")
        if proposal.get("candidate_value"):
            print(f"Rejected model option: {proposal['candidate_value']}")
    if proposal.get("source_id"):
        print(
            "Proposed source: "
            f"{proposal['source_id']} — {proposal.get('source_title') or '[title unavailable]'}"
        )
        print(f"Source excerpt: {proposal.get('excerpt') or '[excerpt unavailable]'}")
    for index, option in enumerate(options, start=1):
        print(f"  {index}. {option}")

    if has_proposal:
        while True:
            action = (
                input_fn("[a]dmit proposal, [e]dit/select option, or [r]eject? ").strip().lower()
            )
            if action == "r":
                return {"admit": False, "rejected": True}
            if action == "a":
                selected = proposed_value
                provenance_id = (proposal.get("source_id") or "").strip()
                break
            if action == "e":
                selected = _prompt_option(options, input_fn, allow_reject=False)
                if selected is None:
                    return {"admit": False, "cancelled": True}
                provenance_id = ""
                break
            print("Enter a, e, or r.")
    else:
        selected = _prompt_option(options, input_fn, allow_reject=True)
        if selected == "__rejected__":
            return {"admit": False, "rejected": True}
        if selected is None:
            return {"admit": False, "cancelled": True}
        provenance_id = ""

    if not provenance_id:
        provenance_id = _prompt_provenance(input_fn)
    if provenance_id is None:
        return {"admit": False, "cancelled": True}
    return {
        "admit": True,
        "value": selected,
        "provenance_id": provenance_id,
    }


def reviewed_admission_decision(
    proposal: dict[str, Any],
    expected_option: str,
    expected_source_id: str,
) -> dict[str, Any]:
    """Admit only the exact grounded proposal a human reviewed out of band."""
    if proposal.get("value") != expected_option:
        raise IntegrationError("Live proposal option differs from the reviewed option")
    if proposal.get("source_id") != expected_source_id:
        raise IntegrationError("Live proposal source differs from the reviewed source")
    if proposal.get("excerpt_verified") is not True:
        raise IntegrationError("Live proposal excerpt did not pass local source validation")
    return {
        "admit": True,
        "value": expected_option,
        "provenance_id": expected_source_id,
    }


def _option_at(options: list[str], raw_index: str) -> str | None:
    try:
        index = int(raw_index)
    except ValueError:
        return None
    if 1 <= index <= len(options):
        return options[index - 1]
    return None


def _prompt_option(
    options: list[str],
    input_fn: Callable[[str], str],
    *,
    allow_reject: bool,
) -> str | None:
    prompt = "Option number, or [r]eject? " if allow_reject else "Option number, or [c]ancel? "
    while True:
        raw = input_fn(prompt).strip().lower()
        if allow_reject and raw == "r":
            return "__rejected__"
        if not allow_reject and raw == "c":
            return None
        selected = _option_at(options, raw)
        if selected is not None:
            return selected
        if allow_reject:
            print(f"Enter an option number from 1 to {len(options)}, or r.")
        else:
            print(f"Enter an option number from 1 to {len(options)}, or c.")


def _prompt_provenance(input_fn: Callable[[str], str]) -> str | None:
    while True:
        provenance_id = input_fn("Non-empty provenance id, or [c]ancel: ").strip()
        if provenance_id:
            if provenance_id.lower() == "c":
                return None
            return provenance_id
        print("Provenance id cannot be blank; enter a value or c to cancel.")


# Prose case from Introducing SMEme. Not a live Listed-tree stem.
ACME_MATTER = """\
ACME, Inc. sale of asset X to party D. CRM matter #123.
Host-side sources: associate intake diagnostic memo, email correspondence,
draft agreement. Only an admitted option + provenance_id go to SMEme.
"""


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--decision-tree-id",
        default=os.environ.get("SMEME_DECISION_TREE_ID", ""),
    )
    parser.add_argument("--thread-id", default="acme-123")
    parser.add_argument(
        "--model",
        action="store_true",
        help="Use a lazy OpenAI-compatible model proposal; default is manual selection.",
    )
    parser.add_argument(
        "--case-bundle",
        type=Path,
        help=(
            "Frozen public smeme-acme-dataset-distributed.zip; verifies its canonical SHA-256 "
            "and keeps all source content in host state"
        ),
    )
    parser.add_argument(
        "--case-id",
        default="matter-123",
        help="Fictional case_id from dataset_manifest.json (default: matter-123).",
    )
    parser.add_argument(
        "--mechanical-first-option",
        action="store_true",
        help="Mechanical demonstration only: admit each task's first option.",
    )
    parser.add_argument(
        "--evidence-output",
        type=Path,
        help="Write sanitized package/tool/interrupt evidence (never OAuth state).",
    )
    parser.add_argument(
        "--stop-after-first-admission",
        action="store_true",
        help="Stop at the next interrupt or terminal result after one admitted continuation.",
    )
    parser.add_argument(
        "--reviewed-option",
        help="Exact model option already reviewed by a human; requires --reviewed-source-id.",
    )
    parser.add_argument(
        "--reviewed-source-id",
        help="Exact public source ID already reviewed by a human; requires --reviewed-option.",
    )
    args = parser.parse_args()
    if not args.decision_tree_id.strip():
        parser.error(
            "--decision-tree-id or SMEME_DECISION_TREE_ID is required; "
            "copy the Listed tree's id from the dashboard or smeme_reasoning_list"
        )
    if bool(args.reviewed_option) != bool(args.reviewed_source_id):
        parser.error("--reviewed-option and --reviewed-source-id must be supplied together")
    if args.reviewed_option and (
        not args.model or not args.case_bundle or not args.stop_after_first_admission
    ):
        parser.error(
            "reviewed admission requires --model, --case-bundle, and --stop-after-first-admission"
        )
    print(f"Connecting to {SMEME_MCP_URL}")
    print(f"OAuth redirect_uri=http://{OAUTH_CALLBACK_HOST}:{OAUTH_CALLBACK_PORT}/callback")
    print("Expect a browser window for Clerk OAuth (Bearer, not the cookie session).")
    case_bundle = (
        load_public_case_bundle(args.case_bundle, args.case_id) if args.case_bundle else None
    )
    matter_context = case_bundle.matter_context() if case_bundle else ACME_MATTER
    if case_bundle is not None:
        print(
            f"Loaded {case_bundle.case_id}: {len(case_bundle.sources)} public synthetic sources "
            f"(SHA-256 {case_bundle.sha256})"
        )
    provider = make_openai_proposal_provider() if args.model else None
    result = await run(
        matter_context,
        args.decision_tree_id,
        args.thread_id,
        case_bundle=case_bundle,
        proposal_provider=provider,
        mechanical_first_option=args.mechanical_first_option,
        evidence_output=args.evidence_output,
        stop_after_admitted_continuations=(1 if args.stop_after_first_admission else None),
        reviewed_admission=(
            (args.reviewed_option, args.reviewed_source_id) if args.reviewed_option else None
        ),
    )
    print(json.dumps(_terminal_summary(result), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
