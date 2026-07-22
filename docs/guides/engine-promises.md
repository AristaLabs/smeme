# SMEme Core: engine promises

SMEme Core helps experts encode judgment as inspectable **decision-trees** and
evaluate structured answers against a deployed version of those trees.

## What Core does

- Authors create and edit decision-trees in the web application.
- **Deploy** validates a saved tree and produces the reasoning artifact used at
  evaluation time.
- Agents and applications submit structured `raw_answers` through MCP.
- The server evaluates those answers and returns a structured **report**.
- **Listed** and **Hidden** control whether a deployed decision-tree appears in
  its owner's MCP tool list.

## What the evaluation boundary means

The server performs the reasoning. The default MCP evaluation path gives an
agent question text, answer shapes, and the resulting report; it does not
return the tree's branch topology or decision rules. This keeps the agent in
the evidence-gathering role and makes the deployed decision-tree the
authoritative evaluator.

## What self-hosting changes

Core runs in your environment with PostgreSQL. The base product does not
include hosted billing, marketing pages, analytics, or Arista Labs legal pages.
Optional AI-assisted generation can send prompts or research content to the
providers you configure; deterministic evaluation remains on your Core server.

See the [self-host quickstart](self-host-quickstart.md) for setup and optional
third-party egress.
