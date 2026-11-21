"""公开站安全加固与双层限流防刷基础设施。

提供：
- 公开模式 / 限流总开关（Feature Flag，默认 off 保证本地开发与既有测试零破坏）
- 真实客户端 IP 提取（仅在可信代理来源下解析转发头，防止 X-Forwarded-For 伪造绕过）
- 线程安全内存令牌桶（TokenBucketLimiter，按 IP + 路由组抑制高频连击与突发流量）
- 基于 SQLite 的自然日配额管理（DailyQuotaStore，支持每 IP 每日限额、全站日熔断、失败退还）
- 全局规划并发信号量（ConcurrencyGuard）
- 统一错误与密钥脱敏（redact_error_text）与管理员口令校验
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

try:
    from sync import persistence
except ModuleNotFoundError:
    import persistence  # type: ignore[no-redef]


CHINA_TZ = timezone(timedelta(hours=8))

_SENSITIVE_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{12,}"), "sk-***"),
    (re.compile(r"(?i)((?:[?&]|\b)key=)[^&\s\"']+"), r"\1***"),
    (re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;\"']+"), r"\1***"),
    (re.compile(r"(?i)(token\s*[:=]\s*)[^\s,;\"']+"), r"\1***"),
]


def _env_flag(name: str, default: str = "off") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(value, minimum)


def public_mode_enabled() -> bool:
    return _env_flag("TRAVELMIND_PUBLIC_MODE", "off")


def rate_limit_enabled() -> bool:
    explicit = os.getenv("TRAVELMIND_RATE_LIMIT")
    if explicit is not None and explicit.strip() != "":
        return _env_flag("TRAVELMIND_RATE_LIMIT", "off")
    return public_mode_enabled()


def redact_error_text(value: Any) -> str:
    """对异常或提示文本中的 API Key / Token 做脱敏处理。"""
    text = str(value or "")
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _trusted_proxy_networks() -> list[ipaddress._BaseNetwork]:
    raw = os.getenv("TRAVELMIND_TRUSTED_PROXIES", "127.0.0.1/32,::1/128")
    networks: list[ipaddress._BaseNetwork] = []
    for entry in raw.split(","):
        item = entry.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return networks


def _is_valid_ip(raw: str) -> str:
    candidate = str(raw or "").strip()
    if not candidate:
        return ""
    # 剥离可能带有的端口号（如 1.2.3.4:5678）
    if candidate.count(":") == 1 and "." in candidate:
        candidate = candidate.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return ""


def _is_trusted_proxy(ip_text: str, networks: list[ipaddress._BaseNetwork]) -> bool:
    if not ip_text:
        return False
    try:
        addr = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    return any(addr in net for net in networks)


def resolve_client_ip(request: Request) -> str:
    """提取真实客户端 IP：仅当直连对端在可信代理列表中时才采信转发头。"""
    peer_ip = _is_valid_ip(request.client.host if request.client else "") or "127.0.0.1"
    networks = _trusted_proxy_networks()
    if not _is_trusted_proxy(peer_ip, networks):
        return peer_ip

    xff = str(request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        # 从右向左跳过可信代理，取最后一个不可信（真实客户端）IP
        parts = [_is_valid_ip(part) for part in xff.split(",")]
        for ip_item in reversed(parts):
            if ip_item and not _is_trusted_proxy(ip_item, networks):
                return ip_item
        for ip_item in parts:
            if ip_item:
                return ip_item

    real_ip = _is_valid_ip(request.headers.get("x-real-ip") or "")
    if real_ip:
        return real_ip
    return peer_ip


@dataclass
class _BucketState:
    tokens: float
    last_refill: float
    last_seen: float


class TokenBucketLimiter:
    """按 (bucket_group, client_ip) 维度隔离的线程安全内存令牌桶。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str], _BucketState] = {}
        self._last_gc = time.monotonic()

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()

    def consume(
        self,
        group: str,
        client_ip: str,
        *,
        capacity: float,
        refill_per_second: float,
        cost: float = 1.0,
    ) -> tuple[bool, int]:
        """尝试消耗令牌；返回 (是否放行, 建议重试秒数)。"""
        now = time.monotonic()
        key = (group, client_ip)
        with self._lock:
            self._gc_if_needed(now)
            state = self._buckets.get(key)
            if state is None:
                state = _BucketState(tokens=float(capacity), last_refill=now, last_seen=now)
                self._buckets[key] = state
            else:
                elapsed = max(0.0, now - state.last_refill)
                state.tokens = min(float(capacity), state.tokens + elapsed * refill_per_second)
                state.last_refill = now
                state.last_seen = now

            if state.tokens >= cost:
                state.tokens -= cost
                return True, 0

            deficit = cost - state.tokens
            retry_after = int(max(1.0, deficit / max(refill_per_second, 1e-6)) + 0.999)
            return False, retry_after

    def _gc_if_needed(self, now: float) -> None:
        if now - self._last_gc < 300.0 and len(self._buckets) < 4096:
            return
        self._last_gc = now
        cutoff = now - 3600.0
        stale = [k for k, v in self._buckets.items() if v.last_seen < cutoff]
        for k in stale:
            self._buckets.pop(k, None)


