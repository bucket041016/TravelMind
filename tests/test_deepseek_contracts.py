from __future__ import annotations

import unittest

from pydantic import ValidationError

from sync.multi_agent.deepseek_brain import DeepSeekPlanningBrainAgent
from sync.multi_agent.deepseek_contracts import (
    HotelPriceOutput,
    PlanOutput,
    ReviewOutput,
    RouteJudgement,
)


class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeModel:
    """记录调用次数与最后一次消息，供 _invoke_parsed 的重试测试使用。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.last_messages = None

    def invoke(self, messages, **kwargs):
        self.last_messages = messages
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return _FakeResponse(self.responses[index])


class TravelMindDeepSeekContractTests(unittest.TestCase):
    def test_parse_fenced_json_returns_validated_dict(self):
        raw = (
            '```json\n{"days":[{"day":1,"theme":"适应","items":['
            '{"title":"深圳湾公园","candidate_id":"p1","category":"activity"}]}]}\n```'
        )
        parsed = DeepSeekPlanningBrainAgent._parse_json_object(raw, PlanOutput)
        self.assertEqual(parsed["days"][0]["items"][0]["title"], "深圳湾公园")
        self.assertIs(parsed["days"][0]["items"][0]["is_suggestion"], False)

    def test_parse_strips_preface_and_postscript(self):
        raw = '好的，这是行程：\n{"days":[]}\n希望有帮助'
        parsed = DeepSeekPlanningBrainAgent._parse_json_object(raw, PlanOutput)
        self.assertEqual(parsed["days"], [])

    def test_type_coercion_string_bool_and_day(self):
        raw = '{"days":[{"day":"2","items":[{"is_suggestion":"false","category":"food"}]}]}'
        parsed = DeepSeekPlanningBrainAgent._parse_json_object(raw, PlanOutput)
        self.assertEqual(parsed["days"][0]["day"], 2)
        self.assertIs(parsed["days"][0]["items"][0]["is_suggestion"], False)

    def test_plan_rejects_non_list_days(self):
        with self.assertRaises(ValidationError):
            DeepSeekPlanningBrainAgent._parse_json_object('{"days":"oops"}', PlanOutput)

    def test_route_requires_decision(self):
        with self.assertRaises(ValidationError):
            DeepSeekPlanningBrainAgent._parse_json_object('{"suggested_mode":"taxi"}', RouteJudgement)

    def test_hotel_prices_drop_unknown_fields(self):
        parsed = DeepSeekPlanningBrainAgent._parse_json_object(
            '{"prices":[{"candidate_id":"h1","estimated_price_range":"300-500","extra":"x"}]}',
            HotelPriceOutput,
        )
        self.assertNotIn("extra", parsed["prices"][0])

    def test_review_coerces_scores_and_needs_repair(self):
        raw = (
            '{"overall_score":"85","route_score":80.5,"pace_score":90,'
            '"cluster_score":70,"logic_score":75,"needs_repair":"true",'
            '"issues":[],"fixes":[]}'
        )
        parsed = DeepSeekPlanningBrainAgent._parse_json_object(raw, ReviewOutput)
        self.assertEqual(parsed["overall_score"], 85.0)
        self.assertEqual(parsed["route_score"], 80.5)
        self.assertIs(parsed["needs_repair"], True)

    def test_invoke_parsed_retries_with_feedback(self):
        brain = DeepSeekPlanningBrainAgent()
        brain.model = _FakeModel(['{"days":"oops"}', '{"days":[]}'])
        parsed = brain._invoke_parsed("system", "user", PlanOutput)
        self.assertEqual(parsed["days"], [])
        self.assertEqual(brain.model.calls, 2)
        human = brain.model.last_messages[1]
        self.assertIn("上一次输出无法解析或校验失败", human.content)

    def test_invoke_parsed_raises_after_exhausting_retries(self):
        brain = DeepSeekPlanningBrainAgent()
        brain.model = _FakeModel(['{"days":"oops"}', '{"days":"still-oops"}'])
        with self.assertRaises(ValueError):
            brain._invoke_parsed("system", "user", PlanOutput)
        self.assertEqual(brain.model.calls, 2)


if __name__ == "__main__":
    unittest.main()
