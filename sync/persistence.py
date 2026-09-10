"""SQLite 持久化层（Phase 5）：计划快照、偏好、任务事件与评测摘要。

设计原则（对应仓库计划 5.1/5.2 与 5.4 反向原则）：
- 观测/持久化失败绝不影响主流程：每个公开方法吞异常并返回安全默认值；
- TRAVELMIND_PERSISTENCE=off 时全部 no-op 且不创建任何目录/文件（回滚点）；
- 连接不跨线程持有（每次调用新建 sqlite3.Connection），WAL + busy_timeout
  消解后台写线程与 SSE 读协程的并发；
- 入库 payload 一律过 redact_secrets（sk- / key= / "api_key" 模式递归脱敏）。

事件绝不写回 run() 的 trace 数组——评测 139/4 断言的调用计数不受本层影响。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PERSISTENCE_FLAG = "TRAVELMIND_PERSISTENCE"
DB_PATH_ENV = "TRAVELMIND_DB_PATH"
DB_PATH_DEFAULT = "data/travelmind.db"
STALE_RUNNING_MINUTES = 10
PRUNE_DAYS = 14

_init_lock = threading.Lock()
_initialized_paths: set[str] = set()

_SECRET_KEY_NAMES = {"api_key", "apikey", "api-key", "secret", "password", "token"}
_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{16,}"), "sk-***"),
    (re.compile(r"(?i)(key=)[A-Za-z0-9]{20,}"), r"\1***"),
]


def persistence_enabled() -> bool:
    return str(os.getenv(PERSISTENCE_FLAG, "on")).strip().lower() not in {"off", "0", "false", "no"}


def redact_secrets(value: Any) -> Any:
    """递归脱敏 dict/list/str 中的密钥（纵深防御：计划 payload 本身不含密钥）。

    dict 键名命中敏感词表时直接掩码值；字符串再叠加 sk-/key= 模式替换。
    """
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            key_text = str(key).strip().lower()
            if key_text in _SECRET_KEY_NAMES and isinstance(item, str) and item.strip():
                redacted[key] = "***"
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        for pattern, replacement in _SECRET_PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_file() -> Path:
    return Path(os.getenv(DB_PATH_ENV, DB_PATH_DEFAULT))


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            client_request_id TEXT UNIQUE,
            status TEXT NOT NULL DEFAULT 'running',
            plan_id TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_events (
            task_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            event TEXT NOT NULL,
            data TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (task_id, seq)
        );
        CREATE TABLE IF NOT EXISTS plan_snapshots (
            plan_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (plan_id, version)
        );
        CREATE TABLE IF NOT EXISTS user_preferences (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS eval_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suite TEXT NOT NULL,
            created_at TEXT NOT NULL,
            metrics TEXT NOT NULL
        );
        """
    )


def _open() -> sqlite3.Connection | None:
    """打开连接并确保建表（每路径仅一次 DDL）。失败返回 None（调用方吞错）。"""
    if not persistence_enabled():
        return None
    path = str(_db_file())
    conn = _connect(_db_file())
    if path not in _initialized_paths:
        with _init_lock:
            if path not in _initialized_paths:
                _ensure_tables(conn)
                conn.commit()
                _initialized_paths.add(path)
    return conn


def create_task(task_id: str, client_request_id: str) -> bool:
    """登记新任务；client_request_id 已存在（幂等命中）返回 False。"""
    try:
        conn = _open()
        if conn is None:
            return True
        try:
            with conn:
                conn.execute(
                    "INSERT INTO tasks (task_id, client_request_id, status, created_at, updated_at) VALUES (?, ?, 'running', ?, ?)",
                    (task_id, client_request_id or task_id, _now(), _now()),
                )
            _prune_old_tasks(conn)
            return True
        finally:
            conn.close()
    except sqlite3.IntegrityError:
        return False
    except Exception:  # noqa: BLE001 - 持久化失败不影响主流程
        return True


def mark_task(task_id: str, status: str, *, plan_id: str | None = None, error: str | None = None) -> None:
    try:
        conn = _open()
        if conn is None:
            return
        try:
            with conn:
                conn.execute(
                    "UPDATE tasks SET status=?, plan_id=COALESCE(?, plan_id), error=?, updated_at=? WHERE task_id=?",
                    (status, plan_id, error, _now(), task_id),
                )
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return


