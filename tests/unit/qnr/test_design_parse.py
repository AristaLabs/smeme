"""Tests for design markdown parsing helpers."""

from smeme.qnr.generation.agentic.design_parse import parse_collect_only_question_ids


def test_parse_collect_only_exact_marker_only():
    design = """
#### Q1: Evidence quality
- **Type**: radio
- **Node kind**: collect_only
- **Options**: High, Low
- **Branching**:
  - If "High" → Q2
  - If "Low" → Q2

#### Q2: Routing question
- **Type**: radio
- **Node kind**: routing
- **Options**: Yes, No
"""
    assert parse_collect_only_question_ids(design) == frozenset({"q1"})


def test_parse_collect_only_ignores_help_text_mention():
    design = """
#### Q1: Not a collect node
- **Type**: radio
- **Help text**: This question is not collect-only and should not match.
- **Options**: A, B
"""
    assert parse_collect_only_question_ids(design) == frozenset()
