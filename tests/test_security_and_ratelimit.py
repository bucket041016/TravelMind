"""公开演示站限流防刷与安全加固测试（全离线，使用临时 SQLite DB）。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from sync import fastmcp_server_streamhttp as mcp_srv
from sync import persistence
from sync import security
from sync import travel_web_app as web
from sync.knowledge.local_poi_store import search_local_pois
from sync.multi_agent.structured_planner import StructuredTravelPlanner
from tests.evals.fixtures import EvalScenario, FixtureDeepSeekBrain, FixtureToolbox
from tests.test_phase5_persistence import _TmpDb


def _make_planner(fail_run: bool = False):
    scenario = EvalScenario(
        name="sec-test",
        payload={
            "originCity": "广州",
            "destinationCity": "深圳",
            "startDate": "2026-08-15",
            "days": 2,
            "budget": 1200,
        },
    )
    planner = StructuredTravelPlanner("fixture://security-test")
    planner.toolbox = FixtureToolbox(scenario)
    planner.deepseek_brain = FixtureDeepSeekBrain(scenario)
    if fail_run:
        def _boom(_payload):
            raise RuntimeError("simulated error with key=ABCDE1234567890FGHIJ and sk-secretkey1234567890")
        planner.run = _boom  # type: ignore[method-assign]
    return planner


class SecurityAndRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.db = _TmpDb()
        self.db.__enter__()
        security.get_token_limiter().clear()
        security.get_quota_store()._initialized_paths.clear()
        web._structured_planner = _make_planner()
        self.client = TestClient(web.app)

    def tearDown(self):
        web._structured_planner = None
        security.get_token_limiter().clear()
        security.get_quota_store()._initialized_paths.clear()
        self.db.__exit__(None, None, None)

    def test_token_bucket_burst_and_block(self):
        limiter = security.TokenBucketLimiter()
        ok1, _ = limiter.consume("plan", "1.2.3.4", capacity=2.0, refill_per_second=1.0 / 30.0)
        ok2, _ = limiter.consume("plan", "1.2.3.4", capacity=2.0, refill_per_second=1.0 / 30.0)
        ok3, retry = limiter.consume("plan", "1.2.3.4", capacity=2.0, refill_per_second=1.0 / 30.0)
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertFalse(ok3)
        self.assertGreaterEqual(retry, 1)

    def test_daily_quota_per_ip_limit_refund_and_global_circuit_breaker(self):
        env = {
            "TRAVELMIND_PUBLIC_MODE": "on",
            "TRAVELMIND_RATE_LIMIT": "on",
            "TRAVELMIND_DAILY_PLAN_LIMIT": "3",
            "TRAVELMIND_DAILY_GLOBAL_LIMIT": "4",
        }
        with patch.dict(os.environ, env):
            # 前 2 次放行；令牌桶容量为 2，第 3 次切换另一个端口模拟或清理桶后测试日配额
            for idx in range(2):
                resp = self.client.post(
                    "/api/plan",
                    json={"originCity": "广州", "destinationCity": "深圳", "days": 2},
                    headers={"X-Real-IP": "10.0.0.1"},
                )
                self.assertEqual(resp.status_code, 200, resp.text)

            # 清空突发令牌桶后执行第 3 次（验证日限额=3）
            security.get_token_limiter().clear()
            resp3 = self.client.post(
                "/api/plan",
                json={"originCity": "广州", "destinationCity": "深圳", "days": 2},
                headers={"X-Real-IP": "10.0.0.1"},
            )
            self.assertEqual(resp3.status_code, 200)

            # 第 4 次应命中单 IP 每日 3 次拦截
            security.get_token_limiter().clear()
            resp4 = self.client.post(
                "/api/plan",
                json={"originCity": "广州", "destinationCity": "深圳", "days": 2},
                headers={"X-Real-IP": "10.0.0.1"},
            )
            self.assertEqual(resp4.status_code, 429)
            self.assertEqual(resp4.json()["detail"]["code"], "daily_quota_exceeded")

            # 查询 /api/quota 验证计数
            q = self.client.get("/api/quota", headers={"X-Real-IP": "10.0.0.1"}).json()
            self.assertEqual(q["used"], 3)
            self.assertEqual(q["remaining"], 0)
            self.assertTrue(q["global_available"])

            # 另一 IP 使用第 4 次全站名额成功，第 5 次触发全站日熔断
            resp_other1 = self.client.post(
                "/api/plan",
                json={"originCity": "广州", "destinationCity": "深圳", "days": 2},
                headers={"X-Real-IP": "10.0.0.2"},
            )
            self.assertEqual(resp_other1.status_code, 200)
            resp_other2 = self.client.post(
                "/api/plan",
                json={"originCity": "广州", "destinationCity": "深圳", "days": 2},
                headers={"X-Real-IP": "10.0.0.2"},
            )
            self.assertEqual(resp_other2.status_code, 429)

    def test_failed_plan_refunds_quota_and_redacts_error(self):
        web._structured_planner = _make_planner(fail_run=True)
        env = {
            "TRAVELMIND_PUBLIC_MODE": "on",
            "TRAVELMIND_RATE_LIMIT": "on",
            "TRAVELMIND_DAILY_PLAN_LIMIT": "3",
        }
        with patch.dict(os.environ, env):
            resp = self.client.post(
                "/api/plan",
                json={"originCity": "广州", "destinationCity": "深圳", "days": 2},
                headers={"X-Real-IP": "10.0.0.9"},
            )
            self.assertEqual(resp.status_code, 500)
            detail = resp.json()["detail"]
            self.assertNotIn("ABCDE1234567890FGHIJ", detail)
            self.assertNotIn("sk-secretkey1234567890", detail)
            self.assertIn("key=***", detail)
            self.assertIn("sk-***", detail)

            # 配额应已退还为 0 已用
            q = self.client.get("/api/quota", headers={"X-Real-IP": "10.0.0.9"}).json()
            self.assertEqual(q["used"], 0)
            self.assertEqual(q["remaining"], 3)

    def test_async_idempotent_replay_does_not_double_debit(self):
        env = {
            "TRAVELMIND_PUBLIC_MODE": "on",
            "TRAVELMIND_RATE_LIMIT": "on",
            "TRAVELMIND_DAILY_PLAN_LIMIT": "3",
        }
        with patch.dict(os.environ, env):
            payload = {
                "originCity": "广州",
                "destinationCity": "深圳",
                "days": 2,
                "clientRequestId": "idem-req-1",
            }
            r1 = self.client.post("/api/plan-async", json=payload, headers={"X-Real-IP": "10.0.0.3"})
            self.assertEqual(r1.status_code, 200)
            self.assertFalse(r1.json()["replayed"])

            # 相同 clientRequestId 重放不额外扣费
            r2 = self.client.post("/api/plan-async", json=payload, headers={"X-Real-IP": "10.0.0.3"})
            self.assertEqual(r2.status_code, 200)
            self.assertTrue(r2.json()["replayed"])

            q = self.client.get("/api/quota", headers={"X-Real-IP": "10.0.0.3"}).json()
            self.assertEqual(q["used"], 1)

    def test_untrusted_proxy_cannot_spoof_xff(self):
        # 构造伪造直连对端（不在 TRAVELMIND_TRUSTED_PROXIES 中）
        class _FakeClient:
            host = "203.0.113.50"

        class _FakeRequest:
            client = _FakeClient()
            headers = {"x-forwarded-for": "8.8.8.8", "x-real-ip": "9.9.9.9"}

        with patch.dict(os.environ, {"TRAVELMIND_TRUSTED_PROXIES": "127.0.0.1/32,::1/128"}):
            ip = security.resolve_client_ip(_FakeRequest())  # type: ignore[arg-type]
            self.assertEqual(ip, "203.0.113.50")

        # 可信本地反代时正确读取 X-Forwarded-For 最右不可信客户端 IP
        class _LocalProxyClient:
            host = "127.0.0.1"

        class _ProxiedRequest:
            client = _LocalProxyClient()
            headers = {"x-forwarded-for": "1.1.1.1, 198.51.100.22"}

        with patch.dict(os.environ, {"TRAVELMIND_TRUSTED_PROXIES": "127.0.0.1/32"}):
            ip = security.resolve_client_ip(_ProxiedRequest())  # type: ignore[arg-type]
            self.assertEqual(ip, "198.51.100.22")

    def test_public_mode_protects_rag_writes_and_disables_shared_chat(self):
        with patch.dict(
            os.environ,
            {"TRAVELMIND_PUBLIC_MODE": "on", "TRAVELMIND_ADMIN_TOKEN": "top-secret-admin"},
        ):
            # 全局共享对话被禁用
            chat_resp = self.client.post("/api/chat", json={"message": "hello"})
            self.assertEqual(chat_resp.status_code, 403)

            # 无口令写 RAG 被拒绝
            rag_deny = self.client.post(
                "/api/rag/docs",
                json={"title": "test", "content": "content", "city": "深圳"},
            )
            self.assertEqual(rag_deny.status_code, 403)

            # 携带正确管理员口令允许写入并删除
            rag_ok = self.client.post(
                "/api/rag/docs",
                json={"title": "公开模式测试攻略", "content": "深圳湾公园看海日落攻略与地铁接驳建议内容不少于十字", "city": "深圳"},
                headers={"X-Admin-Token": "top-secret-admin"},
            )
            self.assertEqual(rag_ok.status_code, 200)
            doc_id = rag_ok.json()["document"]["doc_id"]

            del_deny = self.client.delete(f"/api/rag/docs/{doc_id}")
            self.assertEqual(del_deny.status_code, 403)

            del_ok = self.client.delete(
                f"/api/rag/docs/{doc_id}",
                headers={"X-Admin-Token": "top-secret-admin"},
            )
            self.assertEqual(del_ok.status_code, 200)

    def test_presets_endpoint_and_input_length_limit(self):
        presets = self.client.get("/api/presets")
        self.assertEqual(presets.status_code, 200)
        items = presets.json()["presets"]
        self.assertGreaterEqual(len(items), 2)

        detail = self.client.get(f"/api/presets/{items[0]['id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["plan"]["planning_mode"], "preset_demo")

        # 超长 freeText 触发 422 校验拦截
        too_long = self.client.post(
            "/api/plan",
            json={"originCity": "广州", "destinationCity": "深圳", "freeText": "a" * 1500},
        )
        self.assertEqual(too_long.status_code, 422)

    def test_mcp_sanitize_error_filename_and_public_write_guard(self):
        masked = mcp_srv._sanitize_error("403 error url=https://restapi.amap.com/v3/place/text?key=amap123456&city=sz")
        self.assertNotIn("amap123456", masked)
        self.assertIn("key=***", masked)
        self.assertTrue(mcp_srv._sanitize_filename("..").startswith("itinerary_"))
        self.assertTrue(mcp_srv._sanitize_filename(".").startswith("itinerary_"))

        with patch.dict(os.environ, {"TRAVELMIND_PUBLIC_MODE": "on"}):
            msg = mcp_srv.write_itinerary_file("测试", "# 内容", "test.md")
            self.assertIn("公开演示模式已禁用", msg)

    def test_local_poi_store_immutable_fallback_on_readonly_wal_error(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = Path(tmp) / "wal_pois.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE pois (
                    poi_id TEXT PRIMARY KEY, city TEXT NOT NULL, category TEXT NOT NULL,
                    category_label TEXT NOT NULL, name TEXT NOT NULL, type_name TEXT,
                    typecode TEXT, pname TEXT, cityname TEXT, adname TEXT,
                    business_area TEXT, address TEXT, lng REAL, lat REAL,
                    tel TEXT, rating REAL, cost REAL, tag TEXT
                );
                INSERT INTO pois VALUES (
                    'p1', '深圳', 'scenic', '景点', '深圳湾公园', '公园',
                    '110101', '广东省', '深圳市', '南山区', '后海', '滨海大道',
                    113.95, 22.52, '', 4.9, 0.0, '看海'
                );
                """
            )
            conn.commit()
            conn.close()

            real_connect = sqlite3.connect

            def flaky_connect(dsn, *args, **kwargs):
                if "immutable=1" not in str(dsn):
                    raise sqlite3.OperationalError("attempt to write a readonly database")
                return real_connect(dsn, *args, **kwargs)

            with patch("sync.knowledge.local_poi_store.sqlite3.connect", side_effect=flaky_connect):
                hits = search_local_pois("深圳", keywords="深圳湾", db_path=db_path)
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["name"], "深圳湾公园")
