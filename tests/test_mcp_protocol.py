"""真实 FastMCP 协议级测试（D12）：内存直连覆盖全部结果形态与三入口兼容。

内存 FastMCP server（Client(server) 直连，完整 JSON-RPC 往返，不起 HTTP）覆盖：
结构化 data、文本 content、JSON 文本兜底、wrap 陷阱、空结果、工具异常、
非法 schema，以及三个 API 入口在 dict 返回工具下的兼容行为。

注意：StructuredTravelPlanner 只直调 _build_* 方法（先置 deepseek_brain=None），
禁止调 run()——测试进程可能加载了真实 DEEPSEEK_API_KEY，run() 会触发真实调用。
"""

from __future__ import annotations

import json
import logging
import unittest

from fastmcp import FastMCP

try:
    from fastmcp.exceptions import ToolError
except ImportError:  # pragma: no cover
    from mcp import McpError as ToolError

from sync.mcp_tools_adapter import MCPToolAdapter
from sync.multi_agent.hotel_service import _build_hotels
from sync.multi_agent.orchestrator import MultiAgentTravelPlanner
from sync.multi_agent.poi_service import _build_pois
from sync.multi_agent.structured_planner import StructuredTravelPlanner
from sync.multi_agent.structured_result import parse_poi_response


def _build_protocol_server() -> FastMCP:
    server = FastMCP(name="travelmind-protocol-test")

    @server.tool()
    def search_poi(city: str, preference: str = "经典景点") -> dict:
        """结构化 POI 返回（attractions 内含 2 个坏元素）。"""
        return {
            "attractions": [
                {"name": "深圳湾公园", "location": {"lng": 113.95, "lat": 22.52}, "rating": 4.6},
                {"bad": "element"},
                "junk-text",
            ],
            "foods": [{"name": "椰子鸡", "location": {"lng": 113.93, "lat": 22.54}}],
            "specialty_places": [],
            "generic_foods": [],
        }

    @server.tool()
    def search_hotels(city: str, hotel_level: str = "舒适", near: str = "", limit: int = 6) -> dict:
        """结构化酒店返回。"""
        return {
            "provider_status": "amap_fallback",
            "area_recommendation": "深圳湾公园周边",
            "candidates": [
                {
                    "name": "样例酒店",
                    "address": "科技园",
                    "type": "酒店",
                    "rating": 4.6,
                    "location": {"lng": 114.01, "lat": 22.54},
                }
            ],
        }

    @server.tool()
    def get_weather(city: str, date: str):
        """无返回注解的文本工具（真实 server 的 get_weather 形态）。"""
        return f"{city} {date}：晴，22~30°C。"

    @server.tool()
    def plain_text_note() -> str:
        """-> str 注解工具（非 JSON 文本，wrap 陷阱形态）。"""
        return "【景点/活动】\n1. 深圳湾公园（坐标：113.95,22.52）"

    @server.tool()
    def json_text_note() -> str:
        """-> str 注解但返回 JSON 文本（text_json 兜底形态）。"""
        return json.dumps(
            {
                "attractions": [{"name": "莲花山公园"}],
                "foods": [],
                "specialty_places": [],
                "generic_foods": [],
            },
            ensure_ascii=False,
        )

    @server.tool()
    def empty_note() -> str:
        """空文本工具。"""
        return ""

    @server.tool()
    def boom_tool() -> str:
        """抛错工具。"""
        raise RuntimeError("boom")

    @server.tool()
    def bad_schema_tool() -> dict:
        """声明 dict 却返回 str（非法 schema）。"""
        return "not-a-dict"

    @server.tool()
    def amap_plan_routes(
        origin: str,
        destination: str,
        origin_city: str = "",
        destination_city: str = "",
        modes: str = "driving,transit",
        max_routes: int = 3,
    ) -> str:
        """路线文本工具（旧链路回归用）。"""
        return "【高铁/城际铁路】广州南 -> 深圳北，约 40 分钟。"

    @server.tool()
    def plan_route(origin: str, destination: str, transport_mode: str = "高铁") -> str:
        """路线降级工具（旧链路回归用）。"""
        return f"{origin} -> {destination}，推荐交通方式：{transport_mode}。"

    @server.tool()
    def estimate_budget(
        origin: str,
        destination: str,
        days: int = 2,
        travelers: int = 1,
        hotel_level: str = "舒适",
    ) -> str:
        """预算文本工具（旧链路回归用）。"""
        return f"{origin} -> {destination} {days}天{travelers}人预算估算（{hotel_level}档）：总计：约 600 元。"

    @server.tool()
    def kb_retrieve(city: str, query: str = "", limit: int = 8) -> dict:
        """知识库检索工具（真实 server 的 kb_retrieve 形态：结构化 dict 返回）。"""
        if city not in {"深圳", "广州"}:
            return {
                "provider_status": "not_covered",
                "city": city,
                "query": query,
                "city_guide": None,
                "entries": [],
                "coverage": "none",
                "note": "本地知识库暂未覆盖该目的地。",
            }
        entries = [
            {
                "name": "深圳湾公园",
                "aliases": [],
                "district": "南山区",
                "highlights": ["滨海长廊"],
                "suggested_duration": "2-3 小时",
                "best_time": "傍晚",
                "booking": "免预约，免费开放",
                "ticket": "免费",
                "indoor": False,
                "rainy_alternative": False,
                "keywords": ["海滨"],
                "note": "海边日晒强。",
            }
        ]
        return {
            "provider_status": "knowledge_base",
            "city": city,
            "query": query,
            "city_guide": {"city": city, "summary": "带状沿海城市。", "districts": [], "practical_tips": [], "seasonal": []},
            "entries": entries[: max(0, int(limit))],
            "coverage": "full",
            "note": "知识库为人工策展的背景知识。",
        }

    return server