def _today_cn() -> str:
    return datetime.now(CHINA_TZ).strftime("%Y-%m-%d")


def _next_reset_cn() -> str:
    now = datetime.now(CHINA_TZ)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.isoformat()


class DailyQuotaStore:
    """基于 SQLite 的自然日配额账本（支持单 IP 日限额、全站日熔断与异常退还）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._initialized_paths: set[str] = set()

    def _db_path(self) -> Path:
        return Path(os.getenv(persistence.DB_PATH_ENV, persistence.DB_PATH_DEFAULT))

    def _open_db(self) -> sqlite3.Connection:
        path = self._db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        path_key = str(path)
        if path_key not in self._initialized_paths:
            with self._lock:
                if path_key not in self._initialized_paths:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS daily_quotas (
                            quota_date TEXT NOT NULL,
                            scope TEXT NOT NULL,
                            used_count INTEGER NOT NULL DEFAULT 0,
                            updated_at TEXT NOT NULL,
                            PRIMARY KEY (quota_date, scope)
                        )
                        """
                    )
                    self._initialized_paths.add(path_key)
        return conn

    def acquire(
        self,
        checks: list[tuple[str, int, str]],
        *,
        quota_date: str | None = None,
    ) -> tuple[bool, str]:
        """原子校验并扣减一组配额 [(scope, limit, error_message), ...]。"""
        day = quota_date or _today_cn()
        now_iso = datetime.now(CHINA_TZ).isoformat()
        conn = self._open_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            for scope, limit, error_msg in checks:
                if limit <= 0:
                    conn.execute("ROLLBACK")
                    return False, error_msg
                row = conn.execute(
                    "SELECT used_count FROM daily_quotas WHERE quota_date=? AND scope=?",
                    (day, scope),
                ).fetchone()
                used = int(row["used_count"]) if row else 0
                if used >= limit:
                    conn.execute("ROLLBACK")
                    return False, error_msg

            for scope, _, _ in checks:
                conn.execute(
                    """
                    INSERT INTO daily_quotas (quota_date, scope, used_count, updated_at)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(quota_date, scope) DO UPDATE SET
                        used_count = used_count + 1,
                        updated_at = excluded.updated_at
                    """,
                    (day, scope, now_iso),
                )
            conn.execute("COMMIT")
            return True, ""
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def refund(self, scopes: list[str], *, quota_date: str | None = None) -> None:
        """任务内部失败时退还已预扣的配额，确保最小不低于 0。"""
        if not scopes:
            return
        day = quota_date or _today_cn()
        now_iso = datetime.now(CHINA_TZ).isoformat()
        conn = self._open_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            for scope in scopes:
                conn.execute(
                    """
                    UPDATE daily_quotas
                    SET used_count = MAX(0, used_count - 1), updated_at = ?
                    WHERE quota_date = ? AND scope = ?
                    """,
                    (now_iso, day, scope),
                )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        finally:
            conn.close()

    def get_usage(self, scope: str, *, quota_date: str | None = None) -> int:
        day = quota_date or _today_cn()
        conn = self._open_db()
        try:
            row = conn.execute(
                "SELECT used_count FROM daily_quotas WHERE quota_date=? AND scope=?",
                (day, scope),
            ).fetchone()
            return int(row["used_count"]) if row else 0
        finally:
            conn.close()


