from __future__ import annotations

from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any

from .schemas import AgentStep, TravelPlanState


class MCPToolbox:
    """MCP 工具箱：字符串与结构化双访问（D12）。

    call_text() 恒返回 str（结构化返回以 JSON 文本给出），旧链路 Agent 依赖该契约；
    call_structured() 返回 MCPToolResult 封装（text/data/source/validation_error），
    结构化规划器用它显式取数据。call() 是 call_text 的遗留别名。
    """

    def __init__(self, adapter: Any):
        self.adapter = adapter

    def call_text(self, tool_name: str, **kwargs: Any) -> str:
        return self.adapter.call_mcp_tool(tool_name, **kwargs)

    def call_structured(self, tool_name: str, **kwargs: Any):
        return self.adapter.call_mcp_tool_result(tool_name, **kwargs)

    def call(self, tool_name: str, **kwargs: Any) -> str:
        return self.call_text(tool_name, **kwargs)


class BaseTravelAgent(ABC):
    name = "BaseAgent"

    def __init__(self, toolbox: MCPToolbox | None = None):
        self.toolbox = toolbox

    def execute(self, state: TravelPlanState) -> AgentStep:
        start = perf_counter()
        args = self.describe_input(state)
        status = "success"

        try:
            output = self.run(state)
        except Exception as exc:
            status = "error"
            output = f"{self.name} 执行失败：{exc}"
            state.errors.append(output)

        step = AgentStep(
            name=self.name,
            status=status,
            args=args,
            output=self._compact(output),
            duration_ms=round((perf_counter() - start) * 1000),
        )
        state.steps.append(step)
        return step

    def describe_input(self, state: TravelPlanState) -> str:
        if state.preferences:
            prefs = state.preferences
            return (
                f"origin={prefs.origin}, destination={prefs.destination}, "
                f"days={prefs.days}, travelers={prefs.travelers}"
            )
        return state.raw_request

    @abstractmethod
    def run(self, state: TravelPlanState) -> str:
        raise NotImplementedError

    @staticmethod
    def _compact(value: str, limit: int = 900) -> str:
        value = str(value).strip()
        if len(value) <= limit:
            return value
        return value[:limit].rstrip() + "..."
