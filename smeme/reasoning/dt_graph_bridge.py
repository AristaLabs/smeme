"""DecisionTree → IR bridge. Import this when you have a ``DTGraph``; avoid pulling ``decision_tree`` via ``smeme.reasoning``."""

from __future__ import annotations

from smeme.reasoning.ir.dt_graph_to_ir import compile_dt_graph_to_ir

__all__ = ["compile_dt_graph_to_ir"]
