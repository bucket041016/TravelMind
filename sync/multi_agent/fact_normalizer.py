"""Normalize legacy text/parser output into the Phase 2 fact contracts."""

from __future__ import annotations

import re
from typing import Any

from .contracts import (
    PlaceCandidate,
    RouteFact,
    SourceMeta,
    WeatherFact,
    normalize_point,
    normalize_price_range,
    source_meta,
)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _status(value: Any, default: str = "unknown") -> str:
    text = _text(value).lower()
    if "fixture" in text:
        return "fixture"
    if "error" in text or "失败" in text or "unavailable" in text:
        return "error"
    if "fallback" in text or "降级" in text:
        return "amap_fallback"
    if text in {"live", "success", "used"}:
        return "live"
    return default


def _source_meta_for(
    raw: dict[str, Any],
    *,
    provider: str,
    provider_status: str,
    note: str = "",
) -> SourceMeta:
    existing = raw.get("source_meta") if isinstance(raw.get("source_meta"), dict) else {}
    return source_meta(
        provider=existing.get("provider") or raw.get("source") or provider,
        status=existing.get("status") or _status(provider_status),
        confidence=existing.get("confidence") or raw.get("price_confidence") or "unknown",
        note=existing.get("note") or note,
    )


def normalize_place_candidate(
    raw: dict[str, Any],
    *,
    city: str,
    category: str,
    source: str = "amap_poi",
    provider_status: str = "unknown",
) -> PlaceCandidate:
    """Return a JSON-safe candidate while preserving legacy fields."""

    candidate: dict[str, Any] = dict(raw or {})
    name = _text(candidate.get("name") or candidate.get("title"))
    point = normalize_point(candidate.get("location") or candidate.get("location_point"))
    address = _text(candidate.get("address"))
    has_real_signal = bool(name and (point or address or candidate.get("rating") or candidate.get("type") or candidate.get("photo_url")))
    explicit_real = candidate.get("is_real_place")
    is_real_place = bool(explicit_real) if explicit_real is not None else has_real_signal
    candidate["id"] = _text(candidate.get("id") or candidate.get("candidate_id"))
    candidate["name"] = name
    candidate["city"] = _text(candidate.get("city") or city)
    candidate["category"] = category
    candidate["address"] = address
    candidate["location"] = point
    candidate["is_real_place"] = is_real_place
    candidate["is_suggestion"] = bool(candidate.get("is_suggestion")) or not is_real_place
    candidate["source"] = _text(candidate.get("source") or candidate.get("place_source") or source) or source
    candidate["source_meta"] = _source_meta_for(
        candidate,
        provider=candidate["source"],
        provider_status=provider_status,
        note="事实字段由兼容解析器归一化；供应商实时状态仍需核实。",
    )

    price_range = normalize_price_range(
        candidate.get("price_range")
        or candidate.get("cost_estimate")
        or candidate.get("cost"),
        default_unit="night" if category == "hotel" else "person",
    )
    if price_range:
        candidate["price_range"] = price_range

    errors: list[str] = []
    if not name:
        errors.append("missing_name")
    if not point:
        errors.append("missing_coordinates")
    if not address:
        errors.append("missing_address")
    candidate["validation"] = {
        "status": "invalid" if "missing_name" in errors else ("partial" if errors else "valid"),
        "errors": errors,
    }
    return candidate  # type: ignore[return-value]


def normalize_place_candidates(
    raw_items: list[dict[str, Any]] | None,
    *,
    city: str,
    category: str,
    source: str = "amap_poi",
    provider_status: str = "unknown",
) -> list[PlaceCandidate]:
    return [
        normalize_place_candidate(
            item,
            city=city,
            category=category,
            source=source,
            provider_status=provider_status,
        )
        for item in raw_items or []
        if isinstance(item, dict)
    ]


def normalize_route_fact(
    raw: Any,
    *,
    origin: str = "",
    destination: str = "",
    mode: str = "",
    source: str = "amap_route",
    provider_status: str = "unknown",
) -> RouteFact:
    if isinstance(raw, dict):
        summary = _text(raw.get("summary") or raw.get("raw"))
        distance = raw.get("distance_km")
        duration = raw.get("duration_minutes")
        price = raw.get("price")
    else:
        summary = _text(raw)
        distance = None
        duration = None
        price = None

    if distance is None:
        match = re.search(r"(?:(?:距离|全程)\s*(?:约\s*)?)?(\d+(?:\.\d+)?)\s*(?:km|公里)", summary, re.I)
        distance = float(match.group(1)) if match else None
    if duration is None:
        hour = re.search(r"(\d+)\s*小时", summary)
        minute = re.search(r"(\d+)\s*分钟", summary)
        duration = (int(hour.group(1)) * 60 if hour else 0) + (int(minute.group(1)) if minute else 0)
        if duration == 0:
            duration = None
    if price is None:
        match = re.search(r"(?:票价|过路费|费用)约\s*(\d+(?:\.\d+)?)\s*元", summary)
        price = float(match.group(1)) if match else None

    status = _status(provider_status or summary)
    return {
        "origin": _text(origin),
        "destination": _text(destination),
        "mode": _text(mode),
        "distance_km": distance,
        "duration_minutes": duration,
        "price": price,
        "currency": "CNY",
        "summary": summary,
        "status": status,
        "source": source,
        "source_meta": source_meta(
            provider=source,
            status=status,
            confidence="medium" if status in {"live", "fixture"} else "low",
            note="路线事实仍可能是摘要或规则估算。",
        ),
        "raw": summary,
    }


def normalize_weather_fact(
    raw: Any,
    *,
    city: str,
    date: str = "",
    source: str = "weather",
    provider_status: str = "unknown",
) -> WeatherFact:
    if isinstance(raw, dict):
        summary = _text(raw.get("summary") or raw.get("raw") or raw.get("condition"))
        condition = _text(raw.get("condition"))
        min_temp = raw.get("min_temp_c")
        max_temp = raw.get("max_temp_c")
        rain_probability = raw.get("rain_probability")
        wind_level = raw.get("wind_level")
    else:
        summary = _text(raw)
        condition = ""
        min_temp = max_temp = rain_probability = wind_level = None

    temp_match = re.search(r"(-?\d+(?:\.\d+)?)\s*[~至到-]\s*(-?\d+(?:\.\d+)?)\s*°?C", summary, re.I)
    if temp_match:
        min_temp = float(temp_match.group(1)) if min_temp is None else min_temp
        max_temp = float(temp_match.group(2)) if max_temp is None else max_temp
    if rain_probability is None:
        match = re.search(r"降水概率\s*(\d+(?:\.\d+)?)\s*%", summary)
        rain_probability = float(match.group(1)) if match else None
    if wind_level is None:
        match = re.search(r"风力\s*(\d+(?:\.\d+)?)\s*级", summary)
        wind_level = float(match.group(1)) if match else None
    if not condition:
        condition = summary.split("：", 1)[-1].split("，", 1)[0].strip() if summary else ""

    status = _status(provider_status or source)
    return {
        "city": _text(city),
        "date": _text(date),
        "summary": summary,
        "condition": condition,
        "min_temp_c": min_temp,
        "max_temp_c": max_temp,
        "rain_probability": rain_probability,
        "wind_level": wind_level,
        "source": source,
        "source_meta": source_meta(
            provider=source,
            status=status,
            confidence="medium" if summary and status != "error" else "low",
            note="天气是查询时点快照，出发前需再次核实。",
        ),
        "raw": summary,
    }
