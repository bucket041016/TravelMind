"""Phase 3 预算反馈循环与硬质量门测试。

优化器是纯规则模块（零 LLM/工具调用），单元测试用合成数据精确控制每个
杠杆的触发与节省额；run() 级测试用扩展版文本 fixture 验证端到端调整。
"""

from __future__ import annotations

import copy
import os
import unittest
from unittest.mock import patch

from sync.multi_agent.budget_optimizer import run_budget_feedback_loop
from sync.multi_agent.quality_gate import run_hard_gates
from sync.multi_agent.structured_planner import StructuredTravelPlanner


def _poi(poi_id: str, name: str, cost, *, cluster: str = "c1", lng: float = 114.0, lat: float = 22.5) -> dict:
    return {
        "id": poi_id,
        "name": name,
        "cost": cost,
        "cost_estimate": cost,
        "cost_source": "amap_cost" if cost else "unknown_price",
        "location": {"lng": lng, "lat": lat},
        "address": "深圳市南山区",
        "type": "景点" if cost is None else "餐厅",
        "rating": 4.5,
        "cluster_id": cluster,
        "cluster_name": "测试片区",
    }


def _item(category: str, title: str, cost, *, poi_id: str = "p1", cluster: str = "c1", time: str = "中午", lng: float = 114.0, lat: float = 22.5) -> dict:
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


def _prefs(budget=300, hard=None) -> dict:
    return {
        "travelers": 1,
        "days": 2,
        "budget": budget,
        "hotelLevel": "舒适",
        "originCity": "广州",
        "destinationCity": "深圳",
        "constraintSummary": {"hard": hard or [], "soft": [], "unknown": []},
    }


_ROUTES = {"recommended": "rail", "options": [], "raw": "【高铁/城际铁路】广州南 -> 深圳北，票价约 75 元。"}
_LOCAL = {"recommended_modes": ["transit"], "segments": [], "notes": []}


def _hotels(costs=(400, 200)) -> dict:
    return {
        "area_recommendation": "测试片区",
        "provider_status": "fixture",
        "candidates": [
            _item("hotel", f"酒店{index}", cost, poi_id=f"h{index}", cluster="h1")
            for index, cost in enumerate(costs, 1)
        ],
    }


def _days():
    return [
        {"day": 1, "date": "2026-08-15", "theme": "t1", "items": [_item("food", "贵餐厅", 90, poi_id="f1"), _item("activity", "贵景点", 120, poi_id="a1")]},
        {"day": 2, "date": "2026-08-16", "theme": "t2", "items": [_item("activity", "另一个景点", 100, poi_id="a2", lng=114.01), _item("hotel", "酒店住宿", 0, poi_id="h1", time="下午")]},
    ]


def _pool():
    return {
        "attractions": [
            _poi("a3", "便宜景点", 40, lng=114.02),
            _poi("a4", "免费公园", None, lng=114.03),
            _poi("a5", "另一个便宜景点", 30, lng=114.04),
        ],
        "foods": [_poi("f2", "便宜餐厅", 50, lng=114.05)],
        "specialty_places": [],
    }


def _run_loop(prefs, days, hotels, pois, **kwargs):
    return run_budget_feedback_loop(prefs, _ROUTES, _LOCAL, hotels, days, pois, **kwargs)


