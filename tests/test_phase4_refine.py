"""Phase 4 结构化追问测试：版本链、契约、操作应用、refine_plan 编排与端点。"""

from __future__ import annotations

import copy
import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from sync.multi_agent.deepseek_brain import DeepSeekPlanningBrainAgent
from sync.multi_agent.deepseek_contracts import RefineOutput
from sync.multi_agent.plan_version import (
    bootstrap_version,
    build_explanation,
    compute_diff,
    next_version,
)
from sync.multi_agent.refine_parser import apply_operations, build_refine_payload, locate_targets
from sync.multi_agent.structured_planner import StructuredTravelPlanner
from tests.test_deepseek_contracts import _FakeModel, _RaisingModel
from tests.test_phase3_budget_loop import _RichRunToolbox, _UnavailableBrain


def _item(category: str, title: str, cost, *, poi_id: str = "p1", cluster: str = "c1", time: str = "上午", lng: float = 114.0, lat: float = 22.5) -> dict:
    return {
        "id": f"day1-{title}",
        "poi_id": poi_id,
        "time": time,
        "title": title,
        "location": title,
        "address": "深圳市南山区",
        "transport": "地铁",
        "duration": "2 小时",
        "detail": "",
        "category": category,
        "rating": 4.5,
        "cost": cost if cost else None,
        "cost_estimate": cost,
        "cost_source": "amap_cost" if cost else ("free_or_no_ticket_default" if category == "activity" else "unknown_price"),
        "price_range": None,
        "price_confidence": "unknown",
        "cost_note": "",
        "type": "",
        "cluster_id": cluster,
        "cluster_name": "测试片区",
        "nearby_anchor": "",
        "location_point": {"lng": lng, "lat": lat},
        "location_source": "amap_poi",
        "map_label": "",
        "map_included": False,
        "photo_url": "",
        "image_source": "category_fallback",
        "is_real_place": True,
        "place_source": "amap_poi",
        "validation_note": "",
    }


def _poi(poi_id: str, name: str, cost, *, cluster: str = "c1", lng: float = 114.0, lat: float = 22.5) -> dict:
    return {
        "id": poi_id,
        "name": name,
        "cost": cost,
        "cost_estimate": cost,
        "cost_source": "amap_cost" if cost else "unknown_price",
        "location": {"lng": lng, "lat": lat},
        "address": "深圳市南山区",
        "type": "展览馆" if cost is None else "餐厅",
        "rating": 4.5,
        "cluster_id": cluster,
        "cluster_name": "测试片区",
    }


def _prefs():
    return {
        "travelers": 1,
        "days": 2,
        "budget": 300,
        "hotelLevel": "舒适",
        "originCity": "广州",
        "destinationCity": "深圳",
        "preferenceProfile": {"pace": "标准", "maxTransferMinutes": 45, "hotelStrategy": "近地铁枢纽", "learnedHints": []},
        "constraintSummary": {"hard": [], "soft": [], "unknown": []},
    }


def _days():
    return [
        {
            "day": 1,
            "date": "2026-08-15",
            "theme": "t1",
            "items": [_item("food", "贵餐厅", 90, poi_id="f1", time="中午"), _item("activity", "收费景点", 120, poi_id="a1", time="下午")],
        },
        {
            "day": 2,
            "date": "2026-08-16",
            "theme": "t2",
            "items": [_item("activity", "白天活动", 100, poi_id="a2", lng=114.01), _item("hotel", "酒店休整", 0, poi_id="h1", time="下午")],
        },
    ]


def _pois():
    return {
        "attractions": [
            _poi("a2", "已用景点", 80, lng=114.06),
            _poi("a3", "便宜展览馆", 40, lng=114.02),
            _poi("a4", "免费公园", None, lng=114.03),
        ],
        "foods": [_poi("f2", "便宜面馆", 50, lng=114.05)],
        "specialty_places": [],
    }


