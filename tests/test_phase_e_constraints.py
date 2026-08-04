"""Phase E -- 约束链路集成回归测试。

测试 fact_normalizer / candidate_ranker / contracts 的集成效果。
"""
from __future__ import annotations

import unittest

from sync.multi_agent.contracts import (
    candidate_key,
    normalize_point,
    normalize_price_range,
    source_meta,
    validate_place_candidate,
)
from sync.multi_agent.fact_normalizer import (
    normalize_place_candidate as normalize_pc,
    normalize_place_candidates,
    normalize_route_fact,
    normalize_weather_fact,
)
from sync.multi_agent.candidate_ranker import (
    filter_candidates,
    rank_candidates,
)
from sync.multi_agent.poi_service import _normalize_and_rank_pois
from sync.multi_agent.hotel_service import _normalize_and_rank_hotels
from sync.multi_agent.weather_service import _normalize_weather_facts


class ContractsTests(unittest.TestCase):
    def test_normalize_point_dict(self):
        pt = normalize_point({"lng": 114.05, "lat": 22.55})
        self.assertIsNotNone(pt)
        self.assertAlmostEqual(pt["lng"], 114.05)
        self.assertAlmostEqual(pt["lat"], 22.55)

    def test_normalize_point_string(self):
        pt = normalize_point("114.05,22.55")
        self.assertIsNotNone(pt)
        self.assertAlmostEqual(pt["lng"], 114.05)

    def test_normalize_point_invalid(self):
        self.assertIsNone(normalize_point("abc"))
        self.assertIsNone(normalize_point(None))
        self.assertIsNone(normalize_point({"lng": 999, "lat": 22}))

    def test_normalize_price_range(self):
        pr = normalize_price_range({"min": 200, "max": 500})
        self.assertEqual(pr["min"], 200)
        self.assertEqual(pr["max"], 500)
        self.assertEqual(pr["currency"], "CNY")

    def test_normalize_price_range_from_text(self):
        pr = normalize_price_range("320-520")
        self.assertIsNotNone(pr)
        self.assertEqual(pr["min"], 320)
        self.assertEqual(pr["max"], 520)

    def test_source_meta_defaults(self):
        sm = source_meta(provider="amap_poi", status="live")
        self.assertEqual(sm["provider"], "amap_poi")
        self.assertEqual(sm["status"], "live")
        self.assertEqual(sm["kind"], "amap")

    def test_candidate_key_by_id(self):
        self.assertEqual(candidate_key({"id": "abc123"}), "id:abc123")

    def test_candidate_key_by_location(self):
        key = candidate_key({"location": {"lng": 114.05, "lat": 22.55}})
        self.assertTrue(key.startswith("point:"))

    def test_validate_place_candidate_errors(self):
        errors = validate_place_candidate({}, require_coordinates=True)
        self.assertIn("missing_name", errors)
        self.assertIn("missing_coordinates", errors)

    def test_validate_place_candidate_valid(self):
        errors = validate_place_candidate(
            {"name": "A", "location": {"lng": 114, "lat": 22}},
            require_coordinates=True,
        )
        self.assertEqual(errors, [])


class FactNormalizerTests(unittest.TestCase):
    def test_normalize_place_candidate_adds_standard_fields(self):
        raw = {"name": "世界之窗", "address": "南山区", "location": {"lng": 113.97, "lat": 22.53}}
        result = normalize_pc(raw, city="深圳", category="activity")
        self.assertEqual(result["city"], "深圳")
        self.assertEqual(result["category"], "activity")
        self.assertTrue(result["is_real_place"])
        self.assertIn("source_meta", result)
        self.assertEqual(result["validation"]["status"], "valid")

    def test_normalize_place_candidate_missing_name(self):
        result = normalize_pc({}, city="深圳", category="activity")
        self.assertEqual(result["validation"]["status"], "invalid")
        self.assertIn("missing_name", result["validation"]["errors"])

    def test_normalize_route_fact_extracts_numbers(self):
        fact = normalize_route_fact(
            "高铁约130km，约45分钟，票价约75元",
            origin="广州",
            destination="深圳",
            mode="rail",
        )
        self.assertEqual(fact["origin"], "广州")
        self.assertEqual(fact["destination"], "深圳")
        self.assertAlmostEqual(fact["distance_km"], 130)
        self.assertEqual(fact["duration_minutes"], 45)
        self.assertAlmostEqual(fact["price"], 75)

    def test_normalize_weather_fact_extracts_temp(self):
        fact = normalize_weather_fact(
            "深圳：多云，28~34°C，降水概率30%，风力3级",
            city="深圳",
            date="2026-08-01",
        )
        self.assertEqual(fact["city"], "深圳")
        self.assertAlmostEqual(fact["min_temp_c"], 28)
        self.assertAlmostEqual(fact["max_temp_c"], 34)
        self.assertAlmostEqual(fact["rain_probability"], 30)
        self.assertAlmostEqual(fact["wind_level"], 3)


