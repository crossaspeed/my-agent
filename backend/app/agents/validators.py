"""结构化输出校验与修复（Pydantic 严格模式）。

Agent 输出必须过这一层才能入库：非法输出被准确拦截并给出可回灌的失败原因。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

ERROR_TAGS = ["概念混淆", "遗漏前提", "表述不全", "张冠李戴", "逻辑错误", "计算失误", "未作答"]
BANNED_STEM = ("如图所示", "上题中", "本课件中", "上一题", "下图")


class OptionIn(BaseModel):
    key: str = Field(min_length=1, max_length=4)
    text: str = Field(min_length=1, max_length=300)


class SourceRefIn(BaseModel):
    chunk_id: int
    quote: str = Field(min_length=10, max_length=400)


class RubricItemIn(BaseModel):
    point: str = Field(min_length=2)
    score: float = Field(ge=0, le=100)
    keywords: list[str] = Field(default_factory=list)

    @field_validator("keywords", mode="before")
    @classmethod
    def _ensure_list(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return [str(x) for x in v]


class DraftQuestionIn(BaseModel):
    type: Literal["single", "multiple", "judge", "short", "essay"]
    stem: str = Field(min_length=8, max_length=2000)
    options: list[OptionIn] | None = None
    answer: Any = None
    rubric: list[RubricItemIn] = Field(default_factory=list)
    explanation: str = ""
    difficulty: int = Field(default=3, ge=1, le=5)
    kp_ids: list[int] = Field(default_factory=list)
    source_refs: list[SourceRefIn] = Field(default_factory=list)

    @field_validator("stem")
    @classmethod
    def _check_stem(cls, v: str) -> str:
        for banned in BANNED_STEM:
            if banned in v:
                raise ValueError(f"题干不得依赖外部上下文（出现「{banned}」）")
        return v.strip()

    @model_validator(mode="after")
    def _check_by_type(self) -> DraftQuestionIn:
        keys: set[str] = set()
        if self.type in ("single", "multiple"):
            if not self.options or len(self.options) < 4:
                raise ValueError("选择题至少需要 4 个选项")
            keys = {o.key for o in self.options}
            if len(keys) != len(self.options):
                raise ValueError("选项 key 重复")
            for opt in self.options:
                if opt.text.strip() in ("以上都对", "以上都不对", "都不对", "都对"):
                    raise ValueError("禁止使用「以上都对/都不对」类无效选项")
        if self.type == "single":
            if not isinstance(self.answer, str) or self.answer not in keys:
                raise ValueError("单选题 answer 必须是某个选项 key")
        elif self.type == "multiple":
            if not isinstance(self.answer, list) or len(self.answer) < 2:
                raise ValueError("多选题 answer 至少包含 2 个选项")
            if not set(map(str, self.answer)).issubset(keys):
                raise ValueError("多选题 answer 含非法选项 key")
        elif self.type == "judge":
            if not isinstance(self.answer, bool):
                raise ValueError("判断题 answer 必须是布尔值")
        else:
            if len(self.rubric) < 2:
                raise ValueError("主观题必须提供至少 2 个评分点")
            total = round(sum(r.score for r in self.rubric), 2)
            if total <= 0:
                raise ValueError("评分点分值之和必须大于 0")
        if not self.source_refs:
            raise ValueError("缺少溯源（source_refs 至少 1 条）")
        return self


class RubricDetailIn(BaseModel):
    point: str
    hit: Literal["hit", "partial", "miss"] = "miss"
    score: float = Field(default=0, ge=0)
    evidence: str = ""


class GradeOutputIn(BaseModel):
    rubric_detail: list[RubricDetailIn] = Field(default_factory=list)
    score: float = Field(default=0, ge=0)
    feedback: str = ""
    error_tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0, le=1)

    @field_validator("error_tags")
    @classmethod
    def _check_tags(cls, v: list[str]) -> list[str]:
        return [t for t in v if t in ERROR_TAGS][:3]


def _normalize_answer(data: dict[str, Any]) -> dict[str, Any]:
    """兼容模型常见偏差：判断题用 "true"/"对"、选项用 list[{"A": "..."}] 等。"""
    out = dict(data)
    if out.get("type") == "judge":
        ans = out.get("answer")
        if isinstance(ans, str):
            out["answer"] = ans.strip().lower() in ("true", "t", "对", "正确", "yes", "1")
    if isinstance(out.get("options"), list):
        fixed = []
        for i, opt in enumerate(out["options"]):
            if isinstance(opt, dict) and "key" in opt and "text" in opt:
                fixed.append(opt)
            elif isinstance(opt, dict):
                key, text = next(iter(opt.items()))
                fixed.append({"key": str(key), "text": str(text)})
            elif isinstance(opt, str):
                fixed.append({"key": chr(65 + i), "text": opt})
        out["options"] = fixed
    if isinstance(out.get("kp_ids"), int):
        out["kp_ids"] = [out["kp_ids"]]
    if isinstance(out.get("rubric"), dict):
        out["rubric"] = [out["rubric"]]
    return out


def validate_drafts(
    raw_items: list[dict[str, Any]], score_per_question: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """返回 (合法草稿, 非法草稿+原因)。主观题分值总和按题分归一。"""
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            invalid.append({"index": idx, "raw": raw, "reason": "题目不是 JSON 对象"})
            continue
        data = _normalize_answer(raw)
        try:
            model = DraftQuestionIn(**data)
        except ValidationError as exc:
            reason = "；".join(
                f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:3]
            )
            invalid.append({"index": idx, "raw": raw, "reason": reason or "字段校验失败"})
            continue
        draft = model.model_dump()
        # 主观题分值对齐题分（模型给出的分值之和常与题分不一致）
        if draft["type"] in ("short", "essay") and draft["rubric"]:
            total = sum(r["score"] for r in draft["rubric"]) or 1.0
            ratio = score_per_question / total
            for item in draft["rubric"]:
                item["score"] = round(item["score"] * ratio, 2)
            diff = round(score_per_question - sum(r["score"] for r in draft["rubric"]), 2)
            if abs(diff) > 0:
                draft["rubric"][-1]["score"] = round(draft["rubric"][-1]["score"] + diff, 2)
        valid.append(draft)
    return valid, invalid


def validate_grade(raw: dict[str, Any], max_score: float) -> tuple[dict[str, Any] | None, str | None]:
    try:
        model = GradeOutputIn(**raw)
    except ValidationError as exc:
        return None, "；".join(e["msg"] for e in exc.errors()[:3])
    data = model.model_dump()
    if data["score"] > max_score:
        data["score"] = max_score  # 防 prompt 注入把分数刷满
        data.setdefault("error_tags", [])
    total = round(sum(item["score"] for item in data["rubric_detail"]), 2)
    if data["rubric_detail"] and abs(total - data["score"]) > max(1.0, max_score * 0.2):
        data["score"] = min(total, max_score)
    return data, None
