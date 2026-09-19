# ACME LangGraph technical preview

Start the public LangGraph Inquire example in about five minutes. This
walkthrough calls a running SMEme app over MCP; it does not import SMEme as a
reasoning library.

For the shortest first report, use the no-model
[`smeme_apply_sample.py`](../../examples/README.md#smeme_apply_samplepy-start-here)
example first. The ACME walkthrough is longer because it demonstrates
solver-selected questions and a human admission boundary.

## 1. Load the example

1. Sign in to a Free hosted account and open **Decision trees**.
2. Read the slot warning and the complete fictional-demo disclaimer.
3. Select **Load ACME LangGraph example**.

The action creates, Deploys, and Lists one account-owned decision tree. It is
opt-in and does not replace the generic two-question sample. Repeating the load
reuses the same tree and does not consume another slot.

## 2. Download the case files

Select **Download synthetic case files** on the dashboard. Keep the filename
`smeme-acme-dataset-distributed.zip`; the generated command expects it in your
Downloads directory.

Expected SHA-256:

```text
96b8534209b11ca64899be4f054077ca6000ead1059437cd6343968554add560
```

The 61-file archive contains only public synthetic material. Do not substitute
a maintainer archive, decision-tree export, regression answers, expected
conclusions, role map, or analysis fixture.

## 3. Get the public client

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed,
then clone Core:

```bash
git clone https://github.com/AristaLabs/smeme.git
cd smeme
```

The script carries exact PEP 723 dependency pins. Do not activate the
application virtual environment or install FastMCP manually.

## 4. Run the generated command

Copy **Run with LangGraph** from the dashboard and run it from the repository
root. It has this shape:

```bash
SMEME_MCP_URL=https://your-deployment.example/api/v1/mcp \
SMEME_OAUTH_CLIENT_ID=your_deployment_public_pkce_client_id \
uv run examples/smeme_langgraph_withholding.py \
  --decision-tree-id your_account_tree_uuid \
  --case-bundle ~/Downloads/smeme-acme-dataset-distributed.zip \
  --case-id matter-123
```

Use the generated values. Tree IDs, MCP origins, and OAuth clients are
deployment-scoped; a production client ID can fail against staging and vice
versa. Do not guess a UUID or copy one from another account.

The command opens a browser for OAuth. Sign in to the same account that loaded
the tree. Authentication uses an OAuth Bearer token, not the browser cookie.
The temporary callback is `http://localhost:8787/callback`.

## 5. Admit or reject evidence

The default run is model-free. For each solver-selected task:

1. Inspect the named synthetic sources in the ZIP.
2. Select one exact offered option.
3. Enter the public source ID as provenance.
4. Confirm admission.

Only an admitted option and source ID reach SMEme; the full matter remains in
the host. Enter `r` to reject a proposal. Rejection loops locally and sends no
`evaluate_continue` call.

To let an OpenAI-compatible model propose an exact option, source ID, and
verbatim excerpt before human review, set `OPENAI_API_KEY` (and optionally
`OPENAI_BASE_URL` and `MODEL_ID`) and append `--model`. The model proposes; the
human admits; SMEme determines what follows.

## Expected outcomes

Each continuation returns one of:

- another solver-selected task;
- a structured report; or
- **verification required** (`isolated_evaluations_required`).

Verification required is an intentional fail-closed boundary, not a generic
client error. If a report includes warnings or an operational stop, the client
prints those qualifiers rather than presenting an unqualified success.

## Cleanup and troubleshooting

- Delete the ACME decision tree from the dashboard when finished to recover the
  decision-tree slot.
- Delete the downloaded ZIP and any `--evidence-output` capture you do not need.
- `invalid_client`: copy the generated command again from the target deployment.
- `redirect_uri` mismatch: the OAuth application must allow
  `http://localhost:8787/callback`.
- Tree not Listed: reload the example from the dashboard; the operation repairs
  Deploy/Listed state idempotently.
- Bundle checksum failure: download the ZIP again from the dashboard.

This is fictional technical demonstration material, not legal, tax,
accounting, compliance, or other professional advice. Provenance records where
an answer came from; it does not establish that a source is true,
authoritative, current, or legally sufficient.
