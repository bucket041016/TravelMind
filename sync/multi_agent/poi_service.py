"""TravelMind POI 搜索与空间聚类。"""

from __future__ import annotations

from typing import Any, Callable
import re

from .text_parser import (
    _normalize_point,
    _parse_numbered_section,
)
from .fact_normalizer import normalize_place_candidates
from .candidate_ranker import rank_candidates
from .structured_result import parse_poi_response

def _point_distance_km(start: dict, end: dict) -> float:
    import math
    lat1 = math.radians(float(start["lat"]))
    lat2 = math.radians(float(end["lat"]))
    delta_lat = lat2 - lat1
    delta_lng = math.radians(float(end["lng"]) - float(start["lng"]))
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    return max(0.05, 6371.0 * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine)))


def _build_pois(self, prefs: dict[str, Any]) -> dict[str, Any]:
    result = self.toolbox.call_structured(
        "search_poi",
        city=prefs["destinationCity"],
        preference="、".join(prefs["interests"]),
    )
    parsed = parse_poi_response(result)
    if parsed is not None:
        attractions = parsed.attractions
        real_foods = parsed.foods
        specialty_places = parsed.specialty_places
        generic_foods = parsed.generic_foods
    else:
        text = result.text
        attractions = _parse_numbered_section(text, "景点/活动") or _parse_numbered_section(text, "经典景点")
        real_foods = _parse_numbered_section(text, "美食/餐厅")
        specialty_places = _parse_numbered_section(text, "特色店铺参考")
        generic_foods = _parse_numbered_section(text, "地方特色美食")
    return {
        "attractions": attractions,
        "foods": real_foods or specialty_places or generic_foods,
        "specialty_places": specialty_places,
        "raw": result.text,
    }


def _normalize_and_rank_pois(
    pois: dict[str, Any],
    prefs: dict[str, Any],
    weather: dict[str, str] | None = None,
) -> None:
    """对 POI 候选执行事实归一化和偏好排序（原地修改 pois）。"""
    city = prefs.get("destinationCity", "")
    interests = prefs.get("interests") or []
    weather_summary = " ".join((weather or {}).values())

    for group, category in [
        ("attractions", "activity"),
        ("foods", "food"),
        ("specialty_places", "activity"),
    ]:
        raw_items = pois.get(group)
        if not raw_items:
            continue
        normalized = normalize_place_candidates(
            raw_items,
            city=city,
            category=category,
            source="amap_poi",
        )
        ranked = rank_candidates(
            normalized,
            expected_city=city,
            preferences={"interests": interests},
            weather=weather_summary,
        )
        pois[group] = ranked.get("selected", normalized)


def _enrich_place_clusters(pois: dict[str, Any], hotels: dict[str, Any]) -> None:
    cluster_items: list[dict[str, Any]] = []
    for group_name in ["attractions", "specialty_places", "foods"]:
        for item in pois.get(group_name) or []:
            point = _normalize_point(item.get("location"))
            if point:
                cluster_items.append({"item": item, "point": point})
    for item in hotels.get("candidates") or []:
        point = _normalize_point(item.get("location"))
        if point:
            cluster_items.append({"item": item, "point": point})

    clusters: list[dict[str, Any]] = []
    for entry in cluster_items:
        nearest = _nearest_cluster(entry["point"], clusters)
        cluster = nearest["cluster"] if nearest else None
        if not nearest or nearest["distance_km"] > 8:
            cluster = {
                "id": f"cluster-{len(clusters) + 1}",
                "items": [],
                "center": dict(entry["point"]),
                "anchor": _cluster_anchor(entry["item"]),
            }
            clusters.append(cluster)
        cluster["items"].append(entry)
        count = len(cluster["items"])
        cluster["center"] = {
            "lng": (cluster["center"]["lng"] * (count - 1) + entry["point"]["lng"]) / count,
            "lat": (cluster["center"]["lat"] * (count - 1) + entry["point"]["lat"]) / count,
        }
        if not cluster.get("anchor"):
            cluster["anchor"] = _cluster_anchor(entry["item"])

    for cluster in clusters:
        anchor = cluster.get("anchor") or f"片区{cluster['id'].split('-')[-1]}"
        cluster_name = f"{anchor}片区"
        for entry in cluster["items"]:
            item = entry["item"]
            item["cluster_id"] = cluster["id"]
            item["cluster_name"] = cluster_name
            item["nearby_anchor"] = anchor

