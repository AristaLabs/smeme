"""LangSmith / LangChain tracing must stay disabled (no third-party workflow I/O export)."""

import os

from smeme.app_factory import disable_langsmith_tracing


def test_disable_langsmith_tracing_clears_stale_env():
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = "ls__test"
    os.environ["LANGCHAIN_PROJECT"] = "smeme-platform"
    os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"

    disable_langsmith_tracing()

    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert "LANGCHAIN_API_KEY" not in os.environ
    assert "LANGCHAIN_PROJECT" not in os.environ
    assert "LANGCHAIN_ENDPOINT" not in os.environ

    disable_langsmith_tracing()