class TravelMindPlanVersionTests(unittest.TestCase):
    def test_bootstrap_adds_version_fields_and_constraint_snapshot(self):
        plan = {"preferences": {"constraintSummary": {"hard": [{"id": "c-h-0", "text": "不要夜间"}], "soft": [], "unknown": []}}}
        bootstrap_version(plan)
        self.assertEqual(plan["version"], 0)
        self.assertEqual(plan["parent_version"], 0)
        self.assertEqual(plan["refine_history"], [])
        self.assertEqual(plan["constraint_snapshot"]["hard"][0]["text"], "不要夜间")

    def test_next_version_increments_and_records_history(self):
        plan = {"preferences": {}}
        next_version(plan, "第一条追问", [{"action": "replace_place", "day": 1}], [])
        next_version(plan, "第二条追问", [], [{"action": "remove_item", "reason": "x"}])
        self.assertEqual(plan["version"], 2)
        self.assertEqual(plan["parent_version"], 1)
        self.assertEqual(len(plan["refine_history"]), 2)
        self.assertEqual(plan["refine_history"][1]["message"], "第二条追问")

    def test_history_truncated_to_ten(self):
        plan = {"preferences": {}}
        for index in range(12):
            next_version(plan, f"追问{index}", [], [])
        self.assertEqual(plan["version"], 12)
        self.assertEqual(len(plan["refine_history"]), 10)
        self.assertEqual(plan["refine_history"][0]["message"], "追问2")

    def test_diff_locates_replaced_items_by_day(self):
        old_days = _days()
        new_days = copy.deepcopy(old_days)
        new_days[0]["items"][1] = _item("activity", "便宜展览馆游览", 40, poi_id="a3", time="下午")
        diff = compute_diff({"days": old_days, "budget": {}, "prefs": {}}, {"itinerary_days": new_days, "budget": {}, "preferences": {}})
        replaced = [entry for entry in diff["items_changed"] if entry["action"] == "replaced"]
        self.assertEqual(len(replaced), 1)
        self.assertEqual(replaced[0]["day"], 1)
        self.assertEqual(replaced[0]["before"]["title"], "收费景点")
        self.assertEqual(replaced[0]["after"]["title"], "便宜展览馆游览")
        self.assertTrue(replaced[0]["after"]["item_id"])

    def test_diff_budget_includes_verdict(self):
        diff = compute_diff(
            {"days": [], "budget": {"total": 800, "target": 500, "verdict": "over_budget"}, "prefs": {}},
            {"itinerary_days": [], "budget": {"total": 480, "target": 500, "verdict": "within_budget"}, "preferences": {}},
        )
        self.assertEqual(diff["budget"]["before"]["verdict"], "over_budget")
        self.assertEqual(diff["budget"]["after"]["verdict"], "within_budget")

    def test_diff_preferences_detects_pace_change(self):
        diff = compute_diff(
            {"days": [], "budget": {}, "prefs": {"preferenceProfile": {"pace": "标准"}}},
            {"itinerary_days": [], "budget": {}, "preferences": {"preferenceProfile": {"pace": "轻松"}}},
        )
        self.assertIn({"key": "pace", "before": "标准", "after": "轻松"}, diff["preferences"])

    def test_explanation_covers_applied_skipped_and_loop(self):
        text = build_explanation(
            [{"action": "replace_place", "day": 2, "summary": "A → B", "reason": ""}],
            [{"action": "remove_item", "day": 1, "reason": "低于下限"}],
            {"applied": [{}], "total_saved": 60},
            "已按要求处理。",
        )
        self.assertIn("已按要求处理。", text)
        self.assertIn("替换地点（第 2 天）：A → B", text)
        self.assertIn("已跳过 删除活动（第 1 天）", text)
        self.assertIn("预算循环自动调整 1 项", text)


class TravelMindRefineContractTests(unittest.TestCase):
    def test_valid_operations_round_trip(self):
        raw = (
            '{"operations": [{"action": "replace_place", "day": 2, "item_id": "day2-x", "candidate_id": "a3", "reason": "改室内"}],'
            ' "answer": ""}'
        )
        parsed = RefineOutput.model_validate_json(raw).model_dump()
        self.assertEqual(parsed["operations"][0]["action"], "replace_place")
        self.assertEqual(parsed["operations"][0]["day"], 2)

    def test_missing_operations_rejected(self):
        with self.assertRaises(ValidationError):
            RefineOutput.model_validate_json('{"answer": "只有回答"}')

    def test_missing_action_rejected(self):
        with self.assertRaises(ValidationError):
            RefineOutput.model_validate_json('{"operations": [{"day": 1}]}')

    def test_non_positive_budget_rejected(self):
        with self.assertRaises(ValidationError):
            RefineOutput.model_validate_json('{"operations": [{"action": "adjust_budget", "budget": 0}]}')

    def test_invalid_pace_rejected(self):
        with self.assertRaises(ValidationError):
            RefineOutput.model_validate_json('{"operations": [{"action": "change_pace", "pace": "很快"}]}')

    def test_invalid_hotel_strategy_rejected(self):
        with self.assertRaises(ValidationError):
            RefineOutput.model_validate_json('{"operations": [{"action": "change_hotel_strategy", "hotel_strategy": "近海边"}]}')

    def test_answer_only_requires_answer_text(self):
        with self.assertRaises(ValidationError):
            RefineOutput.model_validate_json('{"operations": []}')
        parsed = RefineOutput.model_validate_json('{"operations": [], "answer": "第一天天气晴。"}').model_dump()
        self.assertEqual(parsed["answer"], "第一天天气晴。")

    def test_extra_fields_ignored(self):
        parsed = RefineOutput.model_validate_json(
            '{"operations": [{"action": "add_activity", "day": 1, "candidate_id": "a3", "unknown_field": 1}], "answer": "", "tail": true}'
        ).model_dump()
        self.assertNotIn("unknown_field", parsed["operations"][0])
        self.assertNotIn("tail", parsed)


