from __future__ import annotations

from .base_agent import BaseTravelAgent
from .schemas import TravelPlanState


class AMapRouteAgent(BaseTravelAgent):
    name = "AMapRouteAgent 高德多路线"

    def run(self, state: TravelPlanState) -> str:
        if not state.preferences or not self.toolbox:
            return "缺少偏好或 MCP 工具，跳过路线规划。"

        prefs = state.preferences
        result = self.toolbox.call(
            "amap_plan_routes",
            origin=prefs.origin,
            destination=prefs.destination,
            origin_city=prefs.origin_city,
            destination_city=prefs.destination_city,
            modes=prefs.route_modes,
            max_routes=3,
        )

        if result.startswith("高德路线规划失败"):
            fallback = self.toolbox.call(
                "plan_route",
                origin=prefs.origin_city,
                destination=prefs.destination_city,
                transport_mode="公共交通/高铁",
            )
            result = f"{result}\n\n已降级到本地路线知识库：\n{fallback}"

        state.routes = result
        return result
