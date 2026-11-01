"""发布质量门测试：compare() 纯函数 + CLI 退出码（不触 DB/网络/历史文件）。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

try:
    from tests.evals.release_gate import compare, main
except ImportError:  # pragma: no cover
    from release_gate import compare, main


def _aggregate(**averages) -> dict:
    return {"averages": dict(averages)}


_HEALTHY = {
    "budget_deviation": 0.4897,
    "real_place_binding_rate": 0.5903,
    "hard_constraint_satisfaction": 0.75,
    "fallback_rate": 0.1,
}


class TravelMindReleaseGateTests(unittest.TestCase):
    def test_identical_metrics_pass(self):
        result = compare(_aggregate(**_HEALTHY), _aggregate(**_HEALTHY))
        self.assertTrue(result["passed"])
        self.assertEqual(result["regressions"], [])

    def test_budget_deviation_relative_regression(self):
        current = dict(_HEALTHY, budget_deviation=0.4897 * 1.15)
        result = compare(_aggregate(**current), _aggregate(**_HEALTHY))
        self.assertFalse(result["passed"])
        self.assertEqual(result["regressions"][0]["metric"], "budget_deviation")

    def test_budget_deviation_small_relative_change_passes(self):
        current = dict(_HEALTHY, budget_deviation=0.4897 * 1.05)
        result = compare(_aggregate(**current), _aggregate(**_HEALTHY))
        self.assertTrue(result["passed"])

    def test_binding_rate_absolute_regression(self):
        current = dict(_HEALTHY, real_place_binding_rate=0.5903 - 0.06)
        result = compare(_aggregate(**current), _aggregate(**_HEALTHY))
        self.assertFalse(result["passed"])
        self.assertEqual(result["regressions"][0]["metric"], "real_place_binding_rate")

    def test_hard_constraint_absolute_regression(self):
        current = dict(_HEALTHY, hard_constraint_satisfaction=0.75 - 0.06)
        result = compare(_aggregate(**current), _aggregate(**_HEALTHY))
        self.assertFalse(result["passed"])
        self.assertEqual(result["regressions"][0]["metric"], "hard_constraint_satisfaction")

    def test_fallback_rate_absolute_regression(self):
        current = dict(_HEALTHY, fallback_rate=0.1 + 0.11)
        result = compare(_aggregate(**current), _aggregate(**_HEALTHY))
        self.assertFalse(result["passed"])
        self.assertEqual(result["regressions"][0]["metric"], "fallback_rate")

    def test_improvements_are_recorded_and_pass(self):
        current = dict(_HEALTHY, budget_deviation=0.30, fallback_rate=0.05)
        result = compare(_aggregate(**current), _aggregate(**_HEALTHY))
        self.assertTrue(result["passed"])
        improved = {item["metric"] for item in result["improvements"]}
        self.assertEqual(improved, {"budget_deviation", "fallback_rate"})

    def test_missing_or_none_metrics_are_skipped(self):
        current = dict(_HEALTHY)
        current.pop("budget_deviation")
        current["fallback_rate"] = None
        result = compare(_aggregate(**current), _aggregate(**_HEALTHY))
        self.assertTrue(result["passed"])
        self.assertIn("budget_deviation", result["skipped"])
        self.assertIn("fallback_rate", result["skipped"])

    def test_zero_reference_budget_uses_absolute_epsilon(self):
        reference = dict(_HEALTHY, budget_deviation=0.0)
        result = compare(_aggregate(**dict(_HEALTHY, budget_deviation=0.05)), _aggregate(**reference))
        self.assertFalse(result["passed"])
        result_small = compare(_aggregate(**dict(_HEALTHY, budget_deviation=0.005)), _aggregate(**reference))
        self.assertTrue(result_small["passed"])

    def test_cli_exit_codes_with_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            reference_path = Path(tmp) / "reference.json"
            good_path = Path(tmp) / "good.json"
            bad_path = Path(tmp) / "bad.json"
            reference_path.write_text(json.dumps({"aggregate": _aggregate(**_HEALTHY)}), encoding="utf-8")
            good_path.write_text(json.dumps({"aggregate": _aggregate(**_HEALTHY)}), encoding="utf-8")
            bad_path.write_text(
                json.dumps({"aggregate": _aggregate(**dict(_HEALTHY, budget_deviation=0.9))}), encoding="utf-8"
            )
            self.assertEqual(main(["--reference", str(reference_path), "--current", str(good_path)]), 0)
            self.assertEqual(main(["--reference", str(reference_path), "--current", str(bad_path)]), 1)
            self.assertEqual(main(["--reference", str(Path(tmp) / "missing.json"), "--current", str(good_path)]), 2)


if __name__ == "__main__":
    unittest.main()
