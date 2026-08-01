"""TravelMind 跨城交通规划。"""

from __future__ import annotations

from typing import Any, Callable
import re

from .constants import (
    MODE_LABELS,
)
from .text_parser import (
    _average_range_from_text,
    _section_summary,
)


def _build_intercity_transport(self, prefs: dict[str, Any]) -> dict[str, Any]:
    origin = prefs["originCity"]
    destination = prefs["destinationCity"]
    modes = prefs["intercityModes"]
    amap_modes = [mode for mode in modes if mode in {"rail", "driving"}]
    route_text = ""
    if amap_modes:
        route_text = self.toolbox.call(
            "amap_plan_routes",
            origin=origin,
            destination=destination,
            origin_city=origin,
            destination_city=destination,
            modes=",".join(amap_modes),
            max_routes=2,
        )

    options = []
    rail_payload = self.rail_provider.query(origin, destination, prefs["startDate"])
    flight_payload = self.flight_provider.query(origin, destination, prefs["startDate"])
    route_origin_detail, route_destination_detail = _route_endpoint_details(route_text, origin, destination)

    if "rail" in modes:
        rail_summary = _section_summary(route_text, "高铁/城际铁路") or rail_payload.message
        rail_origin_detail, rail_destination_detail = _rail_endpoint_details(rail_summary, origin, destination)
        options.append(
            {
                "mode": "rail",
                "title": MODE_LABELS["rail"],
                "status": "fallback",
                "summary": rail_summary,
                "origin": origin,
                "destination": destination,
                "origin_city": origin,
                "destination_city": destination,
                "origin_detail": rail_origin_detail,
                "destination_detail": rail_destination_detail,
                "duration": _transport_duration_label("rail", prefs, rail_summary),
                "price": _transport_price_label("rail", prefs, rail_summary),
                "price_source": "rule_fallback",
                "distance_km": prefs.get("estimatedDistanceKm"),
                "provider_status": rail_payload.status,
                "warning": rail_payload.message,
            }
        )
    if "flight" in modes:
        flight_summary = _flight_strategy(prefs)
        options.append(
            {
                "mode": "flight",
                "title": MODE_LABELS["flight"],
                "status": flight_payload.status,
                "summary": flight_summary,
                "origin": origin,
                "destination": destination,
                "origin_city": origin,
                "destination_city": destination,
                "origin_detail": f"{origin}机场待确认",
                "destination_detail": f"{destination}机场待确认",
                "duration": _transport_duration_label("flight", prefs, flight_summary),
                "price": "航班实时价格未接入",
                "price_source": "unknown_price",
                "distance_km": prefs.get("estimatedDistanceKm"),
                "provider_status": flight_payload.status,
                "warning": flight_payload.message,
            }
        )
    if "driving" in modes:
        driving_summary = _section_summary(route_text, "驾车") or "适合多人同行、行李较多或目的地分散；需关注停车和拥堵。"
        options.append(
            {
                "mode": "driving",
                "title": MODE_LABELS["driving"],
                "status": "amap_fallback" if route_text else "not_configured",
                "summary": driving_summary,
                "origin": origin,
                "destination": destination,
                "origin_city": origin,
                "destination_city": destination,
                "origin_detail": route_origin_detail,
                "destination_detail": route_destination_detail,
                "duration": _transport_duration_label("driving", prefs, driving_summary),
                "price": _transport_price_label("driving", prefs, driving_summary),
                "price_source": "amap_route" if "过路费约" in driving_summary else "rule_fallback",
                "distance_km": prefs.get("estimatedDistanceKm"),
                "provider_status": "amap_fallback",
                "warning": "驾车路线来自高德路线规划，建议出发前再次查看实时路况。",
            }
        )

    recommended = _recommend_intercity_mode(prefs, options)
    notes = [
        "先确定跨城主交通，再安排目的地内交通和酒店位置。",
        "实时票价、余票和航班库存需要接入正式供应商后展示。",
    ]
    if route_text:
        notes.append("高德路线摘要已用于高铁/自驾候选的说明。")

    return {
        "recommended": recommended,
        "options": options,
        "notes": notes,
        "raw": route_text,
    }

def _route_endpoint_details(route_text: str, origin: str, destination: str) -> tuple[str, str]:
    origin_detail = _extract_route_endpoint(route_text, "出发地") or f"{origin}市中心"
    destination_detail = _extract_route_endpoint(route_text, "目的地") or f"{destination}市中心"
    return origin_detail, destination_detail

