"""TravelMind 行程生成（DeepSeek + 规则降级）。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable
import re

from .constants import (
    INTERCITY_MODE_MAP,
    LOCAL_MODE_MAP,
    MODE_LABELS,
    TIME_SLOTS,
)
from .text_parser import (
    _make_item_id,
    _parse_date,
)
from .budget_calculator import (
    _category_image_url,
)
from .poi_service import (
    _cluster_preference_order,
    _dedupe_pois,
    _poi_key,
    _take_unused_poi_for_cluster,
)

def _default_hotel_area(prefs: dict) -> str:
    return f"建议住在{prefs['destinationCity']}核心商圈、地铁枢纽或第一天重点景点附近，减少换乘和搬运行李。"


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    """内联自 StructuredTravelPlanner._bounded_int，用于跨模块调用。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def _parse_price_range(value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return None
    if len(numbers) == 1:
        low = high = numbers[0]
    else:
        low, high = numbers[0], numbers[1]
        if low > high:
            low, high = high, low
    return {
        "min": round(low),
        "max": round(high),
        "currency": "CNY",
        "unit": "person",
    }

def _price_midpoint(price_range: dict[str, Any] | None) -> int | None:
    if not price_range:
        return None
    try:
        low = float(price_range.get("min"))
        high = float(price_range.get("max"))
    except (TypeError, ValueError):
        return None
    if low < 0 or high < 0:
        return None
    return round((low + high) / 2)

def _normalize_price_confidence(value: Any, default: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    return text if text in {"high", "medium", "low", "unknown"} else default

def _cost_metadata(
    *,
    category: str,
    poi_cost: Any = None,
    fallback_cost: int = 0,
    use_poi_cost: bool = True,
    ai_price_range: dict[str, Any] | None = None,
    ai_price_note: str = "",
    ai_price_confidence: str = "medium",
) -> dict[str, Any]:
    has_amap_cost = use_poi_cost and isinstance(poi_cost, (int, float)) and poi_cost > 0
    if has_amap_cost:
        amount = round(float(poi_cost))
        return {
            "cost_estimate": amount,
            "cost_source": "amap_cost",
            "price_range": {"min": amount, "max": amount, "currency": "CNY", "unit": "person"},
            "price_confidence": "high",
            "cost_note": "高德 POI 参考消费，不代表实时票价、库存或可预订价格。",
        }

    ai_midpoint = _price_midpoint(ai_price_range)
    if ai_midpoint is not None and ai_midpoint > 0:
        return {
            "cost_estimate": ai_midpoint,
            "cost_source": "ai_price_range",
            "price_range": ai_price_range,
            "price_confidence": _normalize_price_confidence(ai_price_confidence, "medium"),
            "cost_note": ai_price_note or "AI 常识估算，需以官方/现场为准。",
        }

    if fallback_cost > 0 and category != "activity":
        return {
            "cost_estimate": fallback_cost,
            "cost_source": "category_rule",
            "price_range": {
                "min": round(fallback_cost * 0.7),
                "max": round(fallback_cost * 1.3),
                "currency": "CNY",
                "unit": "person" if category != "hotel" else "night",
            },
            "price_confidence": "low",
            "cost_note": "按地点类型规则估算，需以官方/现场为准。",
        }

    if category == "activity":
        return {
            "cost_estimate": 0,
            "cost_source": "free_or_no_ticket_default",
            "price_range": {"min": 0, "max": 0, "currency": "CNY", "unit": "person"},
            "price_confidence": "low",
            "cost_note": "未获取门票价，按无门票/免费项目默认 0 元；出行前仍建议核实官方信息。",
        }

    return {
        "cost_estimate": 0,
        "cost_source": "unknown_price",
        "price_range": None,
        "price_confidence": "unknown",
        "cost_note": "价格待核实，暂无可靠参考。",
    }

def _timeline_item(
    day_number: int,
    slot: str,
    title: str,
    location_name: str,
    transport: str,
    duration: str,
    detail: str,
    category: str,
    poi: dict[str, Any] | None = None,
    fallback_cost: int = 0,
    *,
    place_source: str | None = None,
    is_real_place: bool | None = None,
    use_poi_cost: bool = True,
    validation_note: str = "",
    ai_price_range: dict[str, Any] | None = None,
    ai_price_note: str = "",
    ai_price_confidence: str = "medium",
) -> dict[str, Any]:
    poi = poi or {}
    poi_cost = poi.get("cost")
    cost_meta = _cost_metadata(
        category=category,
        poi_cost=poi_cost,
        fallback_cost=fallback_cost,
        use_poi_cost=use_poi_cost,
        ai_price_range=ai_price_range,
        ai_price_note=ai_price_note,
        ai_price_confidence=ai_price_confidence,
    )
    item_id = _make_item_id(f"day{day_number}-{slot}", 1, title)
    photo_url = str(poi.get("photo_url") or "").strip()
    has_poi = bool(poi.get("name") or poi.get("id"))
    source = place_source or ("amap_poi" if has_poi else "planning_note")
    real_place = bool(has_poi) if is_real_place is None else bool(is_real_place)
    location_source = "missing"
    if poi.get("location"):
        location_source = source if source in {"hotel_poi", "transport_hub"} else "amap_poi"
    return {
        "id": item_id,
        "poi_id": poi.get("id", ""),
        "time": slot,
        "title": title,
        "location": location_name or poi.get("name", ""),
        "address": poi.get("address", ""),
        "transport": transport,
        "duration": duration,
        "detail": detail,
        "category": category,
        "rating": poi.get("rating"),
        "cost": poi_cost,
        "cost_estimate": cost_meta["cost_estimate"],
        "cost_source": cost_meta["cost_source"],
        "price_range": cost_meta["price_range"],
        "price_confidence": cost_meta["price_confidence"],
        "cost_note": cost_meta["cost_note"],
        "type": poi.get("type", ""),
        "cluster_id": poi.get("cluster_id", ""),
        "cluster_name": poi.get("cluster_name", ""),
        "nearby_anchor": poi.get("nearby_anchor", ""),
        "location_point": poi.get("location"),
        "location_source": location_source,
        "map_label": "",
        "map_included": False,
        "photo_url": photo_url or _category_image_url(category, title),
        "image_source": "amap_photo" if photo_url else "category_fallback",
        "is_real_place": real_place,
        "place_source": source,
        "validation_note": validation_note,
    }

def _note_item(day_number: int, slot: str, title: str, detail: str) -> dict[str, Any]:
    item_id = _make_item_id(f"day{day_number}-{slot}", 1, title)
    return {
        "id": item_id,
        "poi_id": "",
        "time": slot,
        "title": title,
        "location": "",
        "address": "",
        "transport": "",
        "duration": "",
        "detail": detail,
        "category": "note",
        "rating": None,
        "cost": None,
        "cost_estimate": 0,
        "cost_source": "unknown_price",
        "price_range": None,
        "price_confidence": "unknown",
        "cost_note": "说明项不计入预算，具体消费待现场核实。",
        "type": "",
        "location_point": None,
        "location_source": "missing",
        "map_label": "",
        "map_included": False,
        "photo_url": _category_image_url("activity", title),
        "image_source": "category_fallback",
        "is_real_place": False,
        "place_source": "planning_note",
        "validation_note": "",
    }

def _build_deepseek_itinerary_days(
    self,
    prefs: dict[str, Any],
    routes: dict[str, Any],
    local_transport: dict[str, Any],
    hotels: dict[str, Any],
    pois: dict[str, Any],
    weather: dict[str, str],
    weather_advice: dict[str, str],
) -> dict[str, Any]:
    payload, lookup = _planning_brain_payload(prefs, routes, local_transport, hotels, pois, weather, weather_advice)
    brain_result = self.deepseek_brain.plan(payload)
    if brain_result.get("llm_status") != "used":
        return {
            "llm_status": brain_result.get("llm_status", "fallback"),
            "planning_mode": "rule_fallback",
            "reason": brain_result.get("reason", "DeepSeek unavailable"),
            "error_kind": brain_result.get("error_kind"),
            "attempt_count": brain_result.get("attempt_count"),
            "fallback_reason": brain_result.get("fallback_reason"),
            "itinerary_days": [],
        }

    itinerary_days = _materialize_llm_itinerary(
        brain_result.get("plan") or {},
        prefs,
        routes,
        local_transport,
        hotels,
        lookup,
    )
    item_count = sum(len(day.get("items", [])) for day in itinerary_days)
    if item_count < max(2, prefs["days"] * 2):
        return {
            "llm_status": "schema_failed",
            "planning_mode": "rule_fallback",
            "reason": "DeepSeek itinerary did not contain enough usable items",
            "fallback_reason": "itinerary_insufficient_items",
            "itinerary_days": [],
        }

    return {
        "llm_status": "used",
        "planning_mode": "deepseek_hybrid",
        "reason": "DeepSeek generated itinerary from AMap candidates",
        "attempt_count": brain_result.get("attempt_count"),
        "itinerary_days": itinerary_days,
    }

def _planning_brain_payload(
    prefs: dict[str, Any],
    routes: dict[str, Any],
    local_transport: dict[str, Any],
    hotels: dict[str, Any],
    pois: dict[str, Any],
    weather: dict[str, str],
    weather_advice: dict[str, str],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    candidates = []
    lookup: dict[str, dict[str, Any]] = {}
    poi_contracts = pois.get("candidate_contracts") if isinstance(pois.get("candidate_contracts"), dict) else {}
    hotel_contracts = hotels.get("candidate_contracts") if isinstance(hotels.get("candidate_contracts"), list) else hotels.get("candidates")
    if poi_contracts:
        groups = [
            ("activity", "amap_poi", poi_contracts.get("attractions", [])),
            ("activity", "amap_poi", poi_contracts.get("specialty_places", [])),
            ("food", "amap_poi", poi_contracts.get("foods", [])),
            ("hotel", "hotel_poi", _dedupe_pois(hotel_contracts or [])[:6]),
        ]
    else:
        groups = [
            ("activity", "amap_poi", _dedupe_pois(pois.get("attractions"))[:12]),
            ("activity", "amap_poi", _dedupe_pois(pois.get("specialty_places"))[:8]),
            ("food", "amap_poi", _dedupe_pois(pois.get("foods"))[:12]),
            ("hotel", "hotel_poi", _dedupe_pois(hotels.get("candidates"))[:6]),
        ]
    for category, place_source, items in groups:
        for item in items:
            if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
                continue
            enriched = dict(item)
            enriched["_candidate_category"] = category
            enriched["_place_source"] = place_source
            lookup[str(item["id"])] = enriched
            candidates.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "category": category,
                    "address": item.get("address", ""),
                    "rating": item.get("rating"),
                    "cost": item.get("cost") if item.get("cost_source") == "amap_cost" else None,
                    "cost_source": item.get("cost_source") or "unknown_price",
                    "price_range": item.get("price_range"),
                    "price_note": item.get("cost_note") or "",
                    "type": item.get("type", ""),
                    "description": str(item.get("description") or "")[:160],
                    "cluster_id": item.get("cluster_id", ""),
                    "cluster_name": item.get("cluster_name", ""),
                    "nearby_anchor": item.get("nearby_anchor", ""),
                    "selection": item.get("selection"),
                }
            )

    payload = {
        "preferences": prefs,
        "intercity_transport": {
            "recommended": routes.get("recommended"),
            "options": [
                {
                    "mode": option.get("mode"),
                    "title": option.get("title"),
                    "summary": option.get("summary"),
                    "warning": option.get("warning"),
                }
                for option in routes.get("options", [])
            ],
        },
        "local_transport": local_transport,
        "hotel_area": hotels.get("area_recommendation", ""),
        "weather": weather,
        "weather_advice": weather_advice,
        "candidates": candidates,
        "cluster_guidance": [
            "每天优先围绕 1 个 primary_cluster 安排活动，最多补充 1 个相邻片区",
            "不要把相距很远的 cluster 硬排在同一天相邻时段",
            "餐饮优先匹配当天主片区或酒店片区",
        ],
        "constraints": [
            "真实地点必须使用 candidate_id",
            "可以给少量泛化体验建议，但 is_suggestion 必须为 true",
            "不要编造航班号、车次、实时票价、余票、酒店库存或门票库存",
            "最后一天返程交通只作为 transfer，不要把住宿区域建议写进返程 item 的 location 或 detail",
            "高德没有 cost 的景点/活动，只有明确可能收费时才输出正价 estimated_price_range；免费开放或无法判断收费时输出 0-0，并标注需核实",
            *(prefs.get("hardConstraints") or []),
            *(prefs.get("softPreferences") or []),
        ],
        "constraint_summary": prefs.get("constraintSummary") or {},
    }
    return payload, lookup

def _materialize_llm_itinerary(
    plan: dict[str, Any],
    prefs: dict[str, Any],
    routes: dict[str, Any],
    local_transport: dict[str, Any],
    hotels: dict[str, Any],
    lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_days = plan.get("days") if isinstance(plan.get("days"), list) else []
    day_lookup = {}
    for raw_day in raw_days:
        if isinstance(raw_day, dict):
            day_number = _bounded_int(raw_day.get("day"), len(day_lookup) + 1, 1, prefs["days"])
            day_lookup[day_number] = raw_day

    current_date = _parse_date(prefs["startDate"])
    recommended_local = "、".join(MODE_LABELS.get(mode, mode) for mode in local_transport.get("recommended_modes", []))
    hotel_area = hotels.get("area_recommendation") or _default_hotel_area(prefs)
    used_real: set[str] = set()
    materialized_days = []

    for day_number in range(1, prefs["days"] + 1):
        raw_day = day_lookup.get(day_number, {})
        date_text = (current_date + timedelta(days=day_number - 1)).isoformat() if current_date else ""
        theme = str(raw_day.get("theme") or ("抵达适应 + 城市体验" if day_number == 1 else f"{prefs['destinationCity']}深度体验"))
        raw_items = raw_day.get("items") if isinstance(raw_day.get("items"), list) else []
        items = []

        for index, raw_item in enumerate(raw_items[: len(TIME_SLOTS)]):
            if not isinstance(raw_item, dict):
                continue
            slot = TIME_SLOTS[index] if index < len(TIME_SLOTS) else f"第 {index + 1} 段"
            category = _normalize_llm_category(raw_item.get("category"))
            is_return_transfer = _is_return_transfer_raw_item(raw_item, category, prefs, day_number)
            candidate = _find_llm_candidate(raw_item, lookup)
            is_suggestion = bool(raw_item.get("is_suggestion")) or candidate is None
            if candidate and category in {"activity", "food"}:
                key = _poi_key(candidate)
                candidate_id = str(candidate.get("id") or "")
                if key in used_real or (candidate_id and candidate_id in used_real):
                    candidate = None
                    is_suggestion = True
                else:
                    used_real.add(key)
                    if candidate_id:
                        used_real.add(candidate_id)

            if candidate and not is_suggestion:
                candidate_category = candidate.get("_candidate_category") or category
                item_category = category if category in {"transfer", "hotel"} else candidate_category
                if item_category not in {"activity", "food", "hotel", "transfer"}:
                    item_category = candidate_category
                title = str(raw_item.get("title") or f"{candidate['name']}体验")
                detail = str(raw_item.get("detail") or candidate.get("description") or "根据 DeepSeek 智能规划，从高德候选中选择的真实地点。")
                ai_price_range = _parse_price_range(raw_item.get("estimated_price_range"))
                item = _timeline_item(
                    day_number,
                    slot,
                    title,
                    candidate.get("name", ""),
                    _display_transport_text(raw_item.get("transport") or recommended_local or "步行/打车"),
                    str(raw_item.get("duration") or "1-2 小时"),
                    detail,
                    item_category,
                    candidate,
                    _fallback_cost_for_category(item_category),
                    place_source=candidate.get("_place_source") or "amap_poi",
                    is_real_place=True,
                    use_poi_cost=item_category not in {"hotel", "transfer"},
                    validation_note="DeepSeek 已从高德候选中绑定真实地点。",
                    ai_price_range=ai_price_range,
                    ai_price_note=str(raw_item.get("price_note") or ""),
                    ai_price_confidence=str(raw_item.get("price_confidence") or "medium"),
                )
            else:
                item = _llm_suggestion_item(
                    day_number,
                    slot,
                    raw_item,
                    category,
                    hotel_area,
                    prefs,
                )
            if is_return_transfer:
                _normalize_return_transfer_item(item, raw_item, prefs, routes)
            items.append(item)

        materialized_days.append(
            {
                "day": day_number,
                "date": date_text,
                "theme": theme,
                "weather_note": "",
                "items": items,
            }
        )
    return materialized_days

def _normalize_llm_category(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"food", "restaurant", "meal", "lunch", "dinner"}:
        return "food"
    if text in {"hotel", "stay"}:
        return "hotel"
    if text in {"transfer", "transport"}:
        return "transfer"
    if text in {"note", "suggestion"}:
        return "activity"
    return "activity"

def _display_transport_text(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered in MODE_LABELS:
        return MODE_LABELS[lowered]
    if raw in INTERCITY_MODE_MAP:
        return MODE_LABELS.get(INTERCITY_MODE_MAP[raw], raw)
    if raw in LOCAL_MODE_MAP:
        return MODE_LABELS.get(LOCAL_MODE_MAP[raw], raw)
    return raw

def _is_return_transfer_raw_item(raw_item: dict[str, Any], category: str, prefs: dict[str, Any], day_number: int) -> bool:
    if category != "transfer":
        return False
    text = " ".join(str(raw_item.get(key) or "") for key in ["title", "location", "transport", "duration", "detail"])
    origin = str(prefs.get("originCity") or "")
    if origin and origin in text:
        return True
    return day_number == prefs.get("days") and any(keyword in text for keyword in ["返程", "返回", "回程", "回到", "返家", "回家"])

def _normalize_return_transfer_item(
    item: dict[str, Any],
    raw_item: dict[str, Any],
    prefs: dict[str, Any],
    routes: dict[str, Any],
) -> None:
    title = str(item.get("title") or raw_item.get("title") or "")
    route_location = _return_transfer_location(title, raw_item, prefs, routes)
    item["category"] = "transfer"
    item["location"] = route_location
    item["address"] = ""
    item["transport"] = _display_transport_text(raw_item.get("transport") or routes.get("recommended") or item.get("transport"))
    if _looks_like_lodging_text(item.get("detail")):
        item["detail"] = _default_return_transfer_detail(raw_item, prefs, routes)
    item["place_source"] = "transport_note"
    item["location_source"] = "missing"
    item["location_point"] = None
    item["map_included"] = False
    item["is_real_place"] = False
    item["validation_note"] = "返程交通说明，不作为目的地住宿或景点安排。"

def _return_transfer_location(
    title: str,
    raw_item: dict[str, Any],
    prefs: dict[str, Any],
    routes: dict[str, Any],
) -> str:
    text = str(raw_item.get("location") or title or "").strip()
    if _looks_like_lodging_text(text):
        text = title
    route_match = re.search(r"(.+?)\s*(?:->|→|到|至)\s*(.+?)(?:（|\(|，|,|。|$)", text)
    if route_match:
        return f"{route_match.group(1).strip()} → {route_match.group(2).strip()}"
    for option in routes.get("options", []):
        if option.get("mode") == routes.get("recommended"):
            origin_detail = option.get("destination_detail") or f"{prefs.get('destinationCity', '')}车站"
            destination_detail = option.get("origin_detail") or f"{prefs.get('originCity', '')}车站"
            return f"{origin_detail} → {destination_detail}"
    return f"{prefs.get('destinationCity', '')} → {prefs.get('originCity', '')}"

def _looks_like_lodging_text(value: Any) -> bool:
    text = str(value or "")
    lodging_markers = ["建议优先住在", "住宿区域", "住宿参考", "酒店", "周边，减少换乘", "寄存行李"]
    return any(marker in text for marker in lodging_markers)

def _default_return_transfer_detail(raw_item: dict[str, Any], prefs: dict[str, Any], routes: dict[str, Any]) -> str:
    detail = str(raw_item.get("detail") or "").strip()
    if detail and not _looks_like_lodging_text(detail):
        return detail
    mode_label = MODE_LABELS.get(routes.get("recommended"), routes.get("recommended", "高铁/动车/城际"))
    return f"按{mode_label}返回{prefs.get('originCity', '出发城市')}，这是返程交通安排，不需要再安排目的地住宿。"

def _fallback_cost_for_category(category: str) -> int:
    return {"food": 80, "activity": 0, "hotel": 0, "transfer": 0}.get(category, 0)

def _find_llm_candidate(raw_item: dict[str, Any], lookup: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    candidate_id = str(raw_item.get("candidate_id") or raw_item.get("poi_id") or "").strip()
    if candidate_id and candidate_id in lookup:
        return lookup[candidate_id]
    candidate_name = str(raw_item.get("candidate_name") or raw_item.get("location") or raw_item.get("title") or "").strip()
    normalized_name = re.sub(r"\s+", "", candidate_name)
    if not normalized_name:
        return None
    for item in lookup.values():
        name = re.sub(r"\s+", "", str(item.get("name") or ""))
        if name and (name in normalized_name or normalized_name in name):
            return item
    return None

def _llm_suggestion_item(
    day_number: int,
    slot: str,
    raw_item: dict[str, Any],
    category: str,
    hotel_area: str,
    prefs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title = str(raw_item.get("title") or "DeepSeek 待确认建议")
    detail = str(raw_item.get("detail") or "这是 DeepSeek 根据偏好给出的泛化体验建议，需结合现场位置和营业情况确认。")
    note = str(raw_item.get("validation_note") or "DeepSeek 建议，未绑定高德真实 POI，需现场确认。")
    item_id = _make_item_id(f"day{day_number}-{slot}", 1, title)
    item_category = category if category in {"activity", "food", "hotel", "transfer"} else "activity"
    if item_category == "transfer":
        location = str(raw_item.get("location") or title or "")
    else:
        location = str(raw_item.get("location") or hotel_area or "")
    cost_meta = _cost_metadata(
        category=item_category,
        fallback_cost=_fallback_cost_for_category(item_category),
        use_poi_cost=False,
        ai_price_range=_parse_price_range(raw_item.get("estimated_price_range")),
        ai_price_note=str(raw_item.get("price_note") or "AI 常识估算，需以官方/现场为准。"),
        ai_price_confidence=str(raw_item.get("price_confidence") or "low"),
    )
    return {
        "id": item_id,
        "poi_id": "",
        "time": slot,
        "title": title,
        "location": location,
        "address": "",
        "transport": _display_transport_text(raw_item.get("transport") or "就近步行/打车"),
        "duration": str(raw_item.get("duration") or "0.5-1.5 小时"),
        "detail": detail,
        "category": item_category,
        "rating": None,
        "cost": None,
        "cost_estimate": cost_meta["cost_estimate"],
        "cost_source": cost_meta["cost_source"],
        "price_range": cost_meta["price_range"],
        "price_confidence": cost_meta["price_confidence"],
        "cost_note": cost_meta["cost_note"],
        "type": "待确认建议",
        "location_point": None,
        "location_source": "missing",
        "map_label": "",
        "map_included": False,
        "photo_url": _category_image_url(item_category, title),
        "image_source": "category_fallback",
        "is_real_place": False,
        "place_source": "llm_suggestion",
        "validation_note": note,
    }

def _build_itinerary_days(
    prefs: dict[str, Any],
    routes: dict[str, Any],
    local_transport: dict[str, Any],
    hotels: dict[str, Any],
    pois: dict[str, Any],
    weather: dict[str, str],
) -> list[dict[str, Any]]:
    days = []
    attractions = _dedupe_pois(pois.get("attractions"))
    specialty_places = _dedupe_pois(pois.get("specialty_places"))
    foods = _dedupe_pois(pois.get("foods"))
    hotels_candidates = _dedupe_pois(hotels.get("candidates"))
    activity_candidates = _dedupe_pois([*attractions, *specialty_places])
    night_candidates = _dedupe_pois(attractions)
    used_places: set[str] = set()
    hotel_area = hotels.get("area_recommendation") or _default_hotel_area(prefs)
    recommended_local = "、".join(MODE_LABELS.get(mode, mode) for mode in local_transport.get("recommended_modes", []))
    current_date = _parse_date(prefs["startDate"])
    hotel_poi = hotels_candidates[0] if hotels_candidates else None
    cluster_order = _cluster_preference_order(activity_candidates, foods, hotel_poi)
    hotel_cluster = str((hotel_poi or {}).get("cluster_id") or "")
    profile = prefs.get("preferenceProfile") or {}
    learned_hints = " ".join(profile.get("learnedHints") or [])
    relaxed_pace = profile.get("pace") == "轻松" or any(
        keyword in learned_hints for keyword in ["别太赶", "轻松"]
    )

    for day_number in range(1, prefs["days"] + 1):
        date_text = (current_date + timedelta(days=day_number - 1)).isoformat() if current_date else ""
        theme = "抵达入住 + 城市初印象" if day_number == 1 else f"{prefs['destinationCity']}深度体验"
        if day_number == prefs["days"]:
            theme = "轻松收尾 + 返程预留"
        if day_number == 1 and hotel_cluster:
            day_cluster = hotel_cluster
        elif cluster_order:
            day_cluster = cluster_order[(day_number - 1) % len(cluster_order)]
        else:
            day_cluster = ""

        items = []
        if day_number == 1:
            if hotel_poi:
                items.append(
                    _timeline_item(
                        day_number,
                        "上午",
                        f"抵达后前往住宿：{hotel_poi['name']}",
                        hotel_poi["name"],
                        MODE_LABELS.get(routes.get("recommended"), routes.get("recommended", "rail")),
                        "2-4 小时",
                        f"优先按推荐主交通抵达目的地，之后前往真实酒店 POI 办理入住或寄存行李。住宿参考：{hotel_area}",
                        "transfer",
                        hotel_poi,
                        0,
                        place_source="hotel_poi",
                        is_real_place=True,
                        use_poi_cost=False,
                    )
                )
            else:
                items.append(
                    _note_item(
                        day_number,
                        "上午",
                        "交通抵达说明",
                        "优先按推荐主交通抵达目的地；当前未获取到可定位交通枢纽或酒店 POI，因此不把泛化城市名作为真实地点展示。",
                    )
                )
        else:
            morning_poi = _take_unused_poi_for_cluster(activity_candidates, used_places, day_cluster)
            if morning_poi:
                items.append(
                    _timeline_item(
                        day_number,
                        "上午",
                        f"{morning_poi['name']}游览",
                        morning_poi["name"],
                        recommended_local,
                        "2 小时",
                        morning_poi.get("description", "安排真实景点 POI 游览。"),
                        "activity",
                        morning_poi,
                        80,
                        place_source="amap_poi",
                        is_real_place=True,
                    )
                )
            else:
                items.append(
                    _note_item(
                        day_number,
                        "上午",
                        "真实景点候选不足",
                        "高德返回的未使用景点不足，已避免重复安排同一地点；建议将这一时段留作休整或按现场情况补充。",
                    )
                )

        lunch_poi = _take_unused_poi_for_cluster(foods, used_places, day_cluster)
        if lunch_poi:
            items.append(
                _timeline_item(
                    day_number,
                    "中午",
                    f"{lunch_poi['name']}午餐",
                    lunch_poi["name"],
                    recommended_local,
                    "1 小时",
                    lunch_poi.get("description", "选择靠近上午景点或酒店的真实餐厅 POI。"),
                    "food",
                    lunch_poi,
                    70,
                    place_source="amap_poi",
                    is_real_place=True,
                )
            )
        else:
            items.append(
                _note_item(
                    day_number,
                    "中午",
                    "真实餐厅候选不足",
                    "高德返回的未使用餐厅不足，未编造餐厅名称；可在当前景点或酒店周边现场选择。",
                )
            )

        afternoon_poi = _take_unused_poi_for_cluster(activity_candidates, used_places, day_cluster)
        if afternoon_poi:
            items.append(
                _timeline_item(
                    day_number,
                    "下午",
                    f"{afternoon_poi['name']}游览",
                    afternoon_poi["name"],
                    recommended_local,
                    "2-3 小时",
                    f"{afternoon_poi.get('description', '安排真实景点 POI 游览。')} 结束后回到住宿区域休整。",
                    "activity",
                    afternoon_poi,
                    80,
                    place_source="amap_poi",
                    is_real_place=True,
                )
            )
        elif hotel_poi:
            items.append(
                _timeline_item(
                    day_number,
                    "下午",
                    f"{hotel_poi['name']}休整",
                    hotel_poi["name"],
                    recommended_local,
                    "1.5-2 小时",
                    "真实景点候选不足时，安排回到推荐住宿点休整，避免重复塞入同一景点。",
                    "hotel",
                    hotel_poi,
                    0,
                    place_source="hotel_poi",
                    is_real_place=True,
                    use_poi_cost=False,
                )
            )
        else:
            items.append(
                _note_item(
                    day_number,
                    "下午",
                    "真实景点候选不足",
                    "高德返回的未使用景点不足，已减少活动密度，不编造景点。",
                )
            )

        dinner_poi = _take_unused_poi_for_cluster(foods, used_places, day_cluster)
        if dinner_poi:
            dinner_detail = dinner_poi.get("description", "选择真实餐厅 POI 安排晚餐。")
            if day_number == prefs["days"]:
                dinner_detail += " 最后一晚或返程前减少远距离移动，预留取行李和交通缓冲。"
            items.append(
                _timeline_item(
                    day_number,
                    "晚上",
                    f"{dinner_poi['name']}晚餐",
                    dinner_poi["name"],
                    "打车/公共交通/步行",
                    "1-1.5 小时",
                    dinner_detail,
                    "food",
                    dinner_poi,
                    70,
                    place_source="amap_poi",
                    is_real_place=True,
                )
            )
        else:
            items.append(
                _note_item(
                    day_number,
                    "晚上",
                    "真实晚餐候选不足",
                    "高德返回的未使用餐厅不足，未编造晚餐地点；建议就近在酒店或当天最后一个景点周边选择。",
                )
            )

        night_poi = None if relaxed_pace else _take_unused_poi_for_cluster(night_candidates, used_places, day_cluster)
        if night_poi:
            items.append(
                _timeline_item(
                    day_number,
                    "夜间",
                    f"{night_poi['name']}轻量散步",
                    night_poi["name"],
                    "打车/公共交通/步行",
                    "0.5-1 小时",
                    night_poi.get("description", "选择真实 POI 作为夜间轻量散步点，避免使用泛化商圈或城市名。"),
                    "activity",
                    night_poi,
                    30,
                    place_source="amap_poi",
                    is_real_place=True,
                )
            )
        elif day_number == prefs["days"] and not relaxed_pace:
            items.append(
                _note_item(
                    day_number,
                    "夜间",
                    "返程缓冲",
                    "未使用的真实夜游候选不足，最后一晚保留取行李和交通缓冲，不额外编造夜游地点。",
                )
            )

        days.append(
            {
                "day": day_number,
                "date": date_text,
                "theme": theme,
                "weather_note": weather.get(prefs["destinationCity"], ""),
                "items": items,
            }
        )
    return days

