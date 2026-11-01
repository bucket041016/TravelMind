"""E2E fixture server：生产 FastAPI app + 离线 fixture planner（Playwright webServer 入口）。

- 零真实外部调用：toolbox/brain 全部用评测 fixture（毫秒级确定性响应）；
- E2EBrain 补 parse_refine_ops（评测 FixtureDeepSeekBrain 没有该方法，
  缺失会让 /api/refine-plan 500、追问 spec 假绿）；
- freeText == "__e2e_force_error__" 时 run() 抛错（错误态 spec 用，单服务器双场景）；
- E2E_PERSISTENCE_OFF=1 → TRAVELMIND_PERSISTENCE=off（503 回退场景）；
- 独立 DB 路径 data/e2e.db，每次启动清理，不污染开发数据。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.evals.fixtures import EvalScenario, FixtureDeepSeekBrain, FixtureToolbox  # noqa: E402

FORCE_ERROR_MARKER = "__e2e_force_error__"


class E2EBrain(FixtureDeepSeekBrain):
    """追问固定解析为 adjust_budget 操作（确定性 refine 路径）。"""

    def parse_refine_ops(self, payload):
        return {
            "llm_status": "used",
            "reason": "",
            "operations": [
                {"action": "adjust_budget", "budget": 2000, "reason": "E2E 固定操作：预算改为 2000 元"}
            ],
            "answer": "",
        }


class E2EPlanner:
    """包装 fixture planner：freeText 命中注入标记时抛错（错误态 spec）。"""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def run(self, payload):
        if str(payload.get("freeText") or "") == FORCE_ERROR_MARKER:
            raise RuntimeError("E2E 注入的规划失败")
        return self._inner.run(payload)


def _clean_db(path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = Path(str(path) + suffix)
        try:
            if candidate.exists():
                candidate.unlink()
        except OSError:
            pass


def main() -> None:
    if os.getenv("E2E_PERSISTENCE_OFF") == "1":
        os.environ["TRAVELMIND_PERSISTENCE"] = "off"
    os.environ.setdefault("TRAVELMIND_DB_PATH", "data/e2e.db")
    _clean_db(ROOT / os.environ["TRAVELMIND_DB_PATH"])

    from sync import travel_web_app as web
    from sync.multi_agent.structured_planner import StructuredTravelPlanner

    scenario = EvalScenario(
        name="e2e",
        payload={
            "originCity": "广州",
            "destinationCity": "深圳",
            "startDate": "2026-08-15",
            "days": 2,
            "travelers": 1,
            "budget": 1800,
        },
    )
    planner = StructuredTravelPlanner("fixture://e2e")
    planner.toolbox = FixtureToolbox(scenario)
    planner.deepseek_brain = E2EBrain(scenario)
    web._structured_planner = E2EPlanner(planner)

    import uvicorn

    uvicorn.run(
        web.app,
        host="127.0.0.1",
        port=int(os.getenv("E2E_PORT", "8020")),
        log_level="warning",
    )


if __name__ == "__main__":
    main()