class TravelMindRefineBrainTests(unittest.TestCase):
    def test_parse_refine_ops_unavailable(self):
        brain = DeepSeekPlanningBrainAgent()
        brain.model = None
        result = brain.parse_refine_ops({})
        self.assertEqual(result["llm_status"], "unavailable")
        self.assertEqual(result["operations"], [])
        self.assertEqual(result["fallback_reason"], "deepseek_unavailable")

    def test_parse_refine_ops_call_failed(self):
        brain = DeepSeekPlanningBrainAgent()
        brain.model = _RaisingModel(RuntimeError("rate limited"))
        result = brain.parse_refine_ops({})
        self.assertEqual(result["llm_status"], "call_failed")
        self.assertEqual(result["error_kind"], "call")

    def test_parse_refine_ops_schema_failed(self):
        brain = DeepSeekPlanningBrainAgent()
        brain.model = _FakeModel(['{"operations": "oops"}', '{"operations": "still"}'])
        result = brain.parse_refine_ops({})
        self.assertEqual(result["llm_status"], "schema_failed")
        self.assertEqual(result["attempt_count"], 2)


class TravelMindRefineParserTests(unittest.TestCase):
    def _ops(self, *ops):
        return list(ops)

    def test_replace_rebuilds_item_with_same_slot(self):
        days = _days()
        targets = locate_targets(
            [{"action": "replace_place", "day": 1, "item_id": "day1-收费景点", "candidate_id": "a3"}], days
        )
        applied, skipped = apply_operations(days, _prefs(), _pois(), self._ops(
            {"action": "replace_place", "day": 1, "item_id": "day1-收费景点", "candidate_id": "a3", "reason": "改室内"}
        ), targets)
        self.assertEqual(len(applied), 1)
        self.assertEqual(skipped, [])
        replaced = days[0]["items"][1]
        self.assertEqual(replaced["title"], "便宜展览馆游览")
        self.assertEqual(replaced["time"], "下午")
        self.assertEqual(replaced["poi_id"], "a3")
        self.assertEqual(replaced["cost_estimate"], 40)
        self.assertTrue(replaced["is_real_place"])

    def test_replace_with_unknown_candidate_skipped(self):
        days = _days()
        ops = [{"action": "replace_place", "day": 1, "item_id": "day1-收费景点", "candidate_id": "ghost"}]
        targets = locate_targets(ops, days)
        applied, skipped = apply_operations(days, _prefs(), _pois(), ops, targets)
        self.assertEqual(applied, [])
        self.assertIn("候选不存在", skipped[0]["reason"])

    def test_replace_with_used_candidate_skipped(self):
        days = _days()
        ops = [{"action": "replace_place", "day": 1, "item_id": "day1-收费景点", "candidate_id": "a2"}]
        targets = locate_targets(ops, days)
        applied, skipped = apply_operations(days, _prefs(), _pois(), ops, targets)
        self.assertEqual(applied, [])
        self.assertIn("已被行程其他地点使用", skipped[0]["reason"])

    def test_conflicting_ops_on_same_item_first_wins(self):
        days = _days()
        ops = [
            {"action": "replace_place", "day": 1, "item_id": "day1-收费景点", "candidate_id": "a3"},
            {"action": "remove_item", "day": 1, "item_id": "day1-收费景点"},
        ]
        targets = locate_targets(ops, days)
        applied, skipped = apply_operations(days, _prefs(), _pois(), ops, targets)
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["action"], "replace_place")
        self.assertEqual(skipped[0]["reason"], "该活动已有待执行变更，冲突跳过")

    def test_remove_blocked_by_total_minimum(self):
        days = [{"day": 1, "items": [_item("activity", "唯一活动", 50, poi_id="a1")], "date": "", "theme": ""}]
        prefs = _prefs()
        prefs["days"] = 2
        ops = [{"action": "remove_item", "day": 1, "item_id": "day1-唯一活动"}]
        targets = locate_targets(ops, days)
        applied, skipped = apply_operations(days, prefs, _pois(), ops, targets)
        self.assertEqual(applied, [])
        self.assertIn("最低可执行数量", skipped[0]["reason"])

    def test_remove_blocked_by_daily_concrete_minimum(self):
        days = _days()
        days[1]["items"] = [
            _item("activity", "白天活动", 100, poi_id="a2", lng=114.01),
            _item("food", "晚餐", 90, poi_id="f9", time="晚上"),
            _item("hotel", "酒店休整", 0, poi_id="h1", time="下午"),
        ]
        ops = [{"action": "remove_item", "day": 2, "item_id": days[1]["items"][0]["id"]}]
        targets = locate_targets(ops, days)
        applied, skipped = apply_operations(days, _prefs(), _pois(), ops, targets)
        self.assertEqual(applied, [])
        self.assertIn("不足 2 项", skipped[0]["reason"])

    def test_add_blocked_when_day_full(self):
        days = [
            {
                "day": 1,
                "items": [
                    _item("activity", f"活动{index}", 10, poi_id=f"p{index}", time=slot)
                    for index, slot in enumerate(["上午", "中午", "下午", "晚上", "夜间"], 1)
                ],
            }
        ]
        ops = [{"action": "add_activity", "day": 1, "candidate_id": "a3"}]
        targets = locate_targets(ops, days)
        applied, skipped = apply_operations(days, _prefs(), _pois(), ops, targets)
        self.assertEqual(applied, [])
        self.assertIn("时间槽已满", skipped[0]["reason"])

    def test_add_with_invalid_slot_falls_back_to_free_slot(self):
        days = _days()
        ops = [{"action": "add_activity", "day": 1, "candidate_id": "a3", "slot": "凌晨"}]
        targets = locate_targets(ops, days)
        applied, _ = apply_operations(days, _prefs(), _pois(), ops, targets)
        self.assertEqual(len(applied), 1)
        self.assertEqual(len(days[0]["items"]), 3)
        added = days[0]["items"][-1]
        self.assertEqual(added["poi_id"], "a3")
        # 新增触发 retime，按 TIME_SLOTS 重排后第 3 项落在"下午"。
        self.assertEqual(added["time"], "下午")

    def test_add_without_candidate_becomes_suggestion(self):
        days = _days()
        ops = [{"action": "add_activity", "day": 1, "new_title": "自由散步", "reason": "用户建议"}]
        targets = locate_targets(ops, days)
        applied, _ = apply_operations(days, _prefs(), _pois(), ops, targets)
        self.assertEqual(len(applied), 1)
        added = days[0]["items"][-1]
        self.assertFalse(added["is_real_place"])
        self.assertEqual(added["place_source"], "llm_suggestion")

    def test_day_out_of_range_skipped(self):
        days = _days()
        ops = [{"action": "replace_place", "day": 9, "item_id": "whatever", "candidate_id": "a3"}]
        targets = locate_targets(ops, days)
        applied, skipped = apply_operations(days, _prefs(), _pois(), ops, targets)
        self.assertEqual(applied, [])
        self.assertIn("未能在计划中定位", skipped[0]["reason"])

    def test_item_id_takes_priority_over_title(self):
        days = _days()
        ops = [{"action": "replace_place", "day": 1, "item_id": "day1-收费景点", "item_title": "不存在的标题", "candidate_id": "a3"}]
        targets = locate_targets(ops, days)
        applied, _ = apply_operations(days, _prefs(), _pois(), ops, targets)
        self.assertEqual(len(applied), 1)

    def test_adjust_budget_updates_prefs(self):
        days = _days()
        prefs = _prefs()
        ops = [
            {"action": "adjust_budget", "budget": 0},
            {"action": "adjust_budget", "budget": 600},
        ]
        targets = locate_targets(ops, days)
        applied, skipped = apply_operations(days, prefs, _pois(), ops, targets)
        self.assertEqual(len(applied), 1)
        self.assertEqual(skipped[0]["reason"], "预算值无效")
        self.assertEqual(prefs["budget"], 600)

    def test_change_pace_and_hotel_strategy_update_prefs(self):
        days = _days()
        prefs = _prefs()
        ops = [
            {"action": "change_pace", "pace": "轻松"},
            {"action": "change_hotel_strategy", "hotel_strategy": "近商圈"},
        ]
        targets = locate_targets(ops, days)
        applied, _ = apply_operations(days, prefs, _pois(), ops, targets)
        self.assertEqual(len(applied), 2)
        self.assertEqual(prefs["preferenceProfile"]["pace"], "轻松")
        self.assertEqual(prefs["preferenceProfile"]["hotelStrategy"], "近商圈")

    def test_needs_confirmation_ops_never_execute(self):
        days = _days()
        ops = [{"action": "replace_place", "day": 1, "item_id": "day1-收费景点", "candidate_id": "a3", "needs_confirmation": True}]
        targets = locate_targets(ops, days)
        applied, skipped = apply_operations(days, _prefs(), _pois(), ops, targets)
        self.assertEqual(applied, [])
        self.assertIn("语义待确认", skipped[0]["reason"])


