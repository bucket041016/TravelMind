from __future__ import annotations

import unittest

from sync.multi_agent.base_agent import MCPToolbox
from sync.multi_agent.orchestrator import MultiAgentTravelPlanner
from sync.multi_agent.preference_agent import PreferenceAgent
from sync.multi_agent.schemas import TravelPlanState


class _FakeAdapter:
    """离线替身：按工具名返回固定文本，记录调用。"""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    def call_mcp_tool(self, tool_name: str, **kwargs):
        self.calls.append((tool_name, kwargs))
        return self.responses.get(tool_name, "")


def _parse(text: str):
    agent = PreferenceAgent()
    state = TravelPlanState(raw_request=text)
    agent.run(state)
    return state.preferences


class TravelMindMultiAgentChatSmokeTests(unittest.TestCase):
    """旧 /api/multi-agent-chat 链路的冒烟测试（D4：先补冒烟测试再决定退役）。"""

    def test_preference_agent_parses_natural_language(self):
        prefs = _parse("从广州去深圳玩2天，预算800元，喜欢美食和经典景点，住经济型酒店，坐高铁。")
        self.assertEqual(prefs.origin, "广州")
        self.assertEqual(prefs.destination, "深圳")
        self.assertEqual(prefs.days, 2)
        self.assertEqual(prefs.budget, 800)
        self.assertEqual(prefs.hotel_level, "经济")
        self.assertIn("美食", prefs.interests)
        self.assertIn("经典景点", prefs.interests)
        self.assertIn("rail", prefs.route_modes)

    def test_preference_agent_parses_chinese_number_days(self):
        prefs = _parse("周末去厦门玩两天，两人，预算1000。")
        self.assertEqual(prefs.days, 2)
        self.assertEqual(prefs.travelers, 2)
        self.assertEqual(prefs.budget, 1000)

    def test_preference_agent_detects_file_requirement(self):
        prefs = _parse("去杭州玩3天，帮我生成行程文件保存。")
        self.assertTrue(prefs.require_file)

    def test_full_multi_agent_pipeline_smoke(self):
        adapter = _FakeAdapter(
            {
                "get_weather": "深圳 明天天气：晴，22~30°C。",
                "amap_plan_routes": "【高铁/城际铁路】广州南 -> 深圳北，约 40 分钟。",
                "search_poi": "【景点/活动】\n1. 深圳湾公园（评分4.6）",
                "estimate_budget": "总计：约 600 元",
            }
        )
        fake_box = MCPToolbox(adapter)

        planner = MultiAgentTravelPlanner("http://127.0.0.1:1/dummy")
        planner.writer_agent.toolbox = fake_box
        for agent in planner.fact_agents:
            agent.toolbox = fake_box

        result = planner.run("从广州去深圳玩2天，预算800元，喜欢经典景点。")

        self.assertTrue(result["answer"].strip())
        self.assertIn("深圳", result["answer"])
        self.assertTrue(result["trace"])
        self.assertTrue(result["agent_steps"])
        # 四个事实 Agent + 偏好 + Writer 都应出现在步骤里。
        self.assertGreaterEqual(len(result["trace"]), 6)


if __name__ == "__main__":
    unittest.main()
