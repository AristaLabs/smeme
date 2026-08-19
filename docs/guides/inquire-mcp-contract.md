# Inquire MCP contract

Frozen Phase 6 wire contract for calculus §13.9 Inquire over Core MCP.
**Not** a Cowork skill. **Not** Cloud overlay.

Authoritative implementation:

- Persist service: [`smeme/reasoning/orchestration/inquire/persist/`](../../smeme/reasoning/orchestration/inquire/persist/)
- Chat facade: [`smeme/mcp/inquire/chat_facade.py`](../../smeme/mcp/inquire/chat_facade.py)
- Phase 5 blob handlers (tests / in-process): [`smeme/mcp/inquire/`](../../smeme/mcp/inquire/)
- Battery prepare/evaluate: [`smeme/reasoning/orchestration/inquire/verification/transcript.py`](../../smeme/reasoning/orchestration/inquire/verification/transcript.py)
- Layer ownership: [`inquire-execution-boundary.md`](./inquire-execution-boundary.md)

## Product surfaces

| Surface | URL | Gate | Tools |
|---------|-----|------|-------|
| Chat (default) | `settings.mcp_http_path` (`/api/v1/mcp`) | Always (when MCP on) | Reasoning tools **except** `smeme_inquire_*`. Guided gather: `smeme_reasoning_evaluate` (start) + `smeme_reasoning_evaluate_continue` (admit). Bulk Apply: `smeme_reasoning_evaluate_answers`. |
| Orchestrator | `{mcp_http_path}/orchestrator` | `MCP_INQUIRE_TOOLS_ENABLED` (default **false**) | `smeme_reasoning_capabilities`, `smeme_reasoning_list`, inquire guidance, five `smeme_inquire_*` |

Chat capabilities **omit** the inquire tools list and the top-level `inquire` block.
Orchestrator capabilities include:

```json
"inquire": {
  "protocol": "explicit_orchestration",
  "isolated_evaluations_required": true,
  "task_blindness": "server_enforced",
  "evaluator_isolation": "caller_responsibility",
  "verification_battery": "core",
  "persist_v1": true,
  "pv_authority": "server",
  "tools": ["smeme_inquire_start", "smeme_inquire_next", "smeme_inquire_get_task", "smeme_inquire_admit", "smeme_inquire_verify"]
}
```

Do **not** put the orchestrator URL in chat `guidance_get` — name the protocol only.
Starlette mounts the **longer** path first so `/api/v1/mcp` does not swallow `/orchestrator`.
Both mounts get RFC 9728 protected-resource metadata (`resource` = each mount URL).

## Authority

\[
pv\_version := \texttt{DEFAULT\_VERIFICATION\_POLICY.pv\_version}
\]

on the server, **pinned on the session at** ``start``. Later calls require
``session.pv_version == server_pv_version()`` or fail with ``inquire_policy_mismatch``.

The client must not choose which \(P_v\) runs and must not submit a
``VerificationDecision``.

\[
Verified_{pv}(e)
\]

may exist only if this server's \(P_v\) both named \(pv\) and evaluated the
observation transcript to `Retain`.

Invariant:

\[
\text{MCP VERIFY may satisfy only the currently issued VERIFY directive}
\]

## Chat facade (blind gather)

| Tool | Args | Persist |
|------|------|---------|
| `smeme_reasoning_evaluate` | `decision_tree_id` only | `start_inquiry` |
| `smeme_reasoning_evaluate_continue` | `inquiry_session_id`, `question_id`, `option` (or abstain), provenance | `admit` only |

Server mints `expected_revision` / idempotency. Never map continue onto `verify`.

**ACTIVE response:** strip control channel (`directive`, `evaluations[]`, `verification_key`,
`pv_version`, `C_poss`). Return `inquiry_session_id`, `status: ACTIVE`,
`harness_next: continue_evaluate`, and one `{question_id, stem, options}` task.

**VERIFY is a chat-invocation terminal, not an Inquire STOP.** If ANALYZE action is VERIFY:
do not return a task, do not run \(P_v\), do **not** call persist STOP, do **not** set
`stop_reason`. Return structured `isolated_evaluations_required`. Session remains `ACTIVE`
and resumable on `/orchestrator`.

