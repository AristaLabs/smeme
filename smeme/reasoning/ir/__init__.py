"""IR package: types, validation, optional DecisionTree compile submodule (not re-exported here)."""

from smeme.reasoning.ir.serialize import ir_from_json, ir_to_json
from smeme.reasoning.ir.types import (
    DEFAULT_GUARD_EXPR,
    IR,
    IR_FORMAT_VERSION,
    Guard,
    IREdge,
    IRNode,
    IRNodeKind,
    IRQuestionShape,
    ValidationReport,
)
from smeme.reasoning.ir.validate import IRValidationError, validate_ir

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
    "ValidationReport",
    "validate_ir",
    "ir_from_json",
    "ir_to_json",
]
