# SMEme Core documentation

Thin operator and contributor surface for the public Core tree.

## Start here

| Doc | Purpose |
|-----|---------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Core system map |
| [Self-host quickstart](guides/self-host-quickstart.md) | Docker / compose appliance |
| [Engine promises](guides/engine-promises.md) | What Deploy and evaluate guarantee |
| [Contribution paths](CONTRIBUTION_PATHS.md) | Themes welcome in public PRs |
| [Contributing](../CONTRIBUTING.md) | PR / CLA process |

## Operator guides

| Guide | Use when |
|-------|---------|
| [Getting started](guides/getting-started.md) | Local Core development |
| [Installation](guides/installation.md) | Dependencies and environment |
| [MCP / OAuth](guides/dr3-mcp-oauth-authoritative-sources.md) | Configure a self-hosted MCP endpoint, OAuth discovery, and Bearer validation |
| [Frontend CSS build](guides/frontend-css-build.md) | Tailwind pre-build (`make css`) |
| [Data migration](guides/data-migration.md) | Schema vs data migrations |

## Agent guidance authoring

Skill markdown under [`agent-skills/`](../agent-skills/) is the **authoring source** for MCP guidance (`smeme_reasoning_guidance_get`). Agents load that contract over MCP after OAuth — there is no installable plugin zip in Core.

After editing skills, regenerate with `scripts/build_guidance_artifact.py` and run `scripts/validate_agent_skills.py`.
