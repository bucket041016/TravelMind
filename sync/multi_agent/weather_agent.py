from __future__ import annotations

from .base_agent import BaseTravelAgent
from .schemas import TravelPlanState


class WeatherAgent(BaseTravelAgent):
    name = "WeatherAgent 天气与出行建议"

    def run(self, state: TravelPlanState) -> str:
        if not state.preferences or not self.toolbox:
            return "缺少偏好或 MCP 工具，跳过天气查询。"

        prefs = state.preferences
        cities = [prefs.destination_city]
        if prefs.origin_city and prefs.origin_city != prefs.destination_city:
            cities.insert(0, prefs.origin_city)

        weather = {}
        for city in dict.fromkeys(cities):
            weather[city] = self.toolbox.call(
                "get_weather",
                city=city,
                date=prefs.start_date_label,
            )

        state.weather = weather
        return "\n".join(weather.values())
