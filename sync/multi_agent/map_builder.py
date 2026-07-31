"""TravelMind 地图数据生成。"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

from .constants import (
    CITY_CENTER_COORDS,
)
from .text_parser import (
    _first_valid_point,
    _normalize_point,
)


def _build_map(
    plan_id: str,
    prefs: dict[str, Any],
    itinerary_days: list[dict[str, Any]],
    pois: dict[str, Any],
    hotels: dict[str, Any],
) -> dict[str, Any]:
    markers = []
    static_marker_limit = 10
    destination_center = _derive_destination_center(prefs, itinerary_days, pois, hotels)
    hotel_point = _first_valid_point(hotels.get("candidates", [])) or destination_center
    last_point = destination_center

    for day in itinerary_days:
        for item in day.get("items", []):
            point, source = _resolve_item_map_point(
                item,
                destination_center,
                hotel_point,
                last_point,
            )
            if not point:
                item["location_source"] = "missing"
                item["map_label"] = ""
                item["map_included"] = False
                continue

            key = {
                "lng": round(float(point["lng"]), 6),
                "lat": round(float(point["lat"]), 6),
            }
            label = str(len(markers) + 1)
            item["location_point"] = key
            item["location_source"] = source
            item["map_label"] = label
            item["map_included"] = True
            last_point = key
            markers.append(
                {
                    "id": item.get("id", ""),
                    "label": label,
                    "title": item.get("location") or item.get("title", ""),
                    "day": day.get("day"),
                    "time": item.get("time", ""),
                    "lng": key["lng"],
                    "lat": key["lat"],
                    "category": item.get("category", "activity"),
                    "location_source": source,
                    "place_source": item.get("place_source", source),
                    "is_real_place": item.get("is_real_place", False),
                }
            )

    if not markers:
        fallback_titles = []
        for group in [pois.get("attractions", []), pois.get("foods", []), hotels.get("candidates", [])]:
            fallback_titles.extend(item.get("name", "") for item in group[:3])
        return {
            "provider_status": "fallback",
            "image_url": "",
            "center": None,
            "markers": [],
            "path": [],
            "static_marker_limit": static_marker_limit,
            "fallback_points": [title for title in fallback_titles if title],
            "notes": ["高德 POI 未返回可用坐标，暂以点位顺序列表展示。"],
        }

    center = {
        "lng": round(sum(marker["lng"] for marker in markers) / len(markers), 6),
        "lat": round(sum(marker["lat"] for marker in markers) / len(markers), 6),
    }
    static_markers = markers[:static_marker_limit]
    marker_param = ";".join(f"{marker['lng']},{marker['lat']},{marker['label']}" for marker in static_markers)
    path_param = ";".join(f"{marker['lng']},{marker['lat']}" for marker in static_markers)
    image_url = (
        f"/api/map-static?plan_id={quote(plan_id)}"
        f"&markers={quote(marker_param)}"
        f"&path={quote(path_param)}"
        f"&title={quote(str(prefs.get('destinationCity', '')))}"
    )
    return {
        "provider_status": "amap_static",
        "image_url": image_url,
        "center": center,
        "markers": markers,
        "path": [{"lng": marker["lng"], "lat": marker["lat"]} for marker in markers],
        "static_marker_limit": static_marker_limit,
        "notes": ["地图按每日行程顺序标记；兜底点位用于展示规划顺序，不等同实时导航路线。"],
    }

def _derive_destination_center(
    prefs: dict[str, Any],
    itinerary_days: list[dict[str, Any]],
    pois: dict[str, Any],
    hotels: dict[str, Any],
) -> dict[str, float] | None:
    city_center = CITY_CENTER_COORDS.get(str(prefs.get("destinationCity", "")).removesuffix("市"))
    if city_center:
        return city_center

    points = []
    for day in itinerary_days:
        for item in day.get("items", []):
            point = _normalize_point(item.get("location_point"))
            if point:
                points.append(point)
    for group in [
        pois.get("attractions", []),
        pois.get("foods", []),
        pois.get("specialty_places", []),
        hotels.get("candidates", []),
    ]:
        for item in group or []:
            point = _normalize_point(item.get("location"))
            if point:
                points.append(point)
    if points:
        return {
            "lng": sum(point["lng"] for point in points) / len(points),
            "lat": sum(point["lat"] for point in points) / len(points),
        }
    return None

def _resolve_item_map_point(
    item: dict[str, Any],
    destination_center: dict[str, float] | None,
    hotel_point: dict[str, float] | None,
    last_point: dict[str, float] | None,
) -> tuple[dict[str, float] | None, str]:
    point = _normalize_point(item.get("location_point"))
    if point:
        source = item.get("location_source") or item.get("place_source") or "amap_poi"
        if source == "missing":
            source = item.get("place_source") or "amap_poi"
        return point, source

    title = f"{item.get('title', '')}{item.get('location', '')}"
    category = item.get("category")
    place_source = item.get("place_source")
    if place_source in {"planning_note", "transport_note"} or item.get("is_real_place") is False:
        return None, "missing"
    if category == "transfer" and destination_center and place_source == "transport_hub":
        return destination_center, "city_center"
    if ("酒店" in title or "休整" in title or category == "hotel" or place_source == "hotel_poi") and hotel_point:
        return hotel_point, "hotel_area"
    if item.get("is_real_place") and last_point:
        return last_point, "derived"
    if item.get("is_real_place") and destination_center:
        return destination_center, "city_center"
    return None, "missing"

