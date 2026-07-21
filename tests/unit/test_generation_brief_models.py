"""Generation brief form model tests."""

from smeme.qnr.generation.agentic.brief_models import GenerationBriefInput


def _minimal_brief(**overrides):
    base = {
        "title": "Test workflow title",
        "user_prompt": "A" * 25,
    }
    base.update(overrides)
    return GenerationBriefInput.model_validate(base)


def test_confirm_goal_only_coerces_submit_button_value():
    brief = _minimal_brief(confirm_goal_only="on")
    assert brief.confirm_goal_only is True


def test_goal_only_brief_has_no_research_sources_by_default():
    brief = _minimal_brief()
    assert brief.enable_web_search is False
    assert brief.enable_user_materials is False
    assert brief.confirm_goal_only is False


def test_confirm_goal_only_allows_proceeding_without_sources():
    brief = _minimal_brief(confirm_goal_only="on")
    assert not brief.enable_web_search
    assert not brief.enable_user_materials
    assert brief.confirm_goal_only
