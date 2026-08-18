# Inquire execution boundary

Design note for calculus §13.9 caller wiring. **Not a shipped MCP contract.**
No FastMCP tools, agent-skills, or Cloud overlay are registered from this note.

## Layers

```text
MCP / LangGraph / CLI / tests     # transport (future)
        |
        v
smeme.reasoning.orchestration.inquire   # trusted execution
        |
        v
smeme.reasoning.runtime.inquire         # deterministic kernel
```

| Layer | Owns | Must not |
| ----- | ---- | -------- |
| Kernel | `ANALYZE` → `InquiryDirective`; `admit_assertion`; `apply_verification_decision`; blind `ExtractionTask` builder | Run extractors, hold session loops, interpret citations |
| Orchestrator | Convert directive → blind task; bind result to issued task; route to admission or `P_v`; construct `VerificationRequest` | Leak VERIFY vs ACQUIRE to the extractor; auto-REPLACE on option disagreement |
| Extractor | Propose an empirical judgment over sources | See mode, verification keys, conclusions, or prior answers |

Corpus and source access stay on the `Extractor` implementation. `ExtractionTask`
describes the question SMEme demands answered; it is not a document transport.

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

## Blindness (G9)

ACQUIRE and VERIFY share one extractor-facing shape:

```text
ExtractionTask = one EvidenceQuestion(stem, options)
```

Executable indistinguishability:

```text
build_extractor_issue(catalog, q)  # from ACQUIRE
    ==
build_extractor_issue(catalog, q)  # from VERIFY
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
under a later real policy).

## Two identity checks on VERIFY

1. **Assertion under verification** comes from `directive.verification_key` /
   the live admitted assertion. A payload cannot retarget a stale `(q, a, p)`
   (Probe 4).
2. **Which blind extraction produced `r`** requires
   `result.question_id == task.question.question_id == directive.question_id`
   before anything reaches `P_v`.

`execute_directive` owns the bind because it has directive, task, and result.

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

## Forbidden MCP shape

If the same model is expected to perform extraction, do **not** expose:

```json
{"action": "verify", "question": "..."}
```

That leaks mode and breaks G9.

## Safe later MCP surface (orchestrator-facing)

Minimum tools, once the in-process loop stays the source of truth:

- analyze / next-directive
- get blind extractor task
- admit `(q, a, p)` or apply a `VerificationDecision`

MCP is one transport over `smeme.reasoning.orchestration.inquire`. It is not a
second kernel. LangGraph, CLI, and unit tests should drive the same package.

## Out of scope here

Approved paraphrases, cross-family evaluator slots, automated RETRACT/REPLACE,
LLM clients, CEVI corpus wiring, session persistence, and shipped MCP
registration.
