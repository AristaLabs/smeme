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

`list` → `evaluate(decision_tree_id)` → host or optional model proposes one
option → human `interrupt()` → `evaluate_continue` → report, the next task the
solver chooses, **or** `isolated_evaluations_required`.

For the account fixture, public case-file download, and dashboard-generated
command, follow the
[five-minute ACME LangGraph quickstart](../docs/guides/acme-langgraph-quickstart.md).

The last outcome is an intentional fail-closed boundary: the chat connector
does not fabricate the independent verification trials. Apply remains the
shortest first-run path when the host already has a reviewed worksheet and
wants a deterministic report.

The ACME withholding file (CRM #123) is the prose case from
[*Introducing SMEme*](https://aristalabs.ai/introducing-smeme.html). Point
`SMEME_DECISION_TREE_ID` at *your* Listed tree; do not assume it is that matter.

### Pins

The script carries isolated PEP 723 pins, so the recommended setup is:

```bash
uv run examples/smeme_langgraph_withholding.py --help
```

For a reusable examples environment instead, install the same exact pins:

```bash
python -m venv .venv-examples
source .venv-examples/bin/activate
pip install -r examples/requirements.txt
```

`langchain.mcp` is flagged **BETA** in LangChain 1.4.0. The tested client
versions are LangChain 1.4.0, LangGraph 1.2.11, FastMCP 4.0.3, and
langchain-openai 1.6.2.

### SaaS OAuth (DCR off)

Hosted MCP is Bearer OAuth 2.1, not the browser cookie session. Clerk is the
authorization server. Dynamic client registration is off, so pass the public
PKCE `client_id` (default matches `/docs/mcp`). FastMCP listens on
`http://localhost:8787/callback` — that exact URI must be allowed on the MCP
OAuth application. Tokens stay in memory; each run re-opens the browser.

Self-hosted MCP is not a Clerk-free, one-command authenticated path. Configure
an external OIDC/OAuth issuer, the local user mapping, a registered public
client, and the exact callback URI. Then set `SMEME_MCP_URL` and
`SMEME_OAUTH_CLIENT_ID` for that deployment.

### Run

The default is model-free and manual. The operator sees every solver task,
selects or edits an exact offered option, supplies a non-empty provenance ID,
and explicitly admits or rejects it. Blank, nonnumeric, and out-of-range input
re-prompts locally. Only `r` records a rejection; `c` explicitly cancels option
editing or provenance entry without calling `evaluate_continue`:

```bash
export SMEME_DECISION_TREE_ID=<uuid from smeme_reasoning_list.id>

uv run examples/smeme_langgraph_withholding.py
```

Tree selection is mandatory. The script checks that this exact ID appears in
the Listed-tree response; it never falls back to the first row.

To add a lazy OpenAI-compatible proposal model:

```bash
export OPENAI_API_KEY=...              # or provider token
# export OPENAI_BASE_URL=https://...   # Hugging Face endpoint, TGI, vLLM, etc.
# export MODEL_ID=meta-llama/Llama-3.3-70B-Instruct
uv run examples/smeme_langgraph_withholding.py --model
```

The model only proposes. The same operator admission prompt still runs before
`evaluate_continue`.

Terminal JSON keeps the report together with warnings, `harness_next`, status,
and stop reasons. Rank `harness_next` and stop reason over `report.headline`:
`status: ok` plus `missing_evidence_ref` means gather evidence, and a concluded
report may coexist with an operational stop. `isolated_evaluations_required` is
rendered under `verification_required`, not as a generic terminal error.
Operational stops also retain the bounded Inquire status and SAT/timing
diagnostics returned by the server.

To ground that proposal in the frozen public ACME dataset, provide the
public-distribution artifact `smeme-acme-dataset-distributed.zip` and run:

```bash
uv run examples/smeme_langgraph_withholding.py \
  --model \
  --case-bundle /path/to/smeme-acme-dataset-distributed.zip \
  --case-id matter-123
```

The host verifies the canonical bundle checksum, safely reads the selected
matter without extracting files, and gives those public synthetic sources to
the configured model. The model must return an exact offered option, a source
ID from that matter, and an excerpt found in that source by exact matching or
deterministic whitespace normalization for hard-wrapped text. There is no fuzzy
or semantic matching. The operator sees the option, source title, and excerpt
before admission. Full source content stays in LangGraph state; only the
admitted option and source ID reach SMEme. The source is an attribution, not a
claim that SMEme verified its truth or support.

For non-interactive smoke testing only:

```bash
uv run examples/smeme_langgraph_withholding.py --mechanical-first-option
```

That flag prints **MECHANICAL DEMONSTRATION ONLY** and admits the first offered
option. It is not the default or a reference admission policy. A rejection
loops back to proposal/manual selection and sends no continuation call.

For a bounded hosted verification, reject once, admit once, and use:

```bash
uv run examples/smeme_langgraph_withholding.py \
  --model \
  --case-bundle /path/to/smeme-acme-dataset-distributed.zip \
  --case-id matter-123 \
  --stop-after-first-admission \
  --evidence-output /tmp/smeme-langgraph-hosted-evidence.json
```

The evidence file contains package versions, tool names, response kinds, and
sanitized interrupt metadata. Dataset runs also record the public bundle hash,
case ID, source count, selected public source ID, and local excerpt-validation
result. It never serializes OAuth objects, tokens, headers, task stems, option
text, excerpts, or matter context.

For a capture resumed after a human has reviewed a proposal out of band, add
both `--reviewed-option '<exact option>'` and
`--reviewed-source-id '<exact public source ID>'`. This mode requires
`--model`, `--case-bundle`, and `--stop-after-first-admission`; it fails closed
if the fresh proposal differs or its excerpt does not pass local validation.

Help: [GitHub Discussions — Start here](https://github.com/AristaLabs/smeme/discussions/30).
