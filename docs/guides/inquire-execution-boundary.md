# Inquire execution boundary

Design note for calculus §13.9 caller wiring. Layer ownership for kernel,
orchestrator, and extractors. **Shipped MCP wire contract:**
[`inquire-mcp-contract.md`](./inquire-mcp-contract.md).

`MCP_INQUIRE_TOOLS_ENABLED` (default off) gates the **orchestrator** FastMCP mount
(`/api/v1/mcp/orchestrator`), not the chat gather facade. Chat always uses persist
for `smeme_reasoning_evaluate` / `evaluate_continue` when MCP is on (requires Phase 6
tables in the deployed database). No Cowork agent-skills for the explicit Inquire
protocol; chat guidance describes guided evaluate only.

## Layers

```text
Chat /mcp                       # evaluate start + continue (blind facade)
Orchestrator /mcp/orchestrator  # explicit smeme_inquire_* (flag-gated)
        |
        v
smeme.reasoning.orchestration.inquire.persist   # Phase 6 durable sessions
        |
        v
smeme.reasoning.orchestration.inquire           # trusted execution
        |
        v
smeme.reasoning.runtime.inquire                 # deterministic kernel
```

| Layer | Owns | Must not |
| ----- | ---- | -------- |
| Kernel | `ANALYZE` → `InquiryDirective`; `admit_assertion`; `apply_verification_decision`; blind `ExtractionTask` builder | Run extractors, hold session loops, interpret citations |
| Orchestrator (protocol) | Convert directive → blind task; bind result to issued task; route to admission or `P_v`; construct `VerificationRequest`; prepare/evaluate verification transcripts | Leak VERIFY vs ACQUIRE to the extractor; auto-REPLACE on option disagreement |
| Chat facade | Strip control channel; ACQUIRE-only continue; fail-closed VERIFY → `isolated_evaluations_required` without STOP; on true STOP, Apply admitted answers and return `report` + `stop_reason` / `inquire_stop_reason` | Fake a VERIFY battery; invent STOP on VERIFY; treat `operational_budget` as “no report” |
| Persist (Phase 6) | `inquiry_session_id`, frozen artifact snapshot, admitted/verified rows, revision, idempotency receipts | Put DB sessions in kernel state; persist `C_poss` / `D_1` / `S_R` / directive / battery |
| Extractor | Propose an empirical judgment over sources | See mode, verification keys, conclusions, or prior answers |

Corpus and source access stay on the `Extractor` implementation. `ExtractionTask`
describes the question SMEme demands answered; it is not a document transport.

Evaluator isolation for orchestrator VERIFY is **caller_responsibility**. Chat never
runs \(P_v\); when ANALYZE asks VERIFY, the facade returns `isolated_evaluations_required`
and leaves the session `ACTIVE` for an isolated orchestrator.

When ANALYZE issues **STOP**, chat persists STOP then **Applies** the admitted sheet.
Semantic stops (`verified_resolved_consequence`, `inconsistent`, …) and operational /
\(S_R\)-incomplete stops (`operational_budget`, `resolving_support_incomplete`, …) all
follow that path. A concluded `report` with an operational `stop_reason` means Apply
succeeded; it is **not** an MCP quota denial. See [`inquire-mcp-contract.md`](./inquire-mcp-contract.md).

## Kernel primitives

```text
analyze_inquiry
build_extractor_issue
admit_assertion
apply_verification_decision
```

ACQUIRE and VERIFY are symmetrical at the state boundary:

```text
ACQUIRE result  →  admit_assertion
VERIFY  result  →  apply_verification_decision   # after P_v
```

**Python vs MCP:** `apply_verification_decision` is a Core Python primitive for
self-hosters and in-process orchestration. Remotely trustworthy MCP does **not**
accept a client-supplied `VerificationDecision`. MCP clients submit observation
transcripts; Core runs `DefaultVerificationPolicy` then applies the decision.
See [`inquire-mcp-contract.md`](./inquire-mcp-contract.md).

## Blindness (G9)

ACQUIRE and VERIFY share one extractor-facing shape:

```text
ExtractionTask = one EvidenceQuestion(stem, options)
```

Executable indistinguishability:

