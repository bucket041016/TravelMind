from __future__ import annotations

import re

from .base_agent import BaseTravelAgent
from .schemas import TravelPlanState


class BudgetAgent(BaseTravelAgent):
    name = "BudgetAgent 预算评估"

    def run(self, state: TravelPlanState) -> str:
        if not state.preferences or not self.toolbox:
            return "缺少偏好或 MCP 工具，跳过预算估算。"

        prefs = state.preferences
        result = self.toolbox.call(
            "estimate_budget",
            origin=prefs.origin_city,
            destination=prefs.destination_city,
            days=prefs.days,
            travelers=prefs.travelers,
            hotel_level=prefs.hotel_level,
        )
        state.budget_text = result
        state.estimated_total = self._parse_total(result)
        return self._append_budget_signal(result, prefs.budget, state.estimated_total)

    @staticmethod
    def _parse_total(text: str) -> int | None:
        match = re.search(r"总计：约\s*([0-9]+)\s*元", text)
        return int(match.group(1)) if match else None

    @staticmethod
    def _append_budget_signal(text: str, target: int | None, estimated: int | None) -> str:
        if target is None or estimated is None:
            return text
        if estimated <= target:
            return f"{text}\n预算判断：预计总花费在用户预算 {target} 元以内。"
        gap = estimated - target
        return f"{text}\n预算判断：预计超出用户预算约 {gap} 元，建议降低酒店档位或减少付费体验。"
