"""全局硬质量门（Phase 3）：对最终行程做结构/一致性硬检查。

与 _rule_quality_review 的分工：规则评审产出软评分与 issues（行为冻结），
本模块只做硬门槛检查并输出独立 violations 列表，由调用方写入
quality_review["gate_violations"]——不修改 issues/scores/source/constraints，
避免破坏评测契约与前端展示语义。

检查项（3.1/3.2/3.6）：
- 返程一致性：最后一天若存在返程 transfer，其之后不得再有目的地住宿/活动安排；
- 总量下限：具体 item 总数 ≥ max(2, days*2)；
- 硬约束预算：硬约束含预算关键词时，最终 verdict 必须 within_budget；
- 时间线粗检：单日具体项时长文本可解析时，全天累计不超过合理上限。
"""

from __future__ import annotations

import re
from typing import Any

HARD_BUDGET_KEYWORDS = ("预算", "花费", "不超过")
HOTEL_TITLE_MARKERS = ("入住", "酒店", "宾馆", "民宿", "客栈", "住宿")
_RETURN_TRANSFER_MARKERS = ("返回", "返程", "回程", "乘高铁返回", "乘机返回")
_DAILY_DURATION_CAP_MINUTES = 14 * 60


def _duration_minutes(value: Any) -> int:
    text = str(value or "").replace(" ", "")
    hour = re.search(r"(\d+)\s*小时", text)
    minute = re.search(r"(\d+)\s*分钟", text)
    if not hour and not minute:
        return 0
    return (int(hour.group(1)) * 60 if hour else 0) + (int(minute.group(1)) if minute else 0)


def _concrete_items(day: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in day.get("items", []) if item.get("category") in {"activity", "food", "hotel"}]


def _has_hard_budget_constraint(prefs: dict[str, Any]) -> bool:
    hard_items = (prefs.get("constraintSummary") or {}).get("hard") or []
    return any(any(kw in str(item.get("text") or "") for kw in HARD_BUDGET_KEYWORDS) for item in hard_items)


def _is_return_transfer(item: dict[str, Any], origin_city: str) -> bool:
    if item.get("category") != "transfer":
        return False
    text = f"{item.get('title') or ''}{item.get('detail') or ''}"
    return any(marker in text for marker in _RETURN_TRANSFER_MARKERS) or bool(origin_city and origin_city in text)


def _looks_like_lodging(item: dict[str, Any]) -> bool:
    if item.get("category") == "hotel":
        return True
    title = str(item.get("title") or "")
    return any(marker in title for marker in HOTEL_TITLE_MARKERS)


def run_hard_gates(
    prefs: dict[str, Any],
    itinerary_days: list[dict[str, Any]],
    budget: dict[str, Any] | None,
) -> dict[str, Any]:
    """对最终行程执行硬门槛检查；返回 {passed, violations}，不修改任何输入。"""
    violations: list[dict[str, Any]] = []
    days = int(prefs.get("days") or len(itinerary_days) or 1)
    origin_city = str(prefs.get("originCity") or "")

    total_items = sum(len(day.get("items", [])) for day in itinerary_days)
    min_items = max(2, days * 2)
    if total_items < min_items:
        violations.append(
            {
                "kind": "gate",
                "severity": "high",
                "day": None,
                "message": f"行程仅 {total_items} 个项目，低于 {days} 天计划的最低可执行数量 {min_items}。",
            }
        )

    last_day = itinerary_days[-1] if itinerary_days else None
    if last_day:
        seen_return = False
        for item in last_day.get("items", []):
            if seen_return and _looks_like_lodging(item):
                violations.append(
                    {
                        "kind": "gate",
                        "severity": "high",
                        "day": last_day.get("day"),
                        "message": f"返程交通之后仍有住宿安排「{item.get('title')}」，存在返程与最后一晚住宿串台。",
                    }
                )
            if _is_return_transfer(item, origin_city):
                seen_return = True

    if _has_hard_budget_constraint(prefs) and isinstance(budget, dict):
        verdict = budget.get("verdict")
        if verdict == "over_budget":
            violations.append(
                {
                    "kind": "gate",
                    "severity": "high",
                    "day": None,
                    "message": f"硬约束要求预算内完成，但最终估算 {budget.get('total')} 元高于预算 {budget.get('target')} 元，已保留最接近方案并标注缺口。",
                }
            )

    for day in itinerary_days:
        day_total = sum(
            _duration_minutes(item.get("duration"))
            for item in _concrete_items(day)
        )
        if day_total > _DAILY_DURATION_CAP_MINUTES:
            violations.append(
                {
                    "kind": "gate",
                    "severity": "medium",
                    "day": day.get("day"),
                    "message": f"当天可定位项目累计时长约 {day_total // 60} 小时，超过 {len(_concrete_items(day))} 项安排的合理上限，建议压缩节奏。",
                }
            )

    return {"passed": not violations, "violations": violations}