class _RefineBrain(_UnavailableBrain):
    """追问解析替身：脚本化 operations；其余脑调用走不可用降级。"""

    def __init__(self, operations=None, answer="", status="used"):
        self.operations = operations or []
        self.answer = answer
        self.status = status

    def parse_refine_ops(self, payload):
        if self.status != "used":
            return {"llm_status": self.status, "reason": "fake refine failure", "operations": []}
        return {"llm_status": "used", "reason": "", "operations": self.operations, "answer": self.answer}


def _base_plan(budget=5000, free_text=""):
    planner = StructuredTravelPlanner("fixture://phase4-base")
    planner.toolbox = _RichRunToolbox()
    planner.deepseek_brain = _UnavailableBrain()
    payload = {
        "originCity": "广州",
        "destinationCity": "深圳",
        "startDate": "2026-08-15",
        "days": 2,
        "budget": budget,
    }
    if free_text:
        payload["freeText"] = free_text
    return planner.run(payload)


def _unused_candidate(base):
    """保证存在未使用候选：池中找不到就注入一个（refine 只消费 plan.pois）。"""
    used_ids = {item.get("poi_id") for day in base["itinerary_days"] for item in day["items"]}
    unused = next((poi for poi in base["pois"]["attractions"] if poi["id"] not in used_ids), None)
    if unused is None:
        unused = {
            "id": "refine-injected-1",
            "name": "室内科学馆",
            "cost": 40,
            "cost_estimate": 40,
            "cost_source": "amap_cost",
            "location": {"lng": 114.091, "lat": 22.551},
            "address": "深圳市南山区",
            "type": "展览馆",
            "rating": 4.4,
            "cluster_id": "cluster-1",
            "cluster_name": "cluster-1片区",
        }
        base["pois"]["attractions"].append(copy.deepcopy(unused))
    return unused


