from __future__ import annotations

import unittest
from pathlib import Path

from sync.multi_agent.structured_planner import StructuredTravelPlanner
from sync.travel_web_app import amap_static_marker_label


class FakeToolbox:
    def __init__(self, responses: dict[str, str] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool_name: str, **kwargs):
        self.calls.append((tool_name, kwargs))
        response = self.responses.get(tool_name)
        if isinstance(response, Exception):
            raise response
        return response or ""


class FakeHotelBrain:
    def __init__(self, status: str = "used"):
        self.status = status

    def estimate_hotel_prices(self, payload):
        if self.status != "used":
            return {"llm_status": self.status, "reason": "offline", "prices": []}
        first = payload["candidates"][0]
        return {
            "llm_status": "used",
            "reason": "",
            "prices": [
                {
                    "candidate_id": first["candidate_id"],
                    "estimated_price_range": "320-520",
                    "price_confidence": "low",
                    "price_note": "AI 常识估算，需以酒店平台实时房价和房态为准。",
                }
            ],
        }


class FakeRouteJudgeBrain:
    def __init__(self, judgement: dict | None = None, status: str = "used"):
        self.judgement = judgement or {"decision": "accept", "risk_level": "low", "judge_reason": "可接受。"}
        self.status = status
        self.payloads: list[dict] = []

    def judge_route(self, payload):
        self.payloads.append(payload)
        if self.status != "used":
            return {"llm_status": self.status, "reason": "offline", "judgement": None}
        return {"llm_status": "used", "reason": "", "judgement": self.judgement}

    def estimate_hotel_prices(self, payload):
        return {"llm_status": "unavailable", "reason": "unused", "prices": []}


class FakeItineraryReviewBrain:
    def __init__(self, review: dict, status: str = "used"):
        self.review = review
        self.status = status
        self.payloads: list[dict] = []

    def review_itinerary(self, payload):
        self.payloads.append(payload)
        if self.status != "used":
            return {"llm_status": self.status, "reason": "offline", "review": None}
        return {"llm_status": "used", "reason": "", "review": self.review}

    def judge_route(self, payload):
        return {"llm_status": "unavailable", "reason": "unused", "judgement": None}

    def estimate_hotel_prices(self, payload):
        return {"llm_status": "unavailable", "reason": "unused", "prices": []}


def planner_with_toolbox(toolbox: FakeToolbox) -> StructuredTravelPlanner:
    planner = StructuredTravelPlanner("http://unused")
    planner.toolbox = toolbox
    return planner


