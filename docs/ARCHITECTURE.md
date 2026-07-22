# SMEme Core architecture

SMEme Core is a self-hosted application for authoring **decision-trees** and
evaluating structured answers through a server-side reasoning engine.

## Product shape

- **Web application:** authors create, edit, and Deploy decision-trees.
- **Reasoning engine:** Deploy validates and compiles a tree; evaluation uses the
  deployed artifact and returns a structured report.
- **Remote MCP:** OAuth-protected tools let an owner list, validate answers for,
  and evaluate their Listed decision-trees.
- **PostgreSQL:** stores users, decision-tree graphs, deployed artifacts, and
  evaluation records.

The server owns evaluation. MCP clients gather evidence and provide structured
`raw_answers`; they do not receive branch topology or decision rules on the
default evaluate path.

## Core boundaries

The Core image includes the editor, reasoning engine, MCP surface, operator
configuration, and optional AI-assisted generation. It excludes hosted billing,
marketing pages, analytics, waitlist flows, and Arista Labs legal pages.

Core quota metering remains available, while hosted Free/Pro enforcement is not
part of the Core product. AI-assisted generation is optional; deterministic
evaluation stays on the Core server.

## Main components

```text
smeme/
├── app_factory.py   # Core application composition
├── core/            # settings, database, middleware, models
├── auth/            # browser identity and MCP user resolution
├── qnr/             # decision-tree dashboard, editor, viewer, generation
├── reasoning/       # IR, validation, compilation, runtime evaluation
├── mcp/             # OAuth discovery, bearer verification, MCP tools
└── templates/       # Core web templates

plugin/
└── agent-skills/    # Agent guidance authoring source
```

## Runtime flow

1. An author saves a decision-tree.
2. **Deploy** validates it and persists a compiled reasoning artifact.
3. An MCP client authenticates with the configured OAuth provider.
4. The client submits structured answers for a Listed, deployed decision-tree.
5. The server evaluates the artifact and returns a report.

## Operator references

- [Engine promises](guides/engine-promises.md)
- [Self-host quickstart](guides/self-host-quickstart.md)
- [MCP OAuth guide](guides/dr3-mcp-oauth-authoritative-sources.md)
- [Agent Skills source](../plugin/agent-skills/README.md)
