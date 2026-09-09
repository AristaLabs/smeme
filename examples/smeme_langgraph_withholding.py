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
  propose:   open model picks EXACTLY ONE option from the task, citing a source
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

import json
import os
from typing import Any, TypedDict

from fastmcp import Client
from fastmcp.client.auth import OAuth
from langchain.mcp import MCPAdapter
from langchain_openai import ChatOpenAI  # OpenAI-compatible: HF endpoint / TGI / vLLM
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

SMEME_MCP_URL = os.environ.get("SMEME_MCP_URL", "https://www.smeme.ai/api/v1/mcp")
# Public PKCE identifier (not a secret). Same value the dashboard / MCP docs use.
SMEME_OAUTH_CLIENT_ID = os.environ.get("SMEME_OAUTH_CLIENT_ID", "NRdsdBvrio0DW9yo")
OAUTH_CALLBACK_PORT = int(os.environ.get("SMEME_OAUTH_CALLBACK_PORT", "8787"))
OAUTH_CALLBACK_HOST = os.environ.get("SMEME_OAUTH_CALLBACK_HOST", "localhost")

llm = ChatOpenAI(
    base_url=os.environ.get("OPENAI_BASE_URL"),  # e.g. a Hugging Face endpoint
    model=os.environ.get("MODEL_ID", "meta-llama/Llama-3.3-70B-Instruct"),
    temperature=0,
)


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


def _payload(tool_message: Any) -> dict:
    """ToolMessage -> structured content. Artifact first; content may be a
    string, a dict, OR a list of text blocks."""
    art = getattr(tool_message, "artifact", None)
    if isinstance(art, dict) and "structured_content" in art:
        return art["structured_content"]
    content = getattr(tool_message, "content", tool_message)
    if isinstance(content, list):
        content = "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    if isinstance(content, dict):
        return content
    try:
        return json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return {"_raw": content}


def _is_continue(payload: dict) -> bool:
    return payload.get("harness_next") == "continue_evaluate" and isinstance(
        payload.get("task"), dict
    )


def _oauth() -> OAuth:
    return OAuth(
        client_id=SMEME_OAUTH_CLIENT_ID,
        callback_port=OAUTH_CALLBACK_PORT,
        callback_host=OAUTH_CALLBACK_HOST,
        additional_client_metadata={"token_endpoint_auth_method": "none"},
    )


def make_nodes(tools: dict[str, Any]):
    """Nodes close over the tool catalog resolved once at bootstrap."""

    async def bootstrap(state: WithholdingState) -> WithholdingState:
        # Demo shortcut: falling back to the first Listed tree. In real use,
        # pass decision_tree_id in the initial state — an empty list is a valid
        # MCP result (count: 0 + hint), and the first tree may not be the
        # withholding tree (ACME is the prose case).
        tree_id = state.get("decision_tree_id")
        if not tree_id:
            listing = _payload(await tools["smeme_reasoning_list"].ainvoke({}))
            trees = listing.get("decision_trees") or []
            if not trees:
                return {"report": {"error": "no decision trees listed", "listing": listing}}
            tree_id = trees[0]["id"]  # pass this UUID to evaluate as decision_tree_id
        started = _payload(
            await tools["smeme_reasoning_evaluate"].ainvoke({"decision_tree_id": tree_id})
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
        msg = await llm.ainvoke(
            "Pick exactly one option. Cite the source that supports it "
            "(agreement, intake memo, email, CRM record). Do not write a memo.\n"
            f"Question: {task['stem']}\n"
            f"Options: {task['options']}\n---\n{state['matter_context']}"
        )
        return {
            "proposed_answer": {
                "question_id": task["question_id"],
                "raw": msg.content,
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
        decision = interrupt(
            {"type": "admission_required", "proposal": state["proposed_answer"]}
        )
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
        result = _payload(
            await tools["smeme_reasoning_evaluate_continue"].ainvoke(
                {
                    "inquiry_session_id": state["inquiry_session_id"],
                    "question_id": state["proposed_answer"]["question_id"],
                    "selected_option": state["selected_option"],
                    "provenance_id": state["provenance_id"],
                }
            )
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


def build_graph(tools: dict[str, Any]):
    bootstrap, propose, admit, evaluate = make_nodes(tools)

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
):
    """One full turn of the loop, INCLUDING the resume that completes the gate.

    ainvoke pauses at admit and returns __interrupt__; the graph only
    proceeds when counsel resumes with an admission. In a real deployment the
    resume comes from the review UI, hours later if need be — an interrupt can
    outlive this connection, and resuming a thread re-enters the context.

    The Command below is a mechanical resume so the listing compiles as a loop.
    A review UI would put a real option and a real citation (intake memo, SPA
    clause, email) in that payload — not options[0]. A human sits at this gate.
    """
    async with MCPAdapter(Client(SMEME_MCP_URL, auth=_oauth())) as adapter:
        tools = {t.name: t for t in await adapter.list_tools()}
        app = build_graph(tools)
        config = {"configurable": {"thread_id": thread_id}}

        paused = await app.ainvoke(
            {"matter_context": matter_context, "decision_tree_id": decision_tree_id},
            config,
        )
        while paused.get("__interrupt__"):
            proposal = paused["__interrupt__"][0].value["proposal"]
            print("PROPOSED:", proposal["raw"])
            # Mechanical resume for the listing — in real use, counsel reviews:
            paused = await app.ainvoke(
                Command(
                    resume={
                        "admit": True,
                        "value": proposal["options"][0],  # exact option string
                        "provenance_id": "acme-intake-memo",  # your citation reference
                    }
                ),
                config,
            )
        return paused


# Prose case from Introducing SMEme. Not a live Listed-tree stem.
ACME_MATTER = """\
ACME, Inc. sale of asset X to party D. CRM matter #123.
Host-side sources: associate intake diagnostic memo, email correspondence,
draft agreement. Only an admitted option + provenance_id go to SMEme.
"""


if __name__ == "__main__":
    import asyncio

    tree_id = os.environ.get("SMEME_DECISION_TREE_ID", "")
    print(f"Connecting to {SMEME_MCP_URL}")
    print(
        f"OAuth redirect_uri=http://{OAUTH_CALLBACK_HOST}:{OAUTH_CALLBACK_PORT}/callback"
    )
    print("Expect a browser window for Clerk OAuth (Bearer, not the cookie session).")
    if not tree_id:
        print(
            "SMEME_DECISION_TREE_ID unset — bootstrap will use the first Listed tree, "
            "which may not be the ACME withholding tree."
        )
    raise SystemExit(asyncio.run(run(ACME_MATTER, tree_id)))