def append_event(task_id: str, seq: int, event: str, data: dict[str, Any]) -> None:
    try:
        conn = _open()
        if conn is None:
            return
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO task_events (task_id, seq, event, data, created_at) VALUES (?, ?, ?, ?, ?)",
                    (task_id, seq, event, json.dumps(redact_secrets(data), ensure_ascii=False), _now()),
                )
                conn.execute("UPDATE tasks SET updated_at=? WHERE task_id=?", (_now(), task_id))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return


def load_events(task_id: str, after_seq: int = -1) -> list[tuple[int, str, dict[str, Any]]]:
    try:
        conn = _open()
        if conn is None:
            return []
        try:
            rows = conn.execute(
                "SELECT seq, event, data FROM task_events WHERE task_id=? AND seq>? ORDER BY seq",
                (task_id, after_seq),
            ).fetchall()
            return [(int(row["seq"]), str(row["event"]), json.loads(row["data"])) for row in rows]
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return []


def _stale_cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=STALE_RUNNING_MINUTES)).isoformat()


def get_task(task_id: str) -> dict[str, Any] | None:
    try:
        conn = _open()
        if conn is None:
            return None
        try:
            row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                return None
            task = dict(row)
            if task.get("status") == "running" and task.get("updated_at", "") < _stale_cutoff():
                task["status"] = "interrupted"
            return task
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None


def get_task_by_request(client_request_id: str) -> dict[str, Any] | None:
    if not client_request_id:
        return None
    try:
        conn = _open()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT * FROM tasks WHERE client_request_id=? ORDER BY created_at DESC LIMIT 1",
                (client_request_id,),
            ).fetchone()
            if row is None:
                return None
            task = dict(row)
            if task.get("status") == "running" and task.get("updated_at", "") < _stale_cutoff():
                task["status"] = "interrupted"
            return task
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None


def save_plan_snapshot(plan_id: str, version: int, payload: dict[str, Any]) -> None:
    try:
        conn = _open()
        if conn is None:
            return
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO plan_snapshots (plan_id, version, payload, created_at) VALUES (?, ?, ?, ?)",
                    (plan_id, int(version), json.dumps(redact_secrets(payload), ensure_ascii=False), _now()),
                )
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return


def load_plan_snapshot(plan_id: str, version: int | None = None) -> dict[str, Any] | None:
    try:
        conn = _open()
        if conn is None:
            return None
        try:
            if version is None:
                row = conn.execute(
                    "SELECT payload FROM plan_snapshots WHERE plan_id=? ORDER BY version DESC LIMIT 1",
                    (plan_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT payload FROM plan_snapshots WHERE plan_id=? AND version=?",
                    (plan_id, int(version)),
                ).fetchone()
            if row is None:
                return None
            return json.loads(row["payload"])
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None


def save_learned_hints(hints: list[str]) -> None:
    try:
        merged: list[str] = []
        for hint in list(load_learned_hints()) + [str(item) for item in hints or []]:
            text = hint.strip()
            if text and text not in merged:
                merged.append(text)
        conn = _open()
        if conn is None:
            return
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO user_preferences (key, value, updated_at) VALUES ('learnedHints', ?, ?)",
                    (json.dumps(merged[:12], ensure_ascii=False), _now()),
                )
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return


def load_learned_hints() -> list[str]:
    try:
        conn = _open()
        if conn is None:
            return []
        try:
            row = conn.execute("SELECT value FROM user_preferences WHERE key='learnedHints'").fetchone()
            if row is None:
                return []
            value = json.loads(row["value"])
            return [str(item) for item in value] if isinstance(value, list) else []
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return []


def save_eval_summary(suite: str, aggregate: dict[str, Any]) -> None:
    try:
        conn = _open()
        if conn is None:
            return
        try:
            with conn:
                conn.execute(
                    "INSERT INTO eval_summaries (suite, created_at, metrics) VALUES (?, ?, ?)",
                    (suite, _now(), json.dumps(redact_secrets(aggregate), ensure_ascii=False)),
                )
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return


def _prune_old_tasks(conn: sqlite3.Connection, max_age_days: int = PRUNE_DAYS) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    conn.execute("DELETE FROM task_events WHERE task_id IN (SELECT task_id FROM tasks WHERE updated_at < ?)", (cutoff,))
    conn.execute("DELETE FROM tasks WHERE updated_at < ?", (cutoff,))