_PROTOCOL = _build_protocol_server()


def setUpModule():
    logging.getLogger("fastmcp").setLevel(logging.CRITICAL)


class TravelMindMcpProtocolTests(unittest.TestCase):
    """内存直连协议级测试：适配器封装 + 三入口兼容。"""

    def _adapter(self) -> MCPToolAdapter:
        return MCPToolAdapter(_PROTOCOL)

    def test_structured_dict_tool_returns_structured_data(self):
        result = self._adapter().call_mcp_tool_result("search_poi", city="深圳", preference="经典景点")
        self.assertEqual(result.source, "structured_data")
        self.assertIsInstance(result.data, dict)
        self.assertIn("attractions", result.data)
        self.assertEqual(json.loads(result.text), result.data)

    def test_kb_retrieve_returns_structured_data(self):
        result = self._adapter().call_mcp_tool_result("kb_retrieve", city="深圳", limit=1)
        self.assertEqual(result.source, "structured_data")
        self.assertIsInstance(result.data, dict)
        self.assertEqual(result.data["provider_status"], "knowledge_base")
        self.assertEqual([item["name"] for item in result.data["entries"]], ["深圳湾公园"])
        self.assertIn("summary", result.data["city_guide"])
        self.assertEqual(json.loads(result.text), result.data)

    def test_kb_retrieve_uncovered_city_is_structured_not_covered(self):
        result = self._adapter().call_mcp_tool_result("kb_retrieve", city="拉萨")
        self.assertEqual(result.source, "structured_data")
        self.assertEqual(result.data["provider_status"], "not_covered")
        self.assertEqual(result.data["coverage"], "none")
        self.assertEqual(result.data["entries"], [])

    def test_bad_elements_filtered_in_structured_poi(self):
        result = self._adapter().call_mcp_tool_result("search_poi", city="深圳", preference="经典景点")
        parsed = parse_poi_response(result)
        self.assertIsNotNone(parsed)
        self.assertEqual([item["name"] for item in parsed.attractions], ["深圳湾公园"])
        self.assertIn("过滤 2 个非法 POI 候选元素", result.validation_error)

    def test_unannotated_str_tool_is_text_only(self):
        result = self._adapter().call_mcp_tool_result("get_weather", city="深圳", date="明天")
        self.assertEqual(result.source, "text_only")
        self.assertIsNone(result.data)
        self.assertIn("晴", result.text)

    def test_annotated_str_tool_avoids_wrap_trap(self):
        result = self._adapter().call_mcp_tool_result("plain_text_note")
        self.assertEqual(result.source, "text_only")
        self.assertIsNone(result.data)
        self.assertIn("【景点/活动】", result.text)

    def test_json_text_tool_falls_back_to_text_json(self):
        result = self._adapter().call_mcp_tool_result("json_text_note")
        self.assertEqual(result.source, "text_json")
        self.assertEqual(result.data["attractions"][0]["name"], "莲花山公园")

    def test_empty_text_becomes_empty(self):
        result = self._adapter().call_mcp_tool_result("empty_note")
        self.assertEqual(result.source, "empty")
        self.assertIn("空结果", result.text)

    def test_tool_error_propagates(self):
        with self.assertRaises(ToolError):
            self._adapter().call_mcp_tool_result("boom_tool")

    def test_schema_violation_propagates(self):
        with self.assertRaises(ToolError):
            self._adapter().call_mcp_tool_result("bad_schema_tool")

    def test_old_chain_with_structured_poi_does_not_crash(self):
        """已复现 bug（Writer expected str instance, dict found）的回归测试。"""
        planner = MultiAgentTravelPlanner(_PROTOCOL)
        result = planner.run("从广州去深圳玩2天，预算800元，喜欢经典景点。")
        self.assertTrue(result["answer"].strip())
        self.assertIn("深圳", result["answer"])
        self.assertIn("attractions", result["answer"])
        error_steps = [step for step in result["agent_steps"] if step.get("status") == "error"]
        self.assertEqual(error_steps, [])

    def test_structured_planner_consumes_structured_via_protocol(self):
        planner = StructuredTravelPlanner(_PROTOCOL)
        planner.deepseek_brain = None
        prefs = {
            "destinationCity": "深圳",
            "interests": ["经典景点"],
            "hotelLevel": "舒适",
            "startDate": "2026-07-14",
        }
        pois = planner._build_pois(prefs)
        self.assertEqual([item["name"] for item in pois["attractions"]], ["深圳湾公园"])
        self.assertIsInstance(pois["raw"], str)
        hotels = planner._build_hotels(prefs)
        self.assertEqual([item["name"] for item in hotels["candidates"]], ["样例酒店"])
        self.assertEqual(hotels["area_recommendation"], "深圳湾公园周边")
        self.assertEqual(hotels["provider_status"], "amap_fallback")

    def test_langchain_wrapper_returns_text_for_structured_tool(self):
        adapter = self._adapter()
        poi_tool = next(t for t in adapter.get_langchain_tools() if t.name == "search_poi")
        output = poi_tool._run({"city": "深圳", "preference": "经典景点"})
        self.assertIsInstance(output, str)
        self.assertIn("attractions", json.loads(output))


if __name__ == "__main__":
    unittest.main()
