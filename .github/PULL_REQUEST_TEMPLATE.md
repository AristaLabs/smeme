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

## References

<!-- ADR, issue, or sprint doc links -->
