from __future__ import annotations

import json
import unittest

from sync.mcp_tools_adapter import MCPToolAdapter, MCPToolResult
from sync.multi_agent.base_agent import MCPToolbox


class _FakeAdapter:
    """离线替身：同时提供字符串与结构化两种访问形态。"""

    def __init__(self, result):
        self.result = result

    def call_mcp_tool(self, tool_name, **kwargs):
        return MCPToolResult.from_value(tool_name, self.result).text

    def call_mcp_tool_result(self, tool_name, **kwargs):
        return MCPToolResult.from_value(tool_name, self.result)


class TravelMindAdapterStructuredTests(unittest.TestCase):
    def test_coerce_structured_parses_json_object(self):
        self.assertEqual(MCPToolAdapter._coerce_structured('{"attractions": []}'), {"attractions": []})

    def test_coerce_structured_parses_json_array(self):
        self.assertEqual(MCPToolAdapter._coerce_structured('[{"name": "x"}]'), [{"name": "x"}])

    def test_coerce_structured_keeps_plain_text(self):
        text = "【景点/活动】\n1. 深圳湾公园"
        self.assertEqual(MCPToolAdapter._coerce_structured(text), text)

    def test_coerce_structured_keeps_non_object_json_as_text(self):
        self.assertEqual(MCPToolAdapter._coerce_structured("123"), "123")
        self.assertEqual(MCPToolAdapter._coerce_structured("true"), "true")

    def test_from_value_dict_becomes_structured_data(self):
        result = MCPToolResult.from_value("search_poi", {"attractions": []})
        self.assertEqual(result.source, "structured_data")
        self.assertEqual(result.data, {"attractions": []})
        self.assertEqual(result.text, json.dumps({"attractions": []}, ensure_ascii=False))

    def test_from_value_json_text_becomes_text_json(self):
        result = MCPToolResult.from_value("search_poi", '{"candidates": []}')
        self.assertEqual(result.source, "text_json")
        self.assertEqual(result.data, {"candidates": []})
        self.assertEqual(result.text, '{"candidates": []}')

    def test_from_value_plain_text_stays_text_only(self):
        result = MCPToolResult.from_value("get_weather", "深圳 晴")
        self.assertEqual(result.source, "text_only")
        self.assertIsNone(result.data)
        self.assertEqual(result.text, "深圳 晴")

    def test_from_value_blank_becomes_empty(self):
        result = MCPToolResult.from_value("get_weather", "   ")
        self.assertEqual(result.source, "empty")
        self.assertIn("空结果", result.text)
        self.assertIsNone(result.data)

    def test_toolbox_call_and_call_text_return_string(self):
        box = MCPToolbox(_FakeAdapter({"candidates": []}))
        self.assertEqual(box.call("search_hotels"), '{"candidates": []}')
        self.assertEqual(box.call_text("search_hotels"), '{"candidates": []}')

    def test_toolbox_call_text_with_plain_response(self):
        box = MCPToolbox(_FakeAdapter("text result"))
        self.assertEqual(box.call_text("search_poi"), "text result")
        self.assertEqual(box.call("search_poi"), "text result")

    def test_toolbox_call_structured_returns_wrapper(self):
        box = MCPToolbox(_FakeAdapter({"candidates": []}))
        result = box.call_structured("search_hotels")
        self.assertIsInstance(result, MCPToolResult)
        self.assertEqual(result.source, "structured_data")
        self.assertEqual(result.data, {"candidates": []})
        self.assertEqual(result.tool_name, "search_hotels")
        self.assertEqual(result.validation_error, "")

    def test_toolbox_call_structured_with_text_response(self):
        box = MCPToolbox(_FakeAdapter("plain text"))
        result = box.call_structured("get_weather")
        self.assertEqual(result.source, "text_only")
        self.assertIsNone(result.data)
        self.assertEqual(result.text, "plain text")


if __name__ == "__main__":
    unittest.main()
