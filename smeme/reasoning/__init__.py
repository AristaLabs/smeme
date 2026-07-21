"""Production symbolic reasoning pipeline (IR-first). See DECISIONS.md D017.

Heavyweight bridges (e.g. QNR → IR) live in submodules like ``smeme.reasoning.qnr_bridge`` so
``import smeme.reasoning`` stays free of ``smeme.qnr`` dependencies.
"""

from smeme.reasoning.ir import (
    DEFAULT_GUARD_EXPR,
    IR,
    IR_FORMAT_VERSION,
    Guard,
    IREdge,
    IRNode,
    IRNodeKind,
    IRQuestionShape,
    IRValidationError,
    ValidationReport,
    validate_ir,
)
from smeme.reasoning.runtime import ReachabilityWitness, solve_reachability_witness
from smeme.reasoning.theory import IRSymbolTable, compile_ir_to_z3

__all__ = [
    "DEFAULT_GUARD_EXPR",
    "IR_FORMAT_VERSION",
    "Guard",
    "IR",
    "IREdge",
    "IRNode",
    "IRNodeKind",
    "IRQuestionShape",
    "IRValidationError",
    "IRSymbolTable",
    "ReachabilityWitness",
    "ValidationReport",
    "compile_ir_to_z3",
    "solve_reachability_witness",
    "validate_ir",
]
