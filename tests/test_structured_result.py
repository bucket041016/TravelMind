from __future__ import annotations

import unittest

from sync.mcp_tools_adapter import MCPToolResult
from sync.multi_agent.hotel_service import _build_hotels
from sync.multi_agent.poi_service import _build_pois
from sync.multi_agent.structured_result import parse_hotel_response, parse_poi_response


class _FakeToolbox:
    def __init__(self, value):
        self.value = value
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool_name, **kwargs):
        self.calls.append((tool_name, kwargs))
        return self.value

    def call_text(self, tool_name, **kwargs) -> str:
        return self.call(tool_name, **kwargs)

    def call_structured(self, tool_name, **kwargs) -> MCPToolResult:
        return MCPToolResult.from_value(tool_name, self.call(tool_name, **kwargs))


class _FakeSelf:
    def __init__(self, toolbox):
        self.toolbox = toolbox


class _FakeHotelProvider:
    def message(self):
        return "provider message"

    def status(self):
        return "live"


class _FakeHotelSelf:
    def __init__(self, toolbox):
        self.toolbox = toolbox
        self.hotel_provider = _FakeHotelProvider()
        self.deepseek_brain = None


def _structured_poi_value() -> dict:
    return {
        "attractions": [{"name": "深圳湾公园", "location": {"lng": 113.95, "lat": 22.52}}],
        "foods": [{"name": "老街小吃", "location": {"lng": 113.93, "lat": 22.54}}],
        "specialty_places": [],
        "generic_foods": [],
    }


def _structured_hotel_value() -> dict:
    return {
        "provider_status": "amap_fallback",
        "area_recommendation": "深圳国际会展中心塘尾地铁站周边",
        "candidates": [
            {"name": "样例酒店", "address": "科技园", "type": "酒店", "rating": 4.6, "location": {"lng": 114.01, "lat": 22.54}}
        ],
    }


class TravelMindStructuredResultTests(unittest.TestCase):
    def test_parse_poi_response_consumes_structured_data(self):
        result = MCPToolResult.from_value("search_poi", _structured_poi_value())
        parsed = parse_poi_response(result)
        self.assertIsNotNone(parsed)
        self.assertEqual([item["name"] for item in parsed.attractions], ["深圳湾公园"])
        self.assertEqual([item["name"] for item in parsed.foods], ["老街小吃"])

    def test_parse_poi_response_rejects_non_poi_shape(self):
        self.assertIsNone(parse_poi_response(MCPToolResult.from_value("search_poi", {"unrelated": 1})))
        self.assertIsNone(parse_poi_response(MCPToolResult.from_value("search_poi", "【景点/活动】\n1. x")))
        self.assertIsNone(parse_poi_response(MCPToolResult.from_value("search_poi", None)))

    def test_parse_poi_response_filters_bad_elements(self):
        value = _structured_poi_value()
        value["attractions"] = [
            {"name": "深圳湾公园", "location": {"lng": 113.95, "lat": 22.52}},
            {"bad": "element"},
            "junk-text",
        ]
        result = MCPToolResult.from_value("search_poi", value)
        parsed = parse_poi_response(result)
        self.assertEqual(len(parsed.attractions), 1)
        self.assertIn("过滤 2 个非法 POI 候选元素", result.validation_error)

    def test_parse_hotel_response_consumes_structured_data(self):
        result = MCPToolResult.from_value("search_hotels", _structured_hotel_value())
        parsed = parse_hotel_response(result)
        self.assertIsNotNone(parsed)
        self.assertEqual([item["name"] for item in parsed.candidates], ["样例酒店"])
        self.assertEqual(parsed.area_recommendation, "深圳国际会展中心塘尾地铁站周边")
        self.assertEqual(parsed.provider_status, "amap_fallback")

    def test_parse_hotel_response_filters_bad_elements(self):
        value = _structured_hotel_value()
        value["candidates"] = [{"name": "样例酒店"}, 42]
        result = MCPToolResult.from_value("search_hotels", value)
        parsed = parse_hotel_response(result)
        self.assertEqual(len(parsed.candidates), 1)
        self.assertIn("过滤 1 个非法酒店候选元素", result.validation_error)

    def test_build_pois_consumes_structured_dict(self):
        result = _build_pois(
            _FakeSelf(_FakeToolbox(_structured_poi_value())),
            {"destinationCity": "深圳", "interests": ["经典景点"]},
        )
        self.assertEqual(len(result["attractions"]), 1)
        self.assertEqual(result["attractions"][0]["name"], "深圳湾公园")
        self.assertEqual(len(result["foods"]), 1)
        self.assertIsInstance(result["raw"], str)

    def test_build_pois_still_falls_back_to_text(self):
        text = "【景点/活动】\n1. 深圳湾公园（坐标：113.95,22.52）\n"
        result = _build_pois(
            _FakeSelf(_FakeToolbox(text)),
            {"destinationCity": "深圳", "interests": ["经典景点"]},
        )
        self.assertEqual(len(result["attractions"]), 1)
        self.assertEqual(result["attractions"][0]["name"], "深圳湾公园")
        self.assertEqual(result["raw"], text)

    def test_build_hotels_consumes_structured_dict(self):
        result = _build_hotels(
            _FakeHotelSelf(_FakeToolbox(_structured_hotel_value())),
            {"destinationCity": "深圳", "hotelLevel": "舒适", "startDate": "2026-07-14"},
        )
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["name"], "样例酒店")
        self.assertEqual(result["candidates"][0]["cost_source"], "category_rule")
        self.assertEqual(result["area_recommendation"], "深圳国际会展中心塘尾地铁站周边")
        self.assertEqual(result["provider_status"], "amap_fallback")

    def test_build_hotels_still_falls_back_to_text(self):
        text = "【酒店候选】\n1. 文本酒店（评分4.5）\n住宿区域建议：深圳湾公园周边\n"
        result = _build_hotels(
            _FakeHotelSelf(_FakeToolbox(text)),
            {"destinationCity": "深圳", "hotelLevel": "舒适", "startDate": "2026-07-14"},
        )
        self.assertEqual(result["candidates"][0]["name"], "文本酒店")
        self.assertEqual(result["raw"], text)


if __name__ == "__main__":
    unittest.main()
