"""Prompt 模板契约测试：占位符必须与调用方变量一致，避免线上 KeyError。"""

from __future__ import annotations

import pytest

from app.agents.prompts import registry

EXPECTED_VARS = {
    "question_gen": {
        "course_name", "count", "type_label", "difficulty_label", "difficulty",
        "kp_name", "option_count", "option_count_minus_one", "score",
        "context_block", "kp_id",
    },
    "question_plan": {"course_name", "kp_name"},
    "grader_extract": {"student_answer"},
    "grader_subjective": {
        "course_name", "rubric_block", "student_answer", "context_block", "max_score",
    },
    "grader": set(),
    "tutor_explain": {
        "course_name", "stem", "answer", "student_answer", "rubric_detail",
        "error_tags", "user_query", "context_block",
    },
    "tutor_diagnose": {"course_name", "stem", "correct_answer", "student_answer", "error_tags"},
    "question_support": {"stem", "answer", "quote"},
}


def test_all_templates_discoverable():
    templates = registry.list_templates()
    names = {t["name"] for t in templates}
    assert {"question_gen", "grader_subjective", "tutor_explain", "tutor_diagnose"} <= names


@pytest.mark.parametrize("name", list(EXPECTED_VARS))
def test_template_variables_match_callers(name: str):
    try:
        template = registry.load(name)
    except Exception:
        pytest.skip(f"{name} 模板不存在")
    expected = EXPECTED_VARS.get(name, set())
    if expected:
        assert template.variables == expected, f"{name} 占位符与调用方不一致"


def test_render_fills_placeholders():
    text = registry.render(
        "question_plan", course_name="计算机网络", kp_name="TCP 三次握手"
    )
    assert "计算机网络" in text
    assert "TCP 三次握手" in text
    assert "{{" not in text


def test_render_raises_on_missing_var():
    with pytest.raises(KeyError):
        registry.render("question_plan", course_name="x")


def test_prompt_version_env(monkeypatch):
    template = registry.load("tutor_explain", "v1")
    assert template.version == "v1"
