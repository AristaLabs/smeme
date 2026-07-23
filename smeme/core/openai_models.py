"""Default OpenAI model ids for SMEme LLM workloads (June 2026 pricing tier)."""

OPENAI_MODEL_LIGHT = "gpt-5-nano"
OPENAI_MODEL_HEAVY = "gpt-5.4-mini"

# Agentic decision-tree: completion output budgets (research factor lists can be long)
OPENAI_MAX_COMPLETION_RESEARCH = 9_000
OPENAI_MAX_COMPLETION_CONCLUSIONS = 12_000

# Research LLM calls can run long on exhaustive factor analysis; override singleton defaults.
OPENAI_TIMEOUT_RESEARCH_S = 120.0
OPENAI_MAX_RETRIES_RESEARCH = 1
