from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TravelPreferences:
    raw_request: str
    origin: str = "广州"
    destination: str = "深圳"
    origin_city: str = "广州"
    destination_city: str = "深圳"
    start_date_label: str = "明天"
    days: int = 2
    travelers: int = 1
    budget: int | None = None
    hotel_level: str = "舒适"
    interests: list[str] = field(default_factory=lambda: ["经典景点"])
    require_file: bool = False
    route_modes: str = "rail,driving,transit"


@dataclass
class AgentStep:
    name: str
    status: str
    args: str
    output: str
    duration_ms: int

    def to_trace(self) -> dict[str, str]:
        return {
            "name": self.name,
            "args": self.args,
            "output": self.output,
            "status": self.status,
            "duration_ms": str(self.duration_ms),
        }


@dataclass
class TravelPlanState:
    raw_request: str
    preferences: TravelPreferences | None = None
    weather: dict[str, str] = field(default_factory=dict)
    routes: str = ""
    poi: str = ""
    budget_text: str = ""
    estimated_total: int | None = None
    itinerary_markdown: str = ""
    file_path: str = ""
    errors: list[str] = field(default_factory=list)
    steps: list[AgentStep] = field(default_factory=list)