class TravelMindBudgetOptimizerTests(unittest.TestCase):
    def test_lever_priority_replace_first_then_hotel_then_trim(self):
        days = _days()
        hotels = _hotels()
        result = _run_loop(_prefs(budget=300), days, hotels, _pool())
        levers = [action["lever"] for action in result["applied"]]
        self.assertTrue(levers)
        self.assertEqual(levers, sorted(levers, key=lambda lever: {"replace": 0, "hotel_strategy": 1, "trim": 2}[lever]))

    def test_replacement_uses_cheaper_same_cluster_candidate(self):
        days = _days()
        hotels = _hotels()
        result = _run_loop(_prefs(budget=760), days, hotels, _pool())
        replace_actions = [a for a in result["applied"] if a["lever"] == "replace"]
        self.assertEqual(len(replace_actions), 1)
        action = replace_actions[0]
        self.assertEqual(action["before"]["cost"], 120)
        self.assertEqual(action["after"]["cost"], 0)
        self.assertEqual(action["saved"], 120)
        replaced = days[0]["items"][1]
        self.assertEqual(replaced["title"], "免费公园游览")
        self.assertEqual(replaced["cost_estimate"], 0)
        self.assertEqual(result["gap_after"], 0)
        self.assertEqual(result["final_verdict"], "within_budget")

    def test_replacement_accepts_free_candidate(self):
        days = [
            {"day": 1, "date": "2026-08-15", "theme": "t1", "items": [_item("activity", "收费景点", 55, poi_id="a9")]},
        ]
        hotels = _hotels(costs=(200,))
        result = _run_loop(_prefs(budget=410), days, hotels, {"attractions": [_poi("a4", "免费公园", None)], "foods": [], "specialty_places": []})
        replace_actions = [a for a in result["applied"] if a["lever"] == "replace"]
        self.assertTrue(replace_actions)
        self.assertEqual(replace_actions[0]["after"]["cost"], 0)
        self.assertEqual(days[0]["items"][0]["cost_estimate"], 0)
        self.assertEqual(days[0]["items"][0]["title"], "免费公园游览")

    def test_no_candidates_records_skip_and_stops(self):
        days = _days()
        hotels = _hotels(costs=(200,))
        pool = {"attractions": [], "foods": [_poi("f1", "贵餐厅", 90)], "specialty_places": []}
        result = _run_loop(_prefs(budget=300), days, hotels, pool)
        self.assertEqual(result["applied"], [])
        self.assertTrue(any(s.get("lever") == "loop" for s in result["skipped"]))
        self.assertEqual(result["gap_after"], result["gap_before"])

    def test_round_limit_leaves_gap(self):
        days = _days()
        hotels = _hotels()
        result = _run_loop(_prefs(budget=300), days, hotels, _pool(), max_rounds=2)
        self.assertLessEqual(result["rounds_used"], 2)
        self.assertGreater(result["gap_after"], 0)
        self.assertEqual(result["final_verdict"], "over_budget")

    def test_flag_off_leaves_inputs_untouched(self):
        days = _days()
        days_before = copy.deepcopy(days)
        hotels = _hotels()
        hotels_before = copy.deepcopy(hotels)
        with patch.dict(os.environ, {"TRAVELMIND_BUDGET_LOOP": "off"}):
            result = _run_loop(_prefs(budget=300), days, hotels, _pool())
        self.assertFalse(result["enabled"])
        self.assertEqual(days, days_before)
        self.assertEqual(hotels, hotels_before)

    def test_no_budget_disables_loop(self):
        days = _days()
        prefs = _prefs()
        prefs["budget"] = None
        result = _run_loop(prefs, days, _hotels(), _pool())
        self.assertFalse(result["enabled"])

    def test_trim_never_removes_night_items(self):
        days = [
            {"day": 1, "date": "2026-08-15", "theme": "t1", "items": [_item("activity", "夜间演出", 200, poi_id="n1", time="夜间")]},
            {"day": 2, "date": "2026-08-16", "theme": "t2", "items": [_item("activity", "白天活动", 150, poi_id="a2", time="上午"), _item("food", "餐厅", 90, poi_id="f1", time="中午")]},
        ]
        hotels = _hotels(costs=(150,))
        pool = {"attractions": [_poi("a3", "便宜景点", 40)], "foods": [], "specialty_places": []}
        result = _run_loop(_prefs(budget=300), days, hotels, pool, max_rounds=2)
        removed_titles = [a["before"]["title"] for a in result["applied"] if a["lever"] == "trim"]
        self.assertNotIn("夜间演出", removed_titles)
        # 夜间项可被替换（继承时间槽），但不得被删减；时间槽保持夜间。
        night_items = [item for item in days[0]["items"] if "演出" in item["title"] or item["time"] == "夜间"]
        self.assertTrue(night_items)
        self.assertEqual(night_items[0]["time"], "夜间")

    def test_actions_are_deterministic(self):
        first = _run_loop(_prefs(budget=300), _days(), _hotels(), _pool())
        second = _run_loop(_prefs(budget=300), _days(), _hotels(), _pool())
        self.assertEqual(first["applied"], second["applied"])
        self.assertEqual(first["total_saved"], second["total_saved"])

    def test_loop_makes_no_tool_calls(self):
        planner = StructuredTravelPlanner("fixture://phase3-loop")

        class _RecordingToolbox:
            def __init__(self):
                self.calls = []

            def call(self, tool_name, **kwargs):
                self.calls.append(tool_name)
                return ""

            def call_text(self, tool_name, **kwargs):
                self.call(tool_name, **kwargs)
                return ""

            def call_structured(self, tool_name, **kwargs):
                self.call(tool_name, **kwargs)
                return None

        toolbox = _RecordingToolbox()
        planner.toolbox = toolbox
        planner._run_budget_feedback_loop(_prefs(budget=300), _ROUTES, _LOCAL, _hotels(), _days(), _pool())
        self.assertEqual(toolbox.calls, [])