```text
build_extractor_issue(catalog, q)  # from ACQUIRE
    ==
build_extractor_issue(catalog, q)  # from VERIFY (eval-0 / identity presentation)
```

The trusted controller may know `VERIFY q17` and the live `verification_key`.
The extraction model must see only the stem and options.

## Extraction results

```text
AnsweredExtraction   — selected_option + required provenance_id
AbstainedExtraction  — no assertion, therefore no p
```

Abstention on ACQUIRE does not call the kernel. A later `ANALYZE` re-issues the
same ACQUIRE. Abstention on VERIFY is evidence for `P_v` (typically INSUFFICIENT
under the default policy).

## Two identity checks on VERIFY

1. **Assertion under verification** comes from `directive.verification_key` /
   the live admitted assertion. A payload cannot retarget a stale `(q, a, p)`
   (Probe 4).
2. **Which blind extraction produced `r`** requires
   `result.question_id == task.question.question_id == directive.question_id`
   before anything reaches `P_v`.

`execute_directive` owns the bind because it has directive, task, and result.
MCP `smeme_inquire_verify` additionally requires the submitted key to be the
**currently issued** VERIFY target from re-ANALYZE.

## `VerificationRequest` seam

Kernel `VerificationRequest(verification_key=...)` names the assertion under
check. Phase 4’s stateful policy uses that request in `initial_state`; the
extractor never sees it. Disagreement between live option and a fresh extraction
is evidence for `P_v`, not an automatic REPLACE. One-shot kernel fakes still use
`policy.decide(request, result)` for transition goldens.

## Blind verification policy (Phase 4)

VERIFY runs a bounded battery of fresh **ISOLATED** evaluations — fresh
invocations that receive only the blind `ExtractionTask` (no prior result, live
assertion, policy state, or outcome info). This is not a claim of statistically
independent errors; the host may map every `ISOLATED` request to the same model.

Schedule size is adaptive:

```text
N_q = min(3, |A_q|!)
```

so binary questions get 2 trials, three-or-more-option questions get 3, and
one-option questions get 1 (no option-order robustness; recorded as
`len(schedule) == 1`).

Each trial has a deterministic `evaluation_id` (`eval-0`, `eval-1`, …).
`observe` rejects unbound/duplicate ids, presentation mismatches, wrong
`question_id`, and non-canonical `selected_option` — these are **protocol
errors** (fail closed), not `Insufficient`.

**Retain** iff every scheduled observation answered, matches the live canonical
option, and has `provenance_present` (non-empty `provenance_id`). Otherwise
**Insufficient**. Unanimous agreement on an alternative is still Insufficient —
not Replace. Core does not claim grounding or truth.

`execute_directive` injects the policy:

```python
verification_policy: BlindVerificationPolicy = DEFAULT_VERIFICATION_POLICY
```

Core ships one policy; self-hosters may replace the argument. `pv_version`
encodes the algorithm and parameters; schedule or decision rule changes bump it.
On MCP, `pv_version` is **server-owned** (named and executed by this process).

Transcript helpers (no Extractor):

```text
prepare_verification_battery
evaluate_verification_transcript
```

## Forbidden MCP shape

If the same model is expected to perform extraction, do **not** expose:

```json
{"action": "verify", "question": "..."}
```

That leaks mode and breaks G9. Also do **not** expose a tool that accepts a
client-minted `Retain` / `VerificationDecision`.

## Shipped MCP surface

See [`inquire-mcp-contract.md`](./inquire-mcp-contract.md). Summary:

- **Chat:** `smeme_reasoning_evaluate` / `evaluate_continue` (ACQUIRE-only facade; VERIFY → `isolated_evaluations_required`)
- **Bulk Apply:** `smeme_reasoning_evaluate_answers`
- **Orchestrator (flag-gated):** five `smeme_inquire_*` + inquire guidance

MCP is one transport over `smeme.reasoning.orchestration.inquire` (+ persist).
It is not a second kernel. LangGraph, CLI, and unit tests should drive the same
package.

## Out of scope here

Approved paraphrases, cross-family evaluator slots, automated RETRACT/REPLACE,
LLM clients, CEVI corpus wiring, Cowork Inquire skills, dashboard HTMX,
and Cloud overlay billing/quota policy.
