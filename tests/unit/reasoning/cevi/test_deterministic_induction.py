"""Deterministic corpus_partial induction from graph copy."""

from __future__ import annotations

from smeme.decision_tree.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    DTGraphMetadata,
    QuestionData,
)
from smeme.reasoning.cevi.corpus_normalize import build_research_corpus_snapshot
from smeme.reasoning.cevi.deterministic_induction import (
    build_deterministic_corpus_partial_contract,
)
from smeme.reasoning.ir.types import IR_FORMAT_VERSION


def test_deterministic_glosses_identity_options_and_lexical_without_corpus() -> None:
    """No snapshot → empty manifest; glosses and identity paraphrases still emitted."""
    g = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Pick",
                    type="radio",
                    options=["Yes", "No"],
                    required=True,
                ),
            ),
            GraphNode(
                id="c1",
                type="conclusion",
                data=ConclusionData(title="A", summary="outcome a"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
        ],
        metadata=DTGraphMetadata(title="x"),
    )
    snap = build_research_corpus_snapshot(None)
    c = build_deterministic_corpus_partial_contract(
        graph=g,
        corpus_snapshot=snap,
        graph_hash="f" * 64,
        ir_format_version=IR_FORMAT_VERSION,
        legal_at_publish=False,
    )
    assert c.kind == "corpus_partial"
    assert c.corpus_chunk_manifest == ()
    assert c.atom_glosses["node:q1"].corpus_chunk_ids == ()
    assert c.atom_glosses["node:q1"].text == "Pick"
    assert c.atom_glosses["node:c1"].text == "A. outcome a"
    assert c.atom_glosses["node:c1"].corpus_chunk_ids == ()
    assert c.option_paraphrases["node:q1"].by_option["Yes"] == ("Yes",)
    assert c.option_paraphrases["node:q1"].by_option["No"] == ("No",)
    assert "node:q1" in c.lexical_signatures
    assert "node:c1" in c.lexical_signatures
    assert "corpus_attribution_miss" not in "".join(c.warnings)


def test_skips_empty_question_gloss_but_keeps_options() -> None:
    """Whitespace-only stem → no gloss row; options + lexical still emitted."""
    g = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="   ",
                    type="radio",
                    options=["A"],
                    required=True,
                ),
            ),
        ],
        edges=[],
        metadata=DTGraphMetadata(title="y"),
    )
    snap = build_research_corpus_snapshot(None)
    c = build_deterministic_corpus_partial_contract(
        graph=g,
        corpus_snapshot=snap,
        graph_hash="f" * 64,
        ir_format_version=IR_FORMAT_VERSION,
        legal_at_publish=False,
    )
    assert "node:q1" not in c.atom_glosses
    assert c.option_paraphrases["node:q1"].by_option["A"] == ("A",)
    assert c.lexical_signatures["node:q1"].corpus_chunk_ids == ()


def test_attributed_chunk_ids_only_when_corpus_overlaps_question_cues() -> None:
    """Narrow attribution: cite chunks whose text overlaps stem tokens or option labels."""
    g = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Hi",
                    type="radio",
                    options=["X"],
                    required=True,
                ),
            ),
        ],
        edges=[],
        metadata=DTGraphMetadata(title="z"),
    )
    snap = build_research_corpus_snapshot("Hi friend\n\nunrelated block without overlap token")
    assert snap.sha256_hex is not None
    c = build_deterministic_corpus_partial_contract(
        graph=g,
        corpus_snapshot=snap,
        graph_hash="f" * 64,
        ir_format_version=IR_FORMAT_VERSION,
        legal_at_publish=False,
    )
    assert len(c.corpus_chunk_manifest) == 2
    first_id = c.corpus_chunk_manifest[0].chunk_id
    assert c.atom_glosses["node:q1"].corpus_chunk_ids == (first_id,)
    assert c.lexical_signatures["node:q1"].corpus_chunk_ids == (first_id,)
    assert "corpus_attribution_miss:node:q1" not in c.warnings


def test_corpus_attribution_miss_when_manifest_nonempty_but_no_overlap() -> None:
    """Non-empty manifest + authored cues that never appear in chunk text → warn + empty ids."""
    g = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Zebra",
                    type="radio",
                    options=["Q"],
                    required=True,
                ),
            ),
        ],
        edges=[],
        metadata=DTGraphMetadata(title="z"),
    )
    snap = build_research_corpus_snapshot("alpha\n\nbravo")
    assert snap.sha256_hex is not None
    c = build_deterministic_corpus_partial_contract(
        graph=g,
        corpus_snapshot=snap,
        graph_hash="f" * 64,
        ir_format_version=IR_FORMAT_VERSION,
        legal_at_publish=False,
    )
    assert len(c.corpus_chunk_manifest) == 2
    assert c.atom_glosses["node:q1"].corpus_chunk_ids == ()
    assert c.lexical_signatures["node:q1"].corpus_chunk_ids == ()
    assert "corpus_attribution_miss:node:q1" in c.warnings


def test_conclusion_attribution_matches_title_blob_in_corpus() -> None:
    g = DTGraph(
        nodes=[
            GraphNode(
                id="c1",
                type="conclusion",
                data=ConclusionData(title="Outcome Delta", summary="ignored here"),
            ),
        ],
        edges=[],
        metadata=DTGraphMetadata(title="c"),
    )
    snap = build_research_corpus_snapshot("Intro\n\nOutcome Delta extra words")
    c = build_deterministic_corpus_partial_contract(
        graph=g,
        corpus_snapshot=snap,
        graph_hash="f" * 64,
        ir_format_version=IR_FORMAT_VERSION,
        legal_at_publish=False,
    )
    assert len(c.corpus_chunk_manifest) >= 1
    ids = {m.chunk_id for m in c.corpus_chunk_manifest}
    assert set(c.atom_glosses["node:c1"].corpus_chunk_ids).issubset(ids)
    assert len(c.atom_glosses["node:c1"].corpus_chunk_ids) >= 1
    assert "corpus_attribution_miss:node:c1" not in c.warnings
