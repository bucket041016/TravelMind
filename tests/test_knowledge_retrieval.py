"""知识库检索（TRAVELMIND_KNOWLEDGE）：检索器、flag 灰度与候选富化。

覆盖：检索器确定性与排序、flag 关闭时零工具调用、flag 开启时候选与行程项挂上
知识库字段、place_source 不被改写、未覆盖城市静默跳过、refine 后字段不丢。
全部走 FakeToolbox，不触网络、Key 或当前日期。
"""

from __future__ import annotations

import copy
import json
import unittest

from sync.knowledge import retrieve
from sync.knowledge.retriever import KeywordRetriever, _entry_score
from sync.multi_agent.knowledge_service import (
    knowledge_detail_text,
    knowledge_enabled,
    match_knowledge_entry,
)
from sync.multi_agent.structured_planner import StructuredTravelPlanner
from sync.mcp_tools_adapter import MCPToolResult

try:
    from tests.evals.fixtures import FixtureDeepSeekBrain, FixtureToolbox, build_scenarios
except ImportError:  # pragma: no cover - 直接脚本执行回退
    from tests.evals.fixtures import FixtureDeepSeekBrain, FixtureToolbox, build_scenarios


def _scenario(name: str = "standard_weekend"):
    return next(item for item in build_scenarios() if item.name == name)


def _drop_knowledge_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if "知识库详情：" not in line)


class _KbFakeToolbox(FixtureToolbox):
    """在评测 fixture 之上追加可控的知识库返回。"""

    def __init__(self, scenario, kb_status: str = "knowledge_base"):
        super().__init__(scenario)
        self.kb_status = kb_status

    def call(self, tool_name: str, **kwargs):
        if tool_name == "kb_retrieve" and self.kb_status != "knowledge_base":
            self.calls.append((tool_name, dict(kwargs)))
            return {
                "provider_status": self.kb_status,
                "city": str(kwargs.get("city") or ""),
                "query": "",
                "city_guide": None,
                "entries": [],
                "coverage": "none",
                "note": "本地知识库暂未覆盖该目的地。",
            }
        return super().call(tool_name, **kwargs)


def _planner(toolbox, scenario):
    planner = StructuredTravelPlanner("fixture://knowledge")
    planner.toolbox = toolbox
    planner.deepseek_brain = FixtureDeepSeekBrain(scenario)
    return planner


class _RemoveItemBrain(FixtureDeepSeekBrain):
    """只覆盖 refine 需要的 parse_refine_ops：删除指定 item。"""

    def __init__(self, scenario, item_id: str):
        super().__init__(scenario)
        self.item_id = item_id

    def parse_refine_ops(self, payload: dict):
        return {
            "llm_status": "used",
            "operations": [{"action": "remove_item", "item_id": self.item_id, "reason": "测试删除"}],
            "answer": "已删除一项。",
        }


class KnowledgeRetrieverTests(unittest.TestCase):
    """检索器：确定性、城市别名、无覆盖降级与排序。"""

    def setUp(self):
        self.retriever = KeywordRetriever()

    def test_retrieve_is_deterministic(self):
        first = retrieve("深圳")
        second = retrieve("深圳")
        self.assertEqual(
            [item["name"] for item in first["entries"]],
            [item["name"] for item in second["entries"]],
        )

    def test_city_name_variants_resolve_to_same_corpus(self):
        self.assertEqual(
            [item["name"] for item in retrieve("深圳")["entries"]],
            [item["name"] for item in retrieve("深圳市")["entries"]],
        )

    def test_uncovered_city_degrades_to_not_covered(self):
        result = retrieve("拉萨")
        self.assertEqual(result["provider_status"], "not_covered")
        self.assertEqual(result["coverage"], "none")
        self.assertEqual(result["entries"], [])
        self.assertIsNone(result["city_guide"])

    def test_exact_name_ranks_first(self):
        result = retrieve("深圳", query="海上世界文化艺术中心")
        self.assertEqual(result["entries"][0]["name"], "海上世界文化艺术中心")

    def test_rainy_query_ranks_indoor_alternatives_first(self):
        names = [item["name"] for item in retrieve("深圳", query="下雨 室内")["entries"]]
        self.assertTrue(names)
        for name in names:
            entry = next(item for item in retrieve("深圳")["entries"] if item["name"] == name)
            self.assertTrue(entry["indoor"], f"{name} 应在雨天查询中排在前面")

    def test_limit_truncates_entries(self):
        self.assertEqual(len(retrieve("深圳", limit=3)["entries"]), 3)

    def test_entry_score_orders_exact_over_partial(self):
        entries = retrieve("深圳")["entries"]
        exact = next(item for item in entries if item["name"] == "莲花山公园")
        partial = next(item for item in entries if item["name"] == "深圳湾公园")
        self.assertGreater(_entry_score("莲花山公园", exact), _entry_score("莲花山公园", partial))


