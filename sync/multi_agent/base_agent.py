from __future__ import annotations

from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any

from .schemas import AgentStep, TravelPlanState


class MCPToolbox:
    def __init__(self, adapter: Any):
        self.adapter = adapter

    def call(self, tool_name: str, **kwargs: Any) -> str:
        return str(self.adapter.call_mcp_tool(tool_name, **kwargs))


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
