"""TravelMind 行程质量评审与修复。"""

from __future__ import annotations

from typing import Any, Callable

from .itinerary_builder import (
    _materialize_llm_itinerary,
    _normalize_llm_category,
    _planning_brain_payload,
)
from .local_transport_service import (
    _segment_place,
)

def _point_distance_km(start: dict, end: dict) -> float:
    import math
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


def _review_and_repair_itinerary(
    self,
    prefs: dict[str, Any],
    routes: dict[str, Any],
    local_transport: dict[str, Any],
    hotels: dict[str, Any],
    pois: dict[str, Any],
    weather: dict[str, str],
    weather_advice: dict[str, str],
    itinerary_days: list[dict[str, Any]],
) -> dict[str, Any]:
    payload, lookup = _planning_brain_payload(prefs, routes, local_transport, hotels, pois, weather, weather_advice)
    payload["current_itinerary"] = _compact_itinerary_for_review(itinerary_days)
    payload["quality_targets"] = {
        "pace": (prefs.get("preferenceProfile") or {}).get("pace"),
        "max_transfer_minutes": (prefs.get("preferenceProfile") or {}).get("maxTransferMinutes"),
        "hotel_strategy": (prefs.get("preferenceProfile") or {}).get("hotelStrategy"),
        "learned_hints": (prefs.get("preferenceProfile") or {}).get("learnedHints", []),
    }

    result = self.deepseek_brain.review_itinerary(payload)
    if result.get("llm_status") != "used":
        return {"itinerary_days": itinerary_days, "quality_review": _rule_quality_review(prefs, itinerary_days)}

    review = _normalize_quality_review(result.get("review"), "deepseek")
    repaired_days = itinerary_days
    raw_review = result.get("review") if isinstance(result.get("review"), dict) else {}
    repaired_plan = raw_review.get("repaired_plan") if isinstance(raw_review.get("repaired_plan"), dict) else None
    if raw_review.get("needs_repair") and repaired_plan:
        if _repair_plan_uses_known_candidates(repaired_plan, lookup):
            candidate_days = _materialize_llm_itinerary(
                repaired_plan,
                prefs,
                routes,
                local_transport,
                hotels,
                lookup,
            )
            if sum(len(day.get("items", [])) for day in candidate_days) >= max(2, prefs["days"] * 2):
                repaired_days = candidate_days
                _apply_preference_safety_to_itinerary(prefs, repaired_days)
                review["fixes"].append("已按智能体检结果完成一次受控返工。")
                review["repaired"] = True
            else:
                review["issues"].append(
                    {
                        "severity": "medium",
                        "day": None,
                        "message": "DeepSeek 建议返工，但返工结果可用项目不足，已保留原行程。",
                        "kind": "logic",
                    }
                )
        else:
            review["issues"].append(
                {
                    "severity": "medium",
                    "day": None,
                    "message": "DeepSeek 建议返工，但包含未授权或不存在的候选地点，已拒绝本次返工。",
                    "kind": "logic",
                }
            )
    _assign_day_primary_clusters(repaired_days)
    if not review["issues"]:
        rule_review = _rule_quality_review(prefs, repaired_days)
        review["issues"] = rule_review.get("issues", [])
    return {"itinerary_days": repaired_days, "quality_review": review}

def _repair_plan_uses_known_candidates(plan: dict[str, Any], lookup: dict[str, dict[str, Any]]) -> bool:
    raw_days = plan.get("days") if isinstance(plan.get("days"), list) else []
    for raw_day in raw_days:
        if not isinstance(raw_day, dict):
            continue
        raw_items = raw_day.get("items") if isinstance(raw_day.get("items"), list) else []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            category = _normalize_llm_category(raw_item.get("category"))
            if category in {"activity", "food", "hotel"}:
                candidate_id = str(raw_item.get("candidate_id") or raw_item.get("poi_id") or "").strip()
                if not candidate_id or candidate_id not in lookup:
                    return False
    return True

def _compact_itinerary_for_review(itinerary_days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact_days = []
    for day in itinerary_days:
        compact_days.append(
            {
                "day": day.get("day"),
                "theme": day.get("theme"),
                "primary_cluster": day.get("primary_cluster"),
                "items": [
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "category": item.get("category"),
                        "location": item.get("location"),
                        "transport": item.get("transport"),
                        "duration": item.get("duration"),
                        "cluster_id": item.get("cluster_id"),
                        "cluster_name": item.get("cluster_name"),
                        "place_source": item.get("place_source"),
                        "detail": str(item.get("detail") or "")[:120],
                    }
                    for item in day.get("items", [])
                ],
            }
        )
    return compact_days

