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

The ACME file is the **prose** case. Live Listed trees on an account may be a
different matter — pass ``decision_tree_id`` (list item ``id``) and keep
``matter_context`` in the host. Do not paste live task stems into public copy
as if they were the withholding walkthrough.

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
import inspect
import json
import os
from collections.abc import Awaitable, Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from mcp_tool_decode import decode_tool_message, error_payload, transport_is_error

SMEME_MCP_URL = os.environ.get("SMEME_MCP_URL", "https://www.smeme.ai/api/v1/mcp")
# Public PKCE identifier (not a secret). Same value the dashboard / MCP docs use.
SMEME_OAUTH_CLIENT_ID = os.environ.get("SMEME_OAUTH_CLIENT_ID", "NRdsdBvrio0DW9yo")
OAUTH_CALLBACK_PORT = int(os.environ.get("SMEME_OAUTH_CALLBACK_PORT", "8787"))
OAUTH_CALLBACK_HOST = os.environ.get("SMEME_OAUTH_CALLBACK_HOST", "localhost")

REQUIRED_TOOLS = {
    "smeme_reasoning_capabilities",
    "smeme_reasoning_list",
    "smeme_reasoning_evaluate",
    "smeme_reasoning_evaluate_continue",
}
ADVERTISED_REQUIRED_TOOLS = REQUIRED_TOOLS - {"smeme_reasoning_capabilities"}


class IntegrationError(RuntimeError):
    """Actionable hosted-client contract failure."""


class WithholdingState(TypedDict, total=False):
    matter_context: str  # ACME file: agreement, intake memo, email, CRM #123
    decision_tree_id: str  # list item id; pass to evaluate as decision_tree_id
    inquiry_session_id: str
    open_task: dict  # {question_id, stem, options} — from the SOLVER
    proposed_answer: dict  # {question_id, raw, options}
    admission: str  # "admitted" | "rejected"
    selected_option: str  # exact option string
    provenance_id: str  # non-empty when admitted; citation ref (not a check)
    report: dict | None  # also carries terminal non-report payloads; see evaluate


