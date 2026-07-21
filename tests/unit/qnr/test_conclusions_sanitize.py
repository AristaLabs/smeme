"""Tests for LLM conclusion extraction sanitization."""

from smeme.qnr.generation.agentic.conclusions_sanitize import sanitize_extracted_conclusions

_SAMPLE_BLOCK = """**CONCLUSION_1: Form an LLC**

**Summary**: LLC fits your situation.

**When this applies**: Small business, wants liability protection

**Key recommendations**:
1. File articles of organization
2. Create an operating agreement

**Severity**: info"""


def test_strips_trailing_offer_after_hrule() -> None:
    raw = f"""---

{_SAMPLE_BLOCK}

---

If you want, I can also convert these into a **decision tree / questionnaire flowchart** with yes/no branches."""
    out = sanitize_extracted_conclusions(raw)
    assert "If you want" not in out
    assert "**CONCLUSION_1:" in out
    assert "Form an LLC" in out


def test_keeps_multiple_conclusion_blocks() -> None:
    raw = f"""---

{_SAMPLE_BLOCK}

---

**CONCLUSION_2: Stay Sole Proprietor**

**Summary**: Simplicity wins.

**When this applies**: Low risk, no employees

**Key recommendations**:
1. Track expenses

**Severity**: warning

---

Would you like me to diagram this as a flowchart?"""
    out = sanitize_extracted_conclusions(raw)
    assert "CONCLUSION_1" in out
    assert "CONCLUSION_2" in out
    assert "flowchart" not in out


def test_strips_inline_assistant_tail_without_hrule() -> None:
    raw = f"""{_SAMPLE_BLOCK}

If you want, I can also convert these into a decision tree."""
    out = sanitize_extracted_conclusions(raw)
    assert out == _SAMPLE_BLOCK


def test_passthrough_when_no_conclusion_markers() -> None:
    text = "⚠️ LLM unavailable\n\nPlease provide conclusions manually."
    assert sanitize_extracted_conclusions(text) == text