class KnowledgeTextTests(unittest.TestCase):
    """描述句拼接与候选匹配。"""

    def test_detail_text_skips_empty_fields(self):
        text = knowledge_detail_text({"suggested_duration": "2 小时", "highlights": [], "note": ""})
        self.assertEqual(text, "建议游览 2 小时")

    def test_detail_text_marks_indoor_and_rain_alternative(self):
        text = knowledge_detail_text({"indoor": True, "rainy_alternative": True})
        self.assertIn("室内为主", text)
        self.assertIn("可作为雨天替代", text)

    def test_match_prefers_exact_name_over_alias(self):
        entries = [{"name": "海上世界", "aliases": []}, {"name": "海上世界文化艺术中心", "aliases": ["海上世界"]}]
        self.assertEqual(match_knowledge_entry("海上世界文化艺术中心", entries)["name"], "海上世界文化艺术中心")

    def test_match_returns_none_when_nothing_matches(self):
        self.assertIsNone(match_knowledge_entry("不存在的地方", [{"name": "深圳湾公园"}]))


class KnowledgeFlagTests(unittest.TestCase):
    """灰度开关：关闭时规划路径与现状完全一致。"""

    def tearDown(self):
        import os

        os.environ.pop("TRAVELMIND_KNOWLEDGE", None)

    def _run(self, toolbox, scenario, flag: str | None):
        import os

        if flag is None:
            os.environ.pop("TRAVELMIND_KNOWLEDGE", None)
        else:
            os.environ["TRAVELMIND_KNOWLEDGE"] = flag
        return _planner(toolbox, scenario).run(scenario.payload)

    def _strip_volatile(self, plan):
        """去掉每次运行必然不同、以及按设计随开关变化的字段，剩下的应完全一致。"""
        clone = copy.deepcopy(plan)
        clone.pop("knowledge", None)
        plan_id = str(clone.pop("plan_id", "") or "")
        for step in clone["trace"]:
            step.pop("duration_ms", None)
            # KnowledgeAgent 的输出按设计随开关变化；WriterAgent 的输出是截断到 900 字的
            # Markdown，加减知识库行会改变截断位置，因此同样归一——Markdown 本体另行比较。
            if step["name"].startswith(("KnowledgeAgent", "WriterAgent")):
                step["output"] = ""
            elif isinstance(step.get("output"), str):
                step["output"] = _drop_knowledge_lines(step["output"])
        for group in ("attractions", "foods", "specialty_places"):
            for candidate in (clone.get("pois") or {}).get(group) or []:
                candidate.pop("knowledge", None)
                candidate.pop("knowledge_detail", None)
        for day in clone["itinerary_days"]:
            for item in day["items"]:
                item.pop("knowledge_detail", None)
                item.pop("detail_source", None)
        # plan_id 会渗进静态地图 URL 与导出的 Markdown，统一替换后再比较；
        # Markdown（含 trace 里 WriterAgent 的输出）的知识库详情行按设计随开关增减，同样剔除。
        markdown = clone.get("markdown")
        if isinstance(markdown, str):
            clone["markdown"] = _drop_knowledge_lines(markdown)
        text = json.dumps(clone, ensure_ascii=False, default=str)
        return json.loads(text.replace(plan_id, "<plan-id>"))

    def test_flag_defaults_to_off(self):
        import os

        os.environ.pop("TRAVELMIND_KNOWLEDGE", None)
        self.assertFalse(knowledge_enabled())

    def test_flag_off_makes_no_kb_call_and_returns_empty_knowledge(self):
        scenario = _scenario()
        toolbox = _KbFakeToolbox(scenario)
        plan = self._run(toolbox, scenario, None)

        self.assertEqual([name for name, _ in toolbox.calls if name == "kb_retrieve"], [])
        self.assertEqual(plan["knowledge"], {})
        enriched = [
            item
            for day in plan["itinerary_days"]
            for item in day["items"]
            if item.get("knowledge_detail")
        ]
        self.assertEqual(enriched, [])
        self.assertTrue(any(step["name"].startswith("KnowledgeAgent") for step in plan["trace"]))

    def test_flag_off_plan_matches_knowledge_free_baseline(self):
        scenario = _scenario()
        off_plan = self._run(_KbFakeToolbox(scenario), scenario, "off")
        on_plan = self._run(_KbFakeToolbox(scenario), scenario, "on")
        self.assertEqual(self._strip_volatile(off_plan), self._strip_volatile(on_plan))


