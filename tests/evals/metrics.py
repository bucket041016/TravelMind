from __future__ import annotations

import re
from collections import Counter
from typing import Any


CONCRETE_CATEGORIES = {"activity", "food", "hotel"}


def _all_items(plan: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for day in plan.get("itinerary_days") or []:
        for item in day.get("items") or []:
            if isinstance(item, dict):
                items.append(item)
    return items


def _concrete_items(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _all_items(plan) if item.get("category") in CONCRETE_CATEGORIES]


def _bound_real(item: dict[str, Any]) -> bool:
    point = item.get("location_point")
    return bool(
        item.get("is_real_place")
        and isinstance(point, dict)
        and point.get("lng") is not None
        and point.get("lat") is not None
        and item.get("place_source") not in {"planning_note", "transport_note", "llm_suggestion"}
    )


def _place_key(item: dict[str, Any]) -> str:
    candidate_id = str(item.get("poi_id") or "").strip()
    if candidate_id:
        return f"id:{candidate_id}"
    point = item.get("location_point") if isinstance(item.get("location_point"), dict) else {}
    if point.get("lng") is not None and point.get("lat") is not None:
        return f"point:{float(point['lng']):.4f},{float(point['lat']):.4f}"
    return f"name:{str(item.get('location') or item.get('title') or '').strip()}"


def _duration_minutes(value: Any) -> int:
    text = str(value or "").replace(" ", "")
    hour = re.search(r"(\d+)小时", text)
    minute = re.search(r"(\d+)分钟", text)
    if not hour and not minute:
        return 0
    return (int(hour.group(1)) * 60 if hour else 0) + (int(minute.group(1)) if minute else 0)


def _return_transfer_items(plan: dict[str, Any]) -> list[dict[str, Any]]:
    days = plan.get("itinerary_days") or []
    if not days:
        return []
    last_day = days[-1]
    result = []
    for item in last_day.get("items") or []:
        if item.get("category") != "transfer":
            continue
        text = " ".join(str(item.get(key) or "") for key in ["title", "location", "detail", "validation_note"])
        if any(marker in text for marker in ["返程", "返回", "回程", "回到", "广州"]):
            result.append(item)
    return result


def return_hotel_contamination_rate(plan: dict[str, Any]) -> float:
    transfers = _return_transfer_items(plan)
    if not transfers:
        return 0.0
    lodging_markers = ["入住", "酒店", "宾馆", "房间", "住在", "住宿区域"]
    contaminated = 0
    for item in transfers:
        text = " ".join(str(item.get(key) or "") for key in ["title", "location", "detail"])
        if "不需要再安排" in text or "不作为目的地住宿" in text:
            continue
        if any(marker in text for marker in lodging_markers):
            contaminated += 1
    return contaminated / len(transfers)


def route_over_tolerance_rate(plan: dict[str, Any], max_transfer_minutes: int) -> float:
    segments = [segment for segment in (plan.get("local_transport") or {}).get("segments", []) if isinstance(segment, dict)]
    if not segments:
        return 0.0
    over = sum(1 for segment in segments if _duration_minutes(segment.get("duration") or segment.get("summary")) > max_transfer_minutes)
    return over / len(segments)


def hard_constraint_satisfaction(plan: dict[str, Any], expected: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    prefs = plan.get("preferences") or {}
    profile = prefs.get("preferenceProfile") or {}
    if "max_transfer_minutes" in expected:
        limit = int(expected["max_transfer_minutes"])
        rate = route_over_tolerance_rate(plan, limit)
        checks.append({"name": "max_transfer_minutes", "passed": rate == 0.0, "detail": f"over_tolerance_rate={rate:.3f}"})
    if expected.get("budget_must_be_within"):
        budget = plan.get("budget") or {}
        checks.append({"name": "budget_must_be_within", "passed": budget.get("verdict") == "within_budget", "detail": str(budget.get("verdict"))})
    if "max_real_places_per_day" in expected:
        limit = int(expected["max_real_places_per_day"])
        counts = []
        for day in plan.get("itinerary_days") or []:
            counts.append(sum(1 for item in day.get("items") or [] if item.get("category") in CONCRETE_CATEGORIES and _bound_real(item)))
        passed = all(count <= limit for count in counts)
        checks.append({"name": "max_real_places_per_day", "passed": passed, "detail": f"counts={counts}, limit={limit}"})
    if expected.get("no_return_lodging_contamination"):
        rate = return_hotel_contamination_rate(plan)
        checks.append({"name": "no_return_lodging_contamination", "passed": rate == 0.0, "detail": f"contamination_rate={rate:.3f}"})
    if expected.get("free_text_preserved"):
        preserved = bool(prefs.get("freeText") or prefs.get("free_text") or prefs.get("hardConstraints"))
        checks.append({"name": "free_text_preserved", "passed": preserved, "detail": "preferences contains raw constraint"})
    if expected.get("no_night_activity"):
        night_activities = [
            item
            for item in _all_items(plan)
            if item.get("time") == "夜间" and item.get("category") == "activity" and _bound_real(item)
        ]
        checks.append({"name": "no_night_activity", "passed": not night_activities, "detail": f"count={len(night_activities)}"})
    if not checks:
        return 1.0, checks
    return sum(1 for check in checks if check["passed"]) / len(checks), checks


def evaluate_plan(plan: dict[str, Any], scenario: Any, toolbox: Any, brain: Any, duration_ms: int) -> dict[str, Any]:
    concrete = _concrete_items(plan)
    bound = [item for item in concrete if _bound_real(item)]
    keys = [_place_key(item) for item in bound]
    duplicate_occurrences = len(keys) - len(set(keys))
    max_transfer = int((scenario.expected or {}).get("max_transfer_minutes", 45))
    budget = plan.get("budget") or {}
    target = budget.get("target")
    total = budget.get("total")
    budget_deviation = None
    if isinstance(target, (int, float)) and target > 0 and isinstance(total, (int, float)):
        budget_deviation = round(abs(total - target) / target, 4)

    fallback_components = {
        "weather": not bool(plan.get("weather")),
        "pois": not bool((plan.get("pois") or {}).get("attractions") or (plan.get("pois") or {}).get("foods")),
        "hotels": not bool((plan.get("hotels") or {}).get("candidates")),
        "planning": plan.get("planning_mode") != "deepseek_hybrid",
        "review": (plan.get("quality_review") or {}).get("source") == "rule_fallback",
        "local_routes": bool((plan.get("local_transport") or {}).get("segments"))
        and not any(segment.get("source") == "amap_route" for segment in (plan.get("local_transport") or {}).get("segments", [])),
    }
    fallback_rate = round(sum(fallback_components.values()) / len(fallback_components), 4)
    hard_score, hard_checks = hard_constraint_satisfaction(plan, scenario.expected or {})
    call_count = len(getattr(toolbox, "calls", [])) + len(getattr(brain, "calls", []))
    return {
        "scenario": scenario.name,
        "duration_ms": duration_ms,
        "metrics": {
            "real_place_binding_rate": round(len(bound) / len(concrete), 4) if concrete else 0.0,
            "duplicate_place_rate": round(max(0, duplicate_occurrences) / len(bound), 4) if bound else 0.0,
            "hard_constraint_satisfaction": round(hard_score, 4),
            "route_over_tolerance_rate": round(route_over_tolerance_rate(plan, max_transfer), 4),
            "budget_deviation": budget_deviation,
            "return_hotel_contamination_rate": round(return_hotel_contamination_rate(plan), 4),
            "fallback_rate": fallback_rate,
        },
        "hard_constraint_checks": hard_checks,
        "fallback_components": fallback_components,
        "planning_mode": plan.get("planning_mode"),
        "llm_status": plan.get("llm_status"),
        "budget": {
            "total": total,
            "target": target,
            "verdict": budget.get("verdict"),
        },
        "calls": {
            "tool": len(getattr(toolbox, "calls", [])),
            "tool_failures": len(getattr(toolbox, "failures", [])),
            "brain": len(getattr(brain, "calls", [])),
            "total": call_count,
        },
        "trace_statuses": [
            {"name": item.get("name"), "status": item.get("status")}
            for item in plan.get("trace", [])
            if isinstance(item, dict)
        ],
    }


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = [
        "real_place_binding_rate",
        "duplicate_place_rate",
        "hard_constraint_satisfaction",
        "route_over_tolerance_rate",
        "budget_deviation",
        "return_hotel_contamination_rate",
        "fallback_rate",
    ]
    averages: dict[str, float | None] = {}
    for name in metric_names:
        values = [result["metrics"].get(name) for result in results if result["metrics"].get(name) is not None]
        averages[name] = round(sum(values) / len(values), 4) if values else None
    return {
        "scenario_count": len(results),
        "averages": averages,
        "planning_modes": dict(Counter(str(result.get("planning_mode")) for result in results)),
        "total_calls": sum(int(result.get("calls", {}).get("total") or 0) for result in results),
        "total_tool_failures": sum(int(result.get("calls", {}).get("tool_failures") or 0) for result in results),
    }
