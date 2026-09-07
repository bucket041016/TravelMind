"""TravelMind 预算计算。"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

from .constants import (
    MODE_LABELS,
)
from .transport_service import (
    _estimate_intercity_cost,
)

def _hotel_reference_price(hotel_level: str) -> int:
    return {"经济": 220, "舒适": 380, "高端": 680}.get(hotel_level, 380)


def _build_budget(
    prefs: dict[str, Any],
    routes: dict[str, Any],
    local_transport: dict[str, Any],
    hotels: dict[str, Any],
    pois: dict[str, Any],
    itinerary_days: list[dict[str, Any]],
) -> dict[str, Any]:
    travelers = prefs["travelers"]
    days = prefs["days"]
    nights = max(days - 1, 1)
    rooms = max(1, (travelers + 1) // 2)

    route_total, route_source = _estimate_intercity_cost(prefs, routes)
    budget_strategy = str(hotels.get("budget_strategy") or "")
    if budget_strategy == "cheapest_first":
        hotel_unit, hotel_source = _cheapest_cost_by_source(hotels.get("candidates", []))
    else:
        hotel_unit, hotel_source = _average_cost_by_source(hotels.get("candidates", []))
    if hotel_unit:
        hotel_total = round(hotel_unit * nights * rooms)
    else:
        hotel_total = _hotel_reference_price(prefs["hotelLevel"]) * nights * rooms
        hotel_source = "category_rule"

    food_items = _itinerary_items_by_category(itinerary_days, {"food"})
    activity_items = _itinerary_items_by_category(itinerary_days, {"activity"})
    food_total = _sum_itinerary_item_cost(food_items, travelers)
    food_source = _combined_source(food_items)
    ticket_total = _sum_itinerary_item_cost(activity_items, travelers)
    ticket_source = _combined_source(activity_items)
    local_total, local_source, movement_count = _estimate_itinerary_local_transport_cost(
        local_transport,
        itinerary_days,
        travelers,
    )

    breakdown = {
        "intercity_transport": route_total,
        "hotel": hotel_total,
        "food": food_total,
        "tickets": ticket_total,
        "local_transport": local_total,
    }
    total = sum(value for value in breakdown.values() if isinstance(value, int))
    sources = {
        "intercity_transport": route_source,
        "hotel": hotel_source,
        "food": food_source,
        "tickets": ticket_source,
        "local_transport": local_source,
    }
    basis = [
        f"跨城交通按推荐方案「{MODE_LABELS.get(routes.get('recommended'), routes.get('recommended', ''))}」估算。",
        (
            f"住宿按最低价候选估算（预算自动调整策略），{nights} 晚、{rooms} 间房。"
            if budget_strategy == "cheapest_first"
            else f"住宿按 {nights} 晚、{rooms} 间房估算，优先使用高德酒店 POI 参考消费。"
        ),
        f"餐饮按最终行程中的 {len(food_items)} 个餐饮项目估算，优先使用高德餐厅/特色店铺人均。",
        f"门票/体验按最终行程中的 {len(activity_items)} 个活动项目估算；有高德参考消费或 AI 正价区间时计入，缺少可靠门票价时按无门票/免费项目默认 0 元。",
        f"市内交通按每日活动之间约 {movement_count} 次移动估算，结合推荐交通方式计算。",
        "高德 cost、AI 常识区间和类型规则都不是实时库存价、实时门票价或可预订价；活动 0 元默认值仍需出行前核实。",
    ]
    target = prefs.get("budget")
    if target and total:
        verdict = "within_budget" if total <= target else "over_budget"
        advice = f"预计总花费约 {total} 元，{'低于' if total <= target else '高于'}预算 {target} 元。"
    else:
        verdict = "unknown"
        advice = "用户预算或估算总额不完整，建议按高德参考消费和出行当天价格再校准。"
    return {
        "total": total,
        "target": target,
        "verdict": verdict,
        "breakdown": breakdown,
        "sources": sources,
        "basis": basis,
        "advice": advice,
        "text": "按最终每日行程项目、住宿晚数、推荐交通方式和高德参考消费估算。",
    }

def _itinerary_items_by_category(itinerary_days: list[dict[str, Any]], categories: set[str]) -> list[dict[str, Any]]:
    items = []
    for day in itinerary_days:
        for item in day.get("items", []):
            if item.get("category") in categories:
                items.append(item)
    return items

def _sum_itinerary_item_cost(items: list[dict[str, Any]], travelers: int) -> int:
    total = 0
    for item in items:
        total += round(float(item.get("cost_estimate") or 0)) * travelers
    return total

def _combined_source(items: list[dict[str, Any]]) -> str:
    if any(item.get("cost_source") == "amap_cost" for item in items):
        return "amap_cost"
    if any(item.get("cost_source") == "amap_route" for item in items):
        return "amap_route"
    if any(item.get("cost_source") == "ai_price_range" for item in items):
        return "ai_price_range"
    if any(item.get("cost_source") in {"category_rule", "rule_fallback"} for item in items):
        return "category_rule"
    if any(item.get("cost_source") == "free_or_no_ticket_default" for item in items):
        return "free_or_no_ticket_default"
    return "unknown_price"

def _estimate_itinerary_local_transport_cost(
    local_transport: dict[str, Any],
    itinerary_days: list[dict[str, Any]],
    travelers: int,
) -> tuple[int, str, int]:
    segments = local_transport.get("segments") or []
    if segments:
        total = 0
        for segment in segments:
            amount = round(float(segment.get("cost_estimate") or 0))
            if segment.get("cost_unit") == "party":
                total += amount
            else:
                total += amount * travelers
        return total, _combined_segment_source(segments), len(segments)

    movement_count = 0
    for day in itinerary_days:
        movable_items = [
            item
            for item in day.get("items", [])
            if item.get("category") in {"activity", "food", "hotel"}
            and item.get("place_source") not in {"planning_note", "transport_note"}
        ]
        movement_count += max(0, len(movable_items) - 1)

    modes = set(local_transport.get("recommended_modes") or [])
    if "taxi" in modes and "transit" in modes:
        unit = 22
    elif "taxi" in modes:
        unit = 45
    elif "transit" in modes:
        unit = 7
    elif "driving" in modes:
        unit = 28
    elif "bicycling" in modes:
        unit = 5
    else:
        unit = 0

    daily_buffer = 12 if {"transit", "taxi"} & modes else 0
    total = (movement_count * unit + len(itinerary_days) * daily_buffer) * travelers
    return round(total), "category_rule", movement_count

def _combined_segment_source(segments: list[dict[str, Any]]) -> str:
    if any(segment.get("source") == "amap_route" for segment in segments):
        return "amap_route"
    if any(segment.get("source") in {"category_rule", "rule_fallback"} for segment in segments):
        return "category_rule"
    return "unknown_price"

def _average_cost(items: list[dict[str, Any]]) -> float | None:
    costs = []
    for item in items:
        cost = item.get("cost")
        if isinstance(cost, (int, float)) and cost > 0:
            costs.append(float(cost))
    if not costs:
        return None
    return sum(costs) / len(costs)

def _average_cost_by_source(items: list[dict[str, Any]]) -> tuple[float | None, str]:
    for source in ["amap_cost", "ai_price_range", "category_rule", "rule_fallback"]:
        costs = []
        for item in items:
            if item.get("cost_source") != source:
                continue
            raw_cost = item.get("cost") if source == "amap_cost" else item.get("cost_estimate")
            if isinstance(raw_cost, (int, float)) and raw_cost > 0:
                costs.append(float(raw_cost))
        if costs:
            return sum(costs) / len(costs), ("category_rule" if source == "rule_fallback" else source)
    return None, "unknown_price"

def _cheapest_cost_by_source(items: list[dict[str, Any]]) -> tuple[float | None, str]:
    """与 _average_cost_by_source 同一 source 优先级框架，在最高优先非空组内取最低价。"""
    for source in ["amap_cost", "ai_price_range", "category_rule", "rule_fallback"]:
        costs = []
        for item in items:
            if item.get("cost_source") != source:
                continue
            raw_cost = item.get("cost") if source == "amap_cost" else item.get("cost_estimate")
            if isinstance(raw_cost, (int, float)) and raw_cost > 0:
                costs.append(float(raw_cost))
        if costs:
            return min(costs), ("category_rule" if source == "rule_fallback" else source)
    return None, "unknown_price"

def _activity_count(itinerary_days: list[dict[str, Any]]) -> int:
    count = 0
    for day in itinerary_days:
        for item in day.get("items", []):
            title = str(item.get("title", ""))
            if any(keyword in title for keyword in ["午餐", "晚餐", "酒店", "抵达", "出发"]):
                continue
            count += 1
    return max(count, len(itinerary_days))

def _estimate_local_transport_cost(local_transport: dict[str, Any], days: int, travelers: int) -> tuple[int, str]:
    modes = set(local_transport.get("recommended_modes") or [])
    daily = 40
    if "taxi" in modes and "transit" in modes:
        daily = 80
    elif "taxi" in modes:
        daily = 110
    elif "transit" in modes:
        daily = 35
    elif "driving" in modes:
        daily = 90
    elif modes <= {"walking", "bicycling"}:
        daily = 20
    return daily * days * travelers, "rule_fallback"

def _category_image_url(category: str, title: str = "") -> str:
    title_text = str(title or "")
    if category == "food":
        label, start, end = "美食", "#f8efe0", "#f7c66b"
    elif category == "transfer":
        label, start, end = "交通", "#e8f2fb", "#75b8e7"
    elif category == "hotel":
        label, start, end = "住宿", "#edf7ef", "#83d2a0"
    elif "夜" in title_text or "晚上" in title_text:
        label, start, end = "夜游", "#e8e7fb", "#9085df"
    else:
        label, start, end = "景点", "#eaf4ee", "#71c49d"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
  <defs>
<linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
  <stop offset="0" stop-color="{start}"/>
  <stop offset="1" stop-color="{end}"/>
</linearGradient>
  </defs>
  <rect width="640" height="360" rx="18" fill="url(#bg)"/>
  <circle cx="510" cy="82" r="58" fill="#ffffff" opacity=".28"/>
  <circle cx="118" cy="276" r="82" fill="#ffffff" opacity=".18"/>
  <path d="M80 260 C170 175 240 205 318 128 S470 92 560 172" fill="none" stroke="#ffffff" stroke-width="16" opacity=".42" stroke-linecap="round"/>
  <rect x="48" y="48" width="132" height="48" rx="12" fill="#ffffff" opacity=".88"/>
  <text x="114" y="80" text-anchor="middle" font-family="Microsoft YaHei, Arial, sans-serif" font-size="24" font-weight="700" fill="#185577">{label}</text>
  <text x="48" y="302" font-family="Microsoft YaHei, Arial, sans-serif" font-size="26" font-weight="700" fill="#263241" opacity=".82">TravelMind</text>
</svg>"""
    return "data:image/svg+xml;charset=utf-8," + quote(svg)

