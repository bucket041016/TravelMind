from __future__ import annotations

import unittest
from pathlib import Path

from sync.multi_agent.structured_planner import StructuredTravelPlanner
from sync.travel_web_app import PlanRequest


def planner() -> StructuredTravelPlanner:
    return StructuredTravelPlanner("fixture://phase1")


class TravelMindPhase1ConstraintTests(unittest.TestCase):
    def test_plan_request_accepts_constraint_fields_and_keeps_legacy_defaults(self):
        request = PlanRequest(
            freeText="不要安排夜间活动",
            hardConstraints=["必须靠近地铁"],
            softPreferences=["希望节奏轻松"],
        )
        payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()

        self.assertEqual(payload["freeText"], "不要安排夜间活动")
        self.assertEqual(payload["hardConstraints"], ["必须靠近地铁"])
        self.assertEqual(payload["softPreferences"], ["希望节奏轻松"])

        legacy = PlanRequest()
        legacy_payload = legacy.model_dump() if hasattr(legacy, "model_dump") else legacy.dict()
        self.assertEqual(legacy_payload["freeText"], "")
        self.assertEqual(legacy_payload["hardConstraints"], [])
        self.assertEqual(legacy_payload["softPreferences"], [])

    def test_normalization_preserves_raw_text_and_classifies_constraints(self):
        prefs = planner()._normalize_preferences(
            {
                "freeText": "不要安排夜间活动；希望每天留出休息时间；附近商圈即可。",
                "hardConstraints": ["必须靠近地铁"],
                "softPreferences": ["优先选择室内场所"],
            }
        )

        summary = prefs["constraintSummary"]
        hard_text = [item["text"] for item in summary["hard"]]
        soft_text = [item["text"] for item in summary["soft"]]
        unknown_text = [item["text"] for item in summary["unknown"]]

        self.assertEqual(prefs["freeText"], "不要安排夜间活动；希望每天留出休息时间；附近商圈即可。")
        self.assertIn("必须靠近地铁", hard_text)
        self.assertIn("不要安排夜间活动", hard_text)
        self.assertIn("优先选择室内场所", soft_text)
        self.assertIn("希望每天留出休息时间", soft_text)
        self.assertIn("附近商圈即可", unknown_text)
        self.assertEqual(prefs["hardConstraints"], hard_text)
        self.assertEqual(prefs["softPreferences"], soft_text)

    def test_constraint_summary_reaches_planning_brain_payload(self):
        planning = planner()
        prefs = planning._normalize_preferences(
            {
                "freeText": "不要安排夜间活动",
                "hardConstraints": ["必须靠近地铁"],
                "softPreferences": ["希望轻松一点"],
            }
        )
        brain_payload, _ = planning._planning_brain_payload(
            prefs,
            {"recommended": "rail", "options": []},
            {"recommended_modes": ["transit"], "segments": []},
            {"area_recommendation": "后海地铁站", "candidates": []},
            {"attractions": [], "foods": [], "specialty_places": []},
            {},
            {},
        )

        self.assertEqual(brain_payload["constraint_summary"], prefs["constraintSummary"])
        self.assertIn("不要安排夜间活动", " ".join(brain_payload["constraints"]))
        self.assertIn("必须靠近地铁", " ".join(brain_payload["constraints"]))

    def test_rule_quality_review_reports_constraint_status_and_evidence(self):
        planning = planner()
        prefs = planning._normalize_preferences(
            {
                "freeText": "不要安排夜间活动",
                "preferenceProfile": {"pace": "标准", "maxTransferMinutes": 45},
            }
        )
        review = planning._rule_quality_review(
            prefs,
            [
                {
                    "day": 1,
                    "items": [
                        {
                            "time": "夜间",
                            "category": "activity",
                            "title": "夜游建议",
                            "is_real_place": False,
                            "place_source": "llm_suggestion",
                        }
                    ],
                }
            ],
        )

        self.assertTrue(review["constraints"])
        item = next(item for item in review["constraints"] if item["text"] == "不要安排夜间活动")
        self.assertEqual(item["status"], "violated")
        self.assertTrue(item["evidence"])
        self.assertIn(item["kind"], {"hard", "soft", "unknown"})

    def test_frontend_exposes_free_text_and_constraint_contract(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "web" / "app.js").read_text(encoding="utf-8")
        index_html = (root / "web" / "index.html").read_text(encoding="utf-8")

        self.assertIn('name="freeText"', index_html)
        self.assertIn("freeText", app_js)
        self.assertIn("hardConstraints", app_js)
        self.assertIn("softPreferences", app_js)
        self.assertIn("constraintSummary", app_js)


if __name__ == "__main__":
    unittest.main()
