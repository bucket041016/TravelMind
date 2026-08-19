"""Runtime-light JSON contracts shared by fact normalization and ranking.

The current MCP server still returns text. These TypedDicts describe the
stable shape the planner can use after normalization without changing the
supplier protocol yet.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal, TypedDict


SourceStatus = Literal[
    "live",
    "amap_fallback",
    "rule_fallback",
    "fixture",
    "error",
    "unknown",
]
SourceKind = Literal[
    "amap",
    "wttr",
    "knowledge_base",
    "rule",
    "ai",
    "fixture",
    "unknown",
]


class LocationPoint(TypedDict):
    lng: float
    lat: float


class PriceRange(TypedDict, total=False):
    min: float
    max: float
    currency: str
    unit: str


class SourceMeta(TypedDict, total=False):
    provider: str
    status: SourceStatus
    kind: SourceKind
    confidence: Literal["high", "medium", "low", "unknown"]
    note: str


class PlaceCandidate(TypedDict, total=False):
    id: str
    name: str
    city: str
    category: Literal["activity", "food", "hotel"]
    type: str
    description: str
    address: str
    location: LocationPoint | None
    rating: float | None
    cost: float | None
    cost_estimate: float | None
    cost_source: str
    price_range: PriceRange | None
    price_confidence: Literal["high", "medium", "low", "unknown"]
    cost_note: str
    price_note: str
    photo_url: str
    source: str
    source_meta: SourceMeta
    is_real_place: bool
    is_suggestion: bool
    validation: dict[str, Any]
    selection: dict[str, Any]
    cluster_id: str
    cluster_name: str
    nearby_anchor: str


class HotelCandidate(PlaceCandidate, total=False):
    category: Literal["hotel"]
    hotel_level: str
    match_reason: str


class RouteFact(TypedDict, total=False):
    origin: str
    destination: str
    mode: str
    distance_km: float | None
    duration_minutes: int | None
    price: float | None
    currency: str
    summary: str
    status: str
    source: str
    source_meta: SourceMeta
    raw: str


class WeatherFact(TypedDict, total=False):
    city: str
    date: str
    summary: str
    condition: str
    min_temp_c: float | None
    max_temp_c: float | None
    rain_probability: float | None
    wind_level: float | None
    source: str
    source_meta: SourceMeta
    raw: str


SOURCE_KIND_BY_PROVIDER: dict[str, SourceKind] = {
    "amap": "amap",
    "amap_poi": "amap",
    "amap_route": "amap",
    "amap_weather": "amap",
    "hotel_poi": "amap",
    "amap_hotel": "amap",
    "wttr": "wttr",
    "knowledge_base": "knowledge_base",
    "rule_fallback": "rule",
    "category_rule": "rule",
    "ai_price_range": "ai",
    "fixture": "fixture",
}


def normalize_point(value: Any) -> LocationPoint | None:
    """Return a finite WGS84-like point, or ``None`` for unusable data."""

    if isinstance(value, dict):
        lng_value = value.get("lng")
        lat_value = value.get("lat")
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        lng_value, lat_value = value[0], value[1]
    elif isinstance(value, str):
        match = re.search(r"(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)", value)
        if not match:
            return None
        lng_value, lat_value = match.groups()
    else:
        return None

    try:
        lng = float(lng_value)
        lat = float(lat_value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lng) or not math.isfinite(lat):
        return None
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        return None
    return {"lng": lng, "lat": lat}


def normalize_price_range(value: Any, *, default_unit: str = "person") -> PriceRange | None:
    if isinstance(value, dict):
        low = value.get("min")
        high = value.get("max")
        currency = str(value.get("currency") or "CNY")
        unit = str(value.get("unit") or default_unit)
    else:
        numbers = re.findall(r"\d+(?:\.\d+)?", str(value or ""))
        if not numbers:
            return None
        low = numbers[0]
        high = numbers[-1]
        currency = "CNY"
        unit = default_unit
    try:
        low_value = float(low)
        high_value = float(high)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(low_value) or not math.isfinite(high_value):
        return None
    low_value, high_value = sorted((max(0.0, low_value), max(0.0, high_value)))
    return {
        "min": low_value,
        "max": high_value,
        "currency": currency,
        "unit": unit,
    }


def source_kind(provider: Any, fallback: SourceKind = "unknown") -> SourceKind:
    value = str(provider or "").strip().lower()
    if value in SOURCE_KIND_BY_PROVIDER:
        return SOURCE_KIND_BY_PROVIDER[value]
    if "amap" in value or "高德" in value:
        return "amap"
    if "weather" in value or "天气" in value:
        return "wttr"
    return fallback


def source_meta(
    *,
    provider: Any = "",
    status: Any = "unknown",
    confidence: Any = "unknown",
    note: Any = "",
) -> SourceMeta:
    status_value = str(status or "unknown").strip()
    if status_value not in {"live", "amap_fallback", "rule_fallback", "fixture", "error", "unknown"}:
        status_value = "unknown"
    confidence_value = str(confidence or "unknown").strip()
    if confidence_value not in {"high", "medium", "low", "unknown"}:
        confidence_value = "unknown"
    provider_value = str(provider or "unknown").strip() or "unknown"
    return {
        "provider": provider_value,
        "status": status_value,  # type: ignore[typeddict-item]
        "kind": source_kind(provider_value),  # type: ignore[typeddict-item]
        "confidence": confidence_value,  # type: ignore[typeddict-item]
        "note": str(note or "").strip(),
    }


def _slug(value: Any) -> str:
    """归一化为 id 片段：小写、去空白与标点，保留中英文数字与连字符。"""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "-", str(value or "").strip().lower()).strip("-")


def stable_place_id(*, name: str = "", location: LocationPoint | None = None) -> str:
    """确定性候选 id：同一地点（名字+坐标）永远得到同一个 id。

    坐标是地点的全局唯一身份，名字用于无坐标时的可读兜底。该 id 只由后端
    生成，模型只引用、永不生成；后端可用名字/坐标回溯重算完成回填匹配。
    """
    parts = [_slug(name)]
    if location and location.get("lng") is not None and location.get("lat") is not None:
        try:
            parts.append(f"{float(location['lng']):.5f}")
            parts.append(f"{float(location['lat']):.5f}")
        except (TypeError, ValueError):
            pass
    return "-".join(part for part in parts if part)


def candidate_key(candidate: dict[str, Any]) -> str:
    """Build a stable identity key for duplicate filtering."""

    candidate_id = str(candidate.get("id") or candidate.get("candidate_id") or "").strip()
    if candidate_id:
        return f"id:{candidate_id}"
    point = normalize_point(candidate.get("location"))
    if point:
        return f"point:{point['lng']:.5f},{point['lat']:.5f}"
    name = re.sub(r"[\s·,，:：；;（）()]+", "", str(candidate.get("name") or "").strip())
    return f"name:{name}" if name else ""


def validate_place_candidate(
    candidate: dict[str, Any],
    *,
    expected_city: str = "",
    require_coordinates: bool = False,
    require_real_place: bool = False,
) -> list[str]:
    errors: list[str] = []
    name = str(candidate.get("name") or "").strip()
    if not name:
        errors.append("missing_name")
    point = normalize_point(candidate.get("location"))
    if require_coordinates and not point:
        errors.append("missing_coordinates")
    if expected_city and candidate.get("city") and str(candidate["city"]).strip() != expected_city:
        errors.append("city_mismatch")
    if require_real_place and not candidate.get("is_real_place"):
        errors.append("not_real_place")
    return errors
