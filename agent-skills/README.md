# Agent Skills (guidance authoring source)

**Product path:** after OAuth, an MCP client calls
``smeme_reasoning_capabilities`` (or ``smeme_reasoning_guidance_check``), then
``smeme_reasoning_guidance_get``, which returns the calling contract as markdown.
Agents do **not** install a local zip bundle — they ask the server for guidance.

This folder is the **human authoring source** for that guidance (and related MCP
content). Each skill is a directory with **`SKILL.md`** plus optional
`reference.md` / `examples.md`. CI builds the served artifact from these files
(``scripts/build_guidance_artifact.py``); run ``scripts/validate_agent_skills.py``
after edits.

**This README is repo-only** (contributors / operators editing prose). End users
and agents use the in-app **Connect your agent** page at `/docs/mcp` and the MCP
tools.

## Authoring style

Agent hosts and their harnesses can plan tool use. Skills should be **direct,
concise, and hard to misread** — not tutorials.

### Agent-safe vocabulary (required)

Shipped **`SKILL.md`** files are loaded into third-party LLM context. They must **not** reveal how SMEme reasons internally.

| Use (product layer) | Do **not** use (implementation layer) |
|---------------------|----------------------------------------|
| **reasoning engine**, **server**, **report**, **results**, **outcome**, **MCP client** | Z3, SAT, UNSAT, SMT, solver, satisfiable, entailment, theory (except wire `error.code` literals in backticks); host framing (**plugin**, **Cowork**) |
| **`report.result_kind`**, **`brief_memo`**, **`candidates`**, **`blockers`** | `SAT_*`, `triggered_edges`, `true_conclusion_id`, guard/clause/reach atom names |
| Plain-language error meanings (“reasoning engine timed out”) | “Z3 check timed out”, “SAT call budget”, “unsatisfiable” |

**Wire identifiers** (`error.code`, tool names, JSON field names the agent must parse) may appear **in backticks only**. Describe what they mean in product language in the adjacent column — mirror server `error.message` copy from `smeme/mcp/tool_contract.py` / tool handlers, not engineering shorthand from sprint docs.

**Server messages:** `error.message` and `blockers.message` on MCP tool responses follow the same product-vocabulary rules as skills (reasoning engine, report, outcome — not Z3/SAT/entailment). When you change a user-quoted server string, update the matching skill row in the same PR.

`scripts/validate_agent_skills.py` enforces a denylist on agent-skills markdown
(prose only — text inside `` `backticks` `` or HTML comments may use wire field
names such as ``satisfiable``, ``_server_plugin_version``, or
``installed_plugin_version``). Generated per decision tree manifests
([`templates/reasoning-question-manifest/`](templates/reasoning-question-manifest/))
must follow the same rules.

| Do | Don’t |
|----|--------|
| State preconditions as **assumptions**; call tools and follow the error map | Ask the user to confirm setup before the first tool call |
| **`error.code` tables** with plain-language “what to do” (quote `error.message` to the user) | Retry loops, vague “try again”, or re-explaining server logic |
| Name contracts by meaning (**provenance envelope**, `answers` + `evidence_*`) | Internal planning labels (e.g. “shape C”) |
| **`smeme_reasoning_capabilities` → `reasoning.tools`** as the tool catalog; note deferred client lists | Infer tool availability from UI or `tool_search` alone |
| **`raw_answers_json`**: serialized JSON object (`answers`, `evidence_items`, `evidence_refs`); same payload for validate and evaluate; not double-encoded | “JSON string”, duplicate payload examples, full success JSON when a field table suffices |
| Examples and hedging **only** where ambiguity is real (empty list, double-encoding, deferred `evaluate`) | Good/bad example blocks for obvious behavior |
| **`_server_plugin_version`** on **success** responses only | Claim every response carries the version watermark |
| Product vocabulary in prose (**reasoning engine**, **report**, **results**) | Formal-methods or stack terms (Z3, SAT/UNSAT, solver, satisfiable, SMT) |

Blind-evaluation and wire-contract rules are enforced by the server and its
agent-facing tool contracts. Canonical codes: `smeme/mcp/tool_contract.py`.

After editing here, run ``scripts/build_guidance_artifact.py`` and ``scripts/validate_agent_skills.py``.

## Progressive disclosure (how many skills, when they load)

| Skill | Role | When to load |
|-------|------|----------------|
| **`smeme-reasoning`** | Connect to SMEme, list decision trees, template tools, evaluate, MCP errors, blind-protocol boundaries. | **Always** — core reasoning skill. |
| **Per decision tree question manifest** | Flat checklist: question ids, text, valid answers for *this* decision tree — no topology. | **After** the user (or agent) has chosen a target decision tree — from **`template_get`** or CWP-5 file. |
| **`smeme-reasoning-slot-fill`** | Phase 1: subject, gather sources, build **provenance envelope** → **`raw_answers_json`**. | **After** worksheet is loaded, **before** **`smeme_reasoning_evaluate`**. |
| **`smeme-reasoning-outcomes`** | Non-`concluded` **`report.result_kind`**: ambiguous, incomplete, inconsistent, source conflict. | When **`evaluate`** returns a **`report`** that is not **`concluded`**. |
| **`smeme-decision-tree-author`** | Chat-native authoring: design guidance → session fork (Quick encode vs Research & critique) → iterate Q/options/branches in prose → `smeme_authoring_validate_graph` → `smeme_authoring_create_draft`. Secondary path; wizard remains primary for server-side research-heavy greenfield. | When the user wants to build a decision tree in chat. On by default when MCP is enabled; opt out with `MCP_AUTHORING_GRAPH_TOOLS_ENABLED=false`. Calls `smeme_authoring_design_guidance`. |

**Per decision tree skills** should not all sit in the default context. Preferred patterns:

1. **Generated at publish** (recommended — CWP-5): SMEme emits `SKILL.md` from question nodes + decision tree metadata.
2. **Template fill**: Use `templates/reasoning-question-manifest/SKILL.template.md` in CI or a small script; substitute title, slug, question list, and schema JSON.
3. **Manual**: Early adopters add a generated skill to their agent project.

## Layout

```
agent-skills/
├── README.md                          # this file
├── smeme-reasoning/SKILL.md          # core guidance
├── smeme-reasoning-slot-fill/SKILL.md       # Phase 1 subject + gather → raw_answers
├── smeme-reasoning-outcomes/SKILL.md        # non-concluded and conflict report handling
├── smeme-decision-tree-author/
│   ├── SKILL.md                             # chat authoring → validate → create_draft
│   └── DESIGN.md                            # design standard (build → _generated_design_guidance.py)
└── templates/reasoning-question-manifest/
    └── SKILL.template.md              # one copy per decision tree after substitution (not loaded until filled)
```

## MCP error contract

Reasoning tools return structured JSON. Expected failures use `error.code` / `error.message` (see **`smeme-reasoning`** skill table). Server module: `smeme/mcp/tool_contract.py`. Tools do not raise into the MCP layer; LangGraph on the server MCP path is deferred.

## Related docs

- [MCP / OAuth operator guide](../docs/guides/dr3-mcp-oauth-authoritative-sources.md) —
  self-host endpoint, discovery, and OAuth configuration.
- [Self-host quickstart](../docs/guides/self-host-quickstart.md) — Core setup
  and operator configuration.
