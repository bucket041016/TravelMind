"""确定性预算反馈循环（Phase 3）：超预算时按优先级调整行程与住宿策略。

零 LLM、零工具调用：所有决策基于已归一化的候选与 item 成本字段。
调整期预算使用 movement_count 口径（市内交通按移动次数规则估算，通常高于
最终 segments 口径），因此循环决策只消费「每轮节省量 vs 剩余缺口」的相对量；
动作金额为 item 级算术（可信），缺口与 final_verdict 为调整期估算，
最终以 BudgetAgent 的真实口径为准。

调整优先级（3.3）：同片区高价项替换（activity+food）→ 住宿最低价策略 →
非硬性付费活动删减。轮次有硬上限（默认 2）；不可行动作记入 skipped；
TRAVELMIND_BUDGET_LOOP=off 可整体关闭。
"""

from __future__ import annotations

import copy
import os
from typing import Any

from .budget_calculator import _average_cost_by_source, _build_budget, _cheapest_cost_by_source
from .itinerary_builder import _cost_metadata, _fallback_cost_for_category, _retime_day_items, _timeline_item
from .local_transport_service import _itinerary_used_place_keys
from .poi_service import _dedupe_pois, _poi_key
from .text_parser import _normalize_point

BUDGET_LOOP_FLAG = "TRAVELMIND_BUDGET_LOOP"


def _projected_item_cost(category: str, poi_cost: Any) -> int:
    """候选重建为 item 后的成本（与 _timeline_item/_cost_metadata 同口径）。"""
    meta = _cost_metadata(
        category=category,
        poi_cost=poi_cost,
        fallback_cost=_fallback_cost_for_category(category),
        use_poi_cost=True,
    )
    try:
        return int(meta.get("cost_estimate") or 0)
    except (TypeError, ValueError):
        return 0


def _loop_enabled() -> bool:
    return str(os.getenv(BUDGET_LOOP_FLAG, "on")).strip().lower() not in {"off", "0", "false", "no"}


def budget_loop_enabled() -> bool:
    """公开开关读取：TRAVELMIND_BUDGET_LOOP 默认 on，off 为回滚开关。"""
    return _loop_enabled()


def _disabled_result() -> dict[str, Any]:
    return {
        "enabled": False,
        "rounds_used": 0,
        "applied": [],
        "skipped": [],
        "total_saved": 0,
        "gap_before": None,
        "gap_after": None,
        "final_verdict": None,
        "note": "",
    }


def _provisional_budget(
    prefs: dict[str, Any],
    routes: dict[str, Any],
    local_transport: dict[str, Any],
    hotels: dict[str, Any],
    itinerary_days: list[dict[str, Any]],
) -> dict[str, Any]:
    """调整期临时预算：segments 未建，市内交通走 movement_count 估算口径。"""
    return _build_budget(prefs, routes, local_transport, hotels, {}, itinerary_days)


def _item_place_key(item: dict[str, Any]) -> str:
    return "|".join(str(item.get(field) or "").strip() for field in ["location", "address"])


def _is_replaceable_item(item: dict[str, Any]) -> bool:
    """杠杆 1/3 目标：已绑定真实地点、有正成本的 activity/food 项。"""
    if item.get("category") not in {"activity", "food"}:
        return False
    if not item.get("is_real_place") or not _normalize_point(item.get("location_point")):
        return False
    try:
        return float(item.get("cost_estimate") or 0) > 0
    except (TypeError, ValueError):
        return False


def _candidate_pool(pois: dict[str, Any], category: str) -> list[dict[str, Any]]:
    if category == "activity":
        return _dedupe_pois([*(pois.get("attractions") or []), *(pois.get("specialty_places") or [])])
    if category == "food":
        return _dedupe_pois(pois.get("foods"))
    return []


