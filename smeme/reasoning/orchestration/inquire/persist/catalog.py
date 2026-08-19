"""Worksheet catalog from an in-sync DTGraph (stems + IR-canonical options)."""

from __future__ import annotations

from smeme.decision_tree.models import DTGraph
from smeme.mcp.inquire.codec import encode_worksheet_catalog
from smeme.reasoning.ir.types import IR, IRNodeKind
from smeme.reasoning.runtime.inquire.types import WorksheetCatalog, WorksheetItem


def worksheet_catalog_from_graph_and_ir(graph: DTGraph, ir: IR) -> dict[str, WorksheetItem]:
    """Build extractor catalog at session start.

    Stems come from the graph (not in IR). Options come from IR question shapes
    so they match ANALYZE / admission canonical labels.
    """
    ir_options: dict[str, tuple[str, ...]] = {}
    for node in ir.nodes:
        if node.kind != IRNodeKind.QUESTION or node.question is None:
            continue
        ir_options[node.id] = tuple(node.question.options)

    catalog: dict[str, WorksheetItem] = {}
    for node in graph.get_question_nodes():
        qdata = node.question_data
        if qdata is None:
            continue
        opts = ir_options.get(node.id)
        if opts is None:
            opts = tuple(qdata.options)
        catalog[node.id] = WorksheetItem(stem=qdata.text, options=opts)
    return catalog


def catalog_json_dict(catalog: WorksheetCatalog) -> dict:
    """JSONB-ready dict matching encode_worksheet_catalog."""
    return encode_worksheet_catalog(catalog)
