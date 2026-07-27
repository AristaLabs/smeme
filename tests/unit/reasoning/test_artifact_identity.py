"""D025 artifact identity golden bytes."""

from __future__ import annotations

from uuid import UUID

import pytest

from smeme.reasoning.artifact_identity import (
    build_artifact_identity_v1,
    compute_artifact_hash_v1,
    compute_ir_hash_v1,
)
from smeme.reasoning.ir.types import IR_FORMAT_VERSION
from smeme.reasoning.version import REASONING_COMPILER_VERSION


def test_ir_hash_golden_empty_ir_format_3() -> None:
    ir = {"nodes": [], "edges": [], "format": 3}
    assert (
        compute_ir_hash_v1(ir)
        == "40ba7eecae94074afa36cb2a274da387154fd2c15c361c91b9e292b2ca9c25b4"
    )


def test_artifact_hash_golden_v1_preimage() -> None:
    decision_tree_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    graph_hash = "0" * 64
    ir_hash = "40ba7eecae94074afa36cb2a274da387154fd2c15c361c91b9e292b2ca9c25b4"
    identity = build_artifact_identity_v1(
        decision_tree_id=decision_tree_id,
        graph_hash=graph_hash,
        ir_format_version=IR_FORMAT_VERSION,
        ir_hash=ir_hash,
        compiler_version=REASONING_COMPILER_VERSION,
        cevi_contract_hash=None,
        research_corpus_hash=None,
    )
    assert (
        compute_artifact_hash_v1(identity)
        == "1428f0335d5d7b5372c7669b339be5fb4c816d5ffd29b25cbf8844599af485de"
    )


@pytest.mark.parametrize(
    "bad_hash",
    ["", "ABC" * 20 + "AB", "g" * 64],
)
def test_build_identity_rejects_malformed_graph_hash(bad_hash: str) -> None:
    with pytest.raises(Exception):
        build_artifact_identity_v1(
            decision_tree_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            graph_hash=bad_hash,
            ir_format_version=IR_FORMAT_VERSION,
            ir_hash="40ba7eecae94074afa36cb2a274da387154fd2c15c361c91b9e292b2ca9c25b4",
            compiler_version=REASONING_COMPILER_VERSION,
            cevi_contract_hash=None,
            research_corpus_hash=None,
        )
