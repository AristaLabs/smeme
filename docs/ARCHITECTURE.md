# SMEme Core architecture

SMEme Core is a self-hosted application for authoring **decision-trees** and
running them through a server-side **logical analysis engine**.

## Product shape

- **Web application:** authors create, edit, and Deploy decision-trees.
- **Logical analysis engine:** Deploy validates and compiles a tree; the deployed
  artifact supports evaluation (structured answers → **report**) and graph-level
  questions (what-if, reachability, and related analysis).
- **Remote MCP:** OAuth-protected tools let an owner list, validate, evaluate, and
  analyze their Listed decision-trees.
- **PostgreSQL:** stores users, decision-tree graphs, deployed artifacts, and
  evaluation records.

The server owns reasoning. MCP clients gather evidence and pose questions; they
do not receive branch topology or decision rules on the default MCP path.

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
4. The client evaluates structured answers and/or asks graph-level questions
   about a Listed, deployed decision-tree.
5. The server answers from the deployed artifact (report and/or analysis).

## Operator references

- [Engine promises](guides/engine-promises.md)
- [Self-host quickstart](guides/self-host-quickstart.md)
- [MCP OAuth guide](guides/dr3-mcp-oauth-authoritative-sources.md)
- [Agent Skills source](../plugin/agent-skills/README.md)