def _refine(base, operations=None, answer="", status="used"):
    planner = StructuredTravelPlanner("fixture://phase4-refine")
    planner.toolbox = _RichRunToolbox()
    planner.deepseek_brain = _RefineBrain(operations=operations, answer=answer, status=status)
    return planner.refine_plan(base, "把第二天改成室内，预算不变")


class TravelMindRefinePlanTests(unittest.TestCase):
    def test_replace_only_affects_target_day(self):
        base = _base_plan()
        day2_activity = next(item for item in base["itinerary_days"][1]["items"] if item["category"] == "activity")
        unused = _unused_candidate(base)
        base_before = copy.deepcopy(base)
        response = _refine(
            base,
            operations=[{"action": "replace_place", "day": 2, "item_id": day2_activity["id"], "candidate_id": unused["id"], "reason": "改室内"}],
        )
        self.assertEqual(response["status"], "ok")
        self.assertTrue(response["changed"])
        old_day1 = base_before["itinerary_days"][0]
        new_day1 = response["plan"]["itinerary_days"][0]
        self.assertEqual(
            [(item["title"], item["time"], item["cost_estimate"]) for item in old_day1["items"]],
            [(item["title"], item["time"], item["cost_estimate"]) for item in new_day1["items"]],
        )
        new_day2_titles = [item["title"] for item in response["plan"]["itinerary_days"][1]["items"]]
        self.assertIn(unused["name"], " ".join(new_day2_titles))
        self.assertEqual(response["plan"]["version"], 1)

    def test_parse_failure_keeps_plan_untouched(self):
        base = _base_plan()
        base_before = copy.deepcopy(base)
        response = _refine(base, status="schema_failed")
        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["plan"], base_before)
        self.assertIsNone(response["diff"])

    def test_answer_only_returns_plan_unchanged(self):
        base = _base_plan()
        base_before = copy.deepcopy(base)
        response = _refine(base, operations=[], answer="第一天以户外为主，室内偏少。")
        self.assertEqual(response["status"], "ok")
        self.assertFalse(response["changed"])
        self.assertEqual(response["plan"], base_before)
        self.assertIn("第一天以户外为主", response["explanation"])

    def test_adjust_budget_triggers_loop_and_diff(self):
        base = _base_plan()
        response = _refine(base, operations=[{"action": "adjust_budget", "budget": 200}])
        self.assertEqual(response["status"], "ok")
        self.assertTrue(response["plan"]["budget_adjustments"]["applied"])
        self.assertEqual(response["diff"]["budget"]["after"]["verdict"], "over_budget")
        self.assertIn("预算循环自动调整", response["explanation"])
        self.assertEqual(response["plan"]["preferences"]["budget"], 200)

    def test_gate_violation_recorded_after_refine(self):
        base = _base_plan(budget=400, free_text="不要超出预算，总花费不超过 400 元")
        response = _refine(base, operations=[{"action": "adjust_budget", "budget": 100}])
        violations = response["plan"]["quality_review"].get("gate_violations") or []
        self.assertTrue(any("预算内完成" in v["message"] for v in violations))

    def test_two_refines_build_version_chain(self):
        base = _base_plan()
        day2_activity = next(item for item in base["itinerary_days"][1]["items"] if item["category"] == "activity")
        unused = _unused_candidate(base)
        first = _refine(
            base,
            operations=[{"action": "replace_place", "day": 2, "item_id": day2_activity["id"], "candidate_id": unused["id"]}],
        )
        second_plan = first["plan"]
        second = _refine(second_plan, operations=[{"action": "adjust_budget", "budget": 300}])
        self.assertEqual(second["plan"]["version"], 2)
        self.assertEqual(second["plan"]["parent_version"], 1)
        self.assertEqual(len(second["plan"]["refine_history"]), 2)

    def test_refine_payload_carries_ids_types_and_pool(self):
        base = _base_plan()
        payload = build_refine_payload(base)
        self.assertTrue(payload["days"][0]["items"])
        self.assertIn("item_id", payload["days"][0]["items"][0])
        self.assertTrue(any(entry["candidate_id"] for entry in payload["candidate_pool"]))
        self.assertTrue(any(entry.get("type") for entry in payload["candidate_pool"]))
        self.assertIn("message", payload) if "message" in payload else None


