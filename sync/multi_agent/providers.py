from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderPayload:
    status: str
    message: str
    options: list[dict[str, Any]] = field(default_factory=list)


class RailProvider:
    """Placeholder adapter for a future real train-ticket provider."""

    def __init__(self) -> None:
        self.api_key = (
            os.getenv("TRAVELMIND_RAIL_API_KEY")
            or os.getenv("RAIL_API_KEY")
            or ""
        ).strip()

    def query(self, origin: str, destination: str, start_date: str) -> ProviderPayload:
        if not self.api_key:
            return ProviderPayload(
                status="not_configured",
                message=(
                    "火车票实时接口未配置，当前高铁/城际候选来自本地知识库和路线规则；"
                    "具体车次、票价、余票请以 12306 为准。"
                ),
            )
        return ProviderPayload(
            status="not_configured",
            message="已检测到铁路接口 Key，但真实供应商适配尚未实现。",
        )


class FlightProvider:
    """Placeholder adapter for a future real flight provider."""

    def __init__(self) -> None:
        self.api_key = (
            os.getenv("TRAVELMIND_FLIGHT_API_KEY")
            or os.getenv("FLIGHT_API_KEY")
            or ""
        ).strip()

    def query(self, origin: str, destination: str, start_date: str) -> ProviderPayload:
        if not self.api_key:
            return ProviderPayload(
                status="not_configured",
                message=(
                    "航班实时数据未接入，暂不展示航班号、实时票价或余票；"
                    "长距离跨城时仅作为策略候选。"
                ),
            )
        return ProviderPayload(
            status="not_configured",
            message="已检测到航班接口 Key，但真实供应商适配尚未实现。",
        )


class HotelProvider:
    """Placeholder adapter for a future real hotel inventory provider."""

    def __init__(self) -> None:
        self.api_key = (
            os.getenv("TRAVELMIND_HOTEL_API_KEY")
            or os.getenv("HOTEL_API_KEY")
            or ""
        ).strip()

    def status(self) -> str:
        return "live" if self.api_key else "not_configured"

    def message(self) -> str:
        if self.api_key:
            return "已检测到酒店接口 Key，但真实库存适配尚未实现，当前仍使用高德 POI 作为展示候选。"
        return "酒店库存/实时价格接口未配置，当前使用高德 POI 和预算档位生成住宿候选。"
