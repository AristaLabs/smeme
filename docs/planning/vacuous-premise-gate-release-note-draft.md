# Release-note draft: vacuous-premise consistency hardening

This release hardens three related soundness findings:

1. **Vacuous entailment** — queries over inconsistent premises could previously
   return `entailed`.
2. **Possibility collapsing inconsistency into impossibility** — the same
   premises could previously return `impossible`.
3. **Evidence inconsistency misattributed to assumptions** — when assumptions
   were present, an inconsistency already caused by admitted evidence could be
   mislabeled as an assumptions failure.

Consequence reporting now disambiguates UNSAT before returning a logical
result, and cause attribution follows the first failing admitted prefix.

Queries against inconsistent evidence or assumptions now return an explicit
inconsistent status (`answers_inconsistent` or `assumptions_inconsistent`).
Self-hosters on verified older Core image pins remain exposed until they
upgrade. Hosted Cloud remains on its current digest pin until the pin bump
after this Core release.

This is a soundness/correctness fix, not a security change. Version and image
digest exposure are verified at release time. The ALGEBRA amendment remains a
separate human-gated annex publication.
