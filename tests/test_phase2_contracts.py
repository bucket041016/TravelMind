from __future__ import annotations

import unittest

from sync.mcp_tools_adapter import MCPToolResult
from sync.multi_agent.candidate_ranker import filter_candidates, rank_candidates
from sync.multi_agent.contracts import candidate_key, normalize_point
from sync.multi_agent.fact_normalizer import (
    normalize_place_candidate,
    normalize_route_fact,
    normalize_weather_fact,
)
from sync.multi_agent.structured_planner import StructuredTravelPlanner


class TravelMindPhase2ContractTests(unittest.TestCase):
    def test_point_and_place_contract_normalize_legacy_fields(self):
        self.assertEqual(normalize_point("114.0579,22.5431"), {"lng": 114.0579, "lat": 22.5431})
        self.assertIsNone(normalize_point("not-a-point"))

        candidate = normalize_place_candidate(
            {
                "id": "poi-1",
                "name": "室内博物馆",
                "address": "深圳市南山区",
                "location": "114.0579,22.5431",
                "rating": 4.6,
                "cost": 80,
            },
            city="深圳",
            category="activity",
            provider_status="fixture",
        )

        self.assertEqual(candidate["location"], {"lng": 114.0579, "lat": 22.5431})
        self.assertTrue(candidate["is_real_place"])
        self.assertFalse(candidate["is_suggestion"])
        self.assertEqual(candidate["validation"]["status"], "valid")
        self.assertEqual(candidate["source_meta"]["status"], "fixture")
        self.assertEqual(candidate["price_range"]["unit"], "person")

    def test_fallback_candidate_is_marked_partial_and_not_real(self):
        candidate = normalize_place_candidate(
            {"id": "fallback-1", "name": "核心商圈活动区域", "description": "规则建议"},
            city="深圳",
            category="activity",
            source="rule_fallback",
            provider_status="rule_fallback",
        )

        self.assertFalse(candidate["is_real_place"])
        self.assertTrue(candidate["is_suggestion"])
        self.assertEqual(candidate["validation"]["status"], "partial")
        self.assertIn("missing_coordinates", candidate["validation"]["errors"])
        self.assertEqual(candidate["source_meta"]["kind"], "rule")
        self.assertEqual(candidate["source_meta"]["status"], "rule_fallback")

    def test_hotel_route_and_weather_contracts_keep_source_metadata(self):
        hotel = normalize_place_candidate(
            {
                "id": "hotel-1",
                "name": "地铁站酒店",
                "address": "深圳市南山区",
                "location": {"lng": 114.058, "lat": 22.544},
                "price_range": "320-520",
            },
            city="深圳",
            category="hotel",
            source="hotel_poi",
            provider_status="amap_fallback",
        )
        self.assertEqual(hotel["price_range"]["min"], 320.0)
        self.assertEqual(hotel["price_range"]["max"], 520.0)
        self.assertEqual(hotel["price_range"]["unit"], "night")
        self.assertEqual(hotel["source_meta"]["kind"], "amap")

        route = normalize_route_fact(
            "公交换乘：3.2 km，18 分钟，票价约 4 元。",
            origin="酒店",
            destination="餐厅",
            mode="transit",
            provider_status="fixture",
        )
        self.assertEqual(route["distance_km"], 3.2)
        self.assertEqual(route["duration_minutes"], 18)
        self.assertEqual(route["price"], 4.0)
        self.assertEqual(route["source_meta"]["status"], "fixture")

        weather = normalize_weather_fact(
            "深圳：小雨，气温 24~30°C，降水概率 60%，风力 3 级。",
            city="深圳",
            date="2026-08-01",
            source="amap_weather",
            provider_status="live",
        )
        self.assertEqual(weather["min_temp_c"], 24.0)
        self.assertEqual(weather["max_temp_c"], 30.0)
        self.assertEqual(weather["rain_probability"], 60.0)
        self.assertEqual(weather["source_meta"]["status"], "live")

    def test_filter_rejects_duplicates_exclusions_city_and_price(self):
        candidates = [
            {"id": "good", "name": "室内博物馆", "city": "深圳", "is_real_place": True, "location": {"lng": 114.0, "lat": 22.0}, "cost_estimate": 80},
            {"id": "good", "name": "重复博物馆", "city": "深圳", "is_real_place": True, "location": {"lng": 114.1, "lat": 22.1}, "cost_estimate": 80},
            {"id": "other-city", "name": "外地景点", "city": "广州", "is_real_place": True, "location": {"lng": 113.3, "lat": 23.1}, "cost_estimate": 50},
            {"id": "excluded", "name": "夜游活动", "city": "深圳", "is_real_place": True, "location": {"lng": 114.0, "lat": 22.0}, "cost_estimate": 50},
            {"id": "expensive", "name": "高价馆", "city": "深圳", "is_real_place": True, "location": {"lng": 114.0, "lat": 22.0}, "cost_estimate": 500},
        ]
        result = filter_candidates(
            candidates,
            expected_city="深圳",
            excluded_terms=["夜游"],
            require_coordinates=True,
            require_real_place=True,
            max_price=200,
        )

        self.assertEqual([item["id"] for item in result["accepted"]], ["good"])
        rejected_reasons = {reason for item in result["rejected"] for reason in item["reasons"]}
        self.assertTrue({"duplicate_candidate", "city_mismatch", "excluded_by_preference", "over_price_limit"}.issubset(rejected_reasons))

    def test_rank_returns_stable_explanations_and_preference_order(self):
        candidates = [
            {
                "id": "outdoor",
                "name": "滨水公园",
                "type": "公园",
                "address": "深圳市南山区",
                "city": "深圳",
                "rating": 4.8,
                "location": {"lng": 114.08, "lat": 22.55},
                "is_real_place": True,
            },
            {
                "id": "indoor",
                "name": "城市艺术馆",
                "type": "博物馆",
                "address": "深圳市南山区",
                "city": "深圳",
                "rating": 4.2,
                "location": {"lng": 114.01, "lat": 22.01},
                "is_real_place": True,
            },
        ]
        result = rank_candidates(
            candidates,
            expected_city="深圳",
            preferences=["室内", "博物馆"],
            anchor={"lng": 114.0, "lat": 22.0},
            weather="小雨",
            require_coordinates=True,
            require_real_place=True,
        )

        self.assertEqual(result["selected"][0]["id"], "indoor")
        selection = result["selected"][0]["selection"]
        self.assertEqual(selection["status"], "selected")
        self.assertTrue(selection["reasons"])
        self.assertEqual(candidate_key(result["selected"][0]), "id:indoor")

    def test_planner_contract_filters_legacy_candidates_without_changing_source_lists(self):
        planner = StructuredTravelPlanner("fixture://phase2")
        prefs = planner._normalize_preferences({"destinationCity": "深圳", "hardConstraints": ["不要夜游"]})
        pois = {
            "attractions": [
                {"id": "real", "name": "室内馆", "address": "深圳市南山区", "location": {"lng": 114.0, "lat": 22.0}, "rating": 4.5},
                {"id": "suggestion", "name": "泛化区域建议", "description": "没有坐标"},
            ],
            "specialty_places": [],
            "foods": [],
            "raw": "fixture POI",
        }
        hotels = {
            "area_recommendation": "近地铁",
            "candidates": [
                {"id": "hotel", "name": "地铁站酒店", "address": "深圳市南山区", "location": {"lng": 114.01, "lat": 22.01}},
            ],
            "provider_status": "fixture",
            "raw": "fixture hotel",
        }

        contracts = planner._build_candidate_contracts(prefs, pois, hotels, {"深圳": "晴，24~30°C"})

        self.assertEqual(contracts["version"], "travelmind-candidate-v1")
        self.assertEqual(contracts["source_mode"], "legacy_text_compatible")
        self.assertEqual([item["id"] for item in contracts["pois"]["attractions"]], ["real"])
        self.assertEqual([item["id"] for item in contracts["hotels"]], ["hotel"])
        self.assertEqual([item["id"] for item in pois["attractions"]], ["real", "suggestion"])

    def test_planning_payload_uses_contract_candidates_when_present(self):
        planner = StructuredTravelPlanner("fixture://phase2")
        prefs = planner._normalize_preferences({"destinationCity": "深圳"})
        ranked_poi = {
            "id": "ranked-poi",
            "name": "排序候选",
            "category": "activity",
            "location": {"lng": 114.0, "lat": 22.0},
            "is_real_place": True,
            "selection": {"score": 90, "reasons": ["有效坐标"]},
        }
        payload, lookup = planner._planning_brain_payload(
            prefs,
            {"recommended": "rail", "options": []},
            {"recommended_modes": [], "segments": []},
            {"area_recommendation": "近地铁", "candidates": [], "candidate_contracts": [{"id": "ranked-hotel", "name": "排序酒店", "location": {"lng": 114.01, "lat": 22.01}}]},
            {"attractions": [{"id": "legacy-poi", "name": "旧候选", "location": {"lng": 114.0, "lat": 22.0}}], "foods": [], "specialty_places": [], "candidate_contracts": {"attractions": [ranked_poi], "specialty_places": [], "foods": []}},
            {},
            {},
        )

        self.assertIn("ranked-poi", lookup)
        self.assertNotIn("legacy-poi", lookup)
        self.assertEqual([item["id"] for item in payload["candidates"]], ["ranked-poi", "ranked-hotel"])
        self.assertEqual(payload["candidates"][0]["selection"]["score"], 90)