class TravelMindQualityGateTests(unittest.TestCase):
    def test_return_transfer_followed_by_lodging_is_violation(self):
        days = [
            {"day": 1, "items": [_item("activity", "景点", 0)]},
            {
                "day": 2,
                "items": [
                    _item("activity", "景点", 0, poi_id="a2"),
                    _item("transfer", "深圳北站乘高铁返回广州", 0, poi_id="t1", time="晚上"),
                    _item("hotel", "入住广州酒店", 0, poi_id="h9", time="夜间"),
                ],
            },
        ]
        result = run_hard_gates(_prefs(), days, {"verdict": "within_budget", "total": 100, "target": 200})
        self.assertFalse(result["passed"])
        self.assertTrue(any("串台" in v["message"] for v in result["violations"]))

    def test_lodging_before_return_transfer_passes(self):
        days = [
            {"day": 1, "items": [_item("activity", "景点", 0)]},
            {
                "day": 2,
                "items": [
                    _item("hotel", "酒店休整", 0, poi_id="h1", time="下午"),
                    _item("transfer", "深圳北站乘高铁返回广州", 0, poi_id="t1", time="晚上"),
                ],
            },
        ]
        result = run_hard_gates(_prefs(), days, {"verdict": "within_budget", "total": 100, "target": 200})
        self.assertFalse(any("串台" in v["message"] for v in result["violations"]))

    def test_item_count_below_minimum_is_violation(self):
        days = [{"day": 1, "items": [_item("activity", "唯一活动", 0)]}]
        result = run_hard_gates(_prefs(), days, None)
        self.assertTrue(any("最低可执行数量" in v["message"] for v in result["violations"]))

    def test_hard_budget_constraint_requires_within_verdict(self):
        hard = [{"id": "c-h-0", "kind": "hard", "text": "总花费不超过 500 元", "source": "input"}]
        result = run_hard_gates(_prefs(hard=hard), _days(), {"verdict": "over_budget", "total": 800, "target": 500})
        self.assertTrue(any("预算内完成" in v["message"] for v in result["violations"]))

        no_budget_keyword = run_hard_gates(_prefs(), _days(), {"verdict": "over_budget", "total": 800, "target": 500})
        self.assertFalse(any("预算内完成" in v["message"] for v in no_budget_keyword["violations"]))

    def test_overlong_day_timeline_is_violation(self):
        long_item = _item("activity", "全天活动", 0)
        long_item["duration"] = "8 小时"
        another = _item("activity", "又一个活动", 0, poi_id="a2")
        another["duration"] = "7 小时"
        days = [
            {"day": 1, "items": [long_item, another]},
            {"day": 2, "items": [_item("food", "餐厅", 0, poi_id="f1"), _item("activity", "活动", 0, poi_id="a3")]},
        ]
        result = run_hard_gates(_prefs(), days, None)
        self.assertTrue(any("累计时长" in v["message"] and v.get("day") == 1 for v in result["violations"]))

    def test_gate_does_not_mutate_inputs(self):
        days = _days()
        days_before = copy.deepcopy(days)
        prefs = _prefs()
        prefs_before = copy.deepcopy(prefs)
        budget = {"verdict": "within_budget", "total": 100, "target": 200}
        run_hard_gates(prefs, days, budget)
        self.assertEqual(days, days_before)
        self.assertEqual(prefs, prefs_before)