class TravelMindRefineEndpointTests(unittest.TestCase):
    def _client(self, planner):
        from fastapi.testclient import TestClient

        from sync import travel_web_app as web

        web._structured_planner = planner
        return TestClient(web.app)

    def test_refine_plan_endpoint_success_shape(self):
        base = _base_plan()
        day2_activity = next(item for item in base["itinerary_days"][1]["items"] if item["category"] == "activity")
        unused = _unused_candidate(base)
        planner = StructuredTravelPlanner("fixture://phase4-http")
        planner.toolbox = _RichRunToolbox()
        planner.deepseek_brain = _RefineBrain(
            operations=[{"action": "replace_place", "day": 2, "item_id": day2_activity["id"], "candidate_id": unused["id"]}]
        )
        client = self._client(planner)
        response = client.post("/api/refine-plan", json={"plan": base, "message": "把第二天改成室内"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["changed"])
        self.assertEqual(data["plan"]["version"], 1)
        self.assertTrue(data["diff"]["items_changed"])

    def test_refine_plan_endpoint_rejects_incomplete_plan(self):
        planner = StructuredTravelPlanner("fixture://phase4-http-400")
        planner.deepseek_brain = _RefineBrain()
        client = self._client(planner)
        response = client.post("/api/refine-plan", json={"plan": {}, "message": "随便改改"})
        self.assertEqual(response.status_code, 400)


class TravelMindRefineFrontendTests(unittest.TestCase):
    def _source(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "web", "app.js"), encoding="utf-8") as handle:
            return handle.read()

    def test_send_message_routes_to_refine_endpoint(self):
        source = self._source()
        self.assertIn("/api/refine-plan", source)
        self.assertIn("currentPlanData", source)

    def test_legacy_fallback_is_labeled(self):
        self.assertIn("旧链路文本回答，未修改当前计划", self._source())

    def test_version_badge_rendered(self):
        self.assertIn("计划已更新到 v", self._source())


if __name__ == "__main__":
    unittest.main()
