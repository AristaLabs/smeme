"""Pure unit tests for Inquire Phase 6 helpers (no DB)."""

from __future__ import annotations

from smeme.reasoning.orchestration.inquire.persist.catalog import (
    catalog_json_dict,
    worksheet_catalog_from_graph_and_ir,
)
from smeme.reasoning.orchestration.inquire.persist.service import (
    _should_reject_stale_admit_replay,
    canonical_request_hash,
)
from tests.unit.reasoning.runtime.inquire_fixtures import compile_golden, fork_g2_graph


def test_worksheet_catalog_from_graph_and_ir() -> None:
    fixture = compile_golden(fork_g2_graph())
    catalog = worksheet_catalog_from_graph_and_ir(fixture.graph, fixture.ir)
    assert set(catalog) == set(fixture.catalog)
    for qid, item in fixture.catalog.items():
        assert catalog[qid].stem == item.stem
        assert catalog[qid].options == item.options
    encoded = catalog_json_dict(catalog)
    assert encoded["q1"]["stem"] == "Continue on the primary path?"


def test_canonical_request_hash_stable() -> None:
    a = canonical_request_hash({"operation": "admit", "question_id": "q1", "selected_option": "Yes"})
    b = canonical_request_hash({"selected_option": "Yes", "question_id": "q1", "operation": "admit"})
    assert a == b
    assert len(a) == 64


def test_should_reject_stale_admit_replay() -> None:
    assert not _should_reject_stale_admit_replay(
        session_revision=5,
        receipt_response={"revision": 5},
    )
    assert _should_reject_stale_admit_replay(
        session_revision=8,
        receipt_response={"revision": 5},
    )
    assert not _should_reject_stale_admit_replay(
        session_revision=4,
        receipt_response={"revision": 4},
    )
    assert not _should_reject_stale_admit_replay(
        session_revision=4,
        receipt_response={},
    )