class CandidateRankerTests(unittest.TestCase):
    def test_filter_removes_duplicates(self):
        candidates = [
            {"id": "a1", "name": "景点A"},
            {"id": "a1", "name": "景点A"},
        ]
        result = filter_candidates(candidates)
        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(len(result["rejected"]), 1)
        self.assertIn("duplicate_candidate", result["rejected"][0]["reasons"])

    def test_filter_removes_over_price(self):
        candidates = [
            {"id": "cheap", "name": "便宜景点", "cost_estimate": 50},
            {"id": "expensive", "name": "贵景点", "cost_estimate": 500},
        ]
        result = filter_candidates(candidates, max_price=100)
        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(result["accepted"][0]["id"], "cheap")

    def test_rank_candidates_preferences_boost(self):
        candidates = [
            {"id": "a", "name": "普通公园", "type": "公园", "location": {"lng": 114.00, "lat": 22.00}},
            {"id": "b", "name": "世界之窗", "type": "景区", "description": "经典景点", "location": {"lng": 113.97, "lat": 22.53}, "rating": 4.5},
        ]
        result = rank_candidates(
            candidates,
            preferences={"interests": ["经典景点"]},
        )
        selected = result["selected"]
        self.assertEqual(len(selected), 2)
        # 世界之窗应该排在前面（有评分+匹配偏好）
        self.assertEqual(selected[0]["id"], "b")

    def test_rank_candidates_rainy_weather_downgrades_outdoor(self):
        candidates = [
            {"id": "outdoor", "name": "滨海公园", "type": "公园", "location": {"lng": 114.00, "lat": 22.00}},
            {"id": "indoor", "name": "深圳博物馆", "type": "博物馆", "location": {"lng": 114.05, "lat": 22.55}},
        ]
        result = rank_candidates(
            candidates,
            weather="大雨，28~30°C",
        )
        selected = result["selected"]
        # 雨天户外应被降权
        self.assertEqual(selected[0]["id"], "indoor")

    def test_filter_by_excluded_terms(self):
        candidates = [
            {"id": "a", "name": "景点A", "type": "商场"},
            {"id": "b", "name": "景点B", "type": "博物馆"},
        ]
        result = filter_candidates(candidates, excluded_terms=["商场"])
        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(result["accepted"][0]["id"], "b")


class IntegrationTests(unittest.TestCase):
    def test_normalize_and_rank_pois_inplace(self):
        pois = {
            "attractions": [
                {"name": "普通公园", "type": "公园", "location": {"lng": 114.00, "lat": 22.00}},
                {"name": "世界之窗", "type": "景区", "location": {"lng": 113.97, "lat": 22.53}, "rating": 4.5, "description": "经典景点"},
            ],
            "foods": [
                {"name": "老街烧鹅", "type": "粤菜", "address": "东门老街", "location": {"lng": 114.1, "lat": 22.5}},
            ],
            "specialty_places": [],
        }
        prefs = {"destinationCity": "深圳", "interests": ["经典景点", "美食"]}
        _normalize_and_rank_pois(pois, prefs)
        # 景点应该排序后世界之窗在前
        self.assertEqual(pois["attractions"][0]["name"], "世界之窗")
        # 每个候选应该有 source_meta
        self.assertIn("source_meta", pois["attractions"][0])
        # 每个候选应该有 selection
        self.assertIn("selection", pois["attractions"][0])

    def test_normalize_and_rank_hotels_inplace(self):
        hotels = {
            "candidates": [
                {
                    "id": "h1",
                    "name": "经济酒店",
                    "address": "南山区",
                    "location": {"lng": 114, "lat": 22},
                    "cost_estimate": 200,
                    "cost_source": "category_rule",
                },
                {
                    "id": "h2",
                    "name": "豪华大酒店",
                    "address": "福田区",
                    "location": {"lng": 114.05, "lat": 22.55},
                    "cost_estimate": 680,
                    "cost_source": "ai_price_range",
                    "rating": 4.8,
                },
            ],
        }
        prefs = {"destinationCity": "深圳", "hotelLevel": "舒适", "budget": 2000, "days": 2}
        _normalize_and_rank_hotels(hotels, prefs)
        # 每个候选应该有归一化字段
        for c in hotels["candidates"]:
            self.assertIn("source_meta", c)
            self.assertIn("selection", c)

    def test_normalize_weather_facts_structure(self):
        weather = {
            "深圳": "深圳：多云，28~34°C，降水概率30%，风力3级",
            "广州": "广州：晴，26~33°C",
        }
        prefs = {"startDate": "2026-08-01"}
        facts = _normalize_weather_facts(weather, prefs)
        self.assertIn("深圳", facts)
        self.assertIn("广州", facts)
        self.assertEqual(facts["深圳"]["city"], "深圳")
        self.assertAlmostEqual(facts["深圳"]["min_temp_c"], 28)
        self.assertIsNotNone(facts["深圳"]["source_meta"])


if __name__ == "__main__":
    unittest.main()