ProposalProvider = Callable[
    [WithholdingState],
    dict[str, Any] | Awaitable[dict[str, Any]],
]
EventSink = Callable[[dict[str, Any]], None]


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
        message = await model.ainvoke(
            "Return exactly one offered option and no other text. "
            "The operator will separately admit it and attach provenance.\n"
            f"Question: {task['stem']}\n"
            f"Options: {task['options']}\n---\n{state['matter_context']}"
        )
        raw = getattr(message, "content", message)
        text = raw.strip() if isinstance(raw, str) else str(raw)
        value = text if text in task["options"] else None
        return {"question_id": task["question_id"], "raw": raw, "value": value}

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
        return {"decision_tree_id": tree_id, "report": started}

    async def propose(state: WithholdingState) -> WithholdingState:
        task = state["open_task"]
        proposed = provider(state)
        if inspect.isawaitable(proposed):
            proposed = await proposed
        value = proposed.get("value")
        if value not in task["options"]:
            value = None
        return {
            "proposed_answer": {
                "question_id": task["question_id"],
                "stem": task.get("stem"),
                "raw": proposed.get("raw"),
                "value": value,
                "options": task["options"],
            }
        }

    def admit(state: WithholdingState) -> WithholdingState:
        """THE GATE — host interrupt before evaluate_continue, always.

        Rejection never reaches MCP. Out-of-set value or empty provenance_id
        takes the same reject edge as an explicit reject (re-propose). Production
        UIs should re-interrupt on a bad resume; this listing does not add a
        third path.
        """
        decision = interrupt({"type": "admission_required", "proposal": state["proposed_answer"]})
        if not decision.get("admit"):
            return {"admission": "rejected"}
        value = decision.get("value")
        prov = (decision.get("provenance_id") or "").strip()
        # Radio-only, enforced. An out-of-set value is not an admission.
        if value not in state["proposed_answer"]["options"] or not prov:
            return {"admission": "rejected"}
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
        return {"report": result.get("report") or result}

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
    proposal_provider: ProposalProvider | None = None,
    mechanical_first_option: bool = False,
    input_fn: Callable[[str], str] = input,
    evidence_output: Path | None = None,
    stop_after_admitted_continuations: int | None = None,
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

    def record(event: dict[str, Any]) -> None:
        evidence["events"].append(event)

    async with MCPAdapter(Client(SMEME_MCP_URL, auth=_oauth())) as adapter:
        tools = {t.name: t for t in await adapter.list_tools()}
        verify_required_tools(tools)
        record({"event": "tool_inventory", "tools": sorted(tools)})
        app = build_graph(tools, proposal_provider, record)
        config = {"configurable": {"thread_id": thread_id}}

        paused = await app.ainvoke(
            {"matter_context": matter_context, "decision_tree_id": tree_id},
            config,
        )
        admitted_continuations = 0
        while paused.get("__interrupt__"):
            proposal = paused["__interrupt__"][0].value["proposal"]
            record(
                {
                    "event": "interrupt",
                    "question_id": proposal.get("question_id"),
                    "option_count": len(proposal.get("options", [])),
                }
            )
            if (
                stop_after_admitted_continuations is not None
                and admitted_continuations >= stop_after_admitted_continuations
            ):
                break
            if mechanical_first_option:
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
                    "action": "admitted" if decision.get("admit") else "rejected",
                    "continuation_called": bool(decision.get("admit")),
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
    report = state.get("report")
    if isinstance(report, dict):
        error = report.get("error")
        if isinstance(error, dict):
            summary["terminal_error"] = {
                "code": error.get("code"),
                "message": error.get("message"),
                "status": error.get("status"),
            }
        else:
            summary["report"] = {
                "result_kind": report.get("result_kind"),
                "headline": report.get("headline"),
            }
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
    for index, option in enumerate(options, start=1):
        print(f"  {index}. {option}")

    if has_proposal:
        action = input_fn("[a]dmit proposal, [e]dit/select option, or [r]eject? ").strip().lower()
        if action in {"r", "reject"}:
            return {"admit": False}
        if action in {"a", "admit"}:
            selected = proposed_value
        elif action in {"e", "edit"}:
            raw_index = input_fn("Option number: ").strip()
            selected = _option_at(options, raw_index)
        else:
            return {"admit": False}
    else:
        raw_index = input_fn("Option number, or [r]eject? ").strip()
        if raw_index.lower() in {"r", "reject"}:
            return {"admit": False}
        selected = _option_at(options, raw_index)

    if selected is None:
        return {"admit": False}
    provenance_id = input_fn("Non-empty provenance id: ").strip()
    if not provenance_id:
        return {"admit": False}
    return {
        "admit": True,
        "value": selected,
        "provenance_id": provenance_id,
    }


def _option_at(options: list[str], raw_index: str) -> str | None:
    try:
        index = int(raw_index)
    except ValueError:
        return None
    if 1 <= index <= len(options):
        return options[index - 1]
    return None


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
    args = parser.parse_args()
    if not args.decision_tree_id.strip():
        parser.error(
            "--decision-tree-id or SMEME_DECISION_TREE_ID is required; "
            "copy the Listed tree's id from the dashboard or smeme_reasoning_list"
        )
    print(f"Connecting to {SMEME_MCP_URL}")
    print(f"OAuth redirect_uri=http://{OAUTH_CALLBACK_HOST}:{OAUTH_CALLBACK_PORT}/callback")
    print("Expect a browser window for Clerk OAuth (Bearer, not the cookie session).")
    provider = make_openai_proposal_provider() if args.model else None
    result = await run(
        ACME_MATTER,
        args.decision_tree_id,
        args.thread_id,
        proposal_provider=provider,
        mechanical_first_option=args.mechanical_first_option,
        evidence_output=args.evidence_output,
        stop_after_admitted_continuations=(1 if args.stop_after_first_admission else None),
    )
    print(json.dumps(_terminal_summary(result), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
