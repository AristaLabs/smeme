# Cowork / Claude Code — SMEme MCP runbooks

**Status (2026-07):** Product path is **connector-only** — MCP URL + OAuth Client ID + **`smeme_reasoning_guidance_get`**. The installable Cowork plugin zip and dashboard download are **removed**. Skills under [`plugin/cowork-skills/`](../../plugin/cowork-skills/) remain the **authoring source** for guidance content (not a user download).

Operator checklist (deploy + Clerk) and end-user connector flow. **Customer org IT / security:** [SMEme MCP — organization IT and security overview](cowork-plugin-superuser-admin-guide.md). Technical protocol: [DR-3 authoritative sources](dr3-mcp-oauth-authoritative-sources.md), [D016 — Auth & MCP](../DECISIONS.md#d016-authentication--permissions--final-plan-cowork-launch-remote-mcp-sso). Historical zip packaging notes: [`docs/guides/internal/cowork-plugin-artifacts-and-releases.md`](internal/cowork-plugin-artifacts-and-releases.md) (**archived**).

---

## 1. Operator runbook (production / staging)

### 1.1 Enable MCP on the app

1. Set **`MCP_ENABLED=true`** in the deployment environment (Render, Docker, etc.).
2. Restart the web process so settings reload.

Without this, the Streamable HTTP MCP mount and OAuth well-known routes are not registered.

### 1.2 Base URL must match what clients paste

RFC 9728 **`resource`** in protected-resource metadata is built from **`effective_base_url` + `MCP_HTTP_PATH`** (see [`smeme/mcp/urls.py`](../../smeme/mcp/urls.py), [`smeme/core/config.py`](../../smeme/core/config.py)).

| Setting | Role |
|---------|------|
| **`BASE_URL`** | Canonical public origin for local or custom hosting (no trailing slash). |
| **`RENDER_EXTERNAL_URL`** | On Render, if set, **overrides** `BASE_URL` for `effective_base_url`. |

**Rule:** The HTTPS (or dev HTTP) origin in **`BASE_URL` / `RENDER_EXTERNAL_URL`** must be the **same host and scheme** users and connectors use in the MCP URL. If they differ, OAuth discovery may advertise the wrong `resource` and clients will reject the connection. See [LESSONS_LEARNED — resource must match connection URL](../LESSONS_LEARNED.md#mcp-inspector-resource-field-must-match-connection-url-exactly).

### 1.3 MCP path

- Default **`MCP_HTTP_PATH`** is **`/api/v1/mcp`**. Change only if you intentionally mount MCP elsewhere; then update in-app docs / connector copy that cite the default (`MCP_SAAS_PUBLIC_MCP_URL` in [`smeme/mcp/urls.py`](../../smeme/mcp/urls.py)).

### 1.4 Smoke checks

- **Well-known (GET)** when `MCP_ENABLED=true` — **use this for curl** (finite JSON, not the MCP SSE URL):  
  `/.well-known/oauth-protected-resource<MCP_HTTP_PATH>` e.g. `https://<origin>/.well-known/oauth-protected-resource/api/v1/mcp` → expect **200**.  
  One-liner: `curl -sS -o /dev/null -w "%{http_code}\n" --max-time 20 "https://<origin>/.well-known/oauth-protected-resource/api/v1/mcp"`  
  Helper: `bash scripts/smoke_mcp_url.sh https://<origin>`  
  Also: `/.well-known/oauth-protected-resource` (root) and `/.well-known/oauth-authorization-server`.  
  **Do not** treat **`curl --max-time` against `…/api/v1/mcp/`** as down — that path **streams**; exit **28** with **`http_code` 200** often means the server answered. Details: [DR-3 Try locally](dr3-mcp-oauth-authoritative-sources.md#try-locally-dr-3-p0).
- **Streamable HTTP:** clients must send `Accept: application/json, text/event-stream` — a normal browser tab may show **406**; that can still mean the mount is correct.
- **Trailing slash / 307 / 406:** If logs show `POST …/mcp` **307** then `POST …/mcp/` **406**, see [LESSONS_LEARNED — MCP mount path](../LESSONS_LEARNED.md#mcp-mount-path-307-trailing-slash-redirect-and-post-406-starlette-mount). SMEme normalizes bare `{MCP_HTTP_PATH}` when `MCP_ENABLED`; connector URLs ending in **`…/mcp/`** are also safe.

### 1.5 Clerk OAuth application (MCP connector)

In the [Clerk Dashboard](https://dashboard.clerk.com/) → **OAuth applications**, configure the app used by **Cowork / Cursor / Claude Code / Inspector** (see [Clerk — connect MCP clients](https://clerk.com/docs/guides/ai/mcp/connect-mcp-client)).

**Redirect URIs — register every URI your users’ clients will use:**

| Client | Redirect URI(s) |
|--------|------------------|
| **Cowork (production)** | `https://claude.ai/api/mcp/auth_callback` |
| **ChatGPT (custom app / connector)** | `https://chatgpt.com/connector_platform_oauth_redirect` (legacy; register first). Per-app URI `https://chatgpt.com/connector/oauth/{callback_id}` is shown in ChatGPT app settings after create — add that exact URI if OAuth fails with `redirect_uri` mismatch. See [OpenAI Apps SDK auth](https://developers.openai.com/apps-sdk/build/auth). |
| **Cursor (IDE)** | **Per Cursor release** — not the Cowork URL; capture from Clerk error or follow [LESSONS_LEARNED — Cursor IDE](../LESSONS_LEARNED.md#cursor-ide-mcp-oauth) |
| **MCP Inspector — Quick flow** | `http://localhost:6274/oauth/callback` |
| **MCP Inspector — Guided flow** | `http://localhost:6274/oauth/callback/debug` |

Register **both** Inspector URIs or Guided flow fails with `redirect_uri does not match`. Details: [LESSONS_LEARNED](../LESSONS_LEARNED.md#mcp-inspector-has-two-different-oauth-callback-urls).

**Optional (Claude Code):** If you pin a localhost callback port, register `http://localhost:<port>/callback` to match the client. See [Claude Code MCP — OAuth](https://code.claude.com/docs/en/mcp.md).

**Public (PKCE) — must be ON:** Anthropic and other MCP clients use **Authorization Code + PKCE** as public clients (no stored client secret). The Clerk OAuth application must have **Public enabled**; otherwise Clerk rejects the authorization request and clients surface "Couldn't reach the MCP server". SMEme's mirrored AS metadata includes `"none"` in `token_endpoint_auth_methods_supported` so clients see PKCE-compatible token exchange.

**SaaS production policy (2026-06-18):** **Clerk instance DCR on** + **`CLERK_OAUTH_DYNAMIC_REGISTRATION=true`** on SMEme. Mirrored **`/.well-known/oauth-authorization-server`** and **`/.well-known/openid-configuration`** include **`registration_endpoint`** → **`{issuer}/oauth/register`**. **`SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS` is blank** — DCR mints per-connector `client_id` values; a static allowlist is impractical. Residual registration risk sits with **Clerk** (not SMEme as AS); SMEme still validates Bearer JWTs (JWKS, `iss`, `exp`), maps **`sub` → `users`**, and enforces transport rate limits + quotas. Startup may log **`mcp_oauth_client_allowlist_empty`** — expected on SaaS, not an action item.

**Self-hosted (DCR off):** Leave **Clerk instance-level Dynamic Client Registration disabled** if you accept only static clients. Document the static Client ID users paste into connectors (SaaS default: **`NRdsdBvrio0DW9yo`** / `MCP_SAAS_OAUTH_CLIENT_ID` in [`smeme/mcp/urls.py`](../../smeme/mcp/urls.py)). Optionally set **`SMEME_MCP_ALLOWED_OAUTH_CLIENT_IDS`** to that same id so only your declared OAuth app can call MCP.

**GTM (July 2026):** Product default is **DCR off** + **custom connector** (URL + static Client ID) + **`guidance_get`** bootstrap — see [connector-first `/docs/mcp`](/docs/mcp) and [CIMD research snapshot](../planning/cimd-mcp-client-registration-research-2026-07.md) (CIMD not implemented; Clerk has no visible support).

**Secrets:** The OAuth **client secret** is between the **MCP client** and **Clerk** — not stored in SMEme. SMEme only validates Bearer JWTs via JWKS ([LESSONS_LEARNED](../LESSONS_LEARNED.md#clerk-oauth-client-secret-is-between-mcp-client-and-clerk-not-smeme)).

### 1.6 CORS (development)

If browser-based MCP clients fail discovery from another origin, you may need to add Inspector’s origin to **`ALLOWED_ORIGINS`**. Do not widen production origins without intent. See [LESSONS_LEARNED — CORS preflight](../LESSONS_LEARNED.md#cors-preflight-options-400-vs-actual-get-200).

### 1.7 Token expiry and “random” auth failures

[D016](../DECISIONS.md#d016-authentication--permissions--final-plan-cowork-launch-remote-mcp-sso) notes real-world reports of **short-lived access tokens** and connectors showing errors until **re-authentication**. On the SMEme side, tools return structured **`auth_error`** when the Bearer is missing, invalid, or expired; users should **re-connect** the MCP connector (OAuth) rather than assuming the server is down. Align skills with [tool contracts — §5](../planning/cowork-plugin-delivery-sprints.md#5-tool-contracts-for-skills-authoring-canonical).

### 1.8 Dogfood matrix (staging + Cowork)

Use this before calling a release “verified” on anything other than production SaaS.

| Step | What to confirm |
|------|------------------|
| **Origin** | Staging (or dev) **`BASE_URL` / `RENDER_EXTERNAL_URL`** matches the MCP URL you paste in the client; RFC 9728 **`resource`** matches that URL ([§1.2](#12-base-url-must-match-what-clients-paste)). |
| **Connector** | Custom remote MCP connector with staging URL + static OAuth Client ID (or DCR if enabled) — [§2.2](#22-connect-mcp-remote-http). |
| **OAuth** | Clerk app: client redirect URIs + **Public (PKCE) ON**; SaaS/self-host policy per [§1.5](#15-clerk-oauth-application-mcp-connector). |
| **First connect** | Client completes OAuth; **`smeme_reasoning_capabilities`** returns JSON with **`version`** (= **`REASONING_CAPABILITIES_VERSION`**) and **`reasoning_mcp_surface`**. Success tool responses include **`_server_plugin_version`** (MCP surface watermark). Unauthenticated MCP POSTs get **401** + **`WWW-Authenticate`** (challenge includes **`resource_metadata`**). |
| **Web login** | User has signed in to SMEme web once so **`sub`** maps to **`users.clerk_user_id`**. |
| **Happy path** | Two phases in [§2.8](#28-user-happy-path-two-product-phases): list → template → validate (`harness_next`) → evaluate → optional logical analysis ([§2.9](#29-logical-analysis-tools)). Checklist: [§3](#3-one-session-checklist-dogfood--onboarding). |
| **Token refresh** | Leave the session idle past a token rotation (or revoke in Clerk) and retry a tool: expect **`auth_error`** until the user **re-connects** MCP — do not spin retry loops ([§1.7](#17-token-expiry-and-random-auth-failures)). |

Cowork end-to-end automation is still **manual**; MCP unit tests cover discovery and tool contracts ([`tests/unit/mcp/`](../../tests/unit/mcp/)).

---

## 2. End-user runbook

### 2.1 Bootstrap (no zip)

There is **no plugin zip to install**. After the MCP connector is connected ([§2.2](#22-connect-mcp-remote-http)), the agent should:

1. Call **`smeme_reasoning_capabilities`** (read `guidance.content_digest` and the tool list).
2. If needed, call **`smeme_reasoning_guidance_get`** and cache `content_markdown` (full calling contract).
3. Proceed with list → template → validate → evaluate.

In-app steps: **[Connect your agent](/docs/mcp)**. Skills markdown in [`plugin/cowork-skills/`](../../plugin/cowork-skills/) is maintained for **guidance generation**, not for end-user download.

**Version watermark:** Success tool responses include `_server_plugin_version` (= `REASONING_CAPABILITIES_VERSION`). That is an MCP surface version label, not a zip install version.

### 2.2 Connect MCP (remote HTTP)

**SaaS canonical values** (use in a **custom connector** when the plugin-bundled connector fails or greys out Client ID):

| Field | Value |
|-------|--------|
| **URL** | `https://www.smeme.ai/api/v1/mcp` |
| **OAuth Client ID** | `NRdsdBvrio0DW9yo` |
| **OAuth Client Secret** | leave blank (PKCE public client) |

**Recommended path (Claude Chat / Cowork / Desktop, ChatGPT, Cursor, etc.):**

1. **Settings → Connectors → Add custom connector** (or equivalent) with the table above.
2. Complete OAuth when prompted.
3. Sign in on [smeme.ai](https://www.smeme.ai) once ([§2.3](#23-sign-in-to-smeme-on-the-web-once)).
4. Let the agent bootstrap via guidance tools ([§2.1](#21-bootstrap-no-zip)).

With **Clerk DCR enabled**, some clients can self-register via **`registration_endpoint`** instead of pasting Client ID — both paths are supported when DCR is on.

**Self-hosted:** Use your origin + path for the MCP URL and your Clerk OAuth app Client ID; enable DCR or use static client + optional allowlist per [§1.5](#15-clerk-oauth-application-mcp-connector).

### 2.2a Guidance bootstrap (all hosts)

After OAuth, agents on **any** MCP host (Claude, ChatGPT, Cursor, Copilot, Inspector) should:

1. **`smeme_reasoning_capabilities`** — read **`guidance.content_digest`** and **`reasoning.tools`**.
2. If there is no cached guidance or the digest changed → **`smeme_reasoning_guidance_get`** (full calling contract markdown; cache in the conversation/workspace when the host allows).
3. Continue with **`smeme_reasoning_list`** → **`smeme_reasoning_template_get`** → validate → evaluate per the guidance content.

Server **`instructions`** and guidance tools are the product bootstrap path. There is no installable zip.

### 2.3 Sign in to SMEme on the web once

Before **`smeme_reasoning_list`** / **`smeme_reasoning_evaluate`** succeed, the user must have logged into **SMEme’s web app** at least once so a **`users`** row exists with **`clerk_user_id`** matching the Clerk token **`sub`**. Otherwise tools return **`auth_error`**. See [LESSONS_LEARNED](../LESSONS_LEARNED.md#bearer-token-sub-must-match-usersclerk_user_id).

### 2.4 If tools return `auth_error`

1. **Do not** retry the same call in a tight loop.
2. **Re-connect** the MCP connector (or complete OAuth again) and confirm web sign-in.
3. Optionally call **`smeme_reasoning_capabilities`** **after OAuth** (same Bearer as other tools) to confirm reachability and tool names — see [§5 tool contracts](../planning/cowork-plugin-delivery-sprints.md#5-tool-contracts-for-skills-authoring-canonical).

### 2.4a If tools return `concurrency_limit`

`concurrency_limit` means another MCP call for the same account is already mid-flight (lock contention), not that the monthly allowance is exhausted.

1. Wait briefly.
2. Retry once.
3. If it keeps recurring, ask the user to reduce parallel MCP calls and retry after in-flight calls complete.
4. Do **not** frame this as `quota_exceeded` and do **not** suggest upgrading.

### 2.5 What data leaves the device

Reasoning evaluation sends **`raw_answers_json`**: a **JSON object** keyed by **question node id** with discrete answer values. Values may include **user-typed strings** (e.g. free-text questions). There is **no** server-side **`raw_blob`** or document upload channel; emails, PDFs, and other source material stay on the client while the agent maps facts into that object. Blind-protocol framing: [§2.2](../planning/cowork-plugin-delivery-sprints.md#22-blind-evaluation-protocol-settled-design-constraint).

### 2.6 Question IDs and text (worksheet manifest)

**Owners** of **discoverable, compiled** QNRs can fetch a blind-protocol worksheet via MCP:

1. **`smeme_reasoning_template_check`** — `qnr_id`, **`slug`**, **`in_sync`**, **`manifest_core_digest`** (cheap; no compiler/CEVI fields). If **`in_sync`** is false, user re-publishes in the SMEme web app before evaluate.
2. **`smeme_reasoning_template_get`** — per-QNR markdown worksheet (`manifest_markdown` only on the wire); save locally if needed.

**Saved worksheets:** The server does **not** ship an “operator hints” placeholder block. If the user keeps a local copy, they may append **private notes below** the `FROZEN_MACHINE_BLOCK_END` comment; those notes are **not** sent to **`smeme_reasoning_evaluate`** and must not change exact option strings used in **`raw_answers`**.

Then build **`raw_answers`** from question node ids and call **`smeme_reasoning_evaluate`**. Same OAuth Bearer + linked-user rules as **`smeme_reasoning_list`**.

**Optional NL blob path:** When the deployment sets **`MCP_REASONING_BLOB_TOOL_ENABLED=true`** (see [DR-3 guide — environment](../guides/dr3-mcp-oauth-authoritative-sources.md#try-locally-dr-3-p0)), the server also exposes **`smeme_reasoning_evaluate_blob`** — use that for **`evidence_blob_v1`** case text per §2.7. With the default (**`false`**), rely on **`smeme_reasoning_evaluate`** and structured **`raw_answers`** only.

**Alternatives:** hand-fill [`SKILL.template.md`](../../plugin/cowork-skills/templates/reasoning-question-manifest/SKILL.template.md), or (**optional**) publish-time generated file if product ships [CWP-5](../planning/cowork-plugin-delivery-sprints.md#sprint-cwp-5--optional-publish-time-skillmd-file). See [§2.2 production precondition](../planning/cowork-plugin-delivery-sprints.md#22-blind-evaluation-protocol-settled-design-constraint).

### 2.7 Blob evidence evaluate (`smeme_reasoning_evaluate_blob`, opt-in)

**Operator gate:** The MCP tool is registered only when **`MCP_REASONING_BLOB_TOOL_ENABLED=true`** in the server environment (`smeme/core/config.py`). Default **`false`**: connectors do **not** see the tool in **`tools/list`** or **`smeme_reasoning_capabilities`**; **`tools/call`** for that name is not a supported path. Set **`true`** and restart to expose it (CEVI path; see [sprint-cevi-blob-evaluate](../planning/sprint-cevi-blob-evaluate.md)).

**Guidance / skills source:** The default **`plugin/cowork-skills/`** pack documents **`smeme_reasoning_evaluate`** + **`raw_answers`** only. When you turn **blob evaluate on** for a deployment, **update skills in the same release**: extend **`smeme-reasoning-plugin/SKILL.md`** and **`templates/reasoning-question-manifest/SKILL.template.md`**, regenerate guidance (`scripts/build_guidance_artifact.py`), bump **`REASONING_CAPABILITIES_VERSION`**, and run **`scripts/validate_cowork_plugin.py`**. See **`plugin/cowork-skills/README.md`**.

When the tool **is** enabled, users send **`evidence_blob_v1`** DTOs only (pre-processed client-side / harness-side), not ad hoc “set atom” instructions. The runtime path treats extractors as candidate generators; accepted facts must pass deterministic contract-gated checks.

### 2.7a Workflow-candidate scouting (`smeme_authoring_candidate_guidance`, opt-in) — live dogfood

**Operator gate:** Registered only when **`MCP_WORKFLOW_SCOUT_ENABLED=true`** (`smeme/core/config.py`, default **`false`**). One flag gates the **whole surface**: the `smeme_authoring_candidate_guidance` tool, the `candidate_rubric` block in `smeme_reasoning_capabilities`, and the `smeme_reasoning_list` empty-state scout nudge. The flag is read when the FastMCP singleton is built at process start, so **toggling takes effect on restart**, not in-place.

**Current status (2026-07-06):** set **`true` in production for live dogfood** (config default remains `false`). Effective on the next deploy that includes the scout code.

**Kill-switch:** If live scouting misbehaves (e.g. suggests too eagerly), set **`MCP_WORKFLOW_SCOUT_ENABLED=false`** and restart — no code deploy required. On Render the env change triggers the restart. Agents holding cached capabilities will then get clean failures (tool not registered).

**Scout skill:** The rubric *content* is server-side (`_generated_candidate_rubric.py`, served by the tool). Behavior prompts live in `plugin/cowork-skills/smeme-workflow-scout/` as guidance authoring source — not a user-facing zip.

For structured **`raw_answers`** only, use **`smeme_reasoning_evaluate`** as usual.

Expected grounding trace fields in responses/audit are:

- canonical fact id (`fact:*`) and projected solver symbol (`ir_*`) when applicable;
- source pointer (`source_item_id`, span offsets/snippet);
- binding rule id (`bridge_rule_id`) and confidence;
- for text facts, both human-readable `canon_text` and stable `text_digest`.

### 2.8 User happy path (two product phases)

For many creators, the MCP-connected agent acts as the **primary harness** (chat + tools) beside the SMEme web app. End-to-end reasoning is **two phases**, then optional **logical analysis** on the same envelope.

The product path is the **MCP connector** plus **guidance tools** (`smeme_reasoning_guidance_get`). Skill markdown under [`plugin/cowork-skills/`](../../plugin/cowork-skills/) is the authoring source for that guidance—revise it when tool contracts change.

#### Phase 1 — Gather and validate evidence until **E** is ready

1. **Collect** — The user (via their agent) pulls context from **other** MCP connectors, local files, and chat. Raw sources generally **stay client-side**; only derived payloads are sent to SMEme (see [§2.5](#25-what-data-leaves-the-device)).
2. **Shape** — The agent maps that context into SMEme’s **published** shapes: question ids and allowed answers from **`smeme_reasoning_template_get`** / manifest templates ([§2.6](#26-question-ids-and-text-worksheet-manifest)), and—where deployments enable it—**`evidence_blob_v1`** + contract-backed bridge rules ([§2.7](#27-blob-evidence-evaluate-smeme_reasoning_evaluate_blob-opt-in)).

   **Prompting discipline (shape step):** Skill text and harness prompts should **explicitly bound** the agent to an **NLP / slot-filling** role only: given whatever evidence the session has assembled—user-provided files or pasted text, **and/or** data the harness retrieved via **its own tool use** (other MCP servers such as mail, cloud drives, calendars, or issue trackers; local or project folders; session context)—produce **answers per isolated worksheet question id**, without inferring **branch order**, **edge conditions**, **conclusion targets**, or “repairing” the questionnaire. During **evidence gathering and validation**, the harness should **not** treat this step as prep for the solver: avoid anticipating **theories**, **logical reasoning** over the graph, or **`smeme_reasoning_evaluate`** (or outcomes) altogether—no dry-run “what if we evaluated now,” no mental model of **T(IR)**, and no steering answers toward a hoped-for conclusion. Those belong **only** in Phase 2 / analysis, after a valid **E** exists. This keeps the product positioning clear: the bundle is **connector + skills**, where skills teach **how to use our tools**, not a shadow decision engine.

3. **Validate** — Call **`smeme_reasoning_validate_answers`** with the provenance envelope (`answers` + `evidence_items` + `evidence_refs`). Success returns **`status`**, **`warnings[]`**, and **`harness_next`** (`phase_1_continue` | `phase_2_ok` | `user_input_needed`). **Exit criterion:** **`harness_next` is `phase_2_ok`** (typically after resolving `missing_evidence_ref` under `user_input_needed`).
4. **Iterate on failure** — Structured **`error.code`** / warning objects tell the harness *what* to fix (which questions, which sources), without exposing graph topology ([blind protocol §2.2](../planning/cowork-plugin-delivery-sprints.md#22-blind-evaluation-protocol-settled-design-constraint)).

#### Phase 2 — Evaluate **T(IR) ∧ E**

1. **Evaluate** — Call **`smeme_reasoning_evaluate`** only after Phase 1 exits with **`harness_next: phase_2_ok`**; choose **`persist`** deliberately (`reasoning_evaluation_runs` audit when `true`). Optional **`force_reachable_ids` / `force_unreachable_ids`** (assumptions \(\phi\); see [ALGEBRA §18](../../ALGEBRA.md)).
2. **Interpret** — Branch on **`report.result_kind`** and documented report fields. Load **`smeme-reasoning-outcomes`** when not **`concluded`**.
3. **Logical analysis (optional)** — **`what_if`**, **`how_to_reach`**, **`decisive_support`**, **`edit_affects_path`**, **`list_conclusions`** ([§2.9](#29-logical-analysis-tools)). These **often follow** evaluate on the same envelope; they **do not require** a prior evaluate when the user asks analysis up front (still need a baseline envelope).

**Shipping call sequence:** list → template_get → validate (`harness_next`) → evaluate → (optional) logical analysis. See also [§3](#3-one-session-checklist-dogfood--onboarding).

### 2.9 Logical analysis tools

**Tools:** `smeme_reasoning_what_if`, `smeme_reasoning_how_to_reach`, `smeme_reasoning_decisive_support`, `smeme_reasoning_edit_affects_path`, `smeme_reasoning_list_conclusions` — listed in `smeme_reasoning_capabilities` → `reasoning.tools`.

**`what_if`** — send two provenance envelopes (`base_raw_answers_json`, `override_raw_answers_json`); receive `before.report`, `after.report`, and `delta`. Optional shared `force_reachable_ids` / `force_unreachable_ids` apply to both evaluates. Use for “what if this answer were different?”

**`how_to_reach`** — send baseline envelope + `target_conclusion_id` (from `smeme_reasoning_list_conclusions` — **not** from evaluate `report`). Optional `locked_question_ids`, `max_changes` (≤ 5), `top_k` (≤ 10), **`reach_mode`** (`entailed` default, or `possible` for weaker “still reachable under some completion” probes), and the same optional `force_*_ids` reach assumptions. Returns suggested edit plans or `blockers` when no plan is found.

**`decisive_support`** — **minimal sufficient evidence**: when the current answers already force a target conclusion, return inclusion-minimal answered-question supports (question ids + option strings only). \(T\) and \(E\) stay fixed. Use for “which answers mattered?” — **not** abduction under incomplete evidence, and **not** to repair `answers_inconsistent` / `assumptions_inconsistent`. Obtain `target_conclusion_id` from `list_conclusions`.

**`edit_affects_path`** — whether a hypothetical override breaks the **current forced path** (path sensitivity), not a full alternate-world tour (`what_if`).

**v1 persist:** only `persist=false` (default). `persist=true` returns `persist_not_implemented`.

**Agent guidance:** load **`smeme-reasoning-plugin`** (Logical analysis tools + error tables). For non-concluded evaluate results that lead into “what would change?”, also load **`smeme-reasoning-outcomes`**.

**Operator notes:**

| `blockers.code` / situation | Meaning | Do not |
|----------------------------|---------|--------|
| `search_cap_exceeded` (`search_complete: false`) | Server search limit hit before finishing | Tell the user “no plan exists” |
| `no_plan_within_max_changes` (`search_complete: true`) | Search finished; no plan within `max_changes` | Treat as server fault or retry in a loop |
| `already_reachable: true` | Baseline already reaches target | Fabricate edit suggestions |

Quote `error.message` / `blockers.message` to the user — they use product vocabulary aligned with shipped skills.

---

## 3. One-session checklist (dogfood / onboarding)

Goal: a new teammate completes **list → validate → evaluate → interpret**, then optionally **logical analysis**.

1. **Connect** MCP (§2.2); finish **OAuth**.
2. **Open SMEme in the browser** and **sign in** once (§2.3).
3. Load the **`smeme-reasoning-plugin`** skill ([`plugin/cowork-skills/smeme-reasoning-plugin/SKILL.md`](../../plugin/cowork-skills/smeme-reasoning-plugin/SKILL.md)) — follow tool naming and argument rules (`raw_answers_json` as a **bare object**, optional **`persist=false`** for experiments). For connector gather → provenance envelope, also load **`smeme-reasoning-slot-fill`** ([`plugin/cowork-skills/smeme-reasoning-slot-fill/SKILL.md`](../../plugin/cowork-skills/smeme-reasoning-slot-fill/SKILL.md)) after **`template_get`**.
4. Call **`smeme_reasoning_capabilities`** (Bearer + linked SMEme user). Confirm `reasoning.tools` and `harness_next_enum`.
5. Call **`smeme_reasoning_list`**. An **empty** `reasoning_qnrs` list is valid (no Deployed + Listed workflows for this user), not a broken server.
6. Pick a **`qnr_id`** you own; obtain **question ids** via **`smeme_reasoning_template_get`** (§2.6).
7. Build the provenance envelope; call **`smeme_reasoning_validate_answers`**. Proceed only when **`harness_next` is `phase_2_ok`** (resolve `user_input_needed` / `missing_evidence_ref` first).
8. Call **`smeme_reasoning_evaluate`** with the same envelope.
9. If the outcome is not a clean unique conclusion, use **`smeme-reasoning-outcomes`** ([`plugin/cowork-skills/smeme-reasoning-outcomes/SKILL.md`](../../plugin/cowork-skills/smeme-reasoning-outcomes/SKILL.md)).
10. **Logical analysis (pick one):** (a) after evaluate, reuse the envelope → `list_conclusions` → `how_to_reach`; or (b) skip evaluate and call `how_to_reach` with a baseline envelope + `reach_mode=possible`.

Structured error codes: [`smeme/mcp/tool_contract.py`](../../smeme/mcp/tool_contract.py).

---

## 4. Related files

| Doc / path | Purpose |
|------------|---------|
| [SMEme MCP — organization IT and security overview](cowork-plugin-superuser-admin-guide.md) | Customer IT / security: connector purpose, auth and data flow |
| [Internal — Cowork plugin artifacts (archived)](internal/cowork-plugin-artifacts-and-releases.md) | Historical zip packaging notes — **not current product** |
| [`plugin/cowork-skills/README.md`](../../plugin/cowork-skills/README.md) | Guidance / skills authoring source |
| [`dr3-mcp-oauth-authoritative-sources.md`](dr3-mcp-oauth-authoritative-sources.md) | Spec pins, local curl, Inspector pitfalls |
| [`../LESSONS_LEARNED.md`](../LESSONS_LEARNED.md) | OAuth, CORS, `resource`, Inspector callbacks |
| [`../planning/cowork-plugin-delivery-sprints.md`](../planning/cowork-plugin-delivery-sprints.md) | Historical CWP roadmap and tool contract §5 |
| [`../planning/sprint-mcp-two-phase-evidence-and-evaluate.md`](../planning/sprint-mcp-two-phase-evidence-and-evaluate.md) | **Planning:** two-phase harness (evidence → **E**, then evaluate) |

---

## 5. Release sign-off (operators) — plugin zip removed

**The installable Cowork plugin zip, `/downloads/cowork-plugin/`, and `PLUGIN_BUNDLE_*` operator triple are removed.** Clear those env vars on Render if still set.

**Current release coupling for MCP surface version:**

1. Bump **`REASONING_CAPABILITIES_VERSION`** in [`smeme/mcp/reasoning_fastmcp.py`](../../smeme/mcp/reasoning_fastmcp.py) when the tool contract / capabilities payload changes.
2. Keep **`<!-- installed_plugin_version -->`** in [`plugin/cowork-skills/smeme-reasoning-plugin/SKILL.md`](../../plugin/cowork-skills/smeme-reasoning-plugin/SKILL.md) aligned (CI: `scripts/validate_cowork_plugin.py`).
3. Regenerate guidance/rubric/design artifacts when skill sources change: `scripts/build_guidance_artifact.py`, `scripts/build_candidate_rubric_artifact.py`, `scripts/build_design_guidance_artifact.py`.

Historical zip packaging detail (do not follow for new releases): [Internal — Cowork plugin artifacts](internal/cowork-plugin-artifacts-and-releases.md).

<!-- Archived zip subsections §5.1–5.3 removed from the live operator path; see internal archive doc. -->
