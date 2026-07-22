"""Agent-facing MCP message vocabulary and error-code registry coupling."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from smeme.mcp.tool_contract import REASONING_TOOL_ERROR_CODES

REPO_ROOT = Path(__file__).resolve().parents[3]
SMEme_ROOT = REPO_ROOT / "smeme"

# Same denylist intent as agent-skills/README.md (message prose only).
_FORBIDDEN_MESSAGE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bZ3\b", re.IGNORECASE), "Z3"),
    (re.compile(r"\bSAT\b", re.IGNORECASE), "SAT"),
    (re.compile(r"\bSAT/UNSAT\b", re.IGNORECASE), "SAT/UNSAT"),
    (re.compile(r"\bUNSAT\b", re.IGNORECASE), "UNSAT"),
    (re.compile(r"\bSMT\b", re.IGNORECASE), "SMT"),
    (re.compile(r"\bsatisfiable\b", re.IGNORECASE), "satisfiable"),
    (re.compile(r"\bunsatisfiable\b", re.IGNORECASE), "unsatisfiable"),
    (re.compile(r"\bentails?\b", re.IGNORECASE), "entails/entail"),
    (re.compile(r"\bentailment\b", re.IGNORECASE), "entailment"),
    (re.compile(r"\bsolver\b", re.IGNORECASE), "solver"),
)

_SCAN_ROOTS = (
    SMEme_ROOT / "mcp",
    SMEme_ROOT / "billing",
    SMEme_ROOT / "reasoning" / "runtime" / "counterfactual.py",
    SMEme_ROOT / "reasoning" / "runtime" / "path_under_edit.py",
    SMEme_ROOT / "reasoning" / "runtime" / "decisive_support.py",
)

_EMITTER_SCAN_GLOBS = ("**/*.py",)


def _string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None
        return "".join(parts)
    return None


def _collect_emitter_codes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    codes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "tool_error_json":
            if node.args and (code := _string_value(node.args[0])):
                codes.add(code)
        elif isinstance(func, ast.Attribute) and func.attr == "tool_error_json":
            if node.args and (code := _string_value(node.args[0])):
                codes.add(code)
        elif isinstance(func, ast.Name) and func.id == "CounterfactualError":
            if node.args and (code := _string_value(node.args[0])):
                codes.add(code)
        elif isinstance(func, ast.Name) and func.id in {
            "PathUnderEditError",
            "DecisiveSupportError",
        }:
            if node.args and (code := _string_value(node.args[0])):
                codes.add(code)
    return codes


def _collect_agent_messages(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    messages: list[tuple[int, str]] = []

    def add_message(node: ast.AST, text: str | None) -> None:
        if text is not None:
            messages.append((getattr(node, "lineno", 0), text))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_tool_error = (isinstance(func, ast.Name) and func.id == "tool_error_json") or (
            isinstance(func, ast.Attribute) and func.attr == "tool_error_json"
        )
        is_counterfactual = isinstance(func, ast.Name) and func.id == "CounterfactualError"
        is_domain_error = isinstance(func, ast.Name) and func.id in {
            "PathUnderEditError",
            "DecisiveSupportError",
        }
        if is_tool_error and len(node.args) >= 2:
            add_message(node, _string_value(node.args[1]))
        elif is_counterfactual and len(node.args) >= 2:
            add_message(node, _string_value(node.args[1]))
        elif is_domain_error and len(node.args) >= 2:
            add_message(node, _string_value(node.args[1]))
        elif isinstance(func, ast.Name) and func.id == "_how_to_reach_blocked":
            for kw in node.keywords:
                if kw.arg == "message":
                    add_message(kw, _string_value(kw.value))
    return messages


def _iter_scan_paths() -> list[Path]:
    paths: list[Path] = []
    for root in _SCAN_ROOTS:
        if root.is_file():
            paths.append(root)
        else:
            for pattern in _EMITTER_SCAN_GLOBS:
                paths.extend(root.glob(pattern))
    return sorted({p for p in paths if p.is_file() and p.name != "__init__.py"})


def test_concurrency_limit_in_error_registry() -> None:
    assert "concurrency_limit" in REASONING_TOOL_ERROR_CODES


def test_mcp_emitter_codes_subset_of_registry() -> None:
  emitted: set[str] = set()
  for path in _iter_scan_paths():
      emitted |= _collect_emitter_codes(path)
  unknown = sorted(emitted - REASONING_TOOL_ERROR_CODES)
  assert not unknown, f"Live emitter codes missing from REASONING_TOOL_ERROR_CODES: {unknown}"


@pytest.mark.parametrize("path", _iter_scan_paths(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_agent_facing_messages_avoid_formal_methods_vocabulary(path: Path) -> None:
    violations: list[str] = []
    for lineno, text in _collect_agent_messages(path):
        for pattern, label in _FORBIDDEN_MESSAGE_PATTERNS:
            if pattern.search(text):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {label!r} in {text!r}")
                break
    assert not violations, "Agent-facing messages must use product vocabulary:\n" + "\n".join(
        violations
    )