def _normalize_quality_review(value: Any, source: str) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}

    def score(key: str, default: int = 80) -> int:
        try:
            return max(0, min(int(raw.get(key, default)), 100))
        except (TypeError, ValueError):
            return default

    issues = raw.get("issues") if isinstance(raw.get("issues"), list) else []
    normalized_issues = []
    for issue in issues[:8]:
        if not isinstance(issue, dict):
            continue
        severity = str(issue.get("severity") or "medium")
        if severity not in {"low", "medium", "high"}:
            severity = "medium"
        normalized_issues.append(
            {
                "severity": severity,
                "day": issue.get("day"),
                "message": str(issue.get("message") or issue.get("reason") or "").strip(),
                "kind": str(issue.get("kind") or "logic"),
            }
        )
    fixes = [str(item).strip() for item in raw.get("fixes", []) if str(item).strip()] if isinstance(raw.get("fixes"), list) else []
    return {
        "overall_score": score("overall_score"),
        "route_score": score("route_score"),
        "pace_score": score("pace_score"),
        "cluster_score": score("cluster_score"),
        "logic_score": score("logic_score"),
        "issues": normalized_issues,
        "fixes": fixes[:8],
        "source": source,
        "repaired": False,
    }

def _rule_quality_review(prefs: dict[str, Any], itinerary_days: list[dict[str, Any]]) -> dict[str, Any]:
    issues = []
    max_transfer = int((prefs.get("preferenceProfile") or {}).get("maxTransferMinutes") or 45)
    for day in itinerary_days:
        clusters = [item.get("cluster_id") for item in day.get("items", []) if item.get("cluster_id")]
        if len(set(clusters)) > 2:
            issues.append(
                {
                    "severity": "medium",
                    "day": day.get("day"),
                    "message": "当天跨越多个片区，建议压缩到一个主片区和一个相邻片区。",
                    "kind": "cluster",
                }
            )
        places = [_segment_place(item) for item in day.get("items", [])]
        places = [place for place in places if place]
        for previous, current in zip(places, places[1:]):
            distance = _point_distance_km(previous["point"], current["point"])
            if distance > max(12, max_transfer * 0.7):
                issues.append(
                    {
                        "severity": "high" if distance > 35 else "medium",
                        "day": day.get("day"),
                        "message": f"{previous['detail']} 到 {current['detail']} 距离约 {_format_local_distance(distance)}，需重点校验交通体验。",
                        "kind": "route",
                    }
                )
    route_score = 92 - 12 * sum(1 for item in issues if item["kind"] == "route")
    cluster_score = 92 - 10 * sum(1 for item in issues if item["kind"] == "cluster")
    logic_score = 88
    pace_score = 88 if (prefs.get("preferenceProfile") or {}).get("pace") != "轻松" else 92
    scores = [route_score, cluster_score, logic_score, pace_score]
    return {
        "overall_score": max(0, min(round(sum(scores) / len(scores)), 100)),
        "route_score": max(0, min(route_score, 100)),
        "pace_score": max(0, min(pace_score, 100)),
        "cluster_score": max(0, min(cluster_score, 100)),
        "logic_score": logic_score,
        "issues": issues[:8],
        "fixes": [],
        "source": "rule_fallback",
        "repaired": False,
    }

def _apply_preference_safety_to_itinerary(prefs: dict[str, Any], itinerary_days: list[dict[str, Any]]) -> None:
    profile = prefs.get("preferenceProfile") or {}
    hints = " ".join(profile.get("learnedHints") or [])
    relaxed = profile.get("pace") == "轻松" or any(keyword in hints for keyword in ["别太赶", "轻松"])
    if not relaxed:
        return

    for day in itinerary_days:
        items = day.get("items")
        if not isinstance(items, list):
            continue
        while len(items) > 4:
            removable_index = None
            for index in range(len(items) - 1, -1, -1):
                item = items[index]
                if item.get("category") in {"transfer", "hotel"}:
                    continue
                if item.get("time") == "夜间" or item.get("category") in {"note", "activity"}:
                    removable_index = index
                    break
            if removable_index is None:
                for index in range(len(items) - 1, -1, -1):
                    if items[index].get("category") != "transfer":
                        removable_index = index
                        break
            if removable_index is None:
                break
            items.pop(removable_index)

def _assign_day_primary_clusters(itinerary_days: list[dict[str, Any]]) -> None:
    for day in itinerary_days:
        counts: dict[str, dict[str, Any]] = {}
        for item in day.get("items", []):
            cluster_id = str(item.get("cluster_id") or "")
            if not cluster_id:
                continue
            if cluster_id not in counts:
                counts[cluster_id] = {
                    "cluster_id": cluster_id,
                    "cluster_name": item.get("cluster_name") or cluster_id,
                    "nearby_anchor": item.get("nearby_anchor") or "",
                    "count": 0,
                }
            counts[cluster_id]["count"] += 1
        if counts:
            primary = max(counts.values(), key=lambda item: item["count"])
            day["primary_cluster"] = {
                "cluster_id": primary["cluster_id"],
                "cluster_name": primary["cluster_name"],
                "nearby_anchor": primary["nearby_anchor"],
            }
        else:
            day["primary_cluster"] = None