def _nearest_cluster(point: dict[str, float], clusters: list[dict[str, Any]]) -> dict[str, Any] | None:
    nearest = None
    for cluster in clusters:
        distance = _point_distance_km(point, cluster["center"])
        if nearest is None or distance < nearest["distance_km"]:
            nearest = {"cluster": cluster, "distance_km": distance}
    return nearest

def _cluster_anchor(item: dict[str, Any]) -> str:
    for source in [item.get("type"), item.get("address"), item.get("name")]:
        text = str(source or "").strip()
        if not text:
            continue
        match = re.search(
            r"([\u4e00-\u9fffA-Za-z0-9]+?(?:地铁站|会展中心|商业中心|购物中心|公园|广场|海滩|海边|博物馆|美术馆|景区|老街|口岸|机场|火车站|高铁站|北站|南站|东站|西站))",
            text,
        )
        if match:
            return match.group(1).strip()
        piece = re.split(r"[，,；;()（）]", text)[0].strip()
        if 2 <= len(piece) <= 12:
            return piece
    return ""

def _poi_key(poi: dict[str, Any]) -> str:
    name = str(poi.get("name") or "").strip()
    key = re.sub(r"[\s·,，:：；;（）()]+", "", name)
    for suffix in ["体育公园", "森林公园", "湿地公园", "风景名胜区", "风景区", "景区", "公园"]:
        if len(key) > len(suffix) + 1 and key.endswith(suffix):
            key = key[: -len(suffix)]
            break
    return key or str(poi.get("id") or "").strip()

def _dedupe_pois(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    deduped = []
    seen = set()
    for item in items or []:
        if not item.get("name"):
            continue
        if not _has_real_place_signal(item):
            continue
        key = _poi_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped

def _has_real_place_signal(poi: dict[str, Any]) -> bool:
    return bool(
        poi.get("location")
        or poi.get("address")
        or poi.get("rating")
        or poi.get("type")
        or poi.get("photo_url")
    )

def _take_unused_poi(candidates: list[dict[str, Any]], used: set[str]) -> dict[str, Any] | None:
    for poi in candidates:
        key = _poi_key(poi)
        poi_id = str(poi.get("id") or "")
        if not key or key in used or (poi_id and poi_id in used):
            continue
        used.add(key)
        if poi_id:
            used.add(poi_id)
        return poi
    return None

def _take_unused_poi_for_cluster(
    candidates: list[dict[str, Any]],
    used: set[str],
    cluster_id: str | None = None,
) -> dict[str, Any] | None:
    target = str(cluster_id or "")
    if not target:
        return _take_unused_poi(candidates, used)

    same_cluster = [poi for poi in candidates if str(poi.get("cluster_id") or "") == target]
    missing_cluster = [poi for poi in candidates if not poi.get("cluster_id")]
    other_cluster = [
        poi
        for poi in candidates
        if str(poi.get("cluster_id") or "") not in {"", target}
    ]
    return _take_unused_poi([*same_cluster, *missing_cluster, *other_cluster], used)

def _cluster_preference_order(
    activity_candidates: list[dict[str, Any]],
    foods: list[dict[str, Any]],
    hotel_poi: dict[str, Any] | None,
) -> list[str]:
    scores: dict[str, float] = {}

    def add(item: dict[str, Any] | None, weight: float) -> None:
        cluster_id = str((item or {}).get("cluster_id") or "")
        if cluster_id:
            scores[cluster_id] = scores.get(cluster_id, 0) + weight

    add(hotel_poi, 2.0)
    for item in activity_candidates:
        add(item, 3.0)
    for item in foods:
        add(item, 1.0)
    return [cluster_id for cluster_id, _ in sorted(scores.items(), key=lambda pair: pair[1], reverse=True)]

