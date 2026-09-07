"""追问增量操作的定位与应用（Phase 4）。

两阶段设计：locate_targets 先解析全部 op 的目标（item_id 优先、item_title
退化），apply_operations 再执行变更——因为 _retime_day_items 会重生成 item id，
边改边定位会让后续 op 失效。所有护栏与 quality_gate/budget_optimizer 同口径：
删除后总量（含 note/transfer）≥ max(2, days*2)、每日 concrete（activity+food）
≥2、新增每天 movable <5（TIME_SLOTS 5 槽）；候选必须存在于 plan.pois、未被
行程使用且不是目标自身（铁律：模型只引用后端 id，非法引用一律跳过）。
"""

from __future__ import annotations

from typing import Any

from .itinerary_builder import _fallback_cost_for_category, _retime_day_items, _timeline_item
from .local_transport_service import _itinerary_used_place_keys
from .text_parser import _normalize_point

STRUCTURAL_ACTIONS = {"replace_place", "remove_item", "add_activity"}
PREFERENCE_ACTIONS = {"adjust_budget", "change_pace", "change_hotel_strategy"}
TIME_SLOT_ORDER = ["上午", "中午", "下午", "晚上", "夜间"]


def _candidate_group(group_name: str) -> str:
    return "food" if group_name == "foods" else "activity"


def build_refine_payload(plan: dict[str, Any]) -> dict[str, Any]:
    """构造紧凑的追问解析 payload：items 含 id，候选池含 type（场景判定依赖）。"""
    prefs = plan.get("preferences") or {}
    profile = prefs.get("preferenceProfile") or {}
    budget = plan.get("budget") or {}

    days_summary = []
    for day in plan.get("itinerary_days") or []:
        items = [
            {
                "item_id": str(item.get("id") or ""),
                "title": str(item.get("title") or ""),
                "category": str(item.get("category") or ""),
                "time": str(item.get("time") or ""),
                "cost_estimate": item.get("cost_estimate"),
                "cluster_id": str(item.get("cluster_id") or ""),
            }
            for item in day.get("items") or []
        ]
        days_summary.append(
            {"day": day.get("day"), "date": day.get("date", ""), "theme": str(day.get("theme") or ""), "items": items}
        )

    candidate_pool = []
    for group_name in ("attractions", "foods", "specialty_places"):
        for poi in (plan.get("pois") or {}).get(group_name) or []:
            if not str(poi.get("id") or ""):
                continue
            candidate_pool.append(
                {
                    "candidate_id": str(poi.get("id")),
                    "name": str(poi.get("name") or ""),
                    "group": _candidate_group(group_name),
                    "type": str(poi.get("type") or ""),
                    "cost": poi.get("cost") if poi.get("cost") is not None else poi.get("cost_estimate"),
                    "cluster_id": str(poi.get("cluster_id") or ""),
                    "rating": poi.get("rating"),
                }
            )

    return {
        "preferences": {
            "days": prefs.get("days"),
            "travelers": prefs.get("travelers"),
            "budget": prefs.get("budget"),
            "pace": profile.get("pace"),
            "hotel_strategy": profile.get("hotelStrategy"),
        },
        "days": days_summary,
        "candidate_pool": candidate_pool,
        "current_budget": {"total": budget.get("total"), "verdict": budget.get("verdict")},
    }