class TravelMindRegressionTests(unittest.TestCase):
    def test_local_transport_segments_use_real_adjacent_places_only(self):
        toolbox = FakeToolbox(
            {
                "amap_plan_routes": (
                    "高德路线规划结果\n"
                    "出发地：酒店（114.000000,22.000000）\n"
                    "目的地：餐厅（114.030000,22.000000）\n\n"
                    "【公交/地铁】\n"
                    "1. 公交换乘：3.2 km，18 分钟，票价约 4 元，步行约 300 m。\n"
                    "   换乘方案：地铁1号线"
                )
            }
        )
        planner = planner_with_toolbox(toolbox)
        day = {
            "day": 1,
            "items": [
                {
                    "id": "hotel-1",
                    "title": "入住酒店",
                    "location": "酒店",
                    "address": "酒店地址",
                    "category": "hotel",
                    "is_real_place": True,
                    "place_source": "hotel_poi",
                    "location_point": {"lng": 114.0, "lat": 22.0},
                },
                {
                    "id": "note-1",
                    "title": "休息说明",
                    "category": "note",
                    "is_real_place": False,
                    "place_source": "planning_note",
                    "location_point": None,
                },
                {
                    "id": "food-1",
                    "title": "餐厅晚餐",
                    "location": "餐厅",
                    "address": "餐厅地址",
                    "category": "food",
                    "is_real_place": True,
                    "place_source": "amap_poi",
                    "location_point": {"lng": 114.03, "lat": 22.0},
                },
            ],
        }

        result = planner._build_local_transport_segments(
            {"destinationCity": "深圳", "localModes": ["transit", "taxi", "walking"]},
            {"recommended_modes": ["transit", "taxi", "walking"], "notes": []},
            [day],
        )

        self.assertEqual(len(result["segments"]), 1)
        segment = result["segments"][0]
        self.assertEqual(segment["from_detail"], "酒店地址")
        self.assertEqual(segment["to_detail"], "餐厅地址")
        self.assertEqual(segment["source"], "amap_route")
        self.assertEqual(segment["cost_estimate"], 4)
        self.assertEqual(day["items"][2]["arrival_transport_segment"]["source"], "amap_route")

    def test_local_transport_segments_fallback_when_amap_fails(self):
        toolbox = FakeToolbox({"amap_plan_routes": "【公交/地铁】查询失败：CUQPS"})
        planner = planner_with_toolbox(toolbox)
        day = {
            "day": 1,
            "items": [
                {
                    "id": "a",
                    "location": "A",
                    "category": "activity",
                    "is_real_place": True,
                    "place_source": "amap_poi",
                    "location_point": {"lng": 114.0, "lat": 22.0},
                },
                {
                    "id": "b",
                    "location": "B",
                    "category": "activity",
                    "is_real_place": True,
                    "place_source": "amap_poi",
                    "location_point": {"lng": 114.03, "lat": 22.0},
                },
            ],
        }

        result = planner._build_local_transport_segments(
            {"destinationCity": "深圳", "localModes": ["transit"]},
            {"recommended_modes": ["transit"], "notes": []},
            [day],
        )

        self.assertEqual(result["segments"][0]["source"], "rule_fallback")
        self.assertEqual(result["segments"][0]["status"], "fallback")
        self.assertIn("降级", result["segments"][0]["warning"])

    def test_deepseek_route_judge_switches_unreasonable_transit(self):
        toolbox = FakeToolbox(
            {
                "amap_plan_routes": (
                    "【公交/地铁】\n"
                    "1. 公交换乘：93.4 km，5 小时 19 分钟，票价约 12 元。\n"
                    "   换乘方案：92路步行街对面 -> 龙鹏建材城路口"
                )
            }
        )
        planner = planner_with_toolbox(toolbox)
        planner.deepseek_brain = FakeRouteJudgeBrain(
            {
                "decision": "switch_mode",
                "suggested_mode": "taxi",
                "risk_level": "high",
                "judge_reason": "公交耗时过长，旅行体验不合理，建议改打车或重排。",
            }
        )
        day = {
            "day": 1,
            "items": [
                {
                    "id": "a",
                    "location": "A",
                    "category": "activity",
                    "is_real_place": True,
                    "place_source": "amap_poi",
                    "location_point": {"lng": 113.80, "lat": 22.50},
                },
                {
                    "id": "b",
                    "location": "B",
                    "category": "activity",
                    "is_real_place": True,
                    "place_source": "amap_poi",
                    "location_point": {"lng": 114.70, "lat": 22.90},
                },
            ],
        }

        result = planner._build_local_transport_segments(
            {"destinationCity": "深圳", "localModes": ["transit", "taxi"]},
            {"recommended_modes": ["transit", "taxi"], "notes": []},
            [day],
            {},
        )

        segment = result["segments"][0]
        self.assertFalse(segment["status"] == "success" and segment["mode"] == "transit")
        self.assertEqual(segment["status"], "mode_switched")
        self.assertEqual(segment["mode"], "taxi")
        self.assertEqual(segment["judge_source"], "deepseek")
        self.assertEqual(segment["judge_decision"], "switch_mode")
        self.assertIn("距离规则估算", segment["price"])

    def test_deepseek_route_judge_replaces_far_activity_with_real_candidate(self):
        planner = planner_with_toolbox(FakeToolbox())
        planner.deepseek_brain = FakeRouteJudgeBrain(
            {
                "decision": "replace_place",
                "replacement_candidate_id": "near-c",
                "risk_level": "medium",
                "judge_reason": "后一站太远，替换成同片区景点更合理。",
            }
        )
        day = {
            "day": 1,
            "items": [
                {
                    "id": "a",
                    "poi_id": "start-a",
                    "title": "A游览",
                    "location": "A",
                    "category": "activity",
                    "is_real_place": True,
                    "place_source": "amap_poi",
                    "location_point": {"lng": 114.0, "lat": 22.0},
                },
                {
                    "id": "b",
                    "poi_id": "far-b",
                    "title": "B游览",
                    "location": "B",
                    "category": "activity",
                    "is_real_place": True,
                    "place_source": "amap_poi",
                    "location_point": {"lng": 115.0, "lat": 22.0},
                },
            ],
        }
        pois = {
            "attractions": [
                {"id": "far-b", "name": "B", "address": "远处", "location": {"lng": 115.0, "lat": 22.0}},
                {"id": "near-c", "name": "C近景点", "address": "近处", "location": {"lng": 114.01, "lat": 22.0}},
            ],
            "specialty_places": [],
            "foods": [],
        }

        result = planner._build_local_transport_segments(
            {"destinationCity": "深圳", "localModes": ["taxi"]},
            {"recommended_modes": ["taxi"], "notes": []},
            [day],
            pois,
        )

        self.assertEqual(day["items"][1]["location"], "C近景点")
        self.assertEqual(result["segments"][0]["judge_decision"], "replace_place")
        self.assertEqual(result["segments"][0]["replacement_candidate_id"], "near-c")
        self.assertLess(result["segments"][0]["distance_km"], 2)

    def test_route_judge_unavailable_blocks_long_transit_with_rule_fallback(self):
        toolbox = FakeToolbox(
            {
                "amap_plan_routes": (
                    "【公交/地铁】\n"
                    "1. 公交换乘：93.4 km，5 小时 19 分钟，票价约 12 元。"
                )
            }
        )
        planner = planner_with_toolbox(toolbox)
        planner.deepseek_brain = FakeRouteJudgeBrain(status="unavailable")
        day = {
            "day": 1,
            "items": [
                {
                    "id": "a",
                    "location": "A",
                    "category": "activity",
                    "is_real_place": True,
                    "place_source": "amap_poi",
                    "location_point": {"lng": 113.80, "lat": 22.50},
                },
                {
                    "id": "b",
                    "location": "B",
                    "category": "activity",
                    "is_real_place": True,
                    "place_source": "amap_poi",
                    "location_point": {"lng": 114.70, "lat": 22.90},
                },
            ],
        }

        result = planner._build_local_transport_segments(
            {"destinationCity": "深圳", "localModes": ["transit"]},
            {"recommended_modes": ["transit"], "notes": []},
            [day],
            {},
        )

        segment = result["segments"][0]
        self.assertEqual(segment["status"], "impractical")
        self.assertEqual(segment["judge_source"], "rule_fallback")
        self.assertEqual(segment["judge_decision"], "mark_impractical")
        self.assertIn("不建议", segment["warning"])

    def test_hotel_ai_price_range_and_category_fallback(self):
        raw_hotels = "\n".join(
            [
                "深圳 酒店 POI 搜索结果（舒适档，provider_status=amap_fallback）",
                "住宿区域建议：建议住在核心商圈。",
                "",
                "【酒店候选】",
                "1. 样例酒店（南山区，评分 4.6，酒店）；地址：科技园；坐标：114.010000,22.540000",
                "",
                "出行提示：酒店候选来自高德 POI，不代表实时房态。",
            ]
        )
        prefs = {"destinationCity": "深圳", "hotelLevel": "舒适", "startDate": "2026-07-14"}

        planner = planner_with_toolbox(FakeToolbox({"search_hotels": raw_hotels}))
        planner.deepseek_brain = FakeHotelBrain("used")
        ai_result = planner._build_hotels(prefs)
        self.assertEqual(ai_result["candidates"][0]["cost_source"], "ai_price_range")
        self.assertEqual(ai_result["candidates"][0]["price_range"]["unit"], "night")

        fallback_planner = planner_with_toolbox(FakeToolbox({"search_hotels": raw_hotels}))
        fallback_planner.deepseek_brain = FakeHotelBrain("unavailable")
        fallback_result = fallback_planner._build_hotels(prefs)
        self.assertEqual(fallback_result["candidates"][0]["cost_source"], "category_rule")

    def test_hotel_match_reason_names_nearby_landmarks(self):
        raw_hotels = "\n".join(
            [
                "深圳 酒店 POI 搜索结果（高端档，provider_status=amap_fallback）",
                "住宿区域建议：建议住在深圳核心商圈、地铁枢纽或第一天重点景点附近。",
                "",
                "【酒店候选】",
                "1. 枫宜酒店（评分 4.3，高端酒店，深圳国际会展中心塘尾地铁站店）；地址：福永街道凤塘大道6号新田大厦8-12层；坐标：113.820000,22.730000",
                "2. 夏威夷国际酒店（评分 4.5，会展店）；地址：展城社区桥和路318号(福海西地铁站D口步行300米)；坐标：113.810000,22.720000",
                "",
                "出行提示：酒店候选来自高德 POI，不代表实时房态。",
            ]
        )
        planner = planner_with_toolbox(FakeToolbox({"search_hotels": raw_hotels}))
        planner.deepseek_brain = FakeHotelBrain("unavailable")

        result = planner._build_hotels({"destinationCity": "深圳", "hotelLevel": "高端", "startDate": "2026-07-14"})

        self.assertIn("深圳国际会展中心", result["candidates"][0]["match_reason"])
        self.assertIn("塘尾地铁站", result["candidates"][0]["match_reason"])
        self.assertIn("福海西地铁站D口步行300米", result["candidates"][1]["match_reason"])
        self.assertNotIn("核心商圈/地铁枢纽/第一天重点景点", result["candidates"][0]["match_reason"])
        self.assertIn("深圳国际会展中心", result["area_recommendation"])

    def test_return_transfer_does_not_reuse_hotel_area_as_lodging(self):
        planner = planner_with_toolbox(FakeToolbox())
        days = planner._materialize_llm_itinerary(
            {
                "days": [
                    {
                        "day": 1,
                        "theme": "返程收尾",
                        "items": [
                            {
                                "title": "深圳站/福田站 -> 广州南站（高铁）",
                                "category": "transfer",
                                "transport": "rail",
                                "duration": "约30-75分钟",
                                "detail": "从东门老街地铁站前往深圳站或福田站，乘坐高铁返回广州，建议预留充足时间。",
                                "estimated_price_range": "60-90",
                                "price_confidence": "medium",
                                "price_note": "火车票实时接口未配置，具体车次、票价、余票请以12306为准。",
                            }
                        ],
                    }
                ]
            },
            {"originCity": "广州", "destinationCity": "深圳", "startDate": "2026-07-14", "days": 1},
            {"recommended": "rail", "options": []},
            {"recommended_modes": ["transit", "taxi"]},
            {"area_recommendation": "建议优先住在黄田地铁站D口步行320米、沙头角海山地铁站周边，减少换乘和搬运行李。"},
            {},
        )

        item = days[0]["items"][0]
        self.assertEqual(item["location"], "深圳站/福田站 → 广州南站")
        self.assertEqual(item["transport"], "高铁/动车/城际")
        self.assertEqual(item["place_source"], "transport_note")
        self.assertFalse(item["is_real_place"])
        self.assertNotIn("建议优先住在", item["location"])
        self.assertIn("返程交通说明", item["validation_note"])

    def test_rule_fallback_itinerary_prefers_same_cluster(self):
        planner = planner_with_toolbox(FakeToolbox())
        pois = {
            "attractions": [
                {"id": "a1", "name": "近景点1", "address": "A片区", "location": {"lng": 114.00, "lat": 22.00}},
                {"id": "a2", "name": "近景点2", "address": "A片区", "location": {"lng": 114.01, "lat": 22.00}},
                {"id": "a3", "name": "近景点3", "address": "A片区", "location": {"lng": 114.02, "lat": 22.00}},
                {"id": "b1", "name": "远景点", "address": "B片区", "location": {"lng": 114.80, "lat": 22.50}},
            ],
            "specialty_places": [],
            "foods": [
                {"id": "f1", "name": "近餐厅1", "address": "A片区", "location": {"lng": 114.015, "lat": 22.00}},
                {"id": "f2", "name": "近餐厅2", "address": "A片区", "location": {"lng": 114.018, "lat": 22.00}},
            ],
        }
        hotels = {
            "area_recommendation": "近 A 片区",
            "candidates": [
                {"id": "h1", "name": "近酒店", "address": "A片区", "location": {"lng": 114.005, "lat": 22.00}},
            ],
        }
        planner._enrich_place_clusters(pois, hotels)
        days = planner._build_itinerary_days(
            {
                "originCity": "广州",
                "destinationCity": "深圳",
                "startDate": "2026-07-14",
                "days": 1,
                "preferenceProfile": {"pace": "标准", "learnedHints": []},
            },
            {"recommended": "rail", "options": []},
            {"recommended_modes": ["walking", "taxi"], "notes": []},
            hotels,
            pois,
            {},
        )
        planner._assign_day_primary_clusters(days)

        real_clusters = {
            item.get("cluster_id")
            for item in days[0]["items"]
            if item.get("cluster_id") and item.get("category") in {"activity", "food", "hotel", "transfer"}
        }
        self.assertEqual(len(real_clusters), 1)
        self.assertEqual(days[0]["primary_cluster"]["cluster_id"], next(iter(real_clusters)))

    def test_relaxed_less_bus_preferences_affect_modes_and_density(self):
        planner = planner_with_toolbox(FakeToolbox())
        prefs = {
            "originCity": "广州",
            "destinationCity": "深圳",
            "startDate": "2026-07-14",
            "days": 1,
            "localModes": ["transit", "taxi", "walking"],
            "preferenceProfile": {"pace": "轻松", "learnedHints": ["少公交", "别太赶"]},
        }
        local_transport = planner._build_local_transport(prefs, {"recommended": "rail"}, {"area_recommendation": "近地铁"})
        self.assertLess(local_transport["recommended_modes"].index("taxi"), local_transport["recommended_modes"].index("transit"))

        pois = {
            "attractions": [
                {"id": "a1", "name": "景点1", "address": "片区", "location": {"lng": 114.00, "lat": 22.00}},
                {"id": "a2", "name": "景点2", "address": "片区", "location": {"lng": 114.01, "lat": 22.00}},
                {"id": "a3", "name": "景点3", "address": "片区", "location": {"lng": 114.02, "lat": 22.00}},
            ],
            "specialty_places": [],
            "foods": [
                {"id": "f1", "name": "餐厅1", "address": "片区", "location": {"lng": 114.015, "lat": 22.00}},
                {"id": "f2", "name": "餐厅2", "address": "片区", "location": {"lng": 114.018, "lat": 22.00}},
            ],
        }
        hotels = {"area_recommendation": "近地铁", "candidates": []}
        planner._enrich_place_clusters(pois, hotels)
        days = planner._build_itinerary_days(
            prefs,
            {"recommended": "rail", "options": []},
            local_transport,
            hotels,
            pois,
            {},
        )
        self.assertLessEqual(len(days[0]["items"]), 4)

    def test_deepseek_review_repair_uses_real_candidate_ids(self):
        planner = planner_with_toolbox(FakeToolbox())
        pois = {
            "attractions": [
                {"id": "near-a", "name": "近景点", "address": "近处", "location": {"lng": 114.0, "lat": 22.0}},
            ],
            "specialty_places": [],
            "foods": [
                {"id": "near-food", "name": "近餐厅", "address": "近处", "location": {"lng": 114.01, "lat": 22.0}},
            ],
        }
        hotels = {"area_recommendation": "近景点", "candidates": []}
        planner._enrich_place_clusters(pois, hotels)
        planner.deepseek_brain = FakeItineraryReviewBrain(
            {
                "overall_score": 58,
                "route_score": 45,
                "pace_score": 75,
                "cluster_score": 50,
                "logic_score": 80,
                "issues": [{"severity": "high", "day": 1, "message": "跨区过远", "kind": "cluster"}],
                "fixes": ["替换为同片区候选"],
                "needs_repair": True,
                "repaired_plan": {
                    "days": [
                        {
                            "day": 1,
                            "theme": "同片区修复",
                            "items": [
                                {"title": "近景点游览", "candidate_id": "near-a", "category": "activity", "transport": "taxi", "duration": "2 小时", "detail": "同片区活动。"},
                                {"title": "近餐厅午餐", "candidate_id": "near-food", "category": "food", "transport": "walking", "duration": "1 小时", "detail": "同片区餐饮。"},
                            ],
                        }
                    ]
                },
            }
        )

        result = planner._review_and_repair_itinerary(
            {
                "originCity": "广州",
                "destinationCity": "深圳",
                "startDate": "2026-07-14",
                "days": 1,
                "preferenceProfile": {"pace": "标准", "maxTransferMinutes": 45, "hotelStrategy": "近地铁枢纽", "learnedHints": []},
            },
            {"recommended": "rail", "options": []},
            {"recommended_modes": ["taxi"], "notes": []},
            hotels,
            pois,
            {},
            {},
            [{"day": 1, "theme": "原行程", "items": []}],
        )

        self.assertTrue(result["quality_review"]["repaired"])
        self.assertEqual(result["itinerary_days"][0]["items"][0]["poi_id"], "near-a")
        self.assertEqual(result["itinerary_days"][0]["items"][1]["poi_id"], "near-food")
        self.assertEqual(planner.deepseek_brain.payloads[0]["quality_targets"]["max_transfer_minutes"], 45)

    def test_deepseek_review_rejects_unknown_repair_candidate(self):
        planner = planner_with_toolbox(FakeToolbox())
        pois = {
            "attractions": [
                {"id": "real-a", "name": "真实景点", "address": "近处", "location": {"lng": 114.0, "lat": 22.0}},
            ],
            "specialty_places": [],
            "foods": [],
        }
        hotels = {"area_recommendation": "近景点", "candidates": []}
        planner._enrich_place_clusters(pois, hotels)
        planner.deepseek_brain = FakeItineraryReviewBrain(
            {
                "overall_score": 50,
                "route_score": 40,
                "pace_score": 70,
                "cluster_score": 40,
                "logic_score": 80,
                "issues": [{"severity": "high", "day": 1, "message": "需要替换", "kind": "cluster"}],
                "fixes": [],
                "needs_repair": True,
                "repaired_plan": {
                    "days": [
                        {
                            "day": 1,
                            "items": [
                                {"title": "不存在景点", "candidate_id": "made-up", "category": "activity", "transport": "taxi", "duration": "2 小时", "detail": "不应接受。"},
                                {"title": "真实景点", "candidate_id": "real-a", "category": "activity", "transport": "taxi", "duration": "2 小时", "detail": "真实候选。"},
                            ],
                        }
                    ]
                },
            }
        )
        original_days = [{"day": 1, "theme": "原行程", "items": [{"id": "old", "title": "原景点"}]}]

        result = planner._review_and_repair_itinerary(
            {
                "originCity": "广州",
                "destinationCity": "深圳",
                "startDate": "2026-07-14",
                "days": 1,
                "preferenceProfile": {"pace": "标准", "maxTransferMinutes": 45, "hotelStrategy": "近地铁枢纽", "learnedHints": []},
            },
            {"recommended": "rail", "options": []},
            {"recommended_modes": ["taxi"], "notes": []},
            hotels,
            pois,
            {},
            {},
            original_days,
        )

        self.assertFalse(result["quality_review"]["repaired"])
        self.assertEqual(result["itinerary_days"], original_days)
        self.assertIn("不存在", result["quality_review"]["issues"][-1]["message"])

    def test_activity_missing_ticket_defaults_to_zero_but_paid_sources_stay(self):
        amap_meta = StructuredTravelPlanner._cost_metadata(
            category="activity",
            poi_cost=120,
            fallback_cost=80,
        )
        self.assertEqual(amap_meta["cost_source"], "amap_cost")
        self.assertEqual(amap_meta["cost_estimate"], 120)

        ai_meta = StructuredTravelPlanner._cost_metadata(
            category="activity",
            fallback_cost=80,
            use_poi_cost=False,
            ai_price_range={"min": 30, "max": 90, "currency": "CNY", "unit": "person"},
            ai_price_note="AI 常识估算，需以官方/现场为准。",
        )
        self.assertEqual(ai_meta["cost_source"], "ai_price_range")
        self.assertEqual(ai_meta["cost_estimate"], 60)

        free_meta = StructuredTravelPlanner._cost_metadata(
            category="activity",
            fallback_cost=80,
            use_poi_cost=False,
        )
        self.assertEqual(free_meta["cost_source"], "free_or_no_ticket_default")
        self.assertEqual(free_meta["cost_estimate"], 0)

        zero_ai_meta = StructuredTravelPlanner._cost_metadata(
            category="activity",
            fallback_cost=80,
            use_poi_cost=False,
            ai_price_range={"min": 0, "max": 0, "currency": "CNY", "unit": "person"},
        )
        self.assertEqual(zero_ai_meta["cost_source"], "free_or_no_ticket_default")
        self.assertEqual(zero_ai_meta["cost_estimate"], 0)

        food_meta = StructuredTravelPlanner._cost_metadata(
            category="food",
            fallback_cost=80,
            use_poi_cost=False,
        )
        self.assertEqual(food_meta["cost_source"], "category_rule")
        self.assertEqual(food_meta["cost_estimate"], 80)

    def test_budget_tickets_do_not_increase_for_free_ticket_default(self):
        planner = planner_with_toolbox(FakeToolbox())
        budget = planner._build_budget(
            {"travelers": 2, "days": 2, "hotelLevel": "舒适", "budget": 2000, "estimatedDistanceKm": 100},
            {"recommended": "rail", "raw": "二等座通常约 45-70 元", "options": []},
            {"recommended_modes": [], "segments": []},
            {"candidates": [{"cost_estimate": 420, "cost_source": "ai_price_range"}]},
            {},
            [
                {
                    "day": 1,
                    "items": [
                        {"category": "activity", "cost_estimate": 0, "cost_source": "free_or_no_ticket_default"},
                        {"category": "food", "cost_estimate": 80, "cost_source": "category_rule"},
                    ],
                }
            ],
        )

        self.assertEqual(budget["breakdown"]["tickets"], 0)
        self.assertEqual(budget["sources"]["tickets"], "free_or_no_ticket_default")
        self.assertEqual(budget["breakdown"]["food"], 160)

    def test_frontend_labels_free_ticket_default_source(self):
        app_js = Path(__file__).resolve().parents[1] / "web" / "app.js"
        content = app_js.read_text(encoding="utf-8")

        self.assertIn('source === "free_or_no_ticket_default"', content)
        self.assertIn('free_or_no_ticket_default: "无门票/免费默认"', content)
        self.assertIn("无门票/免费默认，需核实", content)

    def test_frontend_rewrites_generic_hotel_match_reason(self):
        app_js = Path(__file__).resolve().parents[1] / "web" / "app.js"
        content = app_js.read_text(encoding="utf-8")

        self.assertIn("function hotelMatchReason", content)
        self.assertIn("function hotelAreaRecommendation", content)
        self.assertIn("核心商圈|地铁枢纽|第一天重点景点|交通枢纽", content)

    def test_frontend_marks_legacy_long_transit_for_replanning(self):
        app_js = Path(__file__).resolve().parents[1] / "web" / "app.js"
        content = app_js.read_text(encoding="utf-8")

        self.assertIn("function normalizeArrivalSegment", content)
        self.assertIn("isImpracticalTransitSegment", content)
        self.assertIn("路线待重新规划", content)
        self.assertIn("function applyClientRouteJudgement", content)

    def test_frontend_rewrites_legacy_return_transfer_lodging_location(self):
        app_js = Path(__file__).resolve().parents[1] / "web" / "app.js"
        content = app_js.read_text(encoding="utf-8")

        self.assertIn("function isReturnTransferItem", content)
        self.assertIn("function returnTransferLocation", content)
        self.assertIn("function timelineItemDetail", content)
        self.assertIn("不需要再安排目的地住宿", content)

    def test_frontend_sends_preference_profile_and_renders_quality_review(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "web" / "app.js").read_text(encoding="utf-8")
        index_html = (root / "web" / "index.html").read_text(encoding="utf-8")

        self.assertIn("preferenceProfile", app_js)
        self.assertIn("learnedHintsStorageKey", app_js)
        self.assertIn("function renderQualityReview", app_js)
        self.assertIn("旧会话缺少体检结果", app_js)
        self.assertIn("renderQualityReview(data.quality_review)", app_js)
        self.assertIn('name="pace"', index_html)
        self.assertIn('name="maxTransferMinutes"', index_html)
        self.assertIn('name="hotelStrategy"', index_html)

    def test_frontend_manual_edits_remember_lightweight_preferences(self):
        app_js = Path(__file__).resolve().parents[1] / "web" / "app.js"
        content = app_js.read_text(encoding="utf-8")

        self.assertIn("function updateLearnedHintsFromText", content)
        self.assertIn("少公交", content)
        self.assertIn('rememberLearnedHints(["别太赶"])', content)
        self.assertIn('rememberLearnedHints(["不去太远景点"])', content)

    def test_budget_sources_follow_hotel_and_local_segment_sources(self):
        planner = planner_with_toolbox(FakeToolbox())
        prefs = {"travelers": 2, "days": 2, "hotelLevel": "舒适", "budget": 2000, "estimatedDistanceKm": 100}
        budget = planner._build_budget(
            prefs,
            {"recommended": "rail", "raw": "二等座通常约 45-70 元", "options": []},
            {
                "recommended_modes": ["transit"],
                "segments": [
                    {"source": "amap_route", "cost_estimate": 5, "cost_unit": "person"},
                    {"source": "rule_fallback", "cost_estimate": 18, "cost_unit": "party"},
                ],
            },
            {"candidates": [{"cost_estimate": 420, "cost_source": "ai_price_range"}]},
            {},
            [
                {
                    "day": 1,
                    "items": [
                        {"category": "food", "cost_estimate": 80, "cost_source": "amap_cost"},
                        {"category": "activity", "cost_estimate": 60, "cost_source": "category_rule"},
                    ],
                }
            ],
        )

        self.assertEqual(budget["sources"]["hotel"], "ai_price_range")
        self.assertEqual(budget["sources"]["local_transport"], "amap_route")
        self.assertEqual(budget["breakdown"]["local_transport"], 28)

    def test_amap_static_marker_label_stays_single_character(self):
        self.assertEqual(amap_static_marker_label("A", 0), "A")
        self.assertEqual(len(amap_static_marker_label("10", 9)), 1)
        self.assertNotEqual(amap_static_marker_label("10", 9), "10")


if __name__ == "__main__":
    unittest.main()
