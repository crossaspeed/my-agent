"""结构化输出校验与规则判分单元测试。"""

from __future__ import annotations

from app.agents.grader_graph import grade_objective
from app.agents.validators import validate_drafts, validate_grade
from app.services.grading_service import _value_of


def _single(**kwargs):
    base = {
        "type": "single",
        "stem": "下列关于三次握手的说法哪一项正确？",
        "options": [
            {"key": "A", "text": "用于同步双方初始序号"},
            {"key": "B", "text": "用于加密数据"},
            {"key": "C", "text": "用于分配 IP 地址"},
            {"key": "D", "text": "用于域名解析"},
        ],
        "answer": "A",
        "rubric": [],
        "explanation": "",
        "difficulty": 3,
        "kp_ids": [1],
        "source_refs": [{"chunk_id": 1, "quote": "三次握手用于同步双方初始序号并确认收发能力"}],
    }
    base.update(kwargs)
    return base


def test_valid_single_question_passes():
    valid, invalid = validate_drafts([_single()], 5)
    assert len(valid) == 1 and not invalid


def test_single_without_four_options_rejected():
    valid, invalid = validate_drafts(
        [_single(options=[{"key": "A", "text": "只有一项"}])], 5
    )
    assert not valid
    assert "至少需要 4 个选项" in invalid[0]["reason"]


def test_answer_not_in_options_rejected():
    valid, invalid = validate_drafts([_single(answer="Z")], 5)
    assert not valid
    assert "answer" in invalid[0]["reason"]


def test_multiple_needs_two_answers():
    base = _single(type="multiple", answer=["A"])
    valid, invalid = validate_drafts([base], 5)
    assert not valid
    base["answer"] = ["A", "B"]
    valid, _ = validate_drafts([base], 5)
    assert len(valid) == 1


def test_judge_answer_must_be_bool():
    base = _single(type="judge", options=None, answer="true")
    valid, _ = validate_drafts([base], 5)
    assert valid and valid[0]["answer"] is True
    base["answer"] = "对"
    valid, _ = validate_drafts([base], 5)
    assert valid and valid[0]["answer"] is True


def test_short_question_rubric_scaled_to_score():
    base = _single(
        type="short",
        options=None,
        answer={"key_points": ["a"]},
        rubric=[
            {"point": "同步初始序号", "score": 2, "keywords": ["同步", "序号"]},
            {"point": "确认收发能力", "score": 2, "keywords": ["确认"]},
        ],
    )
    valid, _ = validate_drafts([base], 10)
    assert abs(sum(r["score"] for r in valid[0]["rubric"]) - 10) < 0.01


def test_banned_stem_rejected():
    valid, invalid = validate_drafts([_single(stem="如图所示，下列哪项正确？")], 5)
    assert not valid
    assert "外部上下文" in invalid[0]["reason"]


def test_missing_refs_rejected():
    valid, invalid = validate_drafts([_single(source_refs=[])], 5)
    assert not valid


def test_validate_grade_caps_score():
    data, err = validate_grade(
        {"rubric_detail": [], "score": 999, "feedback": "ok", "error_tags": ["未作答"], "confidence": 0.9},
        10,
    )
    assert err is None
    assert data["score"] == 10


def test_validate_grade_filters_unknown_tags():
    data, _ = validate_grade(
        {"rubric_detail": [], "score": 3, "feedback": "", "error_tags": ["乱写的标签"], "confidence": 0.5},
        10,
    )
    assert data["error_tags"] == []


def test_objective_single_correct():
    result = grade_objective({"type": "single", "answer": "A"}, "a", 5)
    assert result["score"] == 5 and result["is_correct"]


def test_objective_multiple_strict():
    q = {"type": "multiple", "answer": ["A", "C"]}
    assert grade_objective(q, ["A", "C"], 5)["is_correct"]
    assert not grade_objective(q, ["A"], 5)["is_correct"]


def test_objective_empty_answer():
    result = grade_objective({"type": "judge", "answer": True}, None, 5)
    assert result["score"] == 0
    assert result["error_tags"] == ["未作答"]


def test_value_of_dict_wrapper():
    assert _value_of({"value": "A", "flagged": True}) == "A"
    assert _value_of(None) is None
