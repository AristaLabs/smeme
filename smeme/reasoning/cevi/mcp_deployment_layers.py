"""Author-facing MCP deployment layer labels (workflow deploy status)."""

from __future__ import annotations

from dataclasses import dataclass

from smeme.core.models import ReasoningCompiledArtifact
from smeme.reasoning.publish_readiness import PublishReadiness


@dataclass(frozen=True, slots=True)
class McpDeploymentLayerLine:
    """One row in the MCP plugin deployment summary."""

    title: str
    status: str
    detail: str


def build_mcp_deployment_layer_lines(
    *,
    readiness: PublishReadiness,
    artifact: ReasoningCompiledArtifact | None,
) -> list[McpDeploymentLayerLine]:
    """Short labels for workflow deploy status on the editor Tools tab."""
    if not readiness.ready:
        logic_status = "Blocked"
        logic_detail = "Fix validation errors before deploying."
    elif artifact is None:
        logic_status = "Not deployed"
        logic_detail = "Deploy this workflow to make it available to your AI."
    elif readiness.graph_hash and artifact.graph_hash != readiness.graph_hash:
        logic_status = "Out of date"
        logic_detail = "Your saved workflow has changed since the last deploy."
    else:
        logic_status = "Up to date"
        logic_detail = "Your saved workflow matches the current deployment."

    return [McpDeploymentLayerLine("Workflow", logic_status, logic_detail)]
