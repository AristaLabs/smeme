# Host examples

Host-side clients that call SMEme over MCP. They are **not** part of the Core
appliance image. SMEme is source-available / fair-code under the
[SMEme SUL 1.0](../LICENSE.md) — not open source.

## `smeme_langgraph_withholding.py`

Guided gather against a **Deployed + Listed** decision tree:

`list` → `evaluate(decision_tree_id)` → model proposes one option → human
`interrupt()` → `evaluate_continue` → report **or** the next task the solver
chooses.

The ACME withholding file (CRM #123) is the prose case from
[*Introducing SMEme*](https://aristalabs.ai/introducing-smeme.html). Point
`SMEME_DECISION_TREE_ID` at *your* Listed tree; do not assume it is that matter.

### Pins

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r examples/requirements.txt
```

`langchain.mcp` is flagged **BETA** in langchain 1.4.0.

### SaaS OAuth (DCR off)

Hosted MCP is Bearer OAuth 2.1, not the browser cookie session. Clerk is the
authorization server. Dynamic client registration is off, so pass the public
PKCE `client_id` (default matches `/docs/mcp`). FastMCP listens on
`http://localhost:8787/callback` — that exact URI must be allowed on the MCP
OAuth application. Tokens stay in memory; each run re-opens the browser.

Self-host with DCR off: set `SMEME_MCP_URL` and `SMEME_OAUTH_CLIENT_ID` to your
pre-registered client.

### Run

```bash
export OPENAI_API_KEY=...          # or a Hugging Face / TGI token
# export OPENAI_BASE_URL=https://...   # optional; ChatOpenAI is OpenAI-compatible
# export MODEL_ID=meta-llama/Llama-3.3-70B-Instruct
export SMEME_DECISION_TREE_ID=<uuid from smeme_reasoning_list.id>

python examples/smeme_langgraph_withholding.py
```

`run()` always hits `interrupt()` and then resumes with `Command(resume=…)`.
The file's auto-admit is mechanical so the loop compiles; a human sits at that
gate in production.

Help: [GitHub Discussions — Start here](https://github.com/AristaLabs/smeme/discussions).