def _pick_cheaper_candidate(
    pois: dict[str, Any],
    item: dict[str, Any],
    used_place_keys: set[str],
) -> dict[str, Any] | None:
    """同片区里挑成本严格更低、有坐标、未使用的同类别候选（价格升序确定性）。"""
    category = item["category"]
    current_cost = float(item.get("cost_estimate") or 0)
    current_id = str(item.get("poi_id") or "")

    best: tuple[tuple[float, str], dict[str, Any]] | None = None
    for poi in _candidate_pool(pois, category):
        poi_id = str(poi.get("id") or "")
        if not poi_id or poi_id == current_id:
            continue
        key = _poi_key(poi)
        if poi_id in used_place_keys or (key and key in used_place_keys):
            continue
        projected_cost = _projected_item_cost(category, poi.get("cost"))
        if projected_cost >= round(current_cost):
            continue
        if not _normalize_point(poi.get("location")):
            continue
        if not (item.get("cluster_id") and item.get("cluster_id") == poi.get("cluster_id")):
            continue
        rank = (projected_cost, poi_id)
        if best is None or rank < best[0]:
            best = (rank, poi)
    if best is None:
        return None
    chosen = dict(best[1])
    chosen["_budget_category"] = category
    return chosen


def _replace_item_inplace(
    prefs: dict[str, Any],
    day: dict[str, Any],
    item: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    """用 _timeline_item 重建替换项并原地置换（继承时间槽/transport/duration）。"""
    category = candidate["_budget_category"]
    suffix = "用餐" if category == "food" else "游览"
    replacement = _timeline_item(
        int(day.get("day") or 1),
        str(item.get("time") or ""),
        f"{candidate.get('name', '替换地点')}{suffix}",
        str(candidate.get("name") or ""),
        str(item.get("transport") or "打车/公共交通/步行"),
        str(item.get("duration") or "1-2 小时"),
        "预算自动调整：替换为同片区更低消费的真实地点，原地点成本高于当前预算缺口所需。",
        category,
        candidate,
        _fallback_cost_for_category(category),
        place_source="amap_poi",
        is_real_place=True,
        validation_note="BudgetOptimizer 预算反馈：以同片区更低消费候选替换原地点。",
    )
    item.clear()
    item.update(replacement)


def _apply_replacement_lever(
    prefs: dict[str, Any],
    pois: dict[str, Any],
    itinerary_days: list[dict[str, Any]],
    used_place_keys: set[str],
    projected_total: float,
    target: float,
    rnd: int,
    result: dict[str, Any],
) -> float:
    """杠杆 1：按成本降序替换同片区高价项，直到预计回到预算内或无候选。"""
    travelers = int(prefs.get("travelers") or 1)
    replaceable: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for day in itinerary_days:
        for item in day.get("items", []):
            if _is_replaceable_item(item):
                replaceable.append((float(item.get("cost_estimate") or 0), day, item))
    replaceable.sort(key=lambda entry: entry[0], reverse=True)

    for current_cost, day, item in replaceable:
        if projected_total <= target:
            break
        candidate = _pick_cheaper_candidate(pois, item, used_place_keys)
        if candidate is None:
            result["skipped"].append(
                {
                    "round": rnd,
                    "lever": "replace",
                    "day": day.get("day"),
                    "title": item.get("title"),
                    "reason": "同片区无更低消费且未使用的真实候选",
                }
            )
            continue

        before_title = str(item.get("title") or "")
        before_cost = round(current_cost)
        after_cost = _projected_item_cost(candidate["_budget_category"], candidate.get("cost"))
        old_poi_id = str(item.get("poi_id") or "")
        old_key = _item_place_key(item)

        _replace_item_inplace(prefs, day, item, candidate)
        saved = (before_cost - after_cost) * travelers
        if saved <= 0:
            # 理论不可达（候选要求 round 后严格更低），防御性回滚本项。
            result["skipped"].append(
                {"round": rnd, "lever": "replace", "day": day.get("day"), "title": before_title, "reason": "替换后成本未下降，已放弃"}
            )
            continue

        for stale in (old_poi_id, old_key):
            if stale.strip("|"):
                used_place_keys.discard(stale)
        new_poi_id = str(item.get("poi_id") or "")
        new_key = _item_place_key(item)
        for fresh in (new_poi_id, new_key):
            if fresh.strip("|"):
                used_place_keys.add(fresh)

        projected_total -= saved
        result["applied"].append(
            {
                "round": rnd,
                "lever": "replace",
                "day": day.get("day"),
                "before": {"title": before_title, "cost": before_cost},
                "after": {"title": str(item.get("title") or ""), "cost": after_cost},
                "saved": round(saved),
                "reason": "超出预算：替换为同片区更低消费的真实地点（时间槽与交通文本沿用，最终以路线重建为准）",
            }
        )
    return projected_total


def _apply_hotel_strategy_lever(
    prefs: dict[str, Any],
    hotels: dict[str, Any],
    projected_total: float,
    target: float,
    rnd: int,
    result: dict[str, Any],
) -> float:
    """杠杆 2：住宿按最低价候选估算（同一 source 优先级框架内取 min）。"""
    if hotels.get("budget_strategy") == "cheapest_first":
        return projected_total
    candidates = hotels.get("candidates") or []
    old_unit, _ = _average_cost_by_source(candidates)
    new_unit, _ = _cheapest_cost_by_source(candidates)
    if not old_unit or not new_unit or new_unit >= old_unit:
        result["skipped"].append(
            {"round": rnd, "lever": "hotel_strategy", "reason": "候选均价已接近最低价，无可节省空间"}
        )
        return projected_total
    travelers = int(prefs.get("travelers") or 1)
    nights = max(int(prefs.get("days") or 1) - 1, 1)
    rooms = max(1, (travelers + 1) // 2)
    saved = round((old_unit - new_unit) * nights * rooms)
    hotels["budget_strategy"] = "cheapest_first"
    hotels["candidates"] = sorted(candidates, key=lambda c: float(c.get("cost_estimate") or 0))
    projected_total -= saved
    result["applied"].append(
        {
            "round": rnd,
            "lever": "hotel_strategy",
            "day": None,
            "before": {"title": "住宿策略", "cost": round(old_unit)},
            "after": {"title": "住宿策略（最低价候选）", "cost": round(new_unit)},
            "saved": saved,
            "reason": "活动替换不足以覆盖缺口：住宿改按最低价候选估算，候选列表按价格升序重排",
        }
    )
    return projected_total


def _apply_trim_lever(
    prefs: dict[str, Any],
    itinerary_days: list[dict[str, Any]],
    projected_total: float,
    target: float,
    rnd: int,
    result: dict[str, Any],
) -> float:
    """杠杆 3：从最高价删非硬性付费活动（非餐饮），保持每天 ≥2 个具体项、总数 ≥ 下限。"""
    travelers = int(prefs.get("travelers") or 1)
    days = int(prefs.get("days") or len(itinerary_days) or 1)
    min_total_items = max(2, days * 2)

    def concrete_count(day: dict[str, Any]) -> int:
        return sum(1 for i in day.get("items", []) if i.get("category") in {"activity", "food"})

    total_items = sum(len(day.get("items", [])) for day in itinerary_days)
    removable: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for day in itinerary_days:
        for item in day.get("items", []):
            if item.get("category") != "activity" or not _is_replaceable_item(item):
                continue
            if "夜间" in str(item.get("time") or ""):
                continue
            removable.append((float(item.get("cost_estimate") or 0), day, item))
    removable.sort(key=lambda entry: entry[0], reverse=True)

    for current_cost, day, item in removable:
        if projected_total <= target:
            break
        if total_items - 1 < min_total_items or concrete_count(day) - 1 < 2:
            result["skipped"].append(
                {
                    "round": rnd,
                    "lever": "trim",
                    "day": day.get("day"),
                    "title": item.get("title"),
                    "reason": "删除后低于每日/总量下限，已保留",
                }
            )
            continue
        before_cost = round(current_cost)
        day["items"].remove(item)
        total_items -= 1
        _retime_day_items(day)
        saved = before_cost * travelers
        projected_total -= saved
        result["applied"].append(
            {
                "round": rnd,
                "lever": "trim",
                "day": day.get("day"),
                "before": {"title": item.get("title"), "cost": before_cost},
                "after": {"title": None, "cost": 0},
                "saved": round(saved),
                "reason": "缺口仍在：移除非硬性付费活动并重排当天时间槽",
            }
        )
    return projected_total


def run_budget_feedback_loop(
    prefs: dict[str, Any],
    routes: dict[str, Any],
    local_transport: dict[str, Any],
    hotels: dict[str, Any],
    itinerary_days: list[dict[str, Any]],
    pois: dict[str, Any],
    *,
    max_rounds: int = 2,
) -> dict[str, Any]:
    """超预算时的确定性调整循环；返回 budget_adjustments 记录，行程/酒店原地修改。"""
    result = {
        "enabled": True,
        "rounds_used": 0,
        "applied": [],
        "skipped": [],
        "total_saved": 0,
        "gap_before": None,
        "gap_after": None,
        "final_verdict": None,
        "note": "金额为调整期估算：市内交通按移动次数规则口径，最终以预算大盘为准。",
    }
    target = prefs.get("budget")
    if not _loop_enabled() or not isinstance(target, (int, float)) or target <= 0:
        result["enabled"] = False
        return result

    days_snapshot = copy.deepcopy(itinerary_days)
    candidates_snapshot = copy.deepcopy(hotels.get("candidates", []))
    strategy_snapshot = copy.deepcopy(hotels.get("budget_strategy"))

    try:
        budget = _provisional_budget(prefs, routes, local_transport, hotels, itinerary_days)
        total = int(budget.get("total") or 0)
        result["gap_before"] = max(0, total - int(target))
        used_place_keys = _itinerary_used_place_keys(itinerary_days)

        for rnd in range(1, max_rounds + 1):
            if total <= int(target):
                break
            projected_total = float(total)

            projected_total = _apply_replacement_lever(
                prefs, pois, itinerary_days, used_place_keys, projected_total, float(target), rnd, result
            )
            if projected_total < total:
                budget = _provisional_budget(prefs, routes, local_transport, hotels, itinerary_days)
                total = int(budget.get("total") or 0)
                projected_total = float(total)

            if total > int(target):
                projected_total = _apply_hotel_strategy_lever(prefs, hotels, projected_total, float(target), rnd, result)
                if hotels.get("budget_strategy") == "cheapest_first":
                    budget = _provisional_budget(prefs, routes, local_transport, hotels, itinerary_days)
                    total = int(budget.get("total") or 0)
                    projected_total = float(total)

            if total > int(target):
                _apply_trim_lever(prefs, itinerary_days, projected_total, float(target), rnd, result)
                if any(a.get("lever") == "trim" and a.get("round") == rnd for a in result["applied"]):
                    budget = _provisional_budget(prefs, routes, local_transport, hotels, itinerary_days)
                    total = int(budget.get("total") or 0)

            result["rounds_used"] = rnd
            if not any(a.get("round") == rnd for a in result["applied"]):
                result["skipped"].append({"round": rnd, "lever": "loop", "reason": "无可行调整动作，提前结束"})
                break

        result["gap_after"] = max(0, total - int(target))
        result["final_verdict"] = budget.get("verdict")
        result["total_saved"] = sum(int(a.get("saved") or 0) for a in result["applied"])
    except Exception as exc:  # noqa: BLE001 - 循环失败必须回滚到调整前状态。
        itinerary_days[:] = copy.deepcopy(days_snapshot)
        hotels["candidates"] = copy.deepcopy(candidates_snapshot)
        if strategy_snapshot is None:
            hotels.pop("budget_strategy", None)
        else:
            hotels["budget_strategy"] = strategy_snapshot
        rolled_back_budget = _provisional_budget(prefs, routes, local_transport, hotels, itinerary_days)
        result["applied"] = []
        result["rounds_used"] = 0
        result["total_saved"] = 0
        result["rollback"] = {"reason": str(exc)}
        result["gap_before"] = max(0, int(rolled_back_budget.get("total") or 0) - int(target))
        result["gap_after"] = result["gap_before"]
        result["final_verdict"] = rolled_back_budget.get("verdict")
        result["note"] = "调整过程异常，已回滚到调整前行程。"
    return result