class _FakeRunToolbox:
    """run() 全链路离线替身：按工具名返回稳定文本（格式与评测 fixture 一致）。"""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool_name: str, **kwargs):
        return self.call_text(tool_name, **kwargs)

    def call_text(self, tool_name: str, **kwargs) -> str:
        self.calls.append((tool_name, kwargs))
        if tool_name == "get_weather":
            return f"{kwargs.get('city')}：晴，24-30°C，风力 2 级"
        if tool_name == "search_poi":
            return "\n".join(
                [
                    "【景点/活动】",
                    "1. 深圳湾公园（公园；评分 4.6；地址：深圳市南山区深圳湾公园附近；坐标：114.057900,22.543100）",
                    "2. 海上世界文化艺术中心（博物馆；评分 4.5；地址：深圳市南山区海上世界附近；坐标：114.127900,22.563100）",
                    "【美食/餐厅】",
                    "1. 潮汕牛肉店（餐厅；评分 4.4；地址：深圳市福田区潮汕牛肉店附近；坐标：114.061900,22.545100；人均约 90 元）",
                    "【特色店铺参考】",
                    "1. 南头古城小吃店（小吃店；评分 4.3；地址：深圳市南山区南头古城附近；坐标：114.101900,22.555100；人均约 55 元）",
                ]
            )
        if tool_name == "search_hotels":
            return "\n".join(
                [
                    "【酒店候选】",
                    "1. 后海地铁站智选酒店（舒适型；评分 4.4；地址：深圳市南山区后海地铁站附近；坐标：114.058500,22.544000；人均约 420 元）",
                    "住宿区域建议：后海地铁站、深圳湾公园周边，便于换乘和晚间返程。",
                    "provider_status=amap_fallback",
                ]
            )
        if tool_name == "amap_plan_routes":
            modes = str(kwargs.get("modes") or "")
            if "rail" in modes or "driving" in modes:
                return "\n".join(
                    [
                        "高德路线规划结果",
                        f"出发地：{kwargs.get('origin_city')}南站（113.264400,23.129100）",
                        f"目的地：{kwargs.get('destination_city')}北站（114.057900,22.543100）",
                        "【高铁/城际铁路】",
                        "1. 广州南站 -> 深圳北站，车程约 35 分钟，票价约 75-120 元。",
                        "【驾车】",
                        "1. 约 1 小时 50 分钟，距离约 137 km，过路费约 70 元。",
                    ]
                )
            return "\n".join(
                [
                    "驾车路线：从前一站到后一站，距离约 3.2 km，耗时约 9 分钟。",
                ]
            )
        return "fixture response"

    def call_structured(self, tool_name: str, **kwargs):
        return MCPToolResult.from_value(tool_name, self.call_text(tool_name, **kwargs))


