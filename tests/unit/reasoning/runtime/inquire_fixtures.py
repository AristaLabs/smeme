"""DTGraph goldens for Inquire G1–G9. Compile via ``validate_graph`` → IR."""

from __future__ import annotations

from dataclasses import dataclass

from smeme.decision_tree.helpers.validation import validate_graph
from smeme.decision_tree.models import (
    ConclusionData,
    DTGraph,
    DTGraphMetadata,
    GraphEdge,
    GraphNode,
    QuestionData,
)
from smeme.reasoning.dt_graph_bridge import compile_dt_graph_to_ir
from smeme.reasoning.ir.types import IR
from smeme.reasoning.ir.validate import validate_ir
from smeme.reasoning.runtime.inquire.types import (
    AdmittedAssertion,
    CanonicalProvenanceId,
    VerificationKey,
    WorksheetItem,
)

SENTINEL_ARTIFACT = "inquire-golden-artifact"
SENTINEL_PROVENANCE = "inquire-golden-provenance"
SENTINEL_PV_VERSION = "pv-phase1-sentinel"


def sentinel_provenance(tag: str = SENTINEL_PROVENANCE) -> CanonicalProvenanceId:
    return CanonicalProvenanceId(tag)


def sentinel_assertion(
    question_id: str,
    option: str,
    provenance: str = SENTINEL_PROVENANCE,
) -> AdmittedAssertion:
    return AdmittedAssertion(
        question_id=question_id,
        option=option,
        provenance_id=sentinel_provenance(provenance),
    )


def sentinel_key(
    question_id: str,
    option: str,
    *,
    provenance: str = SENTINEL_PROVENANCE,
    artifact: str = SENTINEL_ARTIFACT,
    pv_version: str = SENTINEL_PV_VERSION,
) -> VerificationKey:
    return VerificationKey(
        artifact_identity=artifact,
        question_id=question_id,
        option=option,
        provenance_identity=provenance,
        pv_version=pv_version,
    )


def _question(node_id: str, text: str, options: list[str]) -> GraphNode:
    return GraphNode(
        id=node_id,
        type="question",
        data=QuestionData(text=text, type="radio", options=options, required=True),
    )


def _conclusion(node_id: str, title: str, summary: str) -> GraphNode:
    return GraphNode(
        id=node_id,
        type="conclusion",
        data=ConclusionData(title=title, summary=summary),
    )


@dataclass(frozen=True)
class GoldenFixture:
    graph: DTGraph
    ir: IR
    catalog: dict[str, WorksheetItem]


def compile_golden(graph: DTGraph) -> GoldenFixture:
    ok, msg = validate_graph(graph)
    assert ok, msg
    ir = compile_dt_graph_to_ir(graph)
    report = validate_ir(ir)
    assert report.valid, report.errors
    catalog: dict[str, WorksheetItem] = {}
    for node in graph.get_question_nodes():
        qdata = node.question_data
        assert qdata is not None
        catalog[node.id] = WorksheetItem(stem=qdata.text, options=tuple(qdata.options))
    return GoldenFixture(graph=graph, ir=ir, catalog=catalog)


def xor_g1_graph() -> DTGraph:
    return DTGraph(
        nodes=[
            _question("q1", "First bit?", ["0", "1"]),
            _question("q2a", "Second bit on the zero path?", ["0", "1"]),
            _question("q2b", "Second bit on the one path?", ["0", "1"]),
            _conclusion("OA", "Match", "Taken second bit matches the first."),
            _conclusion("OB", "Mismatch", "Taken second bit differs from the first."),
        ],
        edges=[
            GraphEdge(source="q1", target="q2a", condition="0"),
            GraphEdge(source="q1", target="q2b", condition="1"),
            GraphEdge(source="q2a", target="OA", condition="0"),
            GraphEdge(source="q2a", target="OB", condition="1"),
            GraphEdge(source="q2b", target="OB", condition="0"),
            GraphEdge(source="q2b", target="OA", condition="1"),
        ],
        metadata=DTGraphMetadata(title="Inquire G1 XOR"),
    )


def fork_g2_graph() -> DTGraph:
    return DTGraph(
        nodes=[
            _question("q1", "Continue on the primary path?", ["Yes", "No"]),
            _question("q2", "Which branch on the primary path?", ["A", "B"]),
            _conclusion("c1", "Primary", "Reached on the Yes path."),
            _conclusion("c2", "Side", "Reached when the branch is A."),
            _conclusion("c3", "Other", "Reached on the No path."),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="q2", condition="Yes"),
            GraphEdge(source="q2", target="c2", condition="A"),
            GraphEdge(source="q2", target="c1", condition="B"),
            GraphEdge(source="q1", target="c3", condition="No"),
        ],
        metadata=DTGraphMetadata(title="Inquire G2 fork"),
    )


def joint_g6_graph() -> DTGraph:
    return DTGraph(
        nodes=[
            _question("q1", "Continue?", ["Yes", "No"]),
            _conclusion("c1", "First", "Yes reaches first."),
            _conclusion("c2", "Second", "Yes reaches second."),
            _conclusion("c3", "Other", "No path."),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="c2", condition="Yes"),
            GraphEdge(source="q1", target="c3", condition="No"),
        ],
        metadata=DTGraphMetadata(title="Inquire G6 joint"),
    )


def fork_g8_graph() -> DTGraph:
    return DTGraph(
        nodes=[
            _question("q1", "Continue on the primary path?", ["Yes", "No"]),
            _question("q2", "Which branch on the primary path?", ["A", "B"]),
            _question("q3", "Off-path detail?", ["X", "Y"]),
            _conclusion("c1", "Primary", "Reached on the Yes path."),
            _conclusion("c2", "Side", "Reached when the branch is A."),
            _conclusion("c3", "Other", "Reached on the No path."),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="q2", condition="Yes"),
            GraphEdge(source="q2", target="c2", condition="A"),
            GraphEdge(source="q2", target="c1", condition="B"),
            GraphEdge(source="q1", target="q3", condition="No"),
            GraphEdge(source="q3", target="c3", condition="X"),
            GraphEdge(source="q3", target="c3", condition="Y"),
        ],
        metadata=DTGraphMetadata(title="Inquire G8 unreachable"),
    )