def _extract_route_endpoint(route_text: str, label: str) -> str:
    if not route_text:
        return ""
    match = re.search(rf"{re.escape(label)}：(.+?)(?:（[^）]*）)?(?:\n|$)", route_text)
    if not match:
        return ""
    value = match.group(1).strip()
    value = re.sub(r"（[^）]*）", "", value).strip()
    return value

def _rail_endpoint_details(summary: str, origin: str, destination: str) -> tuple[str, str]:
    if summary:
        match = re.search(r"(?:高铁/城际铁路|高铁/城际铁路建议)：\s*(.+?)(?:，|。|$)", summary)
        route_text = match.group(1).strip() if match else summary
        route_match = re.search(r"(.+?)\s*(?:->|→|到|至)\s*(.+?)(?:，|。|$)", route_text)
        if route_match:
            return route_match.group(1).strip(), route_match.group(2).strip()
    return f"{origin}主要高铁站待确认", f"{destination}主要高铁站待确认"

def _transport_duration_label(mode: str, prefs: dict[str, Any], text: str) -> str:
    if mode == "rail":
        match = re.search(r"车程\s*([^。；，]+)", text)
        if match:
            return match.group(1).strip()
        distance = prefs.get("estimatedDistanceKm") or 160
        return f"约 {max(30, round(distance / 3))} 分钟"
    if mode == "driving":
        match = re.search(r"(约\s*\d+(?:\.\d+)?\s*(?:小时|分钟)(?:\s*\d+\s*分钟)?)", text)
        if match:
            return match.group(1).strip()
        distance = prefs.get("estimatedDistanceKm") or 180
        return f"约 {round(distance / 75, 1)} 小时"
    if mode == "flight":
        distance = prefs.get("estimatedDistanceKm") or 1000
        return "约 3-5 小时（含机场接驳）" if distance >= 800 else "约 2-4 小时（含机场接驳）"
    return "待校准"

def _transport_price_label(mode: str, prefs: dict[str, Any], text: str) -> str:
    if mode == "rail":
        match = re.search(r"约\s*([0-9.]+)\s*[~\-～]\s*([0-9.]+)\s*元", text)
        if match:
            return f"二等座约 {match.group(1)}-{match.group(2)} 元/人，需以 12306 为准"
        distance = prefs.get("estimatedDistanceKm") or 180
        low = round(distance * 0.45)
        high = round(distance * 0.7)
        return f"二等座约 {low}-{high} 元/人，规则估算，需以 12306 为准"
    if mode == "driving":
        tolls = re.findall(r"过路费约\s*([0-9.]+)\s*元", text)
        if tolls:
            return f"过路费约 {tolls[0]} 元，油电费另计"
        distance = prefs.get("estimatedDistanceKm") or 180
        return f"油电费约 {round(distance * 0.6)}-{round(distance * 1.0)} 元，规则估算"
    return "价格待核实"

def _flight_strategy(prefs: dict[str, Any]) -> str:
    distance = prefs.get("estimatedDistanceKm")
    if distance and distance >= 800:
        return "两地距离较远，飞机适合作为省时主交通；需接入航班供应商后展示具体班次和价格。"
    return "两地距离不算远时，飞机通常不如高铁/自驾顺滑；仅在有直飞且机场接驳方便时考虑。"

def _recommend_intercity_mode(prefs: dict[str, Any], options: list[dict[str, Any]]) -> str:
    available = {option["mode"] for option in options}
    distance = prefs.get("estimatedDistanceKm")
    if "flight" in available and distance and distance >= 800:
        return "flight"
    if "rail" in available:
        return "rail"
    if "driving" in available:
        return "driving"
    return options[0]["mode"] if options else "driving"

def _estimate_intercity_cost(prefs: dict[str, Any], routes: dict[str, Any]) -> tuple[int, str]:
    travelers = prefs["travelers"]
    recommended = routes.get("recommended")
    route_text = str(routes.get("raw") or "")

    if recommended == "driving":
        toll_values = [float(value) for value in re.findall(r"过路费约\s*([0-9.]+)\s*元", route_text)]
        if toll_values:
            return round(min(toll_values) * 2), "amap_route"
        distance = prefs.get("estimatedDistanceKm") or 180
        return round(distance * 1.2), "rule_fallback"

    if recommended == "rail":
        ticket = _average_range_from_text(route_text)
        if ticket:
            return round(ticket * 2 * travelers), "rule_fallback"
        distance = prefs.get("estimatedDistanceKm") or 180
        return round(distance * 0.6 * 2 * travelers), "rule_fallback"

    if recommended == "flight":
        distance = prefs.get("estimatedDistanceKm") or 1000
        one_way = max(450, min(1800, distance * 0.45))
        return round(one_way * 2 * travelers), "rule_fallback"

    return 160 * travelers, "rule_fallback"

