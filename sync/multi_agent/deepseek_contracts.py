"""Pydantic 输出契约：DeepSeek 规划脑的四种结构化输出。

DeepSeek 返回 JSON 后，在边界用 Pydantic 校验并做类型归一化，再以 dict 形式交给
下游（itinerary_builder / hotel_service / local_transport_service / quality_reviewer）。
校验失败会触发带错误回喂的重试，而不是静默降级（见 deepseek_brain._invoke_parsed）。

设计原则（对应 structured-output-validation 技能）：
- 顶层结构（days/prices/decision/各评分）作为硬校验，缺失或类型错误即触发重试；
- 单项字段尽量带默认值 + 类型强转，修复常见的"字段漂移"而不是直接拒绝；
- extra="ignore" 允许模型多给字段，避免新字段破坏兼容；
- 枚举类字段（category/decision/price_confidence 等）在此保持 str，交由下游
  normalizer 统一做枚举兜底，避免在边界过度拒绝导致 fallback 率上升。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _coerce_bool(value: Any) -> Any:
    """把常见的真假写法归一化为 bool，供 is_suggestion / needs_repair 使用。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "on", "是", "真"}:
            return True
        if lowered in {"false", "no", "0", "off", "否", "假", "不是", ""}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return value


def _coerce_day(value: Any) -> Any:
    """把 day 归一化为 int（1.5 -> 1、'2' -> 2），非数值原样返回交由 Pydantic 拒绝。"""
    if value is None or isinstance(value, bool):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


class ItineraryItem(BaseModel):
    """单个行程条目，对应规划 prompt 中的 item schema。"""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(default="", description="展示名称；真实地点须对应候选。")
    candidate_id: str = Field(default="", description="后端候选 id，模型只引用不生成。")
    category: str = Field(default="note", description="activity|food|hotel|transfer|note")
    transport: str = Field(default="", description="移动方式或说明。")
    duration: str = Field(default="", description="预计停留时长文本。")
    detail: str = Field(default="", description="补充说明。")
    is_suggestion: bool = Field(default=False, description="泛化建议而非真实地点。")
    validation_note: str = Field(default="")
    estimated_price_range: str = Field(default="", description="如 '30-80'。")
    price_confidence: str = Field(default="unknown", description="high|medium|low|unknown")
    price_note: str = Field(default="")

    _v_is_suggestion = field_validator("is_suggestion", mode="before")(_coerce_bool)


class DayPlan(BaseModel):
    """某一天的行程。day 缺失时保持 None，由下游 _bounded_int 按顺序补号。"""

    model_config = ConfigDict(extra="ignore")

    day: int | None = Field(default=None, description="第几天，从 1 开始；缺失时下游按顺序补号。")
    theme: str = Field(default="")
    items: list[ItineraryItem] = Field(default_factory=list)

    _v_day = field_validator("day", mode="before")(_coerce_day)


class PlanOutput(BaseModel):
    """plan() 的顶层输出：必须包含 days 列表。"""

    model_config = ConfigDict(extra="ignore")

    days: list[DayPlan] = Field(..., description="逐日行程。")

    @field_validator("days", mode="before")
    @classmethod
    def _require_list(cls, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValueError("days 必须是列表")
        return value


class HotelPriceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    candidate_id: str = Field(default="")
    estimated_price_range: str = Field(default="", description="如 '300-500'。")
    price_confidence: str = Field(default="unknown", description="low|medium|unknown")
    price_note: str = Field(default="")


class HotelPriceOutput(BaseModel):
    """estimate_hotel_prices() 的顶层输出。"""

    model_config = ConfigDict(extra="ignore")

    prices: list[HotelPriceItem] = Field(..., description="酒店价格估算列表。")

    @field_validator("prices", mode="before")
    @classmethod
    def _require_list(cls, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValueError("prices 必须是列表")
        return value


class RouteJudgement(BaseModel):
    """judge_route() 的输出。decision 缺失视为校验失败，触发重试。"""

    model_config = ConfigDict(extra="ignore")

    decision: str = Field(..., description="accept|switch_mode|replace_place|mark_impractical")
    suggested_mode: str = Field(default="", description="taxi|driving|transit|walking|bicycling")
    replacement_candidate_id: str = Field(default="")
    risk_level: str = Field(default="medium", description="low|medium|high")
    judge_reason: str = Field(default="")
    display_summary: str = Field(default="")


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    severity: str = Field(default="medium", description="low|medium|high")
    day: int | None = Field(default=None)
    message: str = Field(default="")
    kind: str = Field(default="logic", description="route|pace|cluster|logic|budget")

    _v_day = field_validator("day", mode="before")(_coerce_day)


class ReviewOutput(BaseModel):
    """review_itinerary() 的输出。五个评分是体检的核心契约，缺失即触发重试。"""

    model_config = ConfigDict(extra="ignore")

    overall_score: float = Field(..., ge=0, le=100, description="0-100")
    route_score: float = Field(..., ge=0, le=100)
    pace_score: float = Field(..., ge=0, le=100)
    cluster_score: float = Field(..., ge=0, le=100)
    logic_score: float = Field(..., ge=0, le=100)
    issues: list[ReviewIssue] = Field(default_factory=list)
    fixes: list[str] = Field(default_factory=list)
    needs_repair: bool = Field(default=False)
    repaired_plan: PlanOutput | None = Field(default=None, description="needs_repair=true 时的返工方案。")

    _v_needs_repair = field_validator("needs_repair", mode="before")(_coerce_bool)

    @model_validator(mode="after")
    def _require_repaired_plan_when_needs_repair(self):
        if self.needs_repair and self.repaired_plan is None:
            raise ValueError("needs_repair=true 时必须提供 repaired_plan")
        return self


# 方法名 -> 对应输出契约，供 deepseek_brain._parse_json_object 统一按模型解析。
MODEL_BY_METHOD: dict[str, type[BaseModel]] = {
    "plan": PlanOutput,
    "estimate_hotel_prices": HotelPriceOutput,
    "judge_route": RouteJudgement,
    "review_itinerary": ReviewOutput,
}
