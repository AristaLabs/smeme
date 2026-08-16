# Inquire target goldens (§13.9)

**Status:** Target. Not Part I. No Appendix B row. Not shipped tests.

These examples fix expected `ANALYZE` results for graphs in the Core compilation domain (§4): one entry question, radio options, conclusions terminal, non-default guards into conclusions. Notation follows [decision-dag-calculus.md](./decision-dag-calculus.md) §13.9. `B` is the fully composed working base.

When Inquire ships, each golden becomes an entry-point test of the Inquire kernel — not a helper-only SAT sketch.

---

## G1 — XOR / joint resolution (`D_1 = ∅`, still `Resolvable`)

Source:

```text
q1 ∈ {0,1}     entry
q2a, q2b ∈ {0,1}

q1 -0→ q2a -0→ OA
         q2a -1→ OB
q1 -1→ q2b -0→ OB
         q2b -1→ OA
```

`OA` iff the taken `q2*` matches `q1`; `OB` iff they differ.

**G1.0** `E = ∅`.

```text
C_poss = {OA, OB}
C_ent  = ∅
Resolved     = false
D_1          = ∅          (every singleton pin leaves C_poss = {OA, OB})
Resolvable   = true
```

A resolving witness: `D = {q1, q2a}`, `α_D = {q1=0, q2a=0}` gives `Resolved` with `OA`. Issued ACQUIRE is one member of `D`, not the pair.

**G1.1** After `ADMIT {q1=0}`.

```text
C_poss = {OA, OB}
D_1    = {q2a}            (q2b is unreachable, hence inert)
```

ACQUIRE `q2a`. This is the sequential demotion of a resolving witness to myopic discrimination.

**G1.2** After `ADMIT {q1=0, q2a=0}`.

```text
Resolved = true, c = OA
S_R      = {(q1,0), (q2a,0)}
```

`q2b` unanswered and inert; not in `S_R`.

---

## G2 — Co-reachable extra conclusion defeats `Resolved`

Source:

```text
q1 ∈ {Yes, No}     entry
q2 ∈ {A, B}

q1 -Yes→ c1
q1 -Yes→ q2
q2 -A→ c2
q1 -No→ c3
```

`q2=B` has no outgoing arc.

**G2.0** `E = {q1=Yes}`, `q2` unanswered.

```text
C_ent  = {c1}
C_poss = {c1, c2}
Resolved = false
D_1      = {q2}     (q2=A keeps {c1,c2}; q2=B yields {c1})
```

ANALYZE → ACQUIRE `q2`. Must not VERIFY a support for `c1`.

Shipped Apply may report `SAT_UNIQUE` here if the first model has `q2=B` (probe `¬reach(c1)` is unsat while `SAT(B ∧ reach(c2))` still holds). Inquire uses `C_poss = C_ent = {c}`, not that shortcut.

---

## G3 — `S_R` is strictly stronger than entailment support

Same source as G2.

**G3.0** `E = {q1=Yes, q2=B}`.

```text
Resolved = true, c = c1
```

Entailment support may be `{(q1,Yes)}` because `T ∧ (q1=Yes) ⊨ reach(c1)`.

```text
C_poss(T ∧ (q1=Yes)) = {c1, c2}     ¬Resolved
S_R(B) = {(q1,Yes), (q2,B)}
```

VERIFY of `{(q1,Yes)}` alone must not STOP. Shipped `decisive_support` for `c1` may return the weaker set; Inquire must not reuse it as `S_R`.

---

## G4 — VERIFY retract rebases

Continue G3.0. `S_R = {(q1,Yes), (q2,B)}`.

**G4.0** `P_v` returns `RETRACT` on `(q2,B)`.

```text
E' = {q1=Yes}
```

Discard `C_poss`, `D_1`, `S_R`, `Resolved`, and all witnesses from the old base. Re-ANALYZE: G2.0 (`¬Resolved`, `D_1 = {q2}`). Do not STOP as “`c1` unsupported”; do not keep directives from `E`.

**G4.1** `P_v` returns `INSUFFICIENT` on `(q2,B)`.

`E` unchanged. Still `Resolved`. Still VERIFY the same `S_R`. No rebase.

**G4.2** `P_v` returns `REPLACE(q2=A)` on `(q2,B)`.

```text
E' = {q1=Yes, q2=A}
C_poss = C_ent = {c1, c2}
Resolved = false
U = ∅
¬Resolvable
```

STOP `not_resolvable_by_remaining_evidence_vocabulary` (jointly entailed pair; no remaining worksheet question).

---

## G5 — Assumptions are retained in `B_S`

Same source as G2. `E = {q1=Yes}`, `q2` unanswered, `φ = force_unreachable(c2)`.

```text
B     = T ∧ E ∧ φ
C_poss(B) = C_ent(B) = {c1}
Resolved(B) = true
```

```text
S_R(B) = {(q1,Yes)}     because φ already excludes c2
```

Computing support as `T ∧ S` without `φ` yields `¬Resolved`. Dropping `φ` while minimizing `E` is a spec defect.

If `φ` is later cleared, that is a replaced base: re-ANALYZE from G2.0.

---

## G6 — Semantic exhaustion (`U = ∅`, `¬Resolved`)

Source:

```text
q1 ∈ {Yes}     (single option, or Yes selected)
q1 -Yes→ c1
q1 -Yes→ c2
```

**G6.0** `E = {q1=Yes}`.

```text
C_poss = C_ent = {c1, c2}
Resolved   = false
U          = ∅
Resolvable = false
```

STOP `not_resolvable_by_remaining_evidence_vocabulary`. Not a budget status. Not VERIFY of either conclusion.

---

## G7 — Budget exhaustion is not semantic exhaustion

Use G1.0 (`D_1 = ∅`, `Resolvable = true`) with a search budget too small to produce a resolving witness.

```text
STOP no_joint_discriminator_within_budget
```

Must not emit `not_resolvable_by_remaining_evidence_vocabulary`. The logical result is undecided (§8.4 analogue).

---

## G8 — Unreachable admitted answers are not in `S_R`

Extend G2:

```text
q1 -No→ q3
q3 -X→ c3
```

**G8.0** `E = {q1=Yes, q2=B, q3=X}`.

`q3` is reachability-inert (§7.2).

```text
Resolved = true, c = c1
S_R      = {(q1,Yes), (q2,B)}     (q3,X) ∉ S_R
```

**G8.1** `D_1` on G2.0 must not include `q3`: pinning `q3` cannot change `C_poss` while `q1=Yes`.

---

## G9 — Issued extraction is always a singleton

On G1.0, even if the planner holds `D = {q1, q2a}`, the extractor prompt contains exactly one question stem and its options. The model does not see `OA`/`OB`, `Resolved`, `S_R`, or that the call is ACQUIRE rather than VERIFY.

---

## Implementation notes (not extra semantics)

- G2 is the Apply `SAT_UNIQUE` hole as an Inquire obligation: ACQUIRE, not VERIFY.
- G3 is why `S_R` cannot be implemented by calling `decisive_support` and stopping.
- G5 is why `B_S` keeps `φ`.
- G1 / G7 are why `D_1 = ∅` is not a semantic STOP.
- G8 is the unreachable-answer regression §7.2 gives “almost for free.”
