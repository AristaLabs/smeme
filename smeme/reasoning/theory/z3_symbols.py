"""Stable Z3 symbol strings for IR theory (shared by guard modules and runtime evaluate)."""

from __future__ import annotations

import hashlib


def z3_sym_fragment(s: str, *, max_len: int = 120) -> str:
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
    return t[:max_len]


def radio_option_symbol_name(question_id: str, option_label: str) -> str:
    """Stable unique atom for a radio option.

    Truncated sanitized fragments alone collide when two labels share a long prefix
    (or differ only after sanitization). Append a digest of the full label so
    distinct options always map to distinct atoms, while staying under the
    ``BlobEvidenceItem.atom`` 256-char cap.
    """
    digest = hashlib.sha256(option_label.encode("utf-8")).hexdigest()[:16]
    return (
        "ir_radioopt_"
        + z3_sym_fragment(question_id, max_len=64)
        + "_"
        + z3_sym_fragment(option_label, max_len=64)
        + "_"
        + digest
    )
