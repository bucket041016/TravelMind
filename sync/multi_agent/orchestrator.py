from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

try:
    from mcp_tools_adapter import MCPToolAdapter
except ModuleNotFoundError:
    from sync.mcp_tools_adapter import MCPToolAdapter

from .amap_route_agent import AMapRouteAgent
from .base_agent import BaseTravelAgent, MCPToolbox
from .budget_agent import BudgetAgent
from .poi_agent import POIAgent
from .preference_agent import PreferenceAgent
from .schemas import AgentStep, TravelPlanState
from .weather_agent import WeatherAgent
from .writer_agent import WriterAgent


class MultiAgentTravelPlanner:
    """A deterministic multi-agent workflow for travel planning.

    The pipeline is intentionally easy to explain in a resume/interview:
    parse user intent, fan out factual tool calls, then synthesize a final plan.
    """

    def __init__(self, mcp_server_url: str):
        toolbox = MCPToolbox(MCPToolAdapter(mcp_server_url))
        self.preference_agent = PreferenceAgent(toolbox)
        self.fact_agents: list[BaseTravelAgent] = [
            WeatherAgent(toolbox),
            AMapRouteAgent(toolbox),
            POIAgent(toolbox),
            BudgetAgent(toolbox),
        ]
        self.writer_agent = WriterAgent(toolbox)

    def run(self, query: str) -> dict:
        state = TravelPlanState(raw_request=query)

        self.preference_agent.execute(state)
        self._run_fact_agents(state)
        self.writer_agent.execute(state)

        ordered_steps = self._ordered_steps(state.steps)
        return {
            "answer": state.itinerary_markdown,
            "trace": [step.to_trace() for step in ordered_steps],
            "agent_steps": [step.to_trace() for step in ordered_steps],
        }

    def _run_fact_agents(self, state: TravelPlanState) -> None:
        with ThreadPoolExecutor(max_workers=len(self.fact_agents)) as executor:
            futures = [executor.submit(agent.execute, state) for agent in self.fact_agents]
            for future in as_completed(futures):
                future.result()

    @staticmethod
    def _ordered_steps(steps: Iterable[AgentStep]) -> list[AgentStep]:
        rank = {
            "PreferenceAgent 需求理解": 0,
            "WeatherAgent 天气与出行建议": 1,
            "AMapRouteAgent 高德多路线": 2,
            "POIAgent 景点美食": 3,
            "BudgetAgent 预算评估": 4,
            "WriterAgent 行程生成": 5,
        }
        return sorted(steps, key=lambda step: rank.get(step.name, 99))