class _RichRunToolbox:
    """run() 级测试替身：候选池比行程更丰富，保证存在未使用的低价候选。"""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool_name, **kwargs):
        return self.call_text(tool_name, **kwargs)

    def call_text(self, tool_name, **kwargs):
        self.calls.append((tool_name, kwargs))
        if tool_name == "get_weather":
            return f"{kwargs.get('city')}：晴，24-30°C，风力 2 级"
        if tool_name == "search_poi":
            return "\n".join(
                [
                    "【景点/活动】",
                    "1. 深圳湾公园（公园；评分 4.6；地址：深圳市南山区；坐标：114.057900,22.543100）",
                    "2. 收费主题乐园（主题公园；评分 4.5；地址：深圳市南山区；坐标：114.067900,22.553100；人均约 120 元）",
                    "3. 便宜展览馆（展览馆；评分 4.4；地址：深圳市南山区；坐标：114.077900,22.543100；人均约 40 元）",
                    "4. 备用美术馆（美术馆；评分 4.2；地址：深圳市南山区；坐标：114.087900,22.547100）",
                    "【美食/餐厅】",
                    "1. 贵海鲜酒楼（海鲜餐厅；评分 4.6；地址：深圳市南山区；坐标：114.061900,22.545100；人均约 160 元）",
                    "2. 便宜茶餐厅（茶餐厅；评分 4.4；地址：深圳市南山区；坐标：114.062900,22.545900；人均约 55 元）",
                    "【特色店铺参考】",
                    "1. 小吃店（小吃店；评分 4.3；地址：深圳市南山区；坐标：114.101900,22.555100；人均约 30 元）",
                ]
            )
        if tool_name == "search_hotels":
            return "\n".join(
                [
                    "【酒店候选】",
                    "1. 贵酒店（舒适型；评分 4.4；地址：深圳市南山区；坐标：114.058500,22.544000；人均约 420 元）",
                    "2. 便宜酒店（舒适型；评分 4.2；地址：深圳市南山区；坐标：114.058600,22.544100；人均约 220 元）",
                    "住宿区域建议：深圳湾公园周边。",
                    "provider_status=amap_fallback",
                ]
            )
        if tool_name == "amap_plan_routes":
            modes = str(kwargs.get("modes") or "")
            if "rail" in modes or "driving" in modes:
                return "\n".join(
                    [
                        "高德路线规划结果",
                        "【高铁/城际铁路】",
                        "1. 广州南站 -> 深圳北站，车程约 35 分钟，票价约 75 元。",
                    ]
                )
            return "驾车路线：从前一站到后一站，距离约 1.2 km，耗时约 6 分钟。"
        return "fixture response"

    def call_structured(self, tool_name, **kwargs):
        from sync.mcp_tools_adapter import MCPToolResult

        return MCPToolResult.from_value(tool_name, self.call_text(tool_name, **kwargs))


class _UnavailableBrain:
    def _result(self, key: str):
        return {"llm_status": "unavailable", "reason": "offline fixture", key: None}

    def plan(self, payload):
        return self._result("plan")

    def estimate_hotel_prices(self, payload):
        return self._result("prices")

    def judge_route(self, payload):
        return self._result("judgement")

    def review_itinerary(self, payload):
        return self._result("review")


class TravelMindBudgetLoopRunTests(unittest.TestCase):
    def _run(self, budget, free_text="", flag="on"):
        planner = StructuredTravelPlanner("fixture://phase3-run")
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
        with patch.dict(os.environ, {"TRAVELMIND_BUDGET_LOOP": flag}):
            return planner.run(payload)

    def test_low_budget_run_applies_adjustments(self):
        response = self._run(budget=500)
        adjustments = response["budget_adjustments"]
        self.assertTrue(adjustments["enabled"])
        self.assertTrue(adjustments["applied"])
        self.assertGreater(adjustments["total_saved"], 0)
        self.assertLessEqual(adjustments["rounds_used"], 2)
        self.assertTrue(any(step["name"].startswith("BudgetOptimizerAgent") for step in response["trace"]))
        self.assertIn("adjustments", response["budget"])
        # 调整后总预算低于不调整参照（同输入 flag off）
        reference = self._run(budget=500, flag="off")
        self.assertLess(response["budget"]["total"], reference["budget"]["total"])

    def test_flag_off_run_keeps_legacy_behavior(self):
        response = self._run(budget=500, flag="off")
        self.assertFalse(response["budget_adjustments"]["enabled"])
        self.assertEqual(response["budget_adjustments"]["applied"], [])
        self.assertNotIn("gate_violations", response["quality_review"])
        self.assertNotIn("BudgetOptimizerAgent", [step["name"] for step in response["trace"]])

    def test_gate_violations_surface_without_touching_issues(self):
        response = self._run(budget=200, free_text="不要超出预算，总花费不超过 200 元")
        review = response["quality_review"]
        self.assertTrue(review.get("gate_violations"))
        self.assertTrue(any("预算内完成" in v["message"] for v in review["gate_violations"]))
        self.assertIsInstance(review.get("issues"), list)

    def test_normal_budget_run_makes_no_adjustment(self):
        response = self._run(budget=5000)
        adjustments = response["budget_adjustments"]
        self.assertTrue(adjustments["enabled"])
        self.assertEqual(adjustments["applied"], [])
        self.assertEqual(adjustments["gap_after"], 0)


if __name__ == "__main__":
    unittest.main()