class KnowledgeEnrichmentTests(unittest.TestCase):
    """开启时：候选与行程项挂上知识库字段，place_source 不被改写。"""

    def tearDown(self):
        import os

        os.environ.pop("TRAVELMIND_KNOWLEDGE", None)

    def setUp(self):
        import os

        os.environ["TRAVELMIND_KNOWLEDGE"] = "on"
        self.scenario = _scenario()
        self.toolbox = _KbFakeToolbox(self.scenario)
        self.plan = _planner(self.toolbox, self.scenario).run(self.scenario.payload)

    def test_exactly_one_kb_call_per_plan(self):
        kb_calls = [kwargs for name, kwargs in self.toolbox.calls if name == "kb_retrieve"]
        self.assertEqual(len(kb_calls), 1)
        self.assertEqual(kb_calls[0].get("city"), "深圳")

    def test_knowledge_summary_reports_match_counts(self):
        knowledge = self.plan["knowledge"]
        self.assertEqual(knowledge["provider_status"], "knowledge_base")
        self.assertGreater(knowledge["matched_count"], 0)
        self.assertEqual(knowledge["candidate_count"], knowledge["matched_count"] + 6)
        self.assertTrue(knowledge["city_guide"]["summary"])

    def test_selected_candidates_carry_knowledge_and_detail(self):
        pois = self.plan["pois"]
        matched = [
            item
            for group in ("attractions", "foods", "specialty_places")
            for item in pois.get(group) or []
            if item.get("knowledge")
        ]
        self.assertTrue(matched)
        for candidate in matched:
            self.assertTrue(candidate["knowledge_detail"])
            self.assertEqual(candidate["knowledge"]["district"], "南山区")

    def test_itinerary_items_carry_knowledge_detail_and_source(self):
        enriched = [
            item
            for day in self.plan["itinerary_days"]
            for item in day["items"]
            if item.get("knowledge_detail")
        ]
        self.assertTrue(enriched)
        for item in enriched:
            self.assertEqual(item["detail_source"], "knowledge_base")
            self.assertIn("建议游览", item["knowledge_detail"])
            # 知识库不引入地点，真实地点来源仍归高德。
            self.assertEqual(item["place_source"], "amap_poi")

    def test_place_source_vocabulary_is_unchanged(self):
        sources = {
            item["place_source"]
            for day in self.plan["itinerary_days"]
            for item in day["items"]
        }
        self.assertTrue(sources.issubset({"amap_poi", "hotel_poi", "planning_note", "transport_note", "llm_suggestion", "transport_hub"}))

    def test_prompt_payload_exposes_knowledge_fields(self):
        payload, _ = _planner(self.toolbox, self.scenario)._planning_brain_payload(
            self.plan["preferences"],
            self.plan["intercity_transport"],
            self.plan["local_transport"],
            self.plan["hotels"],
            self.plan["pois"],
            self.plan["weather"],
            self.plan.get("weather_advice") or {},
            self.plan["knowledge"],
        )
        with_knowledge = [item for item in payload["candidates"] if item["knowledge_duration"]]
        self.assertTrue(with_knowledge)
        self.assertTrue(payload["city_knowledge"]["summary"])
        self.assertTrue(any("knowledge_*" in line for line in payload["constraints"]))

    def test_prompt_payload_omits_knowledge_when_flag_off(self):
        import os

        scenario = _scenario()
        toolbox = _KbFakeToolbox(scenario)
        os.environ.pop("TRAVELMIND_KNOWLEDGE", None)
        plan = _planner(toolbox, scenario).run(scenario.payload)

        payload, _ = _planner(toolbox, scenario)._planning_brain_payload(
            plan["preferences"],
            plan["intercity_transport"],
            plan["local_transport"],
            plan["hotels"],
            plan["pois"],
            plan["weather"],
            plan.get("weather_advice") or {},
            plan["knowledge"],
        )
        self.assertEqual(payload["city_knowledge"], {})
        self.assertFalse(any("knowledge_*" in line for line in payload["constraints"]))
        self.assertFalse(any(item["knowledge_duration"] for item in payload["candidates"]))

    def test_not_covered_city_is_silent(self):
        scenario = _scenario()
        toolbox = _KbFakeToolbox(scenario, kb_status="not_covered")
        plan = _planner(toolbox, scenario).run(scenario.payload)

        self.assertEqual(plan["knowledge"]["provider_status"], "not_covered")
        self.assertEqual(plan["knowledge"]["matched_count"], 0)
        enriched = [
            item
            for day in plan["itinerary_days"]
            for item in day["items"]
            if item.get("knowledge_detail")
        ]
        self.assertEqual(enriched, [])

    def test_refine_preserves_knowledge_detail(self):
        enriched = [
            item
            for day in self.plan["itinerary_days"]
            for item in day["items"]
            if item.get("knowledge_detail")
        ]
        self.assertTrue(enriched)
        keep = enriched[-1]
        drop = next(
            item
            for day in self.plan["itinerary_days"]
            for item in day["items"]
            if item.get("id") != keep["id"]
        )

        planner = _planner(self.toolbox, self.scenario)
        planner.deepseek_brain = _RemoveItemBrain(self.scenario, drop["id"])
        result = planner.refine_plan(self.plan, "删掉一项")

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["changed"])
        remaining = [item for day in result["plan"]["itinerary_days"] for item in day["items"]]
        kept = next((item for item in remaining if item["id"] == keep["id"]), None)
        self.assertIsNotNone(kept)
        self.assertEqual(kept["knowledge_detail"], keep["knowledge_detail"])
        self.assertEqual(kept["detail_source"], "knowledge_base")


if __name__ == "__main__":
    unittest.main()
