"""TravelMind 目的地内交通与路线评审。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable
import math
import os
import re

from .constants import (
    MODE_LABELS,
)
from .text_parser import (
    _compact,
    _format_minutes,
    _normalize_point,
    _parse_local_distance_km,
    _parse_local_duration,
    _parse_local_duration_minutes,
    _section_summary,
)

def _fallback_cost_for_category(category: str) -> int:
    return {"food": 80, "activity": 0, "hotel": 0, "transfer": 0}.get(category, 0)

def _timeline_item(*args, **kwargs):
    """延迟导入 itinerary_builder._timeline_item，打破循环引用。"""
    from .itinerary_builder import _timeline_item as _real_timeline_item
    return _real_timeline_item(*args, **kwargs)


def _poi_key(poi: dict) -> str:
    import re as _re
    name = str(poi.get("name") or "").strip()
    key = _re.sub(r"[\s\xb7,\uff0c:\uff1a\uff1b;\uff08\uff09()]+", "", name)
    for suffix in ["体育公园", "森林公园", "湿地公园", "风景名胜区", "风景区", "景区", "公园"]:
        if len(key) > len(suffix) + 1 and key.endswith(suffix):
            key = key[: -len(suffix)]
            break
    return key or str(poi.get("id") or "").strip()


def _dedupe_pois(items: list | None) -> list:
    deduped = []
    seen = set()
    for item in items or []:
        if not item.get("name"):
            continue
        if not (item.get("location") or item.get("address") or item.get("rating") or item.get("type") or item.get("photo_url")):
            continue
        key = _poi_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _default_hotel_area(prefs: dict) -> str:
    return f"建议住在{prefs['destinationCity']}核心商圈、地铁枢纽或第一天重点景点附近，减少换乘和搬运行李。"


def _build_local_transport(prefs: dict[str, Any], routes: dict[str, Any], hotels: dict[str, Any]) -> dict[str, Any]:
    modes = prefs["localModes"]
    recommended = _ordered_local_modes_for_preferences(modes, prefs)
    notes = []
    if "transit" in modes:
        notes.append("公共交通适合覆盖主城区景点，优先选择地铁可达的酒店和景点组合。")
    if "taxi" in modes:
        notes.append("打车适合车站/机场到酒店、夜间返程和跨区移动，预算需预留弹性。")
    if "walking" in modes:
        notes.append("步行适合商圈、老街和相邻景点之间的短距离接驳。")
    if "bicycling" in modes:
        notes.append("骑行适合滨水、绿道和景区外围路线，雨天或高温时不建议强行安排。")
    if "driving" in modes:
        notes.append("目的地自驾适合郊区景点和多人同行，但要提前确认停车条件。")
    notes.append(f"住宿建议参考：{hotels.get('area_recommendation', _default_hotel_area(prefs))}")
    return {
        "recommended_modes": recommended,
        "notes": notes,
        "route_context": routes.get("recommended", "rail"),
    }

def _ordered_local_modes_for_preferences(modes: list[str], prefs: dict[str, Any]) -> list[str]:
    available = list(dict.fromkeys(modes or []))
    profile = prefs.get("preferenceProfile") or {}
    hints = " ".join(profile.get("learnedHints") or [])
    prefer_less_transit = profile.get("pace") == "轻松" or any(keyword in hints for keyword in ["少公交", "别太赶", "轻松", "不去太远"])
    if prefer_less_transit:
        order = ["walking", "taxi", "driving", "transit", "bicycling"]
    else:
        order = ["walking", "bicycling", "transit", "taxi", "driving"]
    ordered = [mode for mode in order if mode in available]
    return ordered or available

def _build_local_transport_segments(
    prefs: dict[str, Any],
    local_transport: dict[str, Any],
    itinerary_days: list[dict[str, Any]],
    pois: dict[str, Any] | None = None,
    *,
    toolbox=None,
    deepseek_brain=None,
) -> dict[str, Any]:
    enriched = {
        "recommended_modes": list(local_transport.get("recommended_modes") or prefs.get("localModes") or []),
        "notes": list(local_transport.get("notes") or []),
        "route_context": local_transport.get("route_context", ""),
        "segments": [],
    }
    query_limit = _local_route_query_limit()
    route_queries = 0
    used_place_keys = _itinerary_used_place_keys(itinerary_days)

    for day in itinerary_days:
        for item in day.get("items", []):
            item.pop("arrival_transport_segment", None)

        places = [place for place in (_segment_place(item) for item in day.get("items", [])) if place]
        for previous, current in zip(places, places[1:]):
            distance_km = _point_distance_km(previous["point"], current["point"])
            mode = _select_local_segment_mode(enriched["recommended_modes"], distance_km)
            segment, route_queries = _local_segment_for_mode(
                prefs,
                day.get("day"),
                previous,
                current,
                mode,
                distance_km,
                route_queries,
                query_limit,
                toolbox=toolbox,
            )
            replacement_candidates = _replacement_candidates_for_segment(
                pois or {},
                current["item"],
                used_place_keys,
                previous["point"],
            )
            judgement = _judge_local_segment(
                prefs,
                day,
                previous,
                current,
                segment,
                enriched["recommended_modes"],
                replacement_candidates,
                deepseek_brain=deepseek_brain,
            )
            segment, route_queries = _apply_local_route_judgement(
                prefs,
                day.get("day"),
                previous,
                current,
                segment,
                judgement,
                replacement_candidates,
                enriched["recommended_modes"],
                used_place_keys,
                route_queries,
                query_limit,
                toolbox=toolbox,
            )

            enriched["segments"].append(segment)
            current["item"]["arrival_transport_segment"] = _public_item_segment(segment)

    if enriched["segments"]:
        enriched["notes"].append("目的地内路线按最终每日行程相邻真实地点生成；打车费用为距离规则估算，不代表实时叫车价格。")
    else:
        enriched["notes"].append("当前真实可定位相邻地点不足，目的地内路线将在重新规划后补充。")
    return enriched

def _local_route_query_limit() -> int:
    try:
        return max(0, min(int(os.getenv("TRAVELMIND_LOCAL_ROUTE_QUERY_LIMIT", "8")), 20))
    except ValueError:
        return 8

def _local_segment_for_mode(
    prefs: dict[str, Any],
    day_number: Any,
    previous: dict[str, Any],
    current: dict[str, Any],
    mode: str,
    distance_km: float,
    route_queries: int,
    query_limit: int,
    *,
    toolbox=None,
) -> tuple[dict[str, Any], int]:
    if mode == "taxi":
        return _rule_local_segment(day_number, previous, current, mode, distance_km, "estimated"), route_queries
    if route_queries < query_limit:
        return _amap_local_segment(prefs, day_number, previous, current, mode, distance_km, toolbox=toolbox), route_queries + 1
    return _rule_local_segment(day_number, previous, current, mode, distance_km, "limited"), route_queries

def _judge_local_segment(
    prefs: dict[str, Any],
    day: dict[str, Any],
    previous: dict[str, Any],
    current: dict[str, Any],
    segment: dict[str, Any],
    modes: list[str],
    replacement_candidates: list[dict[str, Any]],
    *,
    deepseek_brain=None,
) -> dict[str, Any]:
    rule_judgement = _rule_route_judgement(segment, modes)
    if deepseek_brain is None:
        return rule_judgement
    payload = {
        "preferences": {
            "destination_city": prefs.get("destinationCity"),
            "travelers": prefs.get("travelers"),
            "budget": prefs.get("budget"),
            "local_modes": modes,
            "interests": prefs.get("interests", []),
        },
        "day": {"day": day.get("day"), "theme": day.get("theme", "")},
        "from": {
            "title": previous["item"].get("title", ""),
            "detail": previous["detail"],
            "category": previous["item"].get("category", ""),
        },
        "to": {
            "title": current["item"].get("title", ""),
            "detail": current["detail"],
            "category": current["item"].get("category", ""),
        },
        "route_fact": {
            "mode": segment.get("mode"),
            "duration": segment.get("duration"),
            "duration_minutes": _local_duration_minutes(segment),
            "distance": segment.get("distance"),
            "distance_km": segment.get("distance_km"),
            "price": segment.get("price"),
            "summary": _compact(segment.get("summary", ""), 420),
            "source": segment.get("source"),
            "status": segment.get("status"),
        },
        "replacement_candidates": [
            {
                "candidate_id": item["candidate_id"],
                "name": item["name"],
                "category": item["category"],
                "address": item.get("address", ""),
                "distance_from_previous_km": item.get("distance_from_previous_km"),
                "type": item.get("type", ""),
            }
            for item in replacement_candidates[:6]
        ],
        "constraints": [
            "只基于 route_fact 和 replacement_candidates 判断，不编造路线事实",
            "replacement_candidate_id 必须来自 replacement_candidates",
            "打车价格不是实时价格，只能作为距离规则估算展示",
        ],
    }
    result = deepseek_brain.judge_route(payload)
    if result.get("llm_status") != "used":
        return rule_judgement

    judgement = _normalize_route_judgement(result.get("judgement"), "deepseek")
    if judgement["decision"] == "accept" and rule_judgement["decision"] != "accept":
        rule_judgement["judge_reason"] = f"安全兜底：{rule_judgement['judge_reason']}"
        return rule_judgement
    return judgement

def _apply_local_route_judgement(
    prefs: dict[str, Any],
    day_number: Any,
    previous: dict[str, Any],
    current: dict[str, Any],
    segment: dict[str, Any],
    judgement: dict[str, Any],
    replacement_candidates: list[dict[str, Any]],
    modes: list[str],
    used_place_keys: set[str],
    route_queries: int,
    query_limit: int,
    *,
    toolbox=None,
) -> tuple[dict[str, Any], int]:
    decision = judgement.get("decision")
    if decision == "replace_place":
        replacement = _validated_replacement_candidate(judgement, replacement_candidates, current, previous, used_place_keys)
        if replacement:
            _replace_segment_item(day_number, current, replacement)
            replacement_key = _poi_key(replacement)
            if replacement_key:
                used_place_keys.add(replacement_key)
            replacement_id = str(replacement.get("id") or "")
            if replacement_id:
                used_place_keys.add(replacement_id)
            distance_km = _point_distance_km(previous["point"], current["point"])
            mode = _select_local_segment_mode(modes, distance_km)
            segment, route_queries = _local_segment_for_mode(
                prefs,
                day_number,
                previous,
                current,
                mode,
                distance_km,
                route_queries,
                query_limit,
                toolbox=toolbox,
            )
            return _annotate_route_judgement(segment, judgement), route_queries
        judgement = {
            **judgement,
            "decision": "mark_impractical",
            "risk_level": "high",
            "judge_reason": judgement.get("judge_reason") or "建议替换景点，但未找到可验证的同类近距离候选。",
        }

    if decision == "switch_mode":
        switch_mode = _switch_mode_from_judgement(judgement, modes)
        distance_km = _point_distance_km(previous["point"], current["point"])
        switched, route_queries = _local_segment_for_mode(
            prefs,
            day_number,
            previous,
            current,
            switch_mode,
            distance_km,
            route_queries,
            query_limit,
            toolbox=toolbox,
        )
        switched["status"] = "mode_switched"
        switched["warning"] = judgement.get("judge_reason") or f"原路线体验不佳，已改为{MODE_LABELS.get(switch_mode, switch_mode)}估算。"
        return _annotate_route_judgement(switched, judgement), route_queries

    if decision == "mark_impractical":
        return _impractical_local_segment(day_number, previous, current, segment, judgement), route_queries

    return _annotate_route_judgement(segment, judgement), route_queries

def _rule_route_judgement(segment: dict[str, Any], modes: list[str]) -> dict[str, Any]:
    mode = str(segment.get("mode") or "")
    distance_km = float(segment.get("distance_km") or 0)
    duration_minutes = _local_duration_minutes(segment)
    has_private_mode = "taxi" in modes or "driving" in modes
    too_long_transit = mode == "transit" and (duration_minutes > 90 or distance_km > 35)
    very_far = distance_km > 60
    if too_long_transit or very_far:
        reason_parts = []
        if duration_minutes:
            reason_parts.append(f"耗时约 {_format_minutes(duration_minutes)}")
        if distance_km:
            reason_parts.append(f"距离约 {_format_local_distance(distance_km)}")
        reason = "、".join(reason_parts) or "距离/耗时过长"
        if has_private_mode and not very_far:
            return {
                "decision": "switch_mode",
                "suggested_mode": "taxi" if "taxi" in modes else "driving",
                "replacement_candidate_id": "",
                "risk_level": "medium",
                "judge_reason": f"规则兜底：公共交通{reason}，不适合作为旅行中相邻移动，已改用更省时方式估算。",
                "display_summary": "",
                "judge_source": "rule_fallback",
            }
        return {
            "decision": "mark_impractical",
            "suggested_mode": "",
            "replacement_candidate_id": "",
            "risk_level": "high",
            "judge_reason": f"规则兜底：该段{reason}，不建议作为同一天相邻行程，建议替换或重排景点。",
            "display_summary": "",
            "judge_source": "rule_fallback",
        }
    return {
        "decision": "accept",
        "suggested_mode": mode,
        "replacement_candidate_id": "",
        "risk_level": "low",
        "judge_reason": "路线距离和耗时在可接受范围内。",
        "display_summary": "",
        "judge_source": "rule_fallback",
    }

def _normalize_route_judgement(value: Any, source: str) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    decision = str(raw.get("decision") or "accept").strip()
    if decision not in {"accept", "switch_mode", "replace_place", "mark_impractical"}:
        decision = "accept"
    suggested_mode = str(raw.get("suggested_mode") or "").strip()
    if suggested_mode not in {"taxi", "driving", "transit", "walking", "bicycling"}:
        suggested_mode = ""
    risk = str(raw.get("risk_level") or "medium").strip().lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"
    return {
        "decision": decision,
        "suggested_mode": suggested_mode,
        "replacement_candidate_id": str(raw.get("replacement_candidate_id") or "").strip(),
        "risk_level": risk,
        "judge_reason": str(raw.get("judge_reason") or raw.get("reason") or "").strip(),
        "display_summary": str(raw.get("display_summary") or "").strip(),
        "judge_source": source,
    }

def _annotate_route_judgement(segment: dict[str, Any], judgement: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(segment)
    annotated["judge_source"] = judgement.get("judge_source", "rule_fallback")
    annotated["judge_decision"] = judgement.get("decision", "accept")
    annotated["risk_level"] = judgement.get("risk_level", "low")
    annotated["judge_reason"] = judgement.get("judge_reason", "")
    annotated["replacement_candidate_id"] = judgement.get("replacement_candidate_id", "")
    if judgement.get("display_summary"):
        annotated["summary"] = judgement["display_summary"]
    return annotated

def _impractical_local_segment(
    day_number: Any,
    previous: dict[str, Any],
    current: dict[str, Any],
    base_segment: dict[str, Any],
    judgement: dict[str, Any],
) -> dict[str, Any]:
    reason = judgement.get("judge_reason") or "路线距离或耗时过长，建议替换或重排景点。"
    segment = {
        **base_segment,
        "day": day_number,
        "from_detail": previous["detail"],
        "to_detail": current["detail"],
        "from_item_id": previous["item"].get("id", ""),
        "to_item_id": current["item"].get("id", ""),
        "price": "建议重排，不估算",
        "cost_estimate": 0,
        "cost_unit": "party",
        "status": "impractical",
        "warning": reason,
        "summary": f"路线待重新规划：{reason}",
    }
    return _annotate_route_judgement(segment, {**judgement, "decision": "mark_impractical", "risk_level": "high"})

def _switch_mode_from_judgement(judgement: dict[str, Any], modes: list[str]) -> str:
    suggested = str(judgement.get("suggested_mode") or "")
    if suggested in {"taxi", "driving"}:
        return suggested
    if "taxi" in modes:
        return "taxi"
    if "driving" in modes:
        return "driving"
    return "taxi"

def _replacement_candidates_for_segment(
    pois: dict[str, Any],
    current_item: dict[str, Any],
    used_place_keys: set[str],
    previous_point: dict[str, float],
) -> list[dict[str, Any]]:
    category = current_item.get("category")
    if category == "activity":
        pool = _dedupe_pois([*(pois.get("attractions") or []), *(pois.get("specialty_places") or [])])
    elif category == "food":
        pool = _dedupe_pois(pois.get("foods"))
    else:
        return []

    candidates = []
    current_id = str(current_item.get("poi_id") or "")
    for poi in pool:
        poi_id = str(poi.get("id") or "")
        key = _poi_key(poi)
        if poi_id == current_id or poi_id in used_place_keys or key in used_place_keys:
            continue
        point = _normalize_point(poi.get("location"))
        if not point:
            continue
        distance = _point_distance_km(previous_point, point)
        candidates.append(
            {
                **poi,
                "candidate_id": poi_id,
                "category": category,
                "distance_from_previous_km": round(distance, 2),
            }
        )
    candidates.sort(key=lambda item: item.get("distance_from_previous_km", 9999))
    return candidates[:8]

def _validated_replacement_candidate(
    judgement: dict[str, Any],
    replacement_candidates: list[dict[str, Any]],
    current: dict[str, Any],
    previous: dict[str, Any],
    used_place_keys: set[str],
) -> dict[str, Any] | None:
    for candidate in replacement_candidates:
        candidate_id = str(candidate.get("candidate_id") or candidate.get("id") or "")
        if candidate_id and candidate_id == judgement.get("replacement_candidate_id"):
            current_distance = _point_distance_km(previous["point"], current["point"])
            candidate_point = _normalize_point(candidate.get("location"))
            if candidate_point and _point_distance_km(previous["point"], candidate_point) < current_distance:
                return candidate
    return None

def _replace_segment_item(day_number: Any, current: dict[str, Any], candidate: dict[str, Any]) -> None:
    item = current["item"]
    category = item.get("category") if item.get("category") in {"activity", "food"} else "activity"
    if category == "food":
        suffix = "用餐"
    else:
        suffix = "游览"
    replacement_item = _timeline_item(
        int(day_number or item.get("day") or 1),
        str(item.get("time") or ""),
        f"{candidate.get('name', '替换地点')}{suffix}",
        str(candidate.get("name") or ""),
        str(item.get("transport") or "打车/公共交通/步行"),
        str(item.get("duration") or "1-2 小时"),
        str(candidate.get("description") or "DeepSeek 路线体验评审建议替换为同片区真实地点，减少长距离折返。"),
        category,
        candidate,
        _fallback_cost_for_category(category),
        place_source=candidate.get("_place_source") or "amap_poi",
        is_real_place=True,
    )
    replacement_item["validation_note"] = "DeepSeek 路线体验评审建议替换为更顺路的真实地点。"
    item.clear()
    item.update(replacement_item)
    new_place = _segment_place(item)
    if new_place:
        current.update(new_place)

def _itinerary_used_place_keys(itinerary_days: list[dict[str, Any]]) -> set[str]:
    used: set[str] = set()
    for day in itinerary_days:
        for item in day.get("items", []):
            poi_id = str(item.get("poi_id") or "")
            if poi_id:
                used.add(poi_id)
            key = "|".join(str(item.get(field) or "").strip() for field in ["location", "address"])
            if key.strip("|"):
                used.add(key)
    return used

def _segment_place(item: dict[str, Any]) -> dict[str, Any] | None:
    if item.get("is_real_place") is False:
        return None
    if item.get("place_source") in {"planning_note", "transport_note", "llm_suggestion"}:
        return None
    point = _normalize_point(item.get("location_point"))
    if not point:
        return None
    detail = str(item.get("address") or item.get("location") or item.get("title") or "").strip()
    if not detail:
        return None
    return {"item": item, "point": point, "detail": detail, "title": item.get("title", "")}

def _select_local_segment_mode(modes: list[str], distance_km: float) -> str:
    available = list(dict.fromkeys(modes or []))
    if "walking" in available and distance_km <= 1.2:
        return "walking"
    if "bicycling" in available and distance_km <= 5:
        return "bicycling"
    for mode in ["transit", "driving", "taxi", "walking", "bicycling"]:
        if mode in available:
            return mode
    return "taxi"

def _amap_local_segment(
    prefs: dict[str, Any],
    day_number: Any,
    previous: dict[str, Any],
    current: dict[str, Any],
    mode: str,
    distance_km: float,
    *,
    toolbox=None,
) -> dict[str, Any]:
    if toolbox is None:
        return _rule_local_segment(day_number, previous, current, mode, distance_km, "fallback", "toolbox not available")
    try:
        raw = toolbox.call(
            "amap_plan_routes",
            origin=previous["detail"],
            destination=current["detail"],
            origin_city=prefs["destinationCity"],
            destination_city=prefs["destinationCity"],
            modes=mode,
            max_routes=1,
        )
        summary = _section_summary(raw, _local_route_heading(mode)) or raw
        if "查询失败" in summary or "高德路线规划失败" in summary or "高德未返回可用路线" in summary:
            return _rule_local_segment(day_number, previous, current, mode, distance_km, "fallback", summary)
        return _local_segment_from_summary(day_number, previous, current, mode, distance_km, summary)
    except Exception as exc:  # noqa: BLE001 - route fallback should keep the plan usable.
        return _rule_local_segment(day_number, previous, current, mode, distance_km, "fallback", str(exc))

def _local_route_heading(mode: str) -> str:
    return {
        "transit": "公交/地铁",
        "walking": "步行",
        "bicycling": "骑行",
        "driving": "驾车",
    }.get(mode, MODE_LABELS.get(mode, mode))

def _local_segment_from_summary(
    day_number: Any,
    previous: dict[str, Any],
    current: dict[str, Any],
    mode: str,
    distance_km: float,
    summary: str,
) -> dict[str, Any]:
    parsed_distance = _parse_local_distance_km(summary) or distance_km
    amount, price, cost_unit = _local_segment_price(mode, parsed_distance, summary, "amap_route")
    return {
        "day": day_number,
        "from_detail": previous["detail"],
        "to_detail": current["detail"],
        "from_item_id": previous["item"].get("id", ""),
        "to_item_id": current["item"].get("id", ""),
        "mode": mode,
        "mode_label": MODE_LABELS.get(mode, mode),
        "duration": _parse_local_duration(summary) or _fallback_local_duration(mode, parsed_distance),
        "distance": _format_local_distance(parsed_distance),
        "distance_km": round(parsed_distance, 2),
        "price": price,
        "cost_estimate": amount,
        "cost_unit": cost_unit,
        "summary": summary,
        "source": "amap_route",
        "status": "success",
        "warning": "路线来自高德规划摘要；出发前仍需结合实时路况和运营时间确认。",
    }

def _rule_local_segment(
    day_number: Any,
    previous: dict[str, Any],
    current: dict[str, Any],
    mode: str,
    distance_km: float,
    status: str,
    reason: str = "",
) -> dict[str, Any]:
    amount, price, cost_unit = _local_segment_price(mode, distance_km, reason, "rule_fallback")
    if status == "limited":
        warning = "为避免高德 QPS 过高，超出上限的市内路线使用距离规则估算。"
    elif mode == "taxi":
        warning = "打车价格为距离规则估算，不代表实时叫车价格。"
    else:
        warning = f"高德路线暂不可用，已降级为距离规则估算。{reason}".strip()
    return {
        "day": day_number,
        "from_detail": previous["detail"],
        "to_detail": current["detail"],
        "from_item_id": previous["item"].get("id", ""),
        "to_item_id": current["item"].get("id", ""),
        "mode": mode,
        "mode_label": MODE_LABELS.get(mode, mode),
        "duration": _fallback_local_duration(mode, distance_km),
        "distance": _format_local_distance(distance_km),
        "distance_km": round(distance_km, 2),
        "price": price,
        "cost_estimate": amount,
        "cost_unit": cost_unit,
        "summary": f"{MODE_LABELS.get(mode, mode)}：{previous['detail']} -> {current['detail']}，约 {_format_local_distance(distance_km)}。",
        "source": "rule_fallback",
        "status": status,
        "warning": warning,
    }

def _public_item_segment(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        key: segment.get(key)
        for key in [
            "from_detail",
            "to_detail",
            "mode",
            "mode_label",
            "duration",
            "distance",
            "price",
            "summary",
            "source",
            "status",
            "warning",
            "judge_source",
            "judge_decision",
            "risk_level",
            "judge_reason",
            "replacement_candidate_id",
        ]
    }

def _point_distance_km(start: dict[str, float], end: dict[str, float]) -> float:
    lat1 = math.radians(float(start["lat"]))
    lat2 = math.radians(float(end["lat"]))
    delta_lat = lat2 - lat1
    delta_lng = math.radians(float(end["lng"]) - float(start["lng"]))
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    return max(0.05, 6371.0 * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine)))

def _format_local_distance(distance_km: float) -> str:
    if distance_km < 1:
        return f"{round(distance_km * 1000)} m"
    return f"{distance_km:.1f} km"

def _local_duration_minutes(segment: dict[str, Any]) -> int:
    return _parse_local_duration_minutes(segment.get("duration") or segment.get("summary") or "")

def _fallback_local_duration(mode: str, distance_km: float) -> str:
    speed = {"walking": 4.5, "bicycling": 12, "transit": 18, "driving": 25, "taxi": 25}.get(mode, 18)
    buffer = {"transit": 8, "driving": 8, "taxi": 5}.get(mode, 0)
    minutes = max(3, round(distance_km / speed * 60 + buffer))
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, rest = divmod(minutes, 60)
    return f"{hours} 小时 {rest} 分钟" if rest else f"{hours} 小时"

def _local_segment_price(mode: str, distance_km: float, text: str, source: str) -> tuple[int, str, str]:
    if mode == "taxi":
        amount = round(max(12, 8 + distance_km * 2.8))
        return amount, f"约 ¥{amount}/车，距离规则估算", "party"
    if mode == "transit":
        match = re.search(r"票价约\s*([0-9.]+)\s*元", text)
        amount = round(float(match.group(1))) if match else round(max(2, min(12, distance_km * 1.2 + 2)))
        label = "高德票价参考" if source == "amap_route" and match else "规则估算"
        return amount, f"约 ¥{amount}/人，{label}", "person"
    if mode == "driving":
        toll_match = re.search(r"过路费约\s*([0-9.]+)\s*元", text)
        amount = round(float(toll_match.group(1))) if toll_match else round(max(3, distance_km * 0.9))
        label = "高德过路费参考" if source == "amap_route" and toll_match else "油电规则估算"
        return amount, f"约 ¥{amount}/车，{label}，停车另计", "party"
    if mode in {"walking", "bicycling"}:
        return 0, "¥0，慢行接驳", "person"
    return 0, "价格待核实", "person"

