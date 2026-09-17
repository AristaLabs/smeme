# Host examples

Host-side clients that call SMEme over MCP. They are **not** part of the Core
appliance image. SMEme is source-available / fair-code under the
[SMEme SUL 1.0](../LICENSE.md) — not open source.

## `smeme_apply_sample.py` (start here)

No LLM. OAuth to the running app, list the sample decision tree (the first empty
MCP list seeds it; otherwise click **Load sample** on the dashboard), send
canned radio `raw_answers`, print a `report`. Success is: the solver returned
a report.

### Run it

```bash
uv run examples/smeme_apply_sample.py
```

That is the complete production command. The script's
[PEP 723](https://peps.python.org/pep-0723/) metadata asks uv for the tested
FastMCP version and isolates it from this project's dependencies. Do not
activate `.venv` or install FastMCP manually.

The command opens a browser for OAuth consent and starts a temporary callback
listener at `http://localhost:8787/callback`. Sign in to the same SMEme account
that owns the sample. Success ends with:

```text
result_kind='...'
headline='...'
the solver returned a report.
```

The in-memory OAuth-token warning is expected for this one-shot example.

### Before running

- Use an account with the SMEme sample already loaded, **or** an account with
  zero Listed decision trees. The first empty `smeme_reasoning_list` may create
  the sample automatically.
- If the account has other Listed trees but no sample, list is intentionally
  non-empty and does not seed. Click **Load sample** on the dashboard first.
- The sample consumes one decision-tree slot. At the plan limit, loading or
  seeding returns `quota_exceeded`.
- The script selects only `sample_key: smeme_sample_v1`; it will never send
  canned sample answers to another tree.

### Another deployment

The defaults target `https://www.smeme.ai` and its public PKCE client. For
staging or self-hosting, override **both** values with that deployment's MCP
URL and registered OAuth client:

```bash
SMEME_MCP_URL=https://your-host.example/api/v1/mcp \
SMEME_OAUTH_CLIENT_ID=your_registered_public_client_id \
uv run examples/smeme_apply_sample.py
```

SaaS is **DCR-off**. Do not use bare `OAuth()`. The OAuth application must
allow the exact callback `http://localhost:8787/callback`. Authentication uses
an OAuth Bearer token, not the browser session cookie.

### Troubleshooting

- **`invalid_client`** — the client ID does not exist in the OAuth tenant for
  the target URL. Use that deployment's registered client ID; production and
  internal staging tenants can differ.
- **`redirect_uri` mismatch** — add
  `http://localhost:8787/callback` to the OAuth application's allowed redirect
  URIs, or set `SMEME_OAUTH_CALLBACK_HOST` /
  `SMEME_OAUTH_CALLBACK_PORT` consistently.
- **No Listed `'SMEme sample'` tree** — if list returned other trees, click
  **Load sample**. Automatic creation happens only when list is empty.
- **`ModuleNotFoundError` or mixed `fastmcp`/`mcp` imports** — use the exact
  `uv run examples/smeme_apply_sample.py` command from the repository root.
  Inline metadata isolates the script; manual virtualenv setup is unnecessary.

Help: [GitHub Discussions — Start here](https://github.com/AristaLabs/smeme/discussions/30).

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

Help: [GitHub Discussions — Start here](https://github.com/AristaLabs/smeme/discussions/30).
