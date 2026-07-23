"""Publish-time induction wiring."""

from smeme.qnr.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    QNRMetadata,
    QuestionData,
)
from smeme.reasoning.cevi.induction import induce_published_evidence_contract_at_publish
from smeme.reasoning.ir.serialize import ir_to_json
from smeme.reasoning.ir.types import IR_FORMAT_VERSION
from smeme.reasoning.qnr_bridge import compile_qnr_to_ir


def _minimal_publish_graph() -> DTGraph:
    return DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Q",
                    type="radio",
                    options=["A"],
                    required=True,
                ),
            ),
            GraphNode(
                id="c1",
                type="conclusion",
                data=ConclusionData(title="T", summary="S"),
            ),
        ],
        edges=[GraphEdge(source="q1", target="c1", condition="A")],
        metadata=QNRMetadata(title="minimal induction"),
    )


def test_induce_at_publish_no_corpus_snapshot_is_empty() -> None:
    graph = _minimal_publish_graph()
    ir_json = ir_to_json(compile_qnr_to_ir(graph))
    contract, snap = induce_published_evidence_contract_at_publish(
        ir_json=ir_json,
        graph=graph,
        graph_hash="a" * 64,
        ir_format_version=IR_FORMAT_VERSION,
        corpus_body=None,
        legal_at_publish=False,
    )
    assert snap.text == ""
    assert snap.sha256_hex is None
    assert snap.utf8_bytes == b""
    assert snap.utf8_byte_length == 0
    assert contract.kind == "corpus_partial"
    assert contract.atom_glosses["node:q1"].text == "Q"
    assert contract.option_paraphrases["node:q1"].by_option["A"] == ("A",)
