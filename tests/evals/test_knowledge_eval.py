"""知识库检索离线评测：TRAVELMIND_KNOWLEDGE 开/关两种状态下的可观测指标。

与 tests/evals/test_baseline_eval.py 的分界：后者跑 build_scenarios() 的 10 个
已定基线场景（发布质量门的参照物），本文件跑 build_knowledge_scenarios() 的
知识库专用场景。两者互不影响，因此 139 次调用与 phase3_report.json 基线不变。

指标全部由计划快照直接计算，不触网络、Key 或当前日期。
"""

from __future__ import annotations

import unittest

from sync.multi_agent.knowledge_service import knowledge_enabled
from sync.multi_agent.structured_planner import StructuredTravelPlanner

try:
    from .fixtures import EvalScenario, FixtureDeepSeekBrain, FixtureToolbox, build_knowledge_scenarios
except ImportError:  # pragma: no cover - 直接脚本执行回退
    from fixtures import EvalScenario, FixtureDeepSeekBrain, FixtureToolbox, build_knowledge_scenarios


def knowledge_metrics(plan: dict) -> dict:
    """从计划快照计算知识库检索的可观测指标。"""
    knowledge = plan.get("knowledge") or {}
    items = [item for day in plan.get("itinerary_days") or [] for item in day.get("items") or []]
    enriched = [item for item in items if item.get("knowledge_detail")]
    indoor = [item for item in enriched if item.get("category") in {"activity", "food"}]
    return {
        "provider_status": str(knowledge.get("provider_status") or ""),
        "matched_count": int(knowledge.get("matched_count") or 0),
        "candidate_count": int(knowledge.get("candidate_count") or 0),
        "enriched_items": len(enriched),
        "enriched_real_items": len([item for item in enriched if item.get("is_real_place")]),
        "indoor_enriched_items": len(indoor),
        "detail_sources": {str(item.get("detail_source")) for item in items},
        "place_sources": {str(item.get("place_source")) for item in items},
        "real_place_binding_rate": (
            round(
                len([item for item in items if item.get("is_real_place") and isinstance(item.get("location_point"), dict)]) / len(items),
                4,
            )
            if items
            else 0.0
        ),
    }


def run_knowledge_scenario(scenario: EvalScenario, *, flag: str) -> tuple[dict, dict]:
    import os

    if flag:
        os.environ["TRAVELMIND_KNOWLEDGE"] = flag
    else:
        os.environ.pop("TRAVELMIND_KNOWLEDGE", None)

    toolbox = FixtureToolbox(scenario)
    planner = StructuredTravelPlanner("fixture://knowledge-eval")
    planner.toolbox = toolbox
    planner.deepseek_brain = FixtureDeepSeekBrain(scenario)
    plan = planner.run(scenario.payload)
    kb_calls = [kwargs for name, kwargs in toolbox.calls if name == "kb_retrieve"]
    return plan, {"kb_calls": len(kb_calls), "kb_city": (kb_calls[0].get("city") if kb_calls else "")}


class TravelMindKnowledgeEvalTests(unittest.TestCase):
    """知识库检索评测：开启时富化可观测，关闭时与现状一致。"""

    def setUp(self):
        self.scenarios = {scenario.name: scenario for scenario in build_knowledge_scenarios()}
        self.addCleanup(self._clear_flag)

    @staticmethod
    def _clear_flag():
        import os

        os.environ.pop("TRAVELMIND_KNOWLEDGE", None)

    def test_suite_contains_four_fixed_knowledge_scenarios(self):
        scenarios = build_knowledge_scenarios()
        self.assertEqual(len(scenarios), 4)
        self.assertEqual(len({scenario.name for scenario in scenarios}), 4)

    def test_baseline_scenarios_stay_at_ten(self):
        from .fixtures import build_scenarios

        self.assertEqual(len(build_scenarios()), 10)

    def test_flag_on_enriches_selected_candidates(self):
        scenario = self.scenarios["knowledge_booking_rules"]
        plan, calls = run_knowledge_scenario(scenario, flag="on")

        self.assertEqual(calls["kb_calls"], 1)
        self.assertEqual(calls["kb_city"], "深圳")
        metrics = knowledge_metrics(plan)
        self.assertEqual(metrics["provider_status"], "knowledge_base")
        self.assertGreater(metrics["matched_count"], 0)
        self.assertGreater(metrics["enriched_items"], 0)
        self.assertEqual(metrics["enriched_real_items"], metrics["enriched_items"])
        self.assertIn("knowledge_base", metrics["detail_sources"])
        self.assertTrue(metrics["place_sources"])
        self.assertTrue(
            metrics["place_sources"].issubset(
                {"amap_poi", "hotel_poi", "planning_note", "transport_note", "llm_suggestion", "transport_hub"}
            )
        )
        # 知识库只补文字，不改变真实地点绑定率的口径。
        self.assertGreater(metrics["real_place_binding_rate"], 0.0)

    def test_flag_on_rainy_scenario_surfaces_indoor_facts(self):
        scenario = self.scenarios["knowledge_rainy_indoor"]
        plan, _ = run_knowledge_scenario(scenario, flag="on")
        metrics = knowledge_metrics(plan)
        self.assertGreater(metrics["matched_count"], 0)
        self.assertGreater(metrics["indoor_enriched_items"], 0)

    def test_flag_off_makes_no_call_and_no_enrichment(self):
        scenario = self.scenarios["knowledge_flag_off"]
        plan, calls = run_knowledge_scenario(scenario, flag="")

        self.assertFalse(knowledge_enabled())
        self.assertEqual(calls["kb_calls"], 0)
        self.assertEqual(plan.get("knowledge"), {})
        metrics = knowledge_metrics(plan)
        self.assertEqual(metrics["enriched_items"], 0)
        self.assertNotIn("knowledge_base", metrics["detail_sources"])

    def test_not_covered_city_degrades_silently(self):
        scenario = self.scenarios["knowledge_not_covered"]
        plan, calls = run_knowledge_scenario(scenario, flag="on")

        self.assertEqual(calls["kb_calls"], 1)
        metrics = knowledge_metrics(plan)
        self.assertEqual(metrics["provider_status"], "not_covered")
        self.assertEqual(metrics["matched_count"], 0)
        self.assertEqual(metrics["enriched_items"], 0)
        # 降级不拖垮规划：真实地点仍然绑定。
        self.assertGreater(metrics["real_place_binding_rate"], 0.0)

    def test_flag_on_does_not_regress_real_place_binding(self):
        """开关前后真实地点绑定率应一致——知识库只补文字，不改事实层。"""
        off_plan, _ = run_knowledge_scenario(self.scenarios["knowledge_booking_rules"], flag="")
        on_plan, _ = run_knowledge_scenario(self.scenarios["knowledge_booking_rules"], flag="on")
        self.assertEqual(
            knowledge_metrics(off_plan)["real_place_binding_rate"],
            knowledge_metrics(on_plan)["real_place_binding_rate"],
        )


if __name__ == "__main__":
    unittest.main()
