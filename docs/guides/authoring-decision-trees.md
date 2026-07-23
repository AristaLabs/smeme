# Authoring decision trees

SMEme Core has **one authoring model** and **two draft paths**. Both produce the
same `QNR.graph_data` **DTGraph** JSONB, then share the same lifecycle: editor →
**Deploy** → IR/Z3 → **Listed** → evaluate/report.

| Path | When to use | Server LLM / search |
|------|-------------|---------------------|
| **Web wizard** | Research-heavy greenfield; pasted text/files as context | Yes (OpenAI; optional Tavily) |
| **MCP chat** (`smeme-decision-tree-author` skill) | Iterate in conversation; agent does external research | No server egress |

After either path saves a draft, authors refine structure in the **graph editor**,
**Deploy** a validated version, and optionally mark it **Listed** for MCP tools.

See also: [self-host quickstart](self-host-quickstart.md) · [agent-skills source](../../agent-skills/README.md)

---

## Shared lifecycle

```text
Draft (DTGraph in graph_data)
  → Editor (human edits, validation)
  → Deploy (compile_qnr_to_ir → Z3 artifact)
  → Listed / Hidden (MCP discoverability)
  → Evaluate / report (structured raw_answers)
```

**Deploy** validates graph structure and persists the compiled reasoning artifact.
**Listed** controls whether your MCP-connected agent can discover and invoke the
tree. Evaluation and logical-analysis tools run against the deployed artifact, not
the editor draft.

Wire identifiers stay stable for compatibility: `qnr_id`, REST paths under `/qnr/`,
`compile_qnr_to_ir`, and `.smeme.json` export envelope `qnr.graph`.

---

## Path 1 — Web wizard

**Flag:** `SMEME_AI_GENERATION_ENABLED=true` (off by default in the Core image).

**Goal:** Help a subject-matter expert go from a brief to a draft decision tree
with AI-assisted research, design, and build — then hand off to the editor.

### Source-grounded context (not RAG)

Pasted text and uploaded files are **source-grounded context augmentation** for
the wizard's research and design steps. SMEme does **not** embed them in a vector
store or run retrieval-augmented generation. The LangGraph run carries the brief
and extracted source text in workflow state; optional Tavily search adds external
pages when configured.

### Flow

1. **Brief** — title, domain description, optional pasted text / files.
2. **Research** — OpenAI-assisted factor analysis; optional Tavily web search
   (`TAVILY_API_KEY`). Human review and edits (LangGraph interrupts).
3. **Conclusions** — approve or edit possible outcomes.
4. **Design** — markdown decision-tree design from approved context.
5. **Build** — structured DTGraph JSON → dashboard draft → editor.

Server-side LLM and search calls happen **only** on this path. Operators who need
sovereignty leave `SMEME_AI_GENERATION_ENABLED=false` and use MCP chat or manual
editor authoring.

**Related flags:** `OPENAI_API_KEY` (required when generation is on),
`TAVILY_API_KEY` (optional), `SHOW_QNR_GENERATION_REGION_SELECTOR` (Tavily region
control on the brief form).

---

## Path 2 — MCP chat authoring

**Skill:** [`smeme-decision-tree-author`](../../agent-skills/smeme-decision-tree-author/SKILL.md)

**Flags:** `MCP_ENABLED=true`; authoring tools on by default when MCP is enabled.
Opt out with `MCP_AUTHORING_GRAPH_TOOLS_ENABLED=false`.

**Goal:** The user's agent iterates questions, options, and branches in plain
language, structures a `dt_graph_json` payload, validates it, and creates a
dashboard draft after explicit confirmation. **No server LLM or search egress**
on this path — design guidance is served as static markdown from
`smeme_authoring_design_guidance`.

### Tool sequence

1. `smeme_authoring_design_guidance` — fetch the design standard (cache by digest).
2. Iterate with the user in prose until they are ready to push.
3. `smeme_authoring_validate_graph` — pass `dt_graph_json` (raw graph or
   `.smeme.json` export envelope).
4. `smeme_authoring_create_draft` — persist draft when `draft_ready` and user confirms.

**Deploy** and **Listed** remain in the web editor; the agent does not auto-Deploy.

---

## DTGraph shape (summary)

Stored in `QNR.graph_data` as JSONB:

```json
{
  "nodes": [
    { "id": "q1", "type": "question", "data": { "text": "...", "type": "radio", "options": ["Yes", "No"], "required": true } },
    { "id": "c1", "type": "conclusion", "data": { "title": "...", "summary": "..." } }
  ],
  "edges": [
    { "source": "q1", "target": "c1", "condition": "Yes" }
  ],
  "metadata": { "title": "...", "description": "..." }
}
```

**Constraints today:** radio questions only; every path reaches a conclusion;
option labels on edges must match question options exactly; stable node ids
(letters, digits, `_`, `-`; start with a letter).

**Export envelope** (`.smeme.json`):

```json
{
  "smeme_export_version": "1",
  "qnr": { "title": "...", "graph": { "nodes": [], "edges": [], "metadata": {} } }
}
```

Authoring tools accept either the raw graph object or this envelope.

---

## Operator setup

| Concern | Wizard path | MCP chat path | Shared |
|---------|-------------|---------------|--------|
| Enable | `SMEME_AI_GENERATION_ENABLED=true` + `OPENAI_API_KEY` | `MCP_ENABLED=true` | Editor + Deploy always available |
| Optional research | `TAVILY_API_KEY` | Agent's own tools | — |
| Authoring tools | — | Default on; `MCP_AUTHORING_GRAPH_TOOLS_ENABLED=false` to opt out | — |
| Egress | OpenAI (+ Tavily if set) | None for trees on server | Clerk/OAuth if exposed |

**Not current product paths:** legacy “simple generation”, PydanticAI wrappers, or
a three-phase wizard story as the primary UX. **LangSmith** tracing is
hard-disabled in Core — do not document it as an operator toggle.

**Vocabulary:** “workflow” in code often means a **LangGraph execution graph**
(generation run, editor checkpoint). The **product artifact** is a **decision
tree** (DTGraph). User-facing copy uses *decision tree*; wire ids (`qnr_id`,
`/qnr/`) are unchanged.

---

## Quick reference

| Task | Where |
|------|--------|
| Start web wizard | Dashboard → Create new decision tree (when generation enabled) |
| Start MCP authoring | Connect agent → `smeme-decision-tree-author` skill |
| Edit graph | `/qnr/{qnr_id}/editor` |
| Deploy | Editor or dashboard Deploy / Redeploy |
| List for MCP | Dashboard **Listed** column (after Deploy) |
| Operator egress matrix | [self-host quickstart — sovereignty](self-host-quickstart.md#sovereignty--third-party-egress) |
