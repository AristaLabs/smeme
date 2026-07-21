"""Unit tests for :mod:`smeme.reasoning.cevi.mcp_deployment_layers`."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from smeme.reasoning.cevi.mcp_deployment_layers import build_mcp_deployment_layer_lines
from smeme.reasoning.publish_readiness import PublishReadiness


def _readiness(*, ready: bool, graph_hash: str | None = "abc") -> PublishReadiness:
    return PublishReadiness(
        ready=ready,
        graph_hash=graph_hash,
        ir_json={"nodes": [], "edges": [], "guards": []} if ready else None,
    )


def test_shows_workflow_deploy_row_when_ready_and_deployed() -> None:
    lines = build_mcp_deployment_layer_lines(
        readiness=_readiness(ready=True, graph_hash="same"),
        artifact=SimpleNamespace(graph_hash="same", cevi_contract_json={"version": 1}),
    )
    assert [line.title for line in lines] == ["Workflow"]
    assert lines[0].status == "Up to date"


def test_shows_blocked_when_readiness_fails() -> None:
    lines = build_mcp_deployment_layer_lines(
        readiness=_readiness(ready=False, graph_hash=None),
        artifact=None,
    )
    assert lines[0].status == "Blocked"


def test_shows_out_of_date_when_graph_hash_differs() -> None:
    lines = build_mcp_deployment_layer_lines(
        readiness=_readiness(ready=True, graph_hash="new"),
        artifact=SimpleNamespace(graph_hash="old", cevi_contract_json={"version": 1}),
    )
    assert lines[0].status == "Out of date"
