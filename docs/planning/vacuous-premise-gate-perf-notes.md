# Vacuous-premise gate performance notes

Measured 2026-08-04 on the local Core test environment with the small
two-option entry-radio IR, 20 repetitions per case, `timeout_ms=5000`.
Latency is solver-call time only and is a rough local indication, not a
production benchmark.

| Case | Result | SAT calls | Mean latency | Range |
|---|---|---:|---:|---:|
| Affirmative possible | `possible` | 1 | 0.340 ms | 0.232–0.682 ms |
| Not entailed | `not_entailed` | 1 | 0.293 ms | 0.249–0.345 ms |
| Entailed | `entailed` | 2 | 0.369 ms | 0.317–0.469 ms |
| Impossible | `impossible` | 2 | 0.353 ms | 0.314–0.424 ms |

The delta is witness-first: affirmative witnesses establish consistency for
the exact base, while entailed/impossible results require the query UNSAT
followed by consistency disambiguation. Repair candidates retain the mode
split: possible-mode acceptance may be one call, whereas entailment-mode
acceptance requires `SAT(B')` after `UNSAT(B' ∧ ¬q)`. No uniform
per-candidate call count is claimed across repair modes.
