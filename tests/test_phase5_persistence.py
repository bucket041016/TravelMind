"""Phase 5 持久化层测试：全部使用 tmp DB + 环境变量隔离，绝不污染 data/。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sync import persistence


class _TmpDb:
    def __init__(self):
        # Windows 下 SQLite WAL 伴生文件可能在连接关闭后短暂占用，
        # ignore_cleanup_errors 防止偶发 PermissionError 干扰测试结果。
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tmp.name) / "test.db"
        self.env = patch.dict(
            os.environ,
            {"TRAVELMIND_DB_PATH": str(self.db_path), "TRAVELMIND_PERSISTENCE": "on"},
        )

    def __enter__(self):
        self.env.start()
        persistence._initialized_paths.discard(str(self.db_path))
        return self

    def __exit__(self, *args):
        self.env.stop()
        persistence._initialized_paths.discard(str(self.db_path))
        self.tmp.cleanup()
        return False


class TravelMindPersistenceTests(unittest.TestCase):
    def test_flag_off_is_noop_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "off.db"
            with patch.dict(
                os.environ,
                {"TRAVELMIND_PERSISTENCE": "off", "TRAVELMIND_DB_PATH": str(db_path)},
            ):
                persistence.create_task("t1", "r1")
                persistence.append_event("t1", 0, "step_start", {"step": "x"})
                self.assertIsNone(persistence.get_task("t1"))
                self.assertEqual(persistence.load_events("t1"), [])
            self.assertFalse(db_path.exists())

    def test_redact_secrets_all_patterns(self):
        payload = {
            "api_key": "sk-abcdef0123456789abcdef",
            "url": "https://example.com?key=abcdefghij0123456789",
            "nested": {"api_key": "raw-secret-value", "note": "安全文本"},
            "items": ["sk-zzzzzz123456789012345", 42],
        }
        redacted = persistence.redact_secrets(payload)
        # 敏感键名直接掩码（值整体替换，比模式匹配更强）。
        self.assertEqual(redacted["api_key"], "***")
        self.assertIn("key=***", redacted["url"])
        self.assertEqual(redacted["nested"]["api_key"], "***")
        self.assertEqual(redacted["nested"]["note"], "安全文本")
        # 字符串里的 sk- 前缀令牌仍按模式替换。
        self.assertEqual(redacted["items"][0], "sk-***")
        self.assertEqual(redacted["items"][1], 42)

    def test_create_task_idempotent_by_request_id(self):
        with _TmpDb():
            self.assertTrue(persistence.create_task("task-1", "req-1"))
            self.assertFalse(persistence.create_task("task-2", "req-1"))
            task = persistence.get_task_by_request("req-1")
            self.assertEqual(task["task_id"], "task-1")
            self.assertEqual(task["status"], "running")

    def test_events_roundtrip_with_incremental_semantics(self):
        with _TmpDb():
            persistence.create_task("task-1", "req-1")
            persistence.append_event("task-1", 0, "step_start", {"step": "天气"})
            persistence.append_event("task-1", 1, "step_end", {"step": "天气", "status": "success"})
            persistence.append_event("task-1", 2, "done", {"plan_id": "tm-1"})
            all_events = persistence.load_events("task-1")
            self.assertEqual([event for _, event, _ in all_events], ["step_start", "step_end", "done"])
            after_one = persistence.load_events("task-1", after_seq=0)
            self.assertEqual([event for _, event, _ in after_one], ["step_end", "done"])
            self.assertEqual(after_one[0][2]["status"], "success")

    def test_events_redacted_on_write(self):
        with _TmpDb():
            persistence.create_task("task-1", "req-1")
            persistence.append_event("task-1", 0, "step_start", {"step": "x", "api_key": "sk-abcdef0123456789"})
            events = persistence.load_events("task-1")
            self.assertEqual(events[0][2]["api_key"], "***")

    def test_mark_task_and_get_task(self):
        with _TmpDb():
            persistence.create_task("task-1", "req-1")
            persistence.mark_task("task-1", "done", plan_id="tm-1")
            task = persistence.get_task("task-1")
            self.assertEqual(task["status"], "done")
            self.assertEqual(task["plan_id"], "tm-1")

    def test_stale_running_task_reported_interrupted(self):
        with _TmpDb():
            persistence.create_task("task-1", "req-1")
            # 手工把 updated_at 拨到 11 分钟前，模拟进程被杀后的孤儿任务。
            import sqlite3

            conn = sqlite3.connect(str(persistence._db_file()))
            conn.execute("UPDATE tasks SET updated_at='2000-01-01T00:00:00+00:00' WHERE task_id='task-1'")
            conn.commit()
            conn.close()
            task = persistence.get_task("task-1")
            self.assertEqual(task["status"], "interrupted")

    def test_plan_snapshot_roundtrip_latest_and_exact(self):
        with _TmpDb():
            persistence.save_plan_snapshot("tm-1", 0, {"plan_id": "tm-1", "version": 0})
            persistence.save_plan_snapshot("tm-1", 1, {"plan_id": "tm-1", "version": 1})
            self.assertEqual(persistence.load_plan_snapshot("tm-1")["version"], 1)
            self.assertEqual(persistence.load_plan_snapshot("tm-1", version=0)["version"], 0)
            self.assertIsNone(persistence.load_plan_snapshot("tm-x"))

    def test_learned_hints_merge_and_cap(self):
        with _TmpDb():
            persistence.save_learned_hints(["少走路", "别太赶"])
            persistence.save_learned_hints(["别太赶", "少公交"])
            hints = persistence.load_learned_hints()
            self.assertEqual(hints, ["少走路", "别太赶", "少公交"])
            persistence.save_learned_hints([f"规则{index}" for index in range(20)])
            self.assertEqual(len(persistence.load_learned_hints()), 12)

    def test_eval_summary_and_broken_db_swallow_errors(self):
        with _TmpDb():
            persistence.save_eval_summary("suite-a", {"total_calls": 139})
            conn = persistence._connect(persistence._db_file())
            row = conn.execute("SELECT metrics FROM eval_summaries WHERE suite='suite-a'").fetchone()
            conn.close()
            self.assertIn("139", row["metrics"])

            # 非法 DB 路径：所有公开方法吞异常返回安全默认，不抛出。
            with patch.dict(os.environ, {"TRAVELMIND_DB_PATH": "Z:/nonexistent-drive/x.db"}):
                persistence._initialized_paths.clear()
                self.assertIsNone(persistence.get_task("t"))
                self.assertEqual(persistence.load_events("t"), [])
                persistence.save_plan_snapshot("p", 0, {})
                persistence.append_event("t", 0, "x", {})
                persistence.save_learned_hints(["x"])
                self.assertEqual(persistence.load_learned_hints(), [])


if __name__ == "__main__":
    unittest.main()
