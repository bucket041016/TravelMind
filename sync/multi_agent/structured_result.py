"""结构化 MCP 返回契约（Phase 2.2/D12）：冻结字段命名，规划器优先消费、正则降级兜底。

MCPToolAdapter 把 FastMCP 结果收敛为稳定封装（MCPToolResult：text/data/source/
validation_error）。本模块定义 POI/酒店结构化返回的 Pydantic 响应模型：
- 规划器经 MCPToolbox.call_structured() 拿到封装后，用 parse_* 尝试解析 data；
- 元素级校验：非法元素被过滤并计数（validation_error 回填到封装上），不拖垮整组合法候选；
- 解析失败（data 不是对应形状）返回 None，调用方回退到 result.text 的正则解析。

PlaceCandidate 只作校验闸门：校验通过的元素保留原始 dict（不做模型往返），
下游 hotel_service 等会原地修改候选字段。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

try:
    from mcp_tools_adapter import MCPToolResult
except ModuleNotFoundError:
    from sync.mcp_tools_adapter import MCPToolResult

# 冻结的 POI 结构化返回字段（search_poi 工具）。
POI_ATTRACTIONS = "attractions"
POI_FOODS = "foods"
POI_SPECIALTY_PLACES = "specialty_places"
POI_GENERIC_FOODS = "generic_foods"
POI_STRUCTURED_KEYS = (POI_ATTRACTIONS, POI_FOODS, POI_SPECIALTY_PLACES, POI_GENERIC_FOODS)

# 冻结的酒店结构化返回字段（search_hotels 工具）。
HOTEL_CANDIDATES = "candidates"
HOTEL_AREA = "area_recommendation"
HOTEL_PROVIDER_STATUS = "provider_status"
HOTEL_STRUCTURED_KEYS = (HOTEL_CANDIDATES, HOTEL_AREA, HOTEL_PROVIDER_STATUS)


class PlaceCandidate(BaseModel):
    """POI/酒店结构化元素的校验闸门：只要求 name 非空白，其余字段透传。"""

    model_config = ConfigDict(extra="allow")

    name: str = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name 不能为空白")
        return value


class POIResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    attractions: list[dict[str, Any]] = Field(default_factory=list)
    foods: list[dict[str, Any]] = Field(default_factory=list)
    specialty_places: list[dict[str, Any]] = Field(default_factory=list)
    generic_foods: list[dict[str, Any]] = Field(default_factory=list)


class HotelResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidates: list[dict[str, Any]] = Field(default_factory=list)
    area_recommendation: str = ""
    provider_status: str = ""


def _filter_place_items(value: Any) -> tuple[list[dict[str, Any]], int]:
    """逐元素校验：非法元素丢弃并计数；合法元素保留原始 dict。"""
    if not isinstance(value, list):
        return [], 0
    kept: list[dict[str, Any]] = []
    dropped = 0
    for item in value:
        if isinstance(item, dict):
            try:
                PlaceCandidate.model_validate(item)
            except ValidationError:
                dropped += 1
                continue
            kept.append(item)
        else:
            dropped += 1
    return kept, dropped


def _append_validation_error(result: Any, message: str) -> None:
    current = getattr(result, "validation_error", None)
    if current is None:
        return
    result.validation_error = f"{current}；{message}" if current else message


def parse_poi_response(result: Any) -> POIResponse | None:
    """把 call_structured() 封装解析为 POI 响应；data 不是 POI 形状时返回 None。"""
    data = getattr(result, "data", None)
    if not isinstance(data, dict) or not any(key in data for key in POI_STRUCTURED_KEYS):
        return None
    fields: dict[str, list[dict[str, Any]]] = {}
    dropped_total = 0
    for key in POI_STRUCTURED_KEYS:
        kept, dropped = _filter_place_items(data.get(key))
        fields[key] = kept
        dropped_total += dropped
    if dropped_total:
        _append_validation_error(result, f"过滤 {dropped_total} 个非法 POI 候选元素")
    return POIResponse(**fields)


def parse_hotel_response(result: Any) -> HotelResponse | None:
    """把 call_structured() 封装解析为酒店响应；data 不是酒店形状时返回 None。"""
    data = getattr(result, "data", None)
    if not isinstance(data, dict) or not any(key in data for key in HOTEL_STRUCTURED_KEYS):
        return None
    kept, dropped = _filter_place_items(data.get(HOTEL_CANDIDATES))
    if dropped:
        _append_validation_error(result, f"过滤 {dropped} 个非法酒店候选元素")
    return HotelResponse(
        candidates=kept,
        area_recommendation=str(data.get(HOTEL_AREA) or ""),
        provider_status=str(data.get(HOTEL_PROVIDER_STATUS) or ""),
    )
