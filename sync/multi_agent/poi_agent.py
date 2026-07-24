from __future__ import annotations

from .base_agent import BaseTravelAgent
from .schemas import TravelPlanState


class POIAgent(BaseTravelAgent):
    name = "POIAgent 景点美食"

    def run(self, state: TravelPlanState) -> str:
        if not state.preferences or not self.toolbox:
            return "缺少偏好或 MCP 工具，跳过 POI 查询。"

        prefs = state.preferences
        preference = "、".join(prefs.interests)
        result = self.toolbox.call(
            "search_poi",
            city=prefs.destination_city,
            preference=preference,
        )
        state.poi = result
        return result
