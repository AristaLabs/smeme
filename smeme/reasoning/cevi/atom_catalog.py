"""Canonical IR atom ids allowed as CEVI bridge / lexical targets (derived from validated ``ir_json``).

Allowlist naming (stable string ids):
  - ``node:{id}`` — IR node id (question or conclusion vertex)
  - ``guard:{id}`` — guard row id
  - ``edge:{source}|{target}|{guard_id}`` — directed edge identity
"""

from __future__ import annotations

from typing import Any

from smeme.reasoning.ir.serialize import ir_from_json
from smeme.reasoning.ir.types import IR, IRNodeKind
from smeme.reasoning.ir.validate import validate_ir


class IrAtomCatalogError(ValueError):
    """Persisted ``ir_json`` could not be parsed as IR or failed :func:`~smeme.reasoning.ir.validate.validate_ir`."""


def _atoms_from_valid_ir(ir: IR) -> frozenset[str]:
    out: set[str] = set()
    for n in ir.nodes:
        out.add(f"node:{n.id}")
    for g in ir.guards:
        out.add(f"guard:{g.id}")
    for e in ir.edges:
        out.add(f"edge:{e.source}|{e.target}|{e.guard_id}")
    return frozenset(out)


def _question_option_labels_from_ir(ir: IR) -> dict[str, frozenset[str]]:
    """Map ``node:{id}`` → allowed IR option labels for each question vertex (empty set if none)."""
    out: dict[str, frozenset[str]] = {}
    for n in ir.nodes:
        if n.kind != IRNodeKind.QUESTION:
            continue
        if n.question is None:
            continue
        out[f"node:{n.id}"] = frozenset(n.question.options)
    return out


def parse_validated_ir(ir_json: dict[str, Any]) -> IR:
    """Parse ``ir_json`` and run :func:`~smeme.reasoning.ir.validate.validate_ir`.

    Raises :exc:`IrAtomCatalogError` on parse or validation failure.
    """
    try:
        ir = ir_from_json(ir_json)
    except (KeyError, TypeError, ValueError) as e:
        detail = f"IR JSON parse failed: {e}"
        raise IrAtomCatalogError(detail) from e
    report = validate_ir(ir)
    if not report.valid:
        msg = "; ".join(report.errors) if report.errors else "IR validation failed"
        detail = f"IR failed validate_ir: {msg}"
        raise IrAtomCatalogError(detail)
    return ir


def canonical_ir_validation_context(
    ir_json: dict[str, Any],
) -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """Atom catalog plus per-question option labels for CEVI contract validation."""
    ir = parse_validated_ir(ir_json)
    return _atoms_from_valid_ir(ir), _question_option_labels_from_ir(ir)


def canonical_ir_atom_catalog(ir_json: dict[str, Any]) -> frozenset[str]:
    """Derive the closed set of IR carrier ids from persisted artifact JSON.

    Parses with :func:`~smeme.reasoning.ir.serialize.ir_from_json` and requires
    :func:`~smeme.reasoning.ir.validate.validate_ir` to succeed—malformed or invalid IR never yields a
    partial allowlist.
    """
    return canonical_ir_validation_context(ir_json)[0]
