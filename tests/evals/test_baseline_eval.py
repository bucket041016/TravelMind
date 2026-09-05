from __future__ import annotations

import unittest

try:
    from .fixtures import build_scenarios
    from .run_baseline import render_markdown, run_all, run_scenario
except ImportError:
    from fixtures import build_scenarios
    from run_baseline import render_markdown, run_all, run_scenario


class TravelMindPhase0EvaluationTests(unittest.TestCase):
    def test_suite_contains_ten_fixed_scenarios(self):
        scenarios = build_scenarios()
        self.assertEqual(len(scenarios), 10)
        self.assertEqual(len({scenario.name for scenario in scenarios}), 10)

    def test_each_scenario_is_offline_and_reports_all_metrics(self):
        metric_names = {
            "real_place_binding_rate",
            "duplicate_place_rate",
            "hard_constraint_satisfaction",
            "route_over_tolerance_rate",
            "budget_deviation",
            "return_hotel_contamination_rate",
            "fallback_rate",
        }
        for scenario in build_scenarios():
            with self.subTest(scenario=scenario.name):
                result = run_scenario(scenario)
                self.assertEqual(result["scenario"], scenario.name)
                self.assertTrue(metric_names.issubset(result["metrics"]))
                self.assertGreater(result["calls"]["total"], 0)
                self.assertGreaterEqual(result["metrics"]["real_place_binding_rate"], 0.0)
                self.assertLessEqual(result["metrics"]["real_place_binding_rate"], 1.0)
                self.assertGreaterEqual(result["metrics"]["fallback_rate"], 0.0)
                self.assertLessEqual(result["metrics"]["fallback_rate"], 1.0)

    def test_current_suite_preserves_baseline_risk_signals_and_phase1_constraint_flow(self):
        report = run_all()
        by_name = {item["scenario"]: item for item in report["scenarios"]}
        self.assertEqual(by_name["free_text_hard_constraint"]["metrics"]["hard_constraint_satisfaction"], 1.0)
        self.assertGreater(by_name["dependency_fallback"]["metrics"]["fallback_rate"], 0.0)
        self.assertEqual(by_name["return_transfer_isolation"]["metrics"]["return_hotel_contamination_rate"], 0.0)
        self.assertEqual(report["aggregate"]["scenario_count"], 10)
        self.assertEqual(report["aggregate"]["total_calls"], 141)
        self.assertEqual(report["aggregate"]["total_tool_failures"], 4)

    def test_report_renderer_labels_phase2_suite_separately(self):
        report = {
            "suite": "travelmind-phase2-contract-ranking",
            "aggregate": {"scenario_count": 0, "averages": {}, "planning_modes": {}, "total_calls": 0, "total_tool_failures": 0},
            "scenarios": [],
        }
        rendered = render_markdown(report)
        self.assertIn("TravelMind Phase 2 候选 Contract 与排序评测", rendered)
        self.assertIn("候选 Contract 接入后的变化", rendered)


if __name__ == "__main__":
    unittest.main()
