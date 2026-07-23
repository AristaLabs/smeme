"""QNR → IR bridge. Import this when you have a ``DTGraph``; avoid pulling ``qnr`` via ``smeme.reasoning``."""

from __future__ import annotations

from smeme.reasoning.ir.qnr_to_ir import compile_qnr_to_ir

__all__ = ["compile_qnr_to_ir"]
