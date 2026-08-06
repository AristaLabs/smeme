# SMEme Core architecture

SMEme Core is a self-hosted application for authoring **decision-trees** and
running them through a server-side **logical analysis engine**.

Database migrations hold a PostgreSQL advisory lock for the complete Alembic
transaction (`pg_advisory_lock` / `pg_advisory_unlock`), preventing concurrent
container starts from racing the schema upgrade.

## Product shape

- **Web application:** authors create, edit, and Deploy decision-trees.
- **Logical analysis engine:** Deploy validates and compiles a tree; the deployed
  artifact supports evaluation (structured answers → **report**) and graph-level
  questions (what-if, reachability, and related analysis).
- **Remote MCP:** OAuth-protected tools let an owner list, validate, evaluate, and
  analyze their Listed decision-trees. After connect, the agent **fetches calling
  guidance over MCP** (`smeme_reasoning_guidance_get`) — there is no installable
  installable zip.
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
├── decision_tree/   # decision-tree dashboard, editor, viewer, generation
├── reasoning/       # IR, validation, compilation, runtime evaluation
├── mcp/             # OAuth discovery, bearer verification, MCP tools
└── templates/       # Core web templates

agent-skills/        # Authoring source for MCP guidance markdown
```

## Runtime flow

### Authoring (two draft paths → one artifact)

1. **Web wizard** (`SMEME_AI_GENERATION_ENABLED`) — optional OpenAI/Tavily-assisted
   research, design, and build; LangGraph interrupts for human edits.
2. **MCP chat** (`smeme-decision-tree-author` skill) — agent iterates in prose,
   validates `dt_graph_json`, creates a dashboard draft; no server LLM egress.
3. Both paths persist the same **DTGraph** in `DecisionTree.graph_data`, then converge on
   the **editor**.

### Deploy, list, evaluate

4. An author saves edits and **Deploy** validates and compiles the tree (IR/Z3).
5. **Listed** / **Hidden** controls MCP discoverability on the dashboard.
6. An MCP client authenticates with the configured OAuth provider.
7. The client loads the calling contract via **`smeme_reasoning_guidance_get`**
   (after capabilities / guidance digest check) — served from content built out
   of `agent-skills/`, not a local skill install.
8. The client evaluates structured answers and/or asks graph-level questions
   about a Listed, deployed decision-tree.
9. The server answers from the deployed artifact (report and/or analysis).

See [Authoring decision trees](guides/authoring-decision-trees.md) for path
comparison, DTGraph shape, flags, and egress.

## Operator references

- [Authoring decision trees](guides/authoring-decision-trees.md)
- [Engine promises](guides/engine-promises.md)
- [Decision-DAG algebra](spec/decision-dag-algebra.md)
- [Algebra maintenance](guides/decision-dag-algebra-maintenance.md)
- [Self-host quickstart](guides/self-host-quickstart.md)
- [MCP OAuth guide](guides/dr3-mcp-oauth-authoritative-sources.md)
- [Contribution paths](CONTRIBUTION_PATHS.md)
- [Agent Skills source](../agent-skills/README.md)

## GHCR publish tracks

Core publishes `ghcr.io/aristalabs/smeme` on two tracks (same vocabulary as Cloud):

| Channel | Trigger | Tags | Moves `:latest`? |
|---------|---------|------|------------------|
| **staging** | push to `main` | `sha-<fullsha>`, `staging-latest` | No |
| **release** | `v*.*.*` tag | semver + `latest` + `sha-…` | Yes |

OCI labels: `io.smeme.core.version` (release lineage), `io.smeme.core.ref`,
`io.smeme.core.channel` (`release` \| `staging`). Digest is authoritative.
Cloud may pin staging Core digests for hosted staging only; production Cloud
builds require `channel=release`.

**Theory vs image pins.** Public decision-DAG algebra is cited by Git tag/commit
([`docs/spec/decision-dag-algebra.md`](spec/decision-dag-algebra.md)); runtime is
pinned by image digest. When reasoning or Deploy semantics change, follow
[decision-DAG algebra maintenance](guides/decision-dag-algebra-maintenance.md)
before treating a tip as conformant or cutting a citeable theory revision.
Verify release digests with [image attestations](guides/image-attestations.md).