**Inquire STOP:** persist STOPs only on true STOP. Then run Apply on admitted
`(q → option)` and return `report` + `stop_reason`.

Many `ACTIVE` sessions per tree are normal — there is **no** tree-level ACTIVE lock.
Analysis tools and `evaluate_answers` are not refused merely because another inquiry on
that tree is ACTIVE. Chat blindness is facade + guidance (same thread), not a global lock.

## Tools (five — orchestrator session-scoped)

| Tool | Role |
|------|------|
| `smeme_inquire_start` | Create session on deployed tree; freeze artifact snapshot; ANALYZE; return session id |
| `smeme_inquire_next` | Re-ANALYZE persisted state (read-only) |
| `smeme_inquire_get_task` | Blind render from **session-frozen catalog** |
| `smeme_inquire_admit` | Admit / abstain; persist; ANALYZE; return next directive |
| `smeme_inquire_verify` | Re-ANALYZE gate + Core \(P_v\); persist; ANALYZE; return decision + next directive |

`apply_verification_decision` remains a **Core Python primitive**, not an MCP tool.

Phase 5 blob-signature handlers remain in Python for unit tests; they are **not**
registered on FastMCP.

Evaluator isolation for VERIFY is **caller_responsibility** on the orchestrator mount.
If the caller cannot isolate, do not use VERIFY there (chat `evaluate` will not fake a battery).

## Durable session (persist_v1)

`start(decision_tree_id, force_*?)` is the only call that sees a tree id.
Core authenticates the owner, loads the in-sync compiled artifact, and captures
one atomic **FrozenArtifactSnapshot**:

\[
(artifact\_id,\ artifact\_identity,\ worksheet\_catalog,\ compiled\_IR)
\]

- `artifact_identity` = D025 `artifact_hash` (immutable)
- `worksheet_catalog` is snapshotted at start; **never** rebuilt from live `graph_data`
- compiled IR is reloaded from the artifact row on ANALYZE (not duplicated on the session)
- `artifact_id` is nullable FK (`ON DELETE SET NULL`); execution requires the row still match identity

Persisted ANALYZE preimage only:

```text
admitted assertions
verified keys
assumptions (pinned)
pv_version (pinned)
status / revision
```

**Not** persisted as authoritative: `C_poss`, `D_1`, `S_R`, directive, VERIFY battery.

\[
directive = analyze(session\ state)
\]

every time.

### Revision (Option A)

\[
revision = version(E,\ verified,\ assumptions,\ status)
\]

| Outcome | Bump? |
|---------|-------|
| Admit applied | yes |
| VERIFY Retain | yes |
| VERIFY Insufficient | **no** |
| ACQUIRE abstain | **no** |
| ACTIVE → STOPPED | yes |

Mutations require `expected_revision`. Mismatch → `inquire_revision_conflict`.

### Idempotency

`admit` / `verify` require `idempotency_key`. Receipts store `request_hash`
(canonical JSON; array order preserved). Same key + same hash → replay. Same key
+ different hash → `inquire_idempotency_conflict`.

### Lifecycle

```text
ACTIVE | STOPPED | ABANDONED
```

Mutations persist STOP immediately after post-mutation ANALYZE. `next` is
**write-free**; STOP while status is still ACTIVE → `inquire_session_invariant`.

`INSUFFICIENT` does not STOP the session.

## Blind task shape

Extractor-facing JSON is exactly:

```text
{ "question_id", "stem", "options" }
```

`get_task(session, q)` uses the frozen catalog. Control channel ≠ extractor channel.
`eval-0` identity permutation still holds against that catalog.

## D022 / D023 split

| KEEP (Core) | SAAS-ONLY (overlay later) |
|-------------|---------------------------|
| Session tables, ownership, MCP persist tools, metering via `reserve_mcp_quota` | Hosted Free/Pro caps, Stripe, COGS, upgrade CTAs |
| FLAG-GATED orchestrator: `MCP_INQUIRE_TOOLS_ENABLED` | |

Do not change calculus §13.9 for this contract.

## UI / dashboard

Schema supports later inspect (status, revision, artifact binding, admitted /
verified, stop reason, typed event log). **No** HTMX dashboard in Phase 6.
