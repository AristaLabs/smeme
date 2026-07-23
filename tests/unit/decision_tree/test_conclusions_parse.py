"""Tests for conclusion ID extraction used in design prompts."""

from smeme.decision_tree.generation.agentic.conclusions_parse import (
    extract_conclusion_ids,
    format_allowed_conclusions_list,
)


def test_extract_conclusion_ids_ordered_unique():
    text = """
**CONCLUSION_1: Pursue Strict Liability**

**Summary**: ...

---

**CONCLUSION_2: Consider Warranty Claim**

---

**CONCLUSION_1: Duplicate should be ignored**
"""
    assert extract_conclusion_ids(text) == [
        ("CONCLUSION_1", "Pursue Strict Liability"),
        ("CONCLUSION_2", "Consider Warranty Claim"),
    ]


def test_format_allowed_conclusions_list_closed_set():
    text = "**CONCLUSION_3: No Liability**\n\n**CONCLUSION_1: Win**"
    formatted, parse_ok = format_allowed_conclusions_list(text)
    assert parse_ok is True
    assert "CONCLUSION_3: No Liability" in formatted
    assert "CONCLUSION_1: Win" in formatted
    assert "do not create, rename, merge, or omit" in formatted.lower()


def test_format_allowed_conclusions_list_fails_loud_when_unparsed():
    formatted, parse_ok = format_allowed_conclusions_list("No structured conclusions here.")
    assert parse_ok is False
    assert "PARSER WARNING" in formatted


def test_parse_allowed_conclusions_structured():
    from smeme.decision_tree.generation.agentic.conclusions_parse import parse_allowed_conclusions

    parsed = parse_allowed_conclusions("**CONCLUSION_1: Win**\n\n**CONCLUSION_2: Lose**")
    assert parsed.parse_ok is True
    assert parsed.ids == ("CONCLUSION_1", "CONCLUSION_2")
