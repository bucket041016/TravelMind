from __future__ import annotations

import unittest

from sync.multi_agent.contracts import stable_place_id
from sync.multi_agent.fact_normalizer import normalize_place_candidate
from sync.multi_agent.text_parser import _parse_numbered_section


class TravelMindStableIdTests(unittest.TestCase):
    def test_stable_id_is_deterministic(self):
        first = stable_place_id(name="深圳湾公园", location={"lng": 113.95, "lat": 22.52})
        second = stable_place_id(name="深圳湾公园", location={"lng": 113.95, "lat": 22.52})
        self.assertEqual(first, second)

    def test_stable_id_differs_by_coordinates(self):
        first = stable_place_id(name="深圳湾公园", location={"lng": 113.95, "lat": 22.52})
        second = stable_place_id(name="深圳湾公园", location={"lng": 113.96, "lat": 22.52})
        self.assertNotEqual(first, second)

    def test_stable_id_without_coordinates_uses_name_only(self):
        self.assertEqual(stable_place_id(name="深圳博物馆", location=None), "深圳博物馆")

    def test_normalize_fills_stable_id_when_id_missing(self):
        candidate = normalize_place_candidate(
            {"name": "深圳湾公园", "address": "深圳市南山区", "location": "113.95,22.52"},
            city="深圳",
            category="activity",
            provider_status="fixture",
        )
        self.assertEqual(candidate["id"], "深圳湾公园-113.95000-22.52000")
        self.assertEqual(candidate["id"], candidate["stable_id"])

    def test_normalize_preserves_explicit_id_and_attaches_stable_id(self):
        candidate = normalize_place_candidate(
            {"id": "fixture-a1", "name": "景点A", "location": {"lng": 114.0, "lat": 22.0}},
            city="深圳",
            category="activity",
            provider_status="fixture",
        )
        self.assertEqual(candidate["id"], "fixture-a1")
        self.assertEqual(candidate["stable_id"], "景点a-114.00000-22.00000")
        self.assertNotEqual(candidate["id"], candidate["stable_id"])

    def test_numbered_section_then_normalize_gives_stable_ids(self):
        text = (
            "【景点/活动】\n"
            "1. 深圳湾公园（评分4.6；地址：广东省深圳市南山区；坐标：113.95,22.52；人均约50元）\n"
            "2. 世界之窗（评分4.5；地址：深圳市南山区；坐标：113.97,22.53）\n"
        )
        raw_items = _parse_numbered_section(text, "景点/活动")
        self.assertEqual(len(raw_items), 2)
        self.assertEqual(raw_items[0]["id"], "深圳湾公园-113.95000-22.52000")
        self.assertEqual(raw_items[1]["id"], "世界之窗-113.97000-22.53000")

        normalized = [
            normalize_place_candidate(item, city="深圳", category="activity", provider_status="fixture")
            for item in raw_items
        ]
        self.assertEqual(normalized[0]["id"], normalized[0]["stable_id"])
        self.assertNotEqual(normalized[0]["id"], normalized[1]["id"])


if __name__ == "__main__":
    unittest.main()
