"""计划版本与 Diff（Phase 4）：结构化追问的版本链与变更说明。

版本语义：plan["version"] 从 0（初始 /api/plan 产物）起，每次成功 refine +1；
parent_version 记录父版本；refine_history 追加每次追问的摘要（截断保留最近
10 条）。constraint_snapshot 在首次引导时从 preferences.constraintSummary
落盘（本轮 refine 不改约束文本，diff 的 constraints_changed 恒为空，字段为
后续版本预留）。

服务端无状态：refine 请求携带完整计划 JSON，diff 以「重算前快照 vs 重算后
最终 plan」计算——budget loop 的自动调整与用户操作一并可见。
"""

from __future__ import annotations

import copy
from typing import Any

HISTORY_LIMIT = 10
PREF_DIFF_KEYS = ("budget", "pace", "hotelStrategy", "maxTransferMinutes", "hotelLevel")


def _constraint_snapshot(prefs: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    summary = prefs.get("constraintSummary") or {}
    snapshot: dict[str, list[dict[str, Any]]] = {}
    for kind in ("hard", "soft", "unknown"):
        entries = summary.get(kind) or []
        snapshot[kind] = [
            {"id": str(item.get("id") or ""), "text": str(item.get("text") or "")}
            for item in entries
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
    return snapshot


def bootstrap_version(plan: dict[str, Any]) -> dict[str, Any]:
    """旧计划（无版本字段）原地引导到 v0 结构。"""
    plan.setdefault("version", 0)
    plan.setdefault("parent_version", 0)
    plan.setdefault("refine_history", [])
    if "constraint_snapshot" not in plan:
        plan["constraint_snapshot"] = _constraint_snapshot(plan.get("preferences") or {})
    return plan


def next_version(
    plan: dict[str, Any],
    message: str,
    applied: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> dict[str, Any]:
    """推进到下一版本：version+1、parent_version 回填、history 追加并截断。"""
    bootstrap_version(plan)
    old_version = int(plan.get("version") or 0)
    plan["parent_version"] = old_version
    plan["version"] = old_version + 1
    history = plan.setdefault("refine_history", [])
    history.append(
        {
            "version": plan["version"],
            "message": str(message or ""),
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "applied": copy.deepcopy(applied),
            "skipped": copy.deepcopy(skipped),
        }
    )
    plan["refine_history"] = history[-HISTORY_LIMIT:]
    return plan


def _item_key(item: dict[str, Any]) -> str:
    poi_id = str(item.get("poi_id") or "").strip()
    if poi_id:
        return f"id:{poi_id}"
    return f"text:{str(item.get('title') or '').strip()}|{str(item.get('time') or '').strip()}"


def _compact_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": str(item.get("id") or ""),
        "poi_id": str(item.get("poi_id") or ""),
        "title": str(item.get("title") or ""),
        "time": str(item.get("time") or ""),
        "category": str(item.get("category") or ""),
        "cost_estimate": item.get("cost_estimate"),
    }


def _items_diff(old_days: list[dict[str, Any]], new_days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old_by_day = {day.get("day"): day.get("items") or [] for day in old_days}
    new_by_day = {day.get("day"): day.get("items") or [] for day in new_days}
    changes: list[dict[str, Any]] = []

    for day_number in sorted(set(old_by_day) | set(new_by_day), key=lambda value: (value is None, value)):
        old_items = old_by_day.get(day_number) or []
        new_items = new_by_day.get(day_number) or []
        old_keys = {_item_key(item) for item in old_items}
        new_keys = {_item_key(item) for item in new_items}
        removed = [item for item in old_items if _item_key(item) not in new_keys]
        added = [item for item in new_items if _item_key(item) not in old_keys]

        # 同类别的一删一增配对为 replaced（预算循环/用户替换的常见形态）。
        remaining_added = list(added)
        for old_item in removed:
            match = next(
                (candidate for candidate in remaining_added if candidate.get("category") == old_item.get("category")),
                None,
            )
            if match is not None:
                remaining_added.remove(match)
                changes.append(
                    {
                        "day": day_number,
                        "action": "replaced",
                        "before": _compact_item(old_item),
                        "after": _compact_item(match),
                    }
                )
            else:
                changes.append({"day": day_number, "action": "removed", "before": _compact_item(old_item), "after": None})
        for new_item in remaining_added:
            changes.append({"day": day_number, "action": "added", "before": None, "after": _compact_item(new_item)})

    return changes


def _prefs_diff(old_prefs: dict[str, Any], new_prefs: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    old_profile = old_prefs.get("preferenceProfile") or {}
    new_profile = new_prefs.get("preferenceProfile") or {}
    for key in PREF_DIFF_KEYS:
        old_value = old_profile.get(key) if key in {"pace", "hotelStrategy", "maxTransferMinutes"} else old_prefs.get(key)
        new_value = new_profile.get(key) if key in {"pace", "hotelStrategy", "maxTransferMinutes"} else new_prefs.get(key)
        if old_value != new_value:
            changes.append({"key": key, "before": old_value, "after": new_value})
    return changes


def compute_diff(old_snapshot: dict[str, Any], new_plan: dict[str, Any]) -> dict[str, Any]:
    """以「重算前快照 vs 重算后最终 plan」计算结构化 Diff。"""
    old_budget = old_snapshot.get("budget") or {}
    new_budget = new_plan.get("budget") or {}
    return {
        "items_changed": _items_diff(old_snapshot.get("days") or [], new_plan.get("itinerary_days") or []),
        "budget": {
            "before": {
                "total": old_budget.get("total"),
                "target": old_budget.get("target"),
                "verdict": old_budget.get("verdict"),
            },
            "after": {
                "total": new_budget.get("total"),
                "target": new_budget.get("target"),
                "verdict": new_budget.get("verdict"),
            },
        },
        "preferences": _prefs_diff(old_snapshot.get("prefs") or {}, new_plan.get("preferences") or {}),
        "constraints_changed": [],
    }


ACTION_LABELS = {
    "replace_place": "替换地点",
    "remove_item": "删除活动",
    "add_activity": "新增活动",
    "adjust_budget": "调整预算",
    "change_pace": "调整节奏",
    "change_hotel_strategy": "调整住宿策略",
    "answer_only": "回答",
}


def build_explanation(
    applied: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    budget_adjustments: dict[str, Any] | None,
    answer: str = "",
) -> str:
    """把应用/跳过的操作与预算循环副作用整理为面向用户的中文摘要。"""
    lines: list[str] = []
    if answer.strip():
        lines.append(answer.strip())
    for item in applied:
        label = ACTION_LABELS.get(item.get("action"), item.get("action") or "调整")
        day_text = f"（第 {item.get('day')} 天）" if item.get("day") else ""
        lines.append(f"{label}{day_text}：{item.get('summary') or ''}{('；' + item['reason']) if item.get('reason') else ''}")
    for item in skipped:
        label = ACTION_LABELS.get(item.get("action"), item.get("action") or "调整")
        day_text = f"（第 {item.get('day')} 天）" if item.get("day") else ""
        lines.append(f"已跳过 {label}{day_text}：{item.get('reason') or '无法安全执行'}")
    loop_applied = (budget_adjustments or {}).get("applied") or []
    if loop_applied:
        lines.append(
            f"预算循环自动调整 {len(loop_applied)} 项，合计节省约 {(budget_adjustments or {}).get('total_saved') or 0} 元（调整期估算）。"
        )
    if not lines:
        lines.append("本次未产生可执行的修改。")
    return "\n".join(lines)