class ConcurrencyGuard:
    """限制同时运行的重型规划任务数，避免并发打爆上游 API 与服务器内存。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._limit = _env_int("TRAVELMIND_MAX_CONCURRENT_PLANS", 3, minimum=1)
        self._semaphore = threading.BoundedSemaphore(self._limit)

    def _sync_limit(self) -> threading.BoundedSemaphore:
        configured = _env_int("TRAVELMIND_MAX_CONCURRENT_PLANS", 3, minimum=1)
        if configured != self._limit:
            with self._lock:
                if configured != self._limit:
                    self._limit = configured
                    self._semaphore = threading.BoundedSemaphore(configured)
        return self._semaphore

    def try_acquire(self, timeout: float = 0.5) -> threading.BoundedSemaphore | None:
        sem = self._sync_limit()
        if sem.acquire(timeout=timeout):
            return sem
        return None


_TOKEN_LIMITER = TokenBucketLimiter()
_QUOTA_STORE = DailyQuotaStore()
_CONCURRENCY_GUARD = ConcurrencyGuard()


def get_token_limiter() -> TokenBucketLimiter:
    return _TOKEN_LIMITER


def get_quota_store() -> DailyQuotaStore:
    return _QUOTA_STORE


def get_concurrency_guard() -> ConcurrencyGuard:
    return _CONCURRENCY_GUARD


def plan_daily_limit() -> int:
    return _env_int("TRAVELMIND_DAILY_PLAN_LIMIT", 3, minimum=1)


def refine_daily_limit() -> int:
    return _env_int("TRAVELMIND_DAILY_REFINE_LIMIT", 10, minimum=1)


def global_daily_limit() -> int:
    return _env_int("TRAVELMIND_DAILY_GLOBAL_LIMIT", 100, minimum=1)


def raise_rate_limit_error(message: str, *, code: str, retry_after: int = 60, extra: dict[str, Any] | None = None) -> None:
    detail: dict[str, Any] = {
        "code": code,
        "message": message,
        "retry_after": retry_after,
    }
    if extra:
        detail.update(extra)
    raise HTTPException(
        status_code=429,
        detail=detail,
        headers={"Retry-After": str(max(1, retry_after))},
    )


def enforce_token_bucket(request: Request, group: str) -> str:
    """执行令牌桶限速校验并返回客户端 IP；未开启限流时直接返回 IP。"""
    client_ip = resolve_client_ip(request)
    if not rate_limit_enabled():
        return client_ip

    configs = {
        "plan": (2.0, 1.0 / 30.0, "操作过于频繁，请稍后再试（每 30 秒可恢复 1 次请求令牌）。"),
        "refine": (4.0, 1.0 / 10.0, "追问过于频繁，请稍候几秒再试。"),
        "search": (12.0, 0.5, "搜索请求过于频繁，请稍后再试。"),
    }
    capacity, refill, msg = configs.get(group, configs["search"])
    allowed, retry_after = _TOKEN_LIMITER.consume(
        group, client_ip, capacity=capacity, refill_per_second=refill
    )
    if not allowed:
        raise_rate_limit_error(msg, code="token_bucket_limited", retry_after=retry_after)
    return client_ip


def acquire_plan_quota(client_ip: str) -> tuple[list[str], str]:
    """校验并预扣单 IP 与全站主规划每日额度；返回 (已扣 scope 列表, 日期)。"""
    if not rate_limit_enabled():
        return [], _today_cn()

    ip_limit = plan_daily_limit()
    global_limit = global_daily_limit()
    ip_scope = f"ip:{client_ip}:plan"
    global_scope = "global:plan"
    day = _today_cn()
    ok, msg = _QUOTA_STORE.acquire(
        [
            (ip_scope, ip_limit, f"今日免费规划次数（{ip_limit}/{ip_limit}）已用完，明日 0 点自动重置。您可点击「精选示例」免额度体验，或继续在前端自由编辑当前行程。"),
            (global_scope, global_limit, "今日全站免费 AI 规划额度已达上限，请明日再来；当前可点击「精选示例」秒开完整方案体验。"),
        ],
        quota_date=day,
    )
    if not ok:
        raise_rate_limit_error(
            msg,
            code="daily_quota_exceeded",
            retry_after=3600,
            extra={"reset_at": _next_reset_cn()},
        )
    return [ip_scope, global_scope], day


def acquire_refine_quota(client_ip: str) -> tuple[list[str], str]:
    """校验并预扣追问调整每日额度。"""
    if not rate_limit_enabled():
        return [], _today_cn()

    ip_limit = refine_daily_limit()
    global_limit = max(global_daily_limit() * 4, 200)
    ip_scope = f"ip:{client_ip}:refine"
    global_scope = "global:refine"
    day = _today_cn()
    ok, msg = _QUOTA_STORE.acquire(
        [
            (ip_scope, ip_limit, f"今日智能追问次数（{ip_limit}/{ip_limit}）已用完，您仍可使用页面「编辑行程」直接在前端调整、增删节点与导出。"),
            (global_scope, global_limit, "今日全站智能追问额度已达上限，请使用「编辑行程」手动调整或明日再来。"),
        ],
        quota_date=day,
    )
    if not ok:
        raise_rate_limit_error(
            msg,
            code="refine_quota_exceeded",
            retry_after=3600,
            extra={"reset_at": _next_reset_cn()},
        )
    return [ip_scope, global_scope], day


def quota_status_for_ip(client_ip: str) -> dict[str, Any]:
    enabled = rate_limit_enabled()
    public = public_mode_enabled()
    ip_limit = plan_daily_limit()
    global_limit = global_daily_limit()
    if not enabled:
        return {
            "rate_limit_enabled": False,
            "public_mode": public,
            "rag_write_protected": public,
            "daily_limit": ip_limit,
            "used": 0,
            "remaining": ip_limit,
            "refine_limit": refine_daily_limit(),
            "refine_used": 0,
            "refine_remaining": refine_daily_limit(),
            "global_available": True,
            "reset_at": _next_reset_cn(),
        }

    day = _today_cn()
    used = _QUOTA_STORE.get_usage(f"ip:{client_ip}:plan", quota_date=day)
    refine_used = _QUOTA_STORE.get_usage(f"ip:{client_ip}:refine", quota_date=day)
    global_used = _QUOTA_STORE.get_usage("global:plan", quota_date=day)
    return {
        "rate_limit_enabled": True,
        "public_mode": public,
        "rag_write_protected": public,
        "daily_limit": ip_limit,
        "used": used,
        "remaining": max(0, ip_limit - used),
        "refine_limit": refine_daily_limit(),
        "refine_used": refine_used,
        "refine_remaining": max(0, refine_daily_limit() - refine_used),
        "global_available": global_used < global_limit,
        "reset_at": _next_reset_cn(),
    }


def require_admin_if_public(request: Request) -> None:
    """公开模式下保护写接口，仅当携带合法 X-Admin-Token 时放行。"""
    if not public_mode_enabled():
        return
    expected = os.getenv("TRAVELMIND_ADMIN_TOKEN", "").strip()
    provided = str(request.headers.get("x-admin-token") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=403,
            detail={"code": "public_readonly", "message": "公开演示模式已开启，攻略库管理接口设为只读。"},
        )
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=403,
            detail={"code": "admin_token_required", "message": "需要有效的管理员口令（X-Admin-Token）才能修改公共攻略库。"},
        )
