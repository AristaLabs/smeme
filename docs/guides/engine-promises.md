# SMEme Core: engine promises

SMEme Core helps experts encode judgment as inspectable **decision-trees**, then
run a **logical analysis engine** over a deployed version of those trees.

After **Deploy**, Core supports two complementary uses:

1. **Evaluate** structured answers (`raw_answers`) and return a structured
   **report**.
2. **Ask about the deployed tree itself** — counterfactual and reachability-style
   questions (for example what-if overrides, how to reach an outcome, or path
   sensitivity) answered by the server against the compiled artifact. These
   questions reason about the graph; they do not require treating a full evidence
   pass as the only entry point.

## What Core does

- Authors create and edit decision-trees in the web application.
- **Deploy** validates a saved tree and produces the reasoning artifact used for
  evaluation and logical analysis.
- Agents and applications call MCP tools to validate answers, evaluate them, and
  ask graph-level questions about Listed decision-trees.
- Evaluation returns a structured **report**; logical-analysis tools return
  deterministic answers from the same deployed artifact.
- Queries against inconsistent evidence or assumptions return an explicit
  inconsistent status (`answers_inconsistent` or `assumptions_inconsistent`),
  never a vacuous “entailed” or false “impossible.” When evidence alone is
  inconsistent, the cause is `answers_inconsistent` even if assumptions are
  present.
- **Listed** and **Hidden** control whether a deployed decision-tree appears in
  its owner's MCP tool list.

## What the evaluation boundary means

The server performs the reasoning. On the default MCP path, agents see question
text, answer shapes, and results (reports or analysis answers); they do not
receive the tree's branch topology or decision rules. Agents gather evidence and
pose questions; the deployed decision-tree remains the authoritative evaluator
and analyzer.

## What self-hosting changes

Core runs in your environment with PostgreSQL. The base product does not
include hosted billing, marketing pages, analytics, or Arista Labs legal pages.
Optional AI-assisted generation can send prompts or research content to the
providers you configure; deterministic evaluation and logical analysis remain on
your Core server.

See the [self-host quickstart](self-host-quickstart.md) for setup and optional
third-party egress.
