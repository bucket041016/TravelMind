from __future__ import annotations

import re

from .base_agent import BaseTravelAgent
from .schemas import TravelPlanState


class WriterAgent(BaseTravelAgent):
    name = "WriterAgent 行程生成"

    def run(self, state: TravelPlanState) -> str:
        if not state.preferences:
            return "缺少需求解析结果，无法生成行程。"

        prefs = state.preferences
        markdown = self._build_markdown(state)
        state.itinerary_markdown = markdown
        summary = f"已生成 {prefs.origin_city} 到 {prefs.destination_city} {prefs.days} 天出行方案。"

        if prefs.require_file and self.toolbox:
            filename = self._filename(prefs.origin_city, prefs.destination_city, prefs.days)
            file_result = self.toolbox.call(
                "write_itinerary_file",
                title=f"{prefs.origin_city}到{prefs.destination_city}{prefs.days}天出行方案",
                markdown_content=markdown,
                filename=filename,
            )
            state.file_path = file_result
            markdown += f"\n\n**文件输出**：{file_result}"
            state.itinerary_markdown = markdown
            return f"{summary}\n{file_result}"

        return summary

    def _build_markdown(self, state: TravelPlanState) -> str:
        prefs = state.preferences
        assert prefs is not None

        weather_text = "\n".join(f"- {city}：{text}" for city, text in state.weather.items()) or "- 暂无天气数据"
        budget_advice = self._budget_advice(prefs.budget, state.estimated_total)
        route_recommendation = self._route_recommendation(state.routes, prefs.route_modes)

        lines = [
            f"## {prefs.origin_city} 到 {prefs.destination_city} {prefs.days} 天智能出行方案",
            "",
            "### 需求摘要",
            f"- 出发地：{prefs.origin}",
            f"- 目的地：{prefs.destination}",
            f"- 出行时间：{prefs.start_date_label}",
            f"- 人数与预算：{prefs.travelers} 人；{prefs.budget or '未指定'} 元",
            f"- 偏好：{'、'.join(prefs.interests)}；酒店档位：{prefs.hotel_level}",
            "",
            "### 天气与出行建议",
            weather_text,
            "",
            "### 路线对比",
            state.routes or "暂未获得路线数据。",
            "",
            "### 景点与美食",
            state.poi or "暂未获得景点数据。",
            "",
            "### 预算评估",
            state.budget_text or "暂未估算预算。",
            budget_advice,
            "",
            "### 推荐方案",
            route_recommendation,
            "- 行程节奏：第一天优先安排核心景点和美食，第二天选择轻松路线，保留 1 到 2 小时机动时间。",
            "- 风险控制：出发前再次确认天气、实时路况、景区预约和返程票。",
        ]

        if state.errors:
            lines.extend(["", "### 异常与降级", *[f"- {error}" for error in state.errors]])

        return "\n".join(lines)

    @staticmethod
    def _budget_advice(target: int | None, estimated: int | None) -> str:
        if target is None or estimated is None:
            return "- 预算建议：用户未给出明确预算，可根据住宿档位灵活调整。"
        if estimated <= target:
            return f"- 预算建议：预计 {estimated} 元，控制在 {target} 元预算内。"
        return f"- 预算建议：预计 {estimated} 元，高于 {target} 元预算，优先压缩住宿和门票体验。"

    @staticmethod
    def _route_recommendation(routes: str, modes: str) -> str:
        if "高铁/城际铁路" in routes:
            recommendation = "- 首推高铁/城际铁路：跨城速度快、稳定，不需要考虑停车，适合作为主交通。"
            if "驾车路线" in routes:
                recommendation += "\n- 备选驾车：适合多人同行、携带行李多或目的地分散的情况。"
            if "公交换乘" in routes:
                recommendation += "\n- 公共交通：更适合作为到站后的市内接驳或预算优先方案。"
            return recommendation
        if "驾车路线" in routes and "公交换乘" in routes:
            return (
                "- 首推公共交通/高铁组合：跨城更稳定，不需要考虑停车，适合轻松周末游。\n"
                "- 备选驾车：如果同行人数较多、携带行李多，或目的地分散，可以选择耗时最短的驾车路线。"
            )
        if "驾车路线" in routes:
            return "- 推荐选择高德返回的耗时较短驾车路线，并提前检查停车点和实时拥堵。"
        if "公交换乘" in routes or "transit" in modes:
            return "- 推荐公共交通方案，优先选择换乘少、步行距离短的路线。"
        return "- 推荐根据实时地图路线选择总耗时更短、换乘更少的方案。"

    @staticmethod
    def _filename(origin_city: str, destination_city: str, days: int) -> str:
        raw = f"{origin_city}_{destination_city}_{days}days.md"
        return re.sub(r"[^\w\-.]+", "_", raw, flags=re.UNICODE)
