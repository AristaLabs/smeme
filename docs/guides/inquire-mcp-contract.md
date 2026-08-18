# Inquire MCP contract

Frozen Phase 5 wire contract for calculus §13.9 Inquire over Core MCP.
**Not** a Cowork skill. **Not** Cloud overlay. Gated by ``MCP_INQUIRE_TOOLS_ENABLED``
(default **false**).

Authoritative implementation:

- Handlers: [`smeme/mcp/inquire/`](../../smeme/mcp/inquire/)
- Battery prepare/evaluate: [`smeme/reasoning/orchestration/inquire/verification/transcript.py`](../../smeme/reasoning/orchestration/inquire/verification/transcript.py)
- Layer ownership: [`inquire-execution-boundary.md`](./inquire-execution-boundary.md)

## Authority

\[
pv\_version := \texttt{DEFAULT\_VERIFICATION\_POLICY.pv\_version}
\]

on the server. The client may **echo** a `verification_key` (including its
`pv_version` field as identity). The client must not choose which \(P_v\) runs
and must not submit a `VerificationDecision`.

\[
Verified_{pv}(e)
\]

may exist only if this server's \(P_v\) both named \(pv\) and evaluated the
observation transcript to `Retain`.

VERIFY flow:

```text
Core issues the experiment (analyze → evaluations[])
  → client performs blind trials (forward task only)
  → Core validates the transcript against the currently issued VERIFY directive
  → P_v
  → Core mutates verification state
```

Invariant:

\[
\text{MCP VERIFY may satisfy only the currently issued VERIFY directive}
\]

## Tools (four)

| Tool | Role |
|------|------|
| `smeme_inquire_analyze` | ANALYZE with server `pv_version`; on VERIFY, attach derived `evaluations[]` |
| `smeme_inquire_get_task` | Blind catalog render: `{question_id, stem, options}` only |
| `smeme_inquire_admit` | Admit ACQUIRE answer or abstain |
| `smeme_inquire_verify` | Re-ANALYZE gate + evaluate observation transcript under Core \(P_v\) |

`apply_verification_decision` remains a **Core Python primitive**, not an MCP tool.
Self-hosters customize by replacing `DEFAULT_VERIFICATION_POLICY` in source
(which changes the server's `pv_version`). They do not get a remote “trust my
Retain” endpoint.

## Stateless request context

Every analyze / admit / verify call carries inquiry state. The server stores
**no** case/session state.

Shared (analyze / admit / verify):

- `ir_json`
- `worksheet_catalog_json` — `{question_id: {stem, options}}`
- `admitted_json` — `[{question_id, option, provenance_id}, ...]`
- `verified_json` — server-issued keys
- `artifact_identity`
- optional `force_reachable_ids` / `force_unreachable_ids`
- optional `budget_json`

**Not caller input:** `pv_version` as a policy selector.

`smeme_inquire_get_task` accepts **only**:

```text
worksheet_catalog_json
question_id
```

No `ir_json`. It is a weakly bound catalog render, not directive authorization.

## Trusted directive

`analyze` returns `directive` matching `InquiryDirective`:

- `action`: `ACQUIRE` | `VERIFY` | `STOP`
- `question_id`, `option`, `verification_key` (VERIFY)
- `stop_reason`, `inconsistency_cause`, `operational_status` when applicable

Orchestrator-facing. May contain VERIFY metadata. Never forward to extractors.

## Derived `evaluations[]`

When `action == VERIFY`, `analyze` also returns:

```json
{
  "evaluations": [
    {
      "evaluation_id": "eval-0",
      "task": { "question_id": "q", "stem": "...", "options": ["A", "B"] }
    }
  ]
}
```

`evaluations[]` is **derived data, not caller state**. Identical inputs
(same IR, admitted, verified, assumptions, catalog, artifact identity, server
policy) reproduce the same directive and the same `evaluations[]` byte-for-byte
modulo ordinary JSON key ordering.

\(N_q = \min(3, |A_q|!)\). Tasks are flattened and built from the server catalog.
`eval-0` is the identity permutation: `evaluations[0].task == get_task(q)` at
JSON level. Forward only the inner `task` to extractors — never `evaluation_id`,
the directive, or `verification_key`.

## Blind task shape

Extractor-facing JSON is exactly:

```text
{ "question_id", "stem", "options" }
```

Must not contain: `VERIFY`, `ACQUIRE`, `verification_key`, `live_option`,
`pv_version`, `support`, `resolved`, `conclusion`, `stop_reason`, `action`,
`evaluation_id`.

Control channel ≠ extractor channel.

## Admission

```text
question_id
selected_option | null
provenance_id | null
```

`null` option = abstain (no kernel call). Answered path rebuilds the task via
`build_extractor_issue` then `admit_extraction`.

## Verification transcript

`smeme_inquire_verify` accepts observations, not a decision:

```text
verification_key          # echo of current analyze VERIFY key
observations: [
  { evaluation_id, question_id, selected_option | null, provenance_id | null },
  ...
]
```

plus the shared analyze-class state so the handler can re-ANALYZE.

Core:

1. Run `analyze_inquiry` with **server** `pv_version`.
2. Require `action == VERIFY` and `directive.verification_key == submitted key`.
3. Confirm the assertion is live and `pv_version` matches the server policy.
4. Reconstruct \(ExpectedBattery = f(verification\_key, catalog, server\_policy)\).
5. Bind observations; fill presentation from the schedule.
6. `DefaultVerificationPolicy` → `Retain` | `Insufficient` → `apply_verification_decision`.
7. Return `{admitted, verified, status, base_changed, decision}` where `decision`
   is Core-authored.

## Failure statuses vs Insufficient

| Situation | Result |
|-----------|--------|
| Valid completed battery that fails Retain rules | `decision.kind = insufficient` |
| Incomplete / unscheduled / duplicate / wrong question / non-canonical option | protocol error (`inquire_verification_protocol`) |
| Submitted key ≠ current VERIFY target | `inquire_verify_target_mismatch` |
| Live assertion identity stale | `assertion_mismatch` |
| Invalid admission | `admission_rejected` |
| Malformed JSON / catalog | `inquire_invalid_payload` / `inquire_unknown_question` |

Protocol faults are never converted into `Insufficient`.

## Capabilities

When `MCP_INQUIRE_TOOLS_ENABLED=true`, `smeme_reasoning_capabilities` includes:

```text
inquire.persist_v1: false
inquire.pv_authority: "server"
inquire.verification_battery: "core"
```

## Phase 6 deferred (Core product)

```text
- decision_tree_id / deployed-artifact lookup
- inquiry_session_id
- durable admitted / verified state
- auth / ownership
- product UI / resume behavior
```

## Cloud overlay later

Per D022 / D023 (public Core vs private SaaS overlay):

```text
- hosted quotas / billing / COGS / SaaS policy
```

Do not change calculus §13.9 for this contract.
