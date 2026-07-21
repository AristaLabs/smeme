"""Stable Z3 symbol strings for IR theory (shared by guard modules and runtime evaluate)."""

from __future__ import annotations


def z3_sym_fragment(s: str) -> str:
    """Sanitize arbitrary text for use inside Z3 symbol names (matches prior module behavior)."""
    out: list[str] = []
    for c in s:
        if c.isalnum() or c == "_":
            out.append(c)
        else:
            out.append("_")
    t = "".join(out)
    if not t or t[0].isdigit():
        t = "x_" + t
    return t[:120]


def radio_option_symbol_name(question_id: str, option_label: str) -> str:
    return "ir_radioopt_" + z3_sym_fragment(question_id) + "_" + z3_sym_fragment(option_label)
