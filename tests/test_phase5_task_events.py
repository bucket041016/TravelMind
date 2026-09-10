"""Phase 5 任务事件与 SSE 进度测试：TestClient + 评测 fixture，全离线。"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from sync import persistence
from sync import travel_web_app as web
from sync.multi_agent.structured_planner import StructuredTravelPlanner
from tests.evals.fixtures import EvalScenario, FixtureDeepSeekBrain, FixtureToolbox
from tests.test_phase5_persistence import _TmpDb


def _fixture_planner():
    scenario = EvalScenario(name="p5-events", payload={
        "originCity": "广州",
        "destinationCity": "深圳",
        "startDate": "2026-08-15",
        "days": 2,
        "budget": 5000,
    })
    toolbox = FixtureToolbox(scenario)
    planner = StructuredTravelPlanner("fixture://phase5-events")
    planner.toolbox = toolbox
    planner.deepseek_brain = FixtureDeepSeekBrain(scenario)
    return planner, toolbox


def _parse_sse(lines):
    """把 SSE 文本行解析为 [(event, data)] 列表。"""
    events = []
    current_event = None
    for line in lines:
        line = line.strip()
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and current_event:
            events.append((current_event, line.split(":", 1)[1].strip()))
            current_event = None
    return events


def _wait_task_done(task_id: str, timeout_seconds: float = 10.0) -> None:
    """等待后台 runner 真正终态（done 事件之后还有快照与状态写入）。"""
    import time

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        task = persistence.get_task(task_id)
        if task and task["status"] in {"done", "error"}:
            return
        time.sleep(0.05)


class TravelMindTaskEventsTests(unittest.TestCase):
    def setUp(self):
        self.db = _TmpDb()
        self.db.__enter__()
        self.planner, self.toolbox = _fixture_planner()
        web._structured_planner = self.planner
        self.client = TestClient(web.app)

    def tearDown(self):
        web._structured_planner = None
        self.db.__exit__(None, None, None)

    def test_plan_async_returns_task_and_streams_events(self):
        response = self.client.post("/api/plan-async", json={
            "originCity": "广州", "destinationCity": "深圳", "startDate": "2026-08-15",
            "days": 2, "budget": 5000, "clientRequestId": "req-1",
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["replayed"])
        task_id = body["task_id"]

        with self.client.stream("GET", f"/api/plan-events/{task_id}") as stream:
            lines = [line for line in stream.iter_lines()]
        events = _parse_sse(lines)
        kinds = [event for event, _ in events]
        self.assertEqual(kinds[-1], "done")
        self.assertIn("step_start", kinds)
        self.assertIn("step_end", kinds)
        # step_start/step_end 成对且数量一致
        self.assertEqual(kinds.count("step_start"), kinds.count("step_end"))
        # seq（事件 id）单调递增
        ids = [int(line.split(":", 1)[1].strip()) for line in lines if line.strip().startswith("id:")]
        self.assertEqual(ids, sorted(ids))
        # 事件数据含真实步骤名与状态
        step_starts = [json.loads(data) for event, data in events if event == "step_start"]
        self.assertTrue(any("WeatherAgent" in item.get("step", "") for item in step_starts))
        step_ends = [json.loads(data) for event, data in events if event == "step_end"]
        self.assertTrue(all("status" in item and "duration_ms" in item for item in step_ends))
        # done 事件后 runner 仍在写快照/mark_task，等任务真正终态再结束测试，
        # 避免 Windows 下 tmp DB 文件被后台线程占用。
        _wait_task_done(task_id)

    def test_idempotent_resubmit_does_not_duplicate_calls(self):
        payload = {
            "originCity": "广州", "destinationCity": "深圳", "startDate": "2026-08-15",
            "days": 2, "budget": 5000, "clientRequestId": "req-dup",
        }
        first = self.client.post("/api/plan-async", json=payload).json()
        # 等第一次任务完成（fixture 毫秒级，轮询任务状态）。
        import time

        for _ in range(100):
            task = persistence.get_task(first["task_id"])
            if task and task["status"] in {"done", "error"}:
                break
            time.sleep(0.05)
        calls_after_first = len(self.toolbox.calls)
        second = self.client.post("/api/plan-async", json=payload)
        self.assertEqual(second.status_code, 200)
        second_body = second.json()
        self.assertTrue(second_body["replayed"])
        self.assertEqual(second_body["task_id"], first["task_id"])
        self.assertEqual(len(self.toolbox.calls), calls_after_first)

    def test_task_status_endpoint_returns_plan_when_done(self):
        response = self.client.post("/api/plan-async", json={
            "originCity": "广州", "destinationCity": "深圳", "days": 2, "clientRequestId": "req-2",
        })
        task_id = response.json()["task_id"]
        import time

        for _ in range(100):
            task = persistence.get_task(task_id)
            if task and task["status"] == "done":
                break
            time.sleep(0.05)
        status = self.client.get(f"/api/task/{task_id}")
        self.assertEqual(status.status_code, 200)
        data = status.json()
        self.assertEqual(data["status"], "done")
        self.assertTrue(data["plan"]["itinerary_days"])
        self.assertEqual(data["plan"]["plan_id"], data["plan_id"])

    def test_task_status_unknown_returns_404(self):
        self.assertEqual(self.client.get("/api/task/task-missing").status_code, 404)

    def test_persistence_off_returns_503(self):
        with patch.dict(os.environ, {"TRAVELMIND_PERSISTENCE": "off"}):
            response = self.client.post("/api/plan-async", json={
                "originCity": "广州", "destinationCity": "深圳", "days": 2,
            })
        self.assertEqual(response.status_code, 503)

    def test_progress_callback_exception_does_not_break_run(self):
        def boom(event):
            raise RuntimeError("callback failure")

        self.planner._progress.callback = boom
        try:
            plan = self.planner.run({
                "originCity": "广州", "destinationCity": "深圳", "startDate": "2026-08-15", "days": 2,
            })
        finally:
            self.planner._progress.callback = None
        self.assertTrue(plan["itinerary_days"])
        self.assertIn("markdown", plan)

    def test_record_emits_start_and_end_events_via_thread_local(self):
        events = []
        self.planner._progress.callback = events.append
        try:
            prefs = self.planner._normalize_preferences({"destinationCity": "深圳"})
            trace = []
            self.planner._record(trace, "WeatherAgent 天气与出行建议", prefs, lambda: {"深圳": "晴"})
        finally:
            self.planner._progress.callback = None
        self.assertEqual([event["type"] for event in events], ["step_start", "step_end"])
        self.assertEqual(events[0]["step"], "WeatherAgent 天气与出行建议")
        self.assertEqual(events[1]["status"], "success")
        self.assertIn("duration_ms", events[1])
        # 事件绝不进入 trace 数组（139/4 断言边界）
        self.assertEqual(len(trace), 1)
        self.assertEqual(set(trace[0].keys()), {"name", "status", "args", "output", "duration_ms"})

    def test_run_without_callback_keeps_trace_shape(self):
        plan = self.planner.run({
            "originCity": "广州", "destinationCity": "深圳", "startDate": "2026-08-15", "days": 2,
        })
        for entry in plan["trace"]:
            self.assertEqual(set(entry.keys()), {"name", "status", "args", "output", "duration_ms"})


class TravelMindProgressFrontendTests(unittest.TestCase):
    def _source(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "web", "app.js"), encoding="utf-8") as handle:
            return handle.read()

    def test_send_plan_uses_async_endpoint_and_eventsource(self):
        source = self._source()
        self.assertIn("/api/plan-async", source)
        self.assertIn("new EventSource(", source)
        self.assertIn("BACKEND_STEP_TO_STAGE", source)

    def test_active_task_recovery_and_fallback_present(self):
        source = self._source()
        self.assertIn("travelmind:activeTask:v1", source)
        self.assertIn("sendPlanSync", source)
        self.assertIn("es.close()", source)
        self.assertIn("restoreActiveTask()", source)


if __name__ == "__main__":
    unittest.main()