def _candidate_index(pois: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    index: dict[str, tuple[str, dict[str, Any]]] = {}
    for group_name in ("attractions", "foods", "specialty_places"):
        for poi in (pois or {}).get(group_name) or []:
            candidate_id = str(poi.get("id") or "")
            if candidate_id:
                index[candidate_id] = (_candidate_group(group_name), poi)
    return index


def _concrete_count(day: dict[str, Any]) -> int:
    return sum(1 for item in day.get("items", []) if item.get("category") in {"activity", "food"})


def _movable_count(day: dict[str, Any]) -> int:
    return sum(1 for item in day.get("items", []) if item.get("category") != "note")


def _candidate_place_keys(candidate: dict[str, Any]) -> set[str]:
    """候选的查重键：id + 「名称|地址」（与 _itinerary_used_place_keys 的 item 键对齐）。

    不能用伪 item 调 _itinerary_used_place_keys——POI 的 id 字段名是 "id" 而非
    "poi_id"，且 POI 的 location 是坐标 dict，会让查重键永远错位。
    """
    keys: set[str] = set()
    candidate_id = str(candidate.get("id") or "").strip()
    if candidate_id:
        keys.add(candidate_id)
    key = "|".join(
        str(candidate.get(field) or "").strip() for field in ["name", "address"]
    )
    if key.strip("|"):
        keys.add(key)
    return keys


def _summary_for_replace(before: dict[str, Any], after: dict[str, Any]) -> str:
    return f"{before.get('title') or ''}（{before.get('cost_estimate') or 0} 元）→ {after.get('title') or ''}（{after.get('cost_estimate') or 0} 元）"


def locate_targets(ops: list[dict[str, Any]], itinerary_days: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    """逐 op 解析目标：结构 op 返回 {day_index, item_index}，其余返回 None。

    定位在应用前一次性完成（两阶段），retime 引发的 id 变化不影响后续 op。
    """
    targets: list[dict[str, Any] | None] = []
    for op in ops:
        action = str(op.get("action") or "")
        if action not in {"replace_place", "remove_item"}:
            targets.append(None)
            continue
        wanted_id = str(op.get("item_id") or "").strip()
        wanted_title = str(op.get("item_title") or "").strip()
        wanted_day = op.get("day")
        found: dict[str, Any] | None = None
        for day_index, day in enumerate(itinerary_days):
            if wanted_day is not None and day.get("day") != wanted_day:
                continue
            for item_index, item in enumerate(day.get("items") or []):
                if wanted_id and str(item.get("id") or "") == wanted_id:
                    found = {"day_index": day_index, "item_index": item_index}
                    break
                if not wanted_id and wanted_title and str(item.get("title") or "") == wanted_title:
                    found = {"day_index": day_index, "item_index": item_index}
                    break
            if found:
                break
        if found is None and wanted_day is not None and not wanted_id and wanted_title:
            # day 越界时退化为全行程按标题查找，仍找不到则保持 None。
            for day_index, day in enumerate(itinerary_days):
                for item_index, item in enumerate(day.get("items") or []):
                    if str(item.get("title") or "") == wanted_title:
                        found = {"day_index": day_index, "item_index": item_index}
                        break
                if found:
                    break
        targets.append(found)
    return targets


def _first_free_slot(day: dict[str, Any]) -> str | None:
    used_slots = {str(item.get("time") or "") for item in day.get("items", []) if item.get("category") != "note"}
    for slot in TIME_SLOT_ORDER:
        if slot not in used_slots:
            return slot
    return None


def apply_operations(
    itinerary_days: list[dict[str, Any]],
    prefs: dict[str, Any],
    pois: dict[str, Any],
    ops: list[dict[str, Any]],
    targets: list[dict[str, Any] | None],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """应用增量操作（原地修改行程与 prefs），返回 (applied, skipped) 记录。"""
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    candidate_index = _candidate_index(pois)
    used_place_keys = _itinerary_used_place_keys(itinerary_days)
    claimed: set[tuple[int, int]] = set()
    dirty_days: set[int] = set()
    plan_days = max(len(itinerary_days), int(prefs.get("days") or len(itinerary_days) or 1))
    min_total_items = max(2, plan_days * 2)
    total_items = sum(len(day.get("items", [])) for day in itinerary_days)

    for op_index, op in enumerate(ops):
        action = str(op.get("action") or "")
        day_number = op.get("day")
        reason = str(op.get("reason") or "")
        base = {"action": action, "day": day_number, "reason": reason}

        if op.get("needs_confirmation"):
            skipped.append({**base, "reason": "语义待确认，未执行"})
            continue
        if action in {"answer_only"} or action not in STRUCTURAL_ACTIONS | PREFERENCE_ACTIONS:
            skipped.append({**base, "reason": "非执行类操作"})
            continue

        if action == "replace_place":
            target = targets[op_index] if op_index < len(targets) else None
            if not target:
                skipped.append({**base, "reason": "未能在计划中定位目标活动"})
                continue
            day_index, item_index = target["day_index"], target["item_index"]
            if (day_index, item_index) in claimed:
                skipped.append({**base, "reason": "该活动已有待执行变更，冲突跳过"})
                continue
            day = itinerary_days[day_index]
            item = day["items"][item_index]
            candidate_entry = candidate_index.get(str(op.get("candidate_id") or ""))
            if candidate_entry is None:
                skipped.append({**base, "reason": "候选不存在于计划候选池（拒绝模型编造）"})
                continue
            candidate_group, candidate = candidate_entry
            candidate_id = str(candidate.get("id") or "")
            if candidate_id == str(item.get("poi_id") or ""):
                skipped.append({**base, "reason": "候选与目标为同一地点"})
                continue
            if not _normalize_point(candidate.get("location")):
                skipped.append({**base, "reason": "候选缺少有效坐标，不能进入地图与路线"})
                continue
            if _candidate_place_keys(candidate) & used_place_keys:
                skipped.append({**base, "reason": "候选已被行程其他地点使用"})
                continue
            before = {"title": item.get("title"), "cost_estimate": item.get("cost_estimate"), "time": item.get("time")}
            replacement = _timeline_item(
                int(day.get("day") or 1),
                str(item.get("time") or ""),
                f"{candidate.get('name', '替换地点')}{'用餐' if candidate_group == 'food' else '游览'}",
                str(candidate.get("name") or ""),
                str(item.get("transport") or "打车/公共交通/步行"),
                str(item.get("duration") or "1-2 小时"),
                f"追问调整：{reason or '按用户要求替换为候选真实地点'}",
                candidate_group,
                candidate,
                _fallback_cost_for_category(candidate_group),
                place_source="amap_poi",
                is_real_place=True,
                validation_note="Refine 追问调整：替换为用户指定候选。",
            )
            for stale in (str(item.get("poi_id") or ""), "|".join(str(item.get(field) or "").strip() for field in ["location", "address"])):
                if stale.strip("|"):
                    used_place_keys.discard(stale)
            item.clear()
            item.update(replacement)
            for fresh in (str(item.get("poi_id") or ""), "|".join(str(item.get(field) or "").strip() for field in ["location", "address"])):
                if fresh.strip("|"):
                    used_place_keys.add(fresh)
            claimed.add((day_index, item_index))
            # 替换不改变 item 数量，保留整天的原始时间槽（无需 retime）。
            applied.append(
                {
                    **base,
                    "summary": _summary_for_replace(before, item),
                    "detail": {"before": before, "after": {"title": item.get("title"), "cost_estimate": item.get("cost_estimate")}},
                }
            )
            continue

        if action == "remove_item":
            target = targets[op_index] if op_index < len(targets) else None
            if not target:
                skipped.append({**base, "reason": "未能在计划中定位目标活动"})
                continue
            day_index, item_index = target["day_index"], target["item_index"]
            if (day_index, item_index) in claimed:
                skipped.append({**base, "reason": "该活动已有待执行变更，冲突跳过"})
                continue
            day = itinerary_days[day_index]
            item = day["items"][item_index]
            if total_items - 1 < min_total_items:
                skipped.append({**base, "reason": f"删除后行程低于 {plan_days} 天计划的最低可执行数量 {min_total_items}"})
                continue
            if _concrete_count(day) - 1 < 2:
                skipped.append({**base, "reason": "删除后当天活动+餐饮不足 2 项，已保留"})
                continue
            before = {"title": item.get("title"), "cost_estimate": item.get("cost_estimate"), "time": item.get("time")}
            removed_keys = {
                str(item.get("poi_id") or ""),
                "|".join(str(item.get(field) or "").strip() for field in ["location", "address"]),
            }
            day["items"].remove(item)
            total_items -= 1
            for stale in removed_keys:
                if stale.strip("|"):
                    used_place_keys.discard(stale)
            claimed.add((day_index, item_index))
            dirty_days.add(day_index)
            applied.append(
                {
                    **base,
                    "summary": f"已删除 {before.get('title') or ''}（{before.get('cost_estimate') or 0} 元）",
                    "detail": {"before": before, "after": None},
                }
            )
            continue

        if action == "add_activity":
            day_number_value = int(day_number) if day_number is not None else 1
            day_index = next((index for index, day in enumerate(itinerary_days) if day.get("day") == day_number_value), None)
            if day_index is None:
                skipped.append({**base, "reason": f"第 {day_number_value} 天不存在"})
                continue
            day = itinerary_days[day_index]
            if _movable_count(day) >= len(TIME_SLOT_ORDER):
                skipped.append({**base, "reason": "当天时间槽已满（5 项），无法新增"})
                continue
            candidate_entry = candidate_index.get(str(op.get("candidate_id") or ""))
            slot = str(op.get("slot") or "").strip()
            if slot not in TIME_SLOT_ORDER:
                slot = _first_free_slot(day) or ""
            if not slot:
                skipped.append({**base, "reason": "无可用时间槽"})
                continue
            if candidate_entry is not None:
                candidate_group, candidate = candidate_entry
                if _candidate_place_keys(candidate) & used_place_keys:
                    skipped.append({**base, "reason": "候选已被行程其他地点使用"})
                    continue
                title = f"{candidate.get('name', '新增活动')}{'用餐' if candidate_group == 'food' else '游览'}"
                new_item = _timeline_item(
                    int(day.get("day") or 1),
                    slot,
                    title,
                    str(candidate.get("name") or ""),
                    "打车/公共交通/步行",
                    "1-2 小时",
                    f"追问调整：{reason or '按用户要求新增候选真实地点'}",
                    candidate_group,
                    candidate,
                    _fallback_cost_for_category(candidate_group),
                    place_source="amap_poi",
                    is_real_place=True,
                    validation_note="Refine 追问调整：新增用户指定候选。",
                )
                summary = f"新增 {candidate.get('name') or ''}（{new_item.get('cost_estimate') or 0} 元，{slot}）"
            else:
                new_title = str(op.get("new_title") or "").strip() or "用户建议活动"
                new_item = _timeline_item(
                    int(day.get("day") or 1),
                    slot,
                    new_title,
                    new_title,
                    "",
                    "1-2 小时",
                    f"追问调整：{reason or '按用户建议新增（无具体候选，作为建议项展示）'}",
                    "activity",
                    None,
                    0,
                    place_source="llm_suggestion",
                    is_real_place=False,
                    validation_note="Refine 追问调整：无候选的泛化建议项，不进地图与路线。",
                )
                summary = f"新增建议项 {new_title}（{slot}）"
            day["items"].append(new_item)
            total_items += 1
            new_keys = {
                str(new_item.get("poi_id") or ""),
                "|".join(str(new_item.get(field) or "").strip() for field in ["location", "address"]),
            }
            for fresh in new_keys:
                if fresh.strip("|"):
                    used_place_keys.add(fresh)
            dirty_days.add(day_index)
            applied.append({**base, "summary": summary, "detail": {"before": None, "after": {"title": new_item.get("title"), "cost_estimate": new_item.get("cost_estimate")}}})
            continue

        if action == "adjust_budget":
            budget = op.get("budget")
            if not isinstance(budget, int) or budget <= 0:
                skipped.append({**base, "reason": "预算值无效"})
                continue
            before_budget = prefs.get("budget")
            prefs["budget"] = budget
            applied.append({**base, "summary": f"预算 {before_budget if before_budget is not None else '未设置'} → {budget} 元", "detail": {"before": before_budget, "after": budget}})
            continue

        if action == "change_pace":
            pace = str(op.get("pace") or "").strip()
            if pace not in {"轻松", "标准", "紧凑"}:
                skipped.append({**base, "reason": "节奏取值无效"})
                continue
            profile = prefs.setdefault("preferenceProfile", {})
            before_pace = profile.get("pace")
            profile["pace"] = pace
            applied.append({**base, "summary": f"节奏 {before_pace or '标准'} → {pace}", "detail": {"before": before_pace, "after": pace}})
            continue

        if action == "change_hotel_strategy":
            strategy = str(op.get("hotel_strategy") or "").strip()
            if strategy not in {"近景点", "近地铁枢纽", "近商圈"}:
                skipped.append({**base, "reason": "住宿策略取值无效"})
                continue
            profile = prefs.setdefault("preferenceProfile", {})
            before_strategy = profile.get("hotelStrategy")
            profile["hotelStrategy"] = strategy
            applied.append(
                {
                    **base,
                    "summary": f"住宿策略 {before_strategy or '近地铁枢纽'} → {strategy}（下次完整规划时生效）",
                    "detail": {"before": before_strategy, "after": strategy},
                }
            )
            continue

        skipped.append({**base, "reason": "不支持的操作类型"})

    for day_index in dirty_days:
        _retime_day_items(itinerary_days[day_index])

    return applied, skipped