class _UnavailableBrain:
    """run() 全链路离线替身：所有 LLM 调用走规则降级，保证结果确定。"""

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


class TravelMindCandidateContractsWiringTests(unittest.TestCase):
    """D2：run() 产出可选、版本化 candidate_contracts，旧字段保持兼容。"""

    def test_run_wires_candidate_contracts_and_keeps_legacy_fields(self):
        planner = StructuredTravelPlanner("fixture://phase2-d2")
        planner.toolbox = _FakeRunToolbox()
        planner.deepseek_brain = _UnavailableBrain()

        response = planner.run(
            {
                "originCity": "广州",
                "destinationCity": "深圳",
                "startDate": "2026-08-15",
                "days": 2,
            }
        )

        contracts = response["candidate_contracts"]
        self.assertEqual(contracts["version"], "travelmind-candidate-v1")
        self.assertEqual(contracts["source_mode"], "legacy_text_compatible")
        self.assertTrue(contracts["pois"]["attractions"])
        self.assertTrue(contracts["pois"]["foods"])
        self.assertTrue(contracts["hotels"])
        for group in ("attractions", "foods", "specialty_places"):
            for item in contracts["pois"][group]:
                self.assertTrue(item.get("location") or item.get("is_real_place"))
                self.assertEqual(item["selection"]["status"], "selected")
                self.assertTrue(item["selection"]["reasons"])
                self.assertIn("provider", item["source_meta"])
        self.assertIn("cluster_id", contracts["pois"]["attractions"][0])
        self.assertEqual(contracts["hotels"][0]["name"], "后海地铁站智选酒店")

        self.assertIn("attractions", response["pois"])
        self.assertIn("foods", response["pois"])
        self.assertIn("candidates", response["hotels"])
        self.assertIn("area_recommendation", response["hotels"])
        self.assertIn("itinerary_days", response)
        self.assertIn("markdown", response)
        self.assertIn("trace", response)
        self.assertIn("planning_mode", response)
        self.assertEqual(
            len(response["candidate_contracts"]["pois"]["attractions"]),
            len([item for item in response["pois"]["attractions"] if item.get("location") or item.get("is_real_place")]),
        )


if __name__ == "__main__":
    unittest.main()
