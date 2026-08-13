## Summary

<!-- What changed and why (1–3 bullets). -->

## Distro impact

- [ ] Core-only change (`create_core_app` / public product surface)
- [ ] SaaS overlay only (`saas_overlay`, landing, billing payment, legal) — **private repo after extract**
- [ ] Shared / migration / docs

## Test plan

- [ ] `uv run python scripts/check_core_no_saas_imports.py`
- [ ] `uv run ruff check smeme && uv run ruff format --check smeme`
- [ ] Relevant `pytest` targets
- [ ] If Docker: `docker compose -f docker-compose.core.yml up --build` (Core) or existing SaaS path

## Reasoning / Deploy / MCP evaluate changes

If this PR changes IR, theory compile, evidence ingest, query runtime, Deploy
readiness, or Appendix B–cited tests, follow
[decision-DAG calculus maintenance](../docs/guides/decision-dag-calculus-maintenance.md):

- [ ] Part I / Part II / Appendix B updated as required
- [ ] Entry-point re-audit refreshed for affected rows (B.1 caller path)
- [ ] N/A — no reasoning surface change

## References

<!-- ADR, issue, or sprint doc links -->
