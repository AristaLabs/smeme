"""IR atom catalog allowlist from persisted ``ir_json``."""

import pytest

from smeme.reasoning.cevi.atom_catalog import IrAtomCatalogError, canonical_ir_atom_catalog
from smeme.reasoning.ir.types import IR_FORMAT_VERSION


def test_canonical_ir_atom_catalog_from_sample() -> None:
    ir_json = {
        "format_version": IR_FORMAT_VERSION,
        "nodes": [
            {"id": "q1", "kind": "question", "question": {"qtype": "radio", "options": ["A"]}},
            {"id": "c1", "kind": "conclusion", "question": None},
        ],
        "edges": [{"source": "q1", "target": "c1", "guard_id": "g0"}],
        "guards": [{"id": "g0", "expr": "A"}],
    }
    cat = canonical_ir_atom_catalog(ir_json)
    assert "node:q1" in cat
    assert "node:c1" in cat
    assert "guard:g0" in cat
    assert "edge:q1|c1|g0" in cat


def test_canonical_ir_atom_catalog_rejects_bad_shape() -> None:
    with pytest.raises(IrAtomCatalogError, match="parse failed"):
        canonical_ir_atom_catalog({"format_version": IR_FORMAT_VERSION})


def test_canonical_ir_atom_catalog_rejects_invalid_ir() -> None:
    """Structurally parseable JSON that fails validate_ir must not produce a partial allowlist."""
    ir_json = {
        "format_version": IR_FORMAT_VERSION,
        "nodes": [
            {"id": "q1", "kind": "question", "question": {"qtype": "radio", "options": ["A"]}},
            {"id": "q1", "kind": "conclusion", "question": None},
        ],
        "edges": [{"source": "q1", "target": "c1", "guard_id": "g0"}],
        "guards": [{"id": "g0", "expr": "A"}],
    }
    with pytest.raises(IrAtomCatalogError, match="validate_ir"):
        canonical_ir_atom_catalog(ir_json)
